"""Public-issue regression cases using disposable HTTP suppliers, never real API keys."""
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from sales_scenarios import GeminiFixture


class CountTokensFixture(GeminiFixture):
    def do_POST(self):
        if self.path.endswith(':countTokens'):
            self.rfile.read(int(self.headers['Content-Length']))
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"totalTokens":3}')
            return
        super().do_POST()


class TerminalChunkFixture(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers['Content-Length']))
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.end_headers()
        frames = [
            {'id': 'fixture', 'object': 'chat.completion.chunk', 'model': 'terminal-fixture',
             'choices': [{'index': 0, 'delta': {'content': 'fixture answer'}, 'finish_reason': None}]},
            {'id': 'fixture', 'object': 'chat.completion.chunk', 'model': 'terminal-fixture',
             'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}],
             'usage': {'prompt_tokens': 100, 'completion_tokens': 20, 'total_tokens': 120}},
        ]
        for frame in frames:
            self.wfile.write(('data: ' + json.dumps(frame) + '\n\n').encode())
        self.wfile.write(b'data: [DONE]\n\n')


def run_upstream_issue_scenarios(base, gateway, root, user, rt, ut, call, ok):
    results, servers = [], []
    uid = ok(user, 'GET', '/api/user/self', token=ut)['id']
    ok(root, 'POST', '/api/user/manage', {'id': uid, 'action': 'add_quota',
        'mode': 'override', 'value': 1000000}, rt)
    for option, values in [('ModelRatio', {'h5-fixture': 1, 'gemini-issue-fixture': 1, 'terminal-fixture': 1}),
                            ('CompletionRatio', {'h5-fixture': 2, 'gemini-issue-fixture': 2, 'terminal-fixture': 2})]:
        ok(root, 'PUT', '/api/option/', {'key': option, 'value': json.dumps(values)}, rt)

    def wallet():
        return ok(user, 'GET', '/api/user/self', token=ut)['quota']

    def issue(model):
        name = 'issue-' + secrets.token_hex(4)
        ok(user, 'POST', '/api/token/', {'name': name, 'expired_time': -1,
            'unlimited_quota': True, 'group': 'default',
            'model_limits_enabled': True, 'model_limits': model}, ut)
        tokens = ok(user, 'GET', '/api/token/?p=1&size=100', token=ut)['items']
        key_id = next(row['id'] for row in tokens if row['name'] == name)
        key = ok(user, 'POST', f'/api/token/{key_id}/key', token=ut)['key']
        return key if key.startswith('sk-') else 'sk-' + key

    try:
        for handler, channel_type, name, model, secret in [
            (CountTokensFixture, 24, 'Gemini issue fixture', 'gemini-issue-fixture', 'fixture-google-key'),
            (TerminalChunkFixture, 1, 'Terminal chunk fixture', 'terminal-fixture', 'fixture-upstream-key'),
        ]:
            server = ThreadingHTTPServer((gateway, 0), handler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            servers.append(server)
            ok(root, 'POST', '/api/channel/', {'mode': 'single', 'channel': {
                'name': name, 'type': channel_type, 'key': secret,
                'base_url': f'http://{gateway}:{server.server_port}', 'models': model,
                'group': 'default', 'status': 1, 'weight': 1}}, rt)

        key = issue('gemini-issue-fixture')
        native_body = {'contents': [{'role': 'user', 'parts': [{'text': 'count fixture'}]}]}
        native_path = '/v1beta/models/gemini-issue-fixture:countTokens'
        direct = user.request.post(f'http://{gateway}:{servers[0].server_port}' + native_path, data=native_body)
        assert direct.status == 200 and direct.json()['totalTokens'] == 3, 'direct fixture contract failed'
        GeminiFixture.calls = []
        before = wallet()
        response = call(user, 'POST', native_path, native_body, key)
        charge = before - wallet()
        generation_calls = len(GeminiFixture.calls)
        generated = any(':generateContent' in item['path'] for item in GeminiFixture.calls)
        passed = generation_calls == 0 and charge == 0 and (
            response.status in (400, 404, 501) or
            response.status == 200 and response.json().get('totalTokens') == 3)
        results.append({
            'issue': 7283, 'url': 'https://github.com/QuantumNous/new-api/issues/7283',
            'name': 'countTokens must not execute or charge generation', 'passed': passed,
            'direct_upstream_total_tokens': 3, 'platform_http': response.status,
            'platform_has_total_tokens': 'totalTokens' in response.json(),
            'rewritten_to_generate_content': generated, 'generation_calls': generation_calls, 'charge': charge,
        })

        key = issue('terminal-fixture')

        def finish_reasons(text):
            return [choice.get('finish_reason') for line in text.splitlines()
                    if line.startswith('data: {')
                    for choice in json.loads(line[6:]).get('choices', [])
                    if choice.get('finish_reason')]

        for include_usage in (None, False, True):
            body = {'model': 'terminal-fixture', 'stream': True,
                    'messages': [{'role': 'user', 'content': 'terminal fixture'}]}
            if include_usage is not None:
                body['stream_options'] = {'include_usage': include_usage}
            direct = user.request.post(f'http://{gateway}:{servers[1].server_port}/v1/chat/completions', data=body)
            assert finish_reasons(direct.text()) == ['stop'], 'direct upstream finish_reason missing'
            before = wallet()
            response = call(user, 'POST', '/v1/chat/completions', body, key)
            text, charge = response.text(), before - wallet()
            reasons = finish_reasons(text)
            results.append({
                'issue': 7489, 'url': 'https://github.com/QuantumNous/new-api/issues/7489',
                'name': f'final finish_reason survives with include_usage={include_usage}',
                'passed': response.status == 200 and reasons == ['stop'] and charge == 140,
                'include_usage': include_usage, 'direct_upstream_finish_reasons': ['stop'],
                'downstream_finish_reasons': reasons, 'downstream_done': 'data: [DONE]' in text,
                'platform_http': response.status, 'charge': charge,
            })
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()
    return results
