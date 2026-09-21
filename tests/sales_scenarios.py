"""Extra sales scenarios against the exact deployed app, with disposable fixtures only."""
import concurrent.futures
import json
import secrets
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from chat_integration import MODEL


class GeminiFixture(BaseHTTPRequestHandler):
    calls = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.calls.append({
            'path': self.path,
            'authenticated': self.headers.get('x-goog-api-key') == 'fixture-google-key',
            'has_contents': bool(body.get('contents')),
        })
        if ':streamGenerateContent' in self.path:
            interrupted = any(part.get('text') == 'INTERRUPT'
                              for content in body.get('contents', [])
                              for part in content.get('parts', []))
            first = {'candidates': [{'content': {'role': 'model', 'parts': [{'text': 'partial fixture'}]},
                                     'index': 0}],
                     'usageMetadata': {'promptTokenCount': 100, 'candidatesTokenCount': 5, 'totalTokenCount': 105}}
            wire = ('data: ' + json.dumps(first) + '\n\n').encode()
            if not interrupted:
                last = {'candidates': [{'content': {'role': 'model', 'parts': [{'text': ' completed'}]},
                                        'finishReason': 'STOP', 'index': 0}],
                        'usageMetadata': {'promptTokenCount': 100, 'candidatesTokenCount': 20, 'totalTokenCount': 120}}
                wire += ('data: ' + json.dumps(last) + '\n\n').encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            # A truncated HTTP body makes the interruption unambiguous, unlike a normal SSE EOF.
            self.send_header('Content-Length', str(len(wire) + (128 if interrupted else 0)))
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(wire)
            self.wfile.flush()
            self.close_connection = True
            return
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({
            'candidates': [{'content': {'role': 'model', 'parts': [{'text': 'Gemini fixture only'}]},
                            'finishReason': 'STOP', 'index': 0}],
            'usageMetadata': {'promptTokenCount': 100, 'candidatesTokenCount': 20, 'totalTokenCount': 120},
            'modelVersion': 'gemini-fixture',
        }).encode())


def run_sales_scenarios(browser, base, gateway, root, user, rt, ut, call, ok, provider):
    results = []
    uid = ok(user, 'GET', '/api/user/self', token=ut)['id']

    def wallet():
        return ok(user, 'GET', '/api/user/self', token=ut)['quota']

    def fund(amount):
        ok(root, 'POST', '/api/user/manage', {
            'id': uid, 'action': 'add_quota', 'mode': 'override', 'value': amount}, rt)
        assert wallet() == amount, 'fixture balance adjustment did not persist'

    def issue(**overrides):
        name = 'scenario-' + secrets.token_hex(4)
        fields = {'name': name, 'remain_quota': 100000, 'expired_time': -1,
                  'unlimited_quota': False, 'group': 'default',
                  'model_limits_enabled': True, 'model_limits': MODEL}
        fields.update(overrides)
        ok(user, 'POST', '/api/token/', fields, ut)
        rows = ok(user, 'GET', '/api/token/?p=1&size=100', token=ut)['items']
        key_id = next(row['id'] for row in rows if row['name'] == name)
        key = ok(user, 'POST', f'/api/token/{key_id}/key', token=ut)['key']
        if not key.startswith('sk-'):
            key = 'sk-' + key
        return key_id, key

    def request(key, content='fixture', model=MODEL, stream=False):
        return call(user, 'POST', '/v1/chat/completions', {
            'model': model, 'messages': [{'role': 'user', 'content': content}],
            'max_tokens': 128, 'stream': stream,
            **({'stream_options': {'include_usage': True}} if stream else {})}, key)

    def scenario(name, action):
        try:
            detail = action()
            results.append({'name': name, 'passed': True, 'detail': detail})
        except AssertionError as error:
            results.append({'name': name, 'passed': False, 'failure': str(error)})

    def deny(key, model=MODEL):
        before, count = wallet(), len(provider.requests)
        response = request(key, model=model)
        assert response.status in (401, 403), f'expected auth/quota rejection, HTTP {response.status}'
        assert wallet() == before, 'rejected request charged the customer'
        assert len(provider.requests) == count, 'rejected request reached upstream'
        return {'http': response.status, 'charge': 0, 'upstream_calls': 0}

    fund(1000000)
    _, active = issue()

    def stream_success():
        before = wallet()
        response = request(active, stream=True)
        assert response.status == 200, f'stream HTTP {response.status}'
        text = response.text()
        assert 'data: [DONE]' in text and 'completion_tokens' in text, 'missing stream completion/usage'
        assert before - wallet() == 140, 'stream did not charge exact reported usage'
        return {'http': 200, 'charge': 140, 'completed_sse': True}

    scenario('流式调用完成并按用量扣费', stream_success)

    def upstream_failure():
        before, count = wallet(), len(provider.requests)
        response = request(active, content='FAIL')
        assert response.status >= 400, 'upstream failure reported success'
        for _ in range(40):
            if wallet() == before:
                break
            time.sleep(0.1)
        assert wallet() == before, 'failed request precharge was not refunded'
        assert len(provider.requests) == count + 1, 'unexpected automatic retry'
        return {'http': response.status, 'charge': 0, 'upstream_calls': 1}

    scenario('上游503失败退款且不自动重试', upstream_failure)
    scenario('错误客户Key不能调用', lambda: deny('sk-fixture-invalid'))
    scenario('Key模型白名单之外不能调用', lambda: deny(active, 'not-purchased-fixture'))

    def expired():
        _, key = issue(expired_time=int(time.time()) - 60)
        return deny(key)

    scenario('过期Key不能调用', expired)

    def revoked():
        key_id, key = issue()
        ok(user, 'DELETE', f'/api/token/{key_id}', token=ut)
        return deny(key)

    scenario('删除Key后立即失效', revoked)

    def disabled():
        key_id, key = issue()
        ok(user, 'PUT', '/api/token/?status_only=true', {'id': key_id, 'status': 2}, ut)
        return deny(key)

    scenario('禁用Key后立即失效', disabled)

    def empty_key():
        _, key = issue(remain_quota=0)
        return deny(key)

    scenario('Key独立额度耗尽不能调用', empty_key)

    def empty_wallet():
        fund(0)
        try:
            _, key = issue(unlimited_quota=True)
            return deny(key)
        finally:
            fund(1000000)

    scenario('不限额Key不能绕过账户零余额', empty_wallet)

    def other_customer():
        ctx = browser.new_context()
        try:
            name, password = 'other_' + secrets.token_hex(4), secrets.token_urlsafe(24)
            ok(root, 'POST', '/api/user/', {'username': name, 'password': password, 'role': 1}, rt)
            token = ok(ctx, 'POST', '/api/user/login', {'username': name, 'password': password})['access_token']
            key_id, _ = issue()
            for method, path in [('GET', f'/api/token/{key_id}'),
                                 ('POST', f'/api/token/{key_id}/key'),
                                 ('DELETE', f'/api/token/{key_id}')]:
                response = call(ctx, method, path, token=token)
                assert response.status >= 400 or response.json().get('success') is False, (
                    'other customer accessed the first customer Key')
            ok(user, 'GET', f'/api/token/{key_id}', token=ut)
            logs = ok(ctx, 'GET', '/api/log/self/?p=1&page_size=100', token=token)['items']
            assert not logs, 'new customer can see another customer usage logs'
            return {'key_read_reveal_delete_denied': True, 'other_customer_usage_logs': 0}
        finally:
            ctx.close()

    scenario('两名客户的Key和使用记录互相隔离', other_customer)

    def parallel_requests(balance, count):
        fund(balance)
        before = wallet()
        def consumption_logs():
            return ok(user, 'GET', '/api/log/self/?p=1&page_size=100&type=2', token=ut)['items']
        previous_ids = {entry['id'] for entry in consumption_logs()}
        _, key = issue(unlimited_quota=True)
        barrier = threading.Barrier(count)

        def send_one(_):
            request_body = json.dumps({'model': MODEL, 'max_tokens': 128,
                'messages': [{'role': 'user', 'content': 'parallel fixture'}]}).encode()
            req = urllib.request.Request(base + '/v1/chat/completions', data=request_body,
                headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
            barrier.wait(timeout=10)
            try:
                with urllib.request.urlopen(req, timeout=30) as response:
                    response.read()
                    return response.status
            except urllib.error.HTTPError as error:
                error.read()
                return error.code

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=count) as pool:
                statuses = list(pool.map(send_one, range(count)))
            successes = statuses.count(200)
            assert all(code in (200, 403) for code in statuses), f'unexpected concurrent statuses {statuses}'
            # The relay flushes the HTTP body before settling usage. Wait for the ledger, not just EOF.
            started = time.monotonic()
            while True:
                remaining = wallet()
                records = [entry for entry in consumption_logs() if entry['id'] not in previous_ids]
                if remaining == before - successes * 140 and len(records) == successes:
                    break
                assert time.monotonic() - started < 5, (
                    f'concurrent settlement mismatch after 5s: before={before}, '
                    f'remaining={remaining}, successful={successes}, records={len(records)}')
                time.sleep(0.05)
            assert all(entry['quota'] == 140 for entry in records), 'concurrent per-call ledger mismatch'
            assert remaining >= 0, f'concurrent calls overspent wallet: balance={remaining}, successful={successes}'
            if balance >= 1000000:
                assert successes == count, f'sufficient balance only served {successes}/{count}'
            else:
                assert 0 < successes < count, f'boundary test needs both admitted and denied calls; got {statuses}'
            return {'requests': count, 'succeeded': successes, 'rejected': count - successes,
                    'charge': before - remaining, 'remaining': remaining,
                    'settled_records': len(records), 'settlement_wait_ms': round((time.monotonic() - started) * 1000)}
        finally:
            fund(1000000)

    scenario('充足余额下六路并发扣费一致', lambda: parallel_requests(1000000, 6))
    scenario('临界余额下并发请求不透支', lambda: parallel_requests(700, 6))

    def native_gemini():
        server = ThreadingHTTPServer((gateway, 0), GeminiFixture)
        GeminiFixture.calls = []
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            for option, value in [('ModelRatio', {MODEL: 1, 'private-fixture': 1, 'gemini-fixture': 1}),
                                  ('CompletionRatio', {MODEL: 2, 'gemini-fixture': 2})]:
                ok(root, 'PUT', '/api/option/', {'key': option, 'value': json.dumps(value)}, rt)
            ok(root, 'POST', '/api/channel/', {'mode': 'single', 'channel': {
                'name': 'native-gemini-fixture', 'type': 24, 'key': 'fixture-google-key',
                'base_url': f'http://{gateway}:{server.server_port}', 'models': 'gemini-fixture',
                'group': 'default', 'status': 1, 'weight': 1}}, rt)
            _, key = issue(model_limits='gemini-fixture')
            before = wallet()
            response = request(key, model='gemini-fixture')
            assert response.status == 200, f'Gemini adapter HTTP {response.status}'
            assert response.json()['choices'][0]['message']['content'] == 'Gemini fixture only'
            assert len(GeminiFixture.calls) == 1, 'Gemini upstream request count mismatch'
            info = GeminiFixture.calls[0]
            assert info['path'] in ('/v1beta/models/gemini-fixture:generateContent',
                                    '/v1/models/gemini-fixture:generateContent'), 'Gemini URL assembly incorrect'
            assert info['authenticated'] and info['has_contents'], 'Gemini protocol/auth translation failed'
            assert before - wallet() == 140, 'Gemini usage metadata billing mismatch'

            def gemini_stream():
                balance = wallet()
                streamed = request(key, model='gemini-fixture', stream=True)
                assert streamed.status == 200 and 'data: [DONE]' in streamed.text(), 'Gemini stream did not complete'
                assert balance - wallet() == 140, 'Gemini cumulative stream usage not billed exactly once'
                return {'http': 200, 'charge': 140, 'cumulative_usage': True}

            scenario('Gemini流式累计usage不重复扣费', gemini_stream)

            def gemini_interrupted():
                balance = wallet()
                interrupted = request(key, content='INTERRUPT', model='gemini-fixture', stream=True)
                text = interrupted.text()
                done = 'data: [DONE]' in text
                stream_error = '"error"' in text
                billed = balance - wallet()
                assert stream_error and not done and billed == 110, (
                    f'truncated Gemini upstream was returned as successful completion: '
                    f'HTTP={interrupted.status}, DONE={done}, explicit_error={stream_error}, billed={billed}')
                return {'http': interrupted.status, 'done': done, 'explicit_error': stream_error, 'charge': billed}

            scenario('Gemini上游中途断流不能伪装正常完成', gemini_interrupted)

            def interrupted_protocol(path, body):
                balance, calls = wallet(), len(GeminiFixture.calls)
                interrupted = call(user, 'POST', path, body, key)
                text = interrupted.text()
                billed = balance - wallet()
                assert '"error"' in text, f'missing explicit stream error: {path}'
                assert 'data: [DONE]' not in text and 'response.completed' not in text
                assert 'event: message_stop' not in text
                assert billed == 110, f'partial usage settlement changed: {path}, charged={billed}'
                assert len(GeminiFixture.calls) == calls + 1, f'interrupted request retried: {path}'
                return {'http': interrupted.status, 'explicit_error': True,
                        'charge': billed, 'upstream_calls': 1}

            scenario('Gemini原生入站断流显式错误且保留部分计费', lambda: interrupted_protocol(
                '/v1beta/models/gemini-fixture:streamGenerateContent?alt=sse',
                {'contents': [{'role': 'user', 'parts': [{'text': 'INTERRUPT'}]}]}))
            scenario('Gemini转Claude断流显式错误且不正常结束', lambda: interrupted_protocol(
                '/v1/messages', {'model': 'gemini-fixture', 'stream': True, 'max_tokens': 128,
                'messages': [{'role': 'user', 'content': 'INTERRUPT'}]}))
            scenario('Gemini转Responses断流失败终态且不重试', lambda: interrupted_protocol(
                '/v1/responses', {'model': 'gemini-fixture', 'stream': True, 'input': 'INTERRUPT'}))
            return {'native_type': 24, 'path': info['path'], 'charge': 140,
                    'real_google_contacted': False}
        finally:
            server.shutdown()
            server.server_close()

    scenario('Gemini原生渠道路径认证协议转换及计费', native_gemini)

    def reconcile():
        logs = ok(user, 'GET', '/api/log/self/?p=1&page_size=100&type=2', token=ut)['items']
        assert logs and all(item['user_id'] == uid for item in logs), 'usage records missing or ownership mismatch'
        assert all(item['quota'] in (140, 110) for item in logs), 'calls have inconsistent billed quota'
        return {'consumption_records': len(logs),
                'full_calls_140': sum(item['quota'] == 140 for item in logs),
                'partial_calls_110': sum(item['quota'] == 110 for item in logs)}

    scenario('使用日志归属和每笔消费金额一致', reconcile)
    return results
