#!/usr/bin/env python3
"""Native New API auth/billing + H5 browser acceptance against a local deterministic provider.

Disposable Docker network/database only. No production writes, real model or payment calls.
Only aggregate, non-secret evidence is written. All fixture credentials die with the containers.
"""
import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright
from public_site import verify_public_site
from console_interface import verify_auth_pages, verify_console_pages

ROOT = Path(__file__).resolve().parents[1]
MODEL = 'h5-fixture'
IMAGES = {
    'api': 'calciumion/new-api@sha256:846a5b12f6b3a78acbf59201ffc1d4f0b31c701d252eff8238cefa6ab3643029',
    'ingress': 'nginx@sha256:9874b7a098bbd4e9454941c9e3f87600d7a6e2bb081a06f453202933fe7520d1',
}


def docker(*args):
    result = subprocess.run(['docker', *args], text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f'Docker {args[0]} failed: {result.stderr[:600]}')
    return result.stdout.strip()


class Provider(BaseHTTPRequestHandler):
    requests = []
    lock = threading.Lock()

    def log_message(self, *args):
        pass  # Fixture prompts and credentials must not enter access logs.

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        assert self.path == '/v1/chat/completions'
        with self.lock:
            self.requests.append(body)
        text = body['messages'][-1]['content']
        if text == 'FAIL':
            self.send_response(503)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"error":{"message":"fixture unavailable","type":"server_error"}}')
            return
        usage = {'prompt_tokens': 100, 'completion_tokens': 20, 'total_tokens': 120}
        answer = 'FIXTURE ONLY: 中文 <img src=x onerror=alert(1)>'
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream' if body.get('stream') else 'application/json')
        self.end_headers()
        try:
            if not body.get('stream'):
                self.wfile.write(json.dumps({'id': 'fixture', 'object': 'chat.completion', 'model': MODEL,
                    'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': answer}, 'finish_reason': 'stop'}],
                    'usage': usage}).encode())
                return
            def event(payload):
                raw = ('data: ' + json.dumps(payload, ensure_ascii=False) + '\n\n').encode()
                # Deliberately split UTF-8 and SSE frames across writes.
                for start in range(0, len(raw), 7):
                    self.wfile.write(raw[start:start + 7])
                self.wfile.flush()
            for fragment in ['FIXTURE ONLY: ', '中文 ', '<img src=x onerror=alert(1)>']:
                event({'id': 'fixture', 'object': 'chat.completion.chunk', 'model': MODEL,
                       'choices': [{'index': 0, 'delta': {'content': fragment}, 'finish_reason': None}]})
                if text == 'SLOW':
                    time.sleep(1)
            if text == 'SLOW':
                for _ in range(6):
                    event({'choices': [{'index': 0, 'delta': {'content': ' slow'}, 'finish_reason': None}]})
                    time.sleep(1)
            event({'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}], 'usage': usage})
            self.wfile.write(b'data: [DONE]\n\n')
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass  # Expected only when exercising explicit browser cancellation.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='evidence/chat-integration')
    parser.add_argument('--api-image', default='modelport-new-api:auth-session-limits-v1')
    args = parser.parse_args()
    IMAGES['api'] = args.api_image
    output = (ROOT / args.output).resolve()
    assert output.is_relative_to(ROOT)
    output.mkdir(parents=True, exist_ok=True)
    tag = 'h5-test-' + secrets.token_hex(4)
    containers, networks = [], []
    provider = None
    report = {'provider': 'local deterministic fixture, NOT a real AI model',
              'production_writes': 0, 'paid_calls': 0, 'checks': [],
              'fixture_critical_rate_limit': 200}
    # Chrome creates and removes its own private profile; avoid Unix socket path limits.
    os.environ['TMPDIR'] = '/tmp'
    try:
        docker('network', 'create', '--internal', tag)
        networks.append(tag)
        docker('network', 'create', tag + '-edge')
        networks.append(tag + '-edge')
        gateway = json.loads(docker('network', 'inspect', tag))[0]['IPAM']['Config'][0]['Gateway']
        provider = ThreadingHTTPServer((gateway, 0), Provider)
        threading.Thread(target=provider.serve_forever, daemon=True).start()
        with tempfile.TemporaryDirectory(prefix=tag + '-', dir=ROOT) as directory:
            temp = Path(directory)
            shutil.copytree(ROOT / 'h5', temp / 'h5')
            config = (ROOT / 'nginx.conf').read_text()
            (temp / 'nginx.conf').write_text(config)
            for component in ['api', 'ingress']:
                name = tag + '-' + component
                cmd = ['run', '-d', '--name', name, '--network', tag, '--log-driver', 'none',
                       '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
                       '--user', '1000:1000', '--read-only',
                       '--tmpfs', '/tmp:rw,nosuid,size=256m,mode=1777', '--memory', '1g', '--cpus', '2']
                if component == 'api':
                    cmd += ['--network-alias', 'new-api',
                            '-e', 'SQLITE_PATH=/tmp/fixture.db', '-e', 'SESSION_COOKIE_SECURE=false',
                            '-e', 'BATCH_UPDATE_ENABLED=false', '-e', 'ERROR_LOG_ENABLED=true',
                            # Many viewport reloads share one fixture IP; production keeps its own limit.
                            '-e', 'CRITICAL_RATE_LIMIT=200',
                            '-e', 'NODE_NAME=h5-isolated-test',
                            IMAGES[component], '--port', '3000', '--log-dir', '/tmp/logs']
                else:
                    cmd += ['--network', tag + '-edge', '-p', '127.0.0.1::8080',
                            '-v', f'{temp / "nginx.conf"}:/etc/nginx/nginx.conf:ro',
                            '-v', f'{temp / "h5"}:/srv/h5:ro', '--entrypoint', 'nginx',
                            '-v', f'{ROOT / "console-dist"}:/srv/modelport-console:ro',
                            IMAGES[component], '-g', 'daemon off;']
                docker(*cmd)
                containers.append(name)
            port = docker('port', containers[-1], '8080/tcp').rsplit(':', 1)[1]
            base = 'http://127.0.0.1:' + port
            for attempt in range(60):
                try:
                    with urlopen(base + '/api/setup', timeout=2) as response:
                        if json.load(response)['success']:
                            break
                except OSError:
                    if attempt == 59:
                        raise
                    time.sleep(1)
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path='/usr/bin/google-chrome',
                    headless=True, chromium_sandbox=True, args=['--disable-gpu'])
                report['public_site'] = verify_public_site(browser, base, output / 'public-site')
                admin_context = browser.new_context(locale='en-US', reduced_motion='reduce')
                admin_page = admin_context.new_page()
                admin_password = secrets.token_urlsafe(24)
                setup = admin_context.request.post(base + '/api/setup', data={
                    'username': 'fixtureadmin', 'password': admin_password, 'confirmPassword': admin_password,
                    'SelfUseModeEnabled': False, 'DemoSiteEnabled': False})
                assert setup.json()['success'], 'isolated setup failed'

                def login(page, username, password, workspace=False):
                    if workspace:
                        page.goto(base + '/h5/#login')
                        page.locator('#native-login').click()
                    else:
                        page.goto(base + '/sign-in?redirect=%2Fpricing')
                    page.locator('input[name="username"]').fill(username)
                    page.locator('input[name="password"]').fill(password)
                    with page.expect_response(lambda r: '/api/user/login' in r.url and r.request.method == 'POST') as response:
                        page.locator('form button[type="submit"]').click()
                    if workspace:
                        assert response.value.ok
                        page.wait_for_url(base + '/h5/#chat')
                        expect(page.locator('#chat-session')).to_contain_text('已登录：' + username)
                        # The document navigation discards Chrome's old response body.
                        # Read only the fixture session restored by the actual H5 refresh path.
                        return page.evaluate('authBundle')
                    result = response.value.json()
                    assert result.get('success') and result.get('data', {}).get('access_token'), 'native login failed'
                    page.wait_for_url(base + '/pricing')
                    return result['data']

                admin_bundle = login(admin_page, 'fixtureadmin', admin_password)
                def call(context, method, path, data=None, token=None, success=True):
                    headers = {'Authorization': 'Bearer ' + token} if token else {}
                    response = context.request.fetch(base + path, method=method, data=data, headers=headers)
                    if not success:
                        return response
                    result = response.json()
                    assert response.ok and result.get('success'), f'{method} {path}: {response.status} {result.get("message", "")}'
                    return result.get('data')

                for key, value in [('QuotaForNewUser', '1000000'), ('RegisterEnabled', 'true'),
                                   ('PasswordRegisterEnabled', 'true'), ('EmailVerificationEnabled', 'false'),
                                   ('ModelRatio', json.dumps({MODEL: 1, 'h5-private': 1})),
                                   ('CompletionRatio', json.dumps({MODEL: 2, 'h5-private': 2})),
                                   ('GroupRatio', json.dumps({'default': 1, 'vip': 0.6})),
                                   ('RetryTimes', '0')]:
                    call(admin_context, 'PUT', '/api/option/', {'key': key, 'value': value}, admin_bundle['access_token'])
                for name, group, model in [('fixture', 'default', MODEL), ('vip', 'vip', MODEL), ('private', 'private', 'h5-private')]:
                    call(admin_context, 'POST', '/api/channel/', {'mode': 'single', 'channel': {
                        'name': name, 'type': 1, 'key': 'fixture-not-a-real-provider-key',
                        'base_url': f'http://{gateway}:{provider.server_port}', 'models': model,
                        'group': group, 'status': 1, 'priority': 0, 'weight': 1}}, admin_bundle['access_token'])
                report['checks'].append('native isolated initialization and channel configuration')
                verify_auth_pages(browser, base, output / 'auth-interface')
                report['admin_console'] = verify_console_pages(admin_context, base, output / 'admin-interface', admin=True)
                admin_page.set_viewport_size({'width': 1440, 'height': 960})
                admin_errors = []
                admin_page.on('pageerror', lambda error: admin_errors.append(str(error)))
                admin_page.goto(base + '/h5/#operations')
                expect(admin_page.locator('#operations-content')).to_be_visible()
                expect(admin_page.locator('[data-admin-permission="channel.read"]')).to_have_attribute('href', '/channels')
                expect(admin_page.locator('[data-admin-permission="audit.read"]')).to_have_attribute('href', '/usage-logs/audit')
                admin_page.locator('#operations-refresh').click()
                expect(admin_page.locator('#operations-state')).to_contain_text('暂无调用样本')
                expect(admin_page.locator('#operations-models')).to_contain_text('无近期样本 · 未知')
                assert not Provider.requests, 'read-only operations triggered a paid inference path'
                report['checks'].append('native administrator capability links and empty metrics never claim healthy')
                admin_page.goto(base + '/h5/#about')
                expect(admin_page.locator('#about')).to_be_visible()
                assert '平台运营者' not in admin_page.locator('#about').inner_text()
                assert admin_page.locator('[data-admin-only]:visible').count() == 0
                admin_page.locator('.public-nav [data-tab=models]').click()
                expect(admin_page.locator('#models-title')).to_have_text('模型与价格')
                expect(admin_page.locator('.workspace-sidebar')).to_be_hidden()
                assert admin_page.locator('[data-admin-only]:visible').count() == 0
                admin_page.goto(base + '/h5/#operations')
                expect(admin_page.locator('#operations-content')).to_be_visible()
                report['checks'].append('public introduction/catalog omit operator entry even for authenticated administrators')
                context = browser.new_context(viewport={'width': 390, 'height': 844}, locale='en-US', reduced_motion='reduce')
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                password = secrets.token_urlsafe(24)
                page.goto(base + '/h5/#register')
                expect(page.locator('#register-continue')).to_have_attribute('href', '/register')
                assert page.locator('#register form, #register input').count() == 0
                page.locator('#register-continue').click()
                page.wait_for_url(base + '/sign-up')
                page.locator('input[name="username"]').fill('fixtureclient')
                page.locator('input[name="password"]').fill(password)
                page.locator('input[name="confirmPassword"]').fill(password)
                with page.expect_response(lambda r: '/api/user/register' in r.url and r.request.method == 'POST') as registration:
                    page.locator('form button[type="submit"]').click()
                assert registration.value.json()['success'], 'unified registration failed'
                page.wait_for_url('**/sign-in*')
                customer = login(page, 'fixtureclient', password, workspace=True)
                token = customer['access_token']
                for caller, access_token in [(context, token), (admin_context, admin_bundle['access_token'])]:
                    for path in ['/api/user/self', '/api/user/self/', '/api/user/self?confirm=true']:
                        blocked = call(caller, 'DELETE', path, token=access_token, success=False)
                        assert blocked.status == 403
                        assert blocked.json()['code'] == 'SELF_ACCOUNT_DELETION_DISABLED'
                        assert blocked.json()['success'] is False
                    assert call(caller, 'GET', '/api/user/self', token=access_token)['id'] > 0
                before_profile = call(context, 'GET', '/api/user/self', token=token)
                call(context, 'PUT', '/api/user/self', {
                    'id': customer['user']['id'], 'username': before_profile['username'],
                    'display_name': 'Fixture retained'}, token)
                retained = call(context, 'GET', '/api/user/self', token=token)
                assert retained['display_name'] == 'Fixture retained'
                assert retained['quota'] == before_profile['quota']
                assert retained['used_quota'] == before_profile['used_quota']
                bypass = call(context, 'DELETE', '/api/user/' + str(customer['user']['id']), token=token, success=False)
                assert bypass.status == 403
                assert call(context, 'GET', '/api/user/self', token=token)['id'] == customer['user']['id']
                report['checks'].append('self-deletion denied for customer/admin; profile update, balance and session retained; admin-path bypass denied')
                report['checks'].append('single H5 registration entry -> native compiled registration -> login (ephemeral test account)')
                expect(page.locator('#chat-session')).to_contain_text('已登录：fixtureclient')
                expect(page.locator('#chat [data-tab="login"]')).to_have_text('账户与安全')
                expect(page.locator('#session-refresh')).to_have_text('刷新权限')
                report['customer_console'] = verify_console_pages(context, base, output / 'customer-interface')
                page.goto(base + '/h5/#login')
                expect(page.locator('#native-login')).to_have_attribute('href', '/security')
                page.locator('#native-login').click()
                page.wait_for_url(base + '/security')
                for route in ['/sign-in', '/sign-up']:
                    page.goto(base + route)
                    page.wait_for_url(base + '/h5/#chat')
                    expect(page.locator('#chat-session')).to_contain_text('已登录：fixtureclient')
                report['checks'].append('branded auth, customer and admin pages; full-document login return restores H5 session')
                page.goto(base + '/h5/#chat')
                expect(page.locator('#chat-session')).to_contain_text('已登录：fixtureclient')
                assert page.locator('[data-admin-only]:visible').count() == 0
                rejected_ops = call(context, 'GET', '/api/channel/ops', token=token, success=False)
                assert rejected_ops.status == 403
                expect(page.locator('#chat-model')).to_have_value('')
                expect(page.locator('#chat-send')).to_be_disabled()
                page.locator('#chat-model').select_option(MODEL)
                before = call(context, 'GET', '/api/user/self', token=token)
                def send(text):
                    previous_count = page.locator('#chat-messages article').count()
                    page.locator('#chat-input').fill(text)
                    expect(page.locator('#chat-send')).to_be_enabled()
                    page.locator('#chat-send').click()
                    expect(page.locator('#chat-messages article')).to_have_count(previous_count + 2)
                send('Hello')
                expect(page.locator('#chat-messages article').last).to_contain_text('已完成', timeout=30000)
                expect(page.locator('#chat-messages article').last).to_contain_text('中文 <img')
                assert page.locator('#chat-messages img').count() == 0
                after = call(context, 'GET', '/api/user/self', token=token)
                assert before['quota'] - after['quota'] == 140, (before['quota'], after['quota'])
                assert after['used_quota'] - before['used_quota'] == 140
                send('Second turn')
                expect(page.locator('#chat-messages article').last).to_contain_text('已完成')
                assert len(Provider.requests[-1]['messages']) == 3
                assert len(Provider.requests) == 2
                admin_page.locator('#operations-refresh').click()
                expect(admin_page.locator('#operations-state')).to_contain_text('1 个模型有近期观测')
                expect(admin_page.locator('#operations-models')).to_contain_text(MODEL)
                expect(admin_page.locator('#operations-models')).to_contain_text('100%')
                assert len(Provider.requests) == 2, 'passive metrics caused an inference'
                logs = call(context, 'GET', '/api/log/self/?p=1&page_size=20', token=token)
                items = logs.get('items', []) if isinstance(logs, dict) else logs
                consume = [entry for entry in items if entry.get('type') == 2]
                assert len(consume) == 2 and all(entry['quota'] == 140 for entry in consume)
                report['checks'].append('SSE Chinese/text safety, explicit model, multi-turn context, exact 140-unit charge and own logs')

                call(context, 'POST', '/api/token/', {'name': 'fixture-client-api', 'remain_quota': 10000,
                    'expired_time': -1, 'group': 'default', 'unlimited_quota': False}, token)
                keys = call(context, 'GET', '/api/token/?p=1&size=10', token=token)
                key_id = keys['items'][0]['id']
                key = call(context, 'POST', f'/api/token/{key_id}/key', token=token)['key']
                quota_before_api = call(context, 'GET', '/api/user/self', token=token)['quota']
                api_response = call(context, 'POST', '/v1/chat/completions', {
                    'model': MODEL, 'messages': [{'role': 'user', 'content': 'Developer API'}], 'max_tokens': 1024},
                    key, success=False)
                assert api_response.ok and api_response.json()['choices'][0]['message']['content'].startswith('FIXTURE')
                assert quota_before_api - call(context, 'GET', '/api/user/self', token=token)['quota'] == 140
                report['checks'].append('developer API and H5 debit the same customer wallet')

                quota_before_fail = call(context, 'GET', '/api/user/self', token=token)['quota']
                count = len(Provider.requests)
                send('FAIL')
                expect(page.locator('#chat-messages article').last).to_contain_text('调用失败', timeout=30000)
                assert call(context, 'GET', '/api/user/self', token=token)['quota'] == quota_before_fail
                assert len(Provider.requests) == count + 1, 'unexpected chargeable request retry'
                error_logs = call(admin_context, 'GET', '/api/log/?p=1&page_size=20&type=5',
                                  token=admin_bundle['access_token'])
                assert any(entry['type'] == 5 and entry['model_name'] == MODEL
                           for entry in error_logs['items']), 'native error logging is not active'
                admin_page.locator('#operations-refresh').click()
                expect(admin_page.locator('#operations-models')).to_contain_text('近期有失败')
                admin_page.evaluate('window.scrollTo(0, 0)')
                admin_page.screenshot(path=str(output / 'fixture-operations-1440.png'), full_page=True)
                report['checks'].append('real passive success/failure metrics and native persisted upstream error logs')
                send('After failure')
                expect(page.locator('#chat-messages article').last).to_contain_text('已完成')
                assert all(m['content'] != 'FAIL' for m in Provider.requests[-1]['messages'])
                report['checks'].append('503 precharge refund, no automatic retry, failed turn excluded from context')
                send('SLOW')
                expect(page.locator('#chat-messages article').last).to_contain_text('FIXTURE', timeout=30000)
                page.locator('#chat-stop').click()
                expect(page.locator('#chat-messages article').last).to_contain_text('已停止接收')
                expect(page.locator('#chat-send')).to_be_visible()
                assert page.locator('#chat-input').input_value() == 'SLOW'
                report['checks'].append('real stream cancellation and explicit billing uncertainty')

                # Fault injection is limited to the browser transport, not billed as real upstream work.
                for payload, expected_error in [
                    ('data: {"choices":[{"delta":{"content":"partial"}}]}\n\n', '连接在完成标记前断开'),
                    ('data: not-json\n\n', '模型事件流格式异常'),
                    ('data: {"error":{"message":"fixture error"}}\n\n', '模型返回错误'),
                ]:
                    provider_count = len(Provider.requests)
                    page.route('**/pg/chat/completions', lambda route:
                        route.fulfill(status=200, content_type='text/event-stream', body=payload))
                    send('Browser-only transport fault')
                    expect(page.locator('#chat-messages article').last).to_contain_text(expected_error)
                    page.unroute('**/pg/chat/completions')
                    assert len(Provider.requests) == provider_count
                report['checks'].append('browser-only fault injection: truncated SSE, malformed JSON, streamed errors fail explicitly')

                page.evaluate('authBundle.access_expires_at = 0')
                with page.expect_response(lambda r: r.url.endswith('/api/user/auth/refresh')) as refreshed:
                    page.locator('#session-refresh').click()
                renewed = refreshed.value.json()
                assert renewed['success'], 'native refresh failed'
                token = renewed['data']['access_token']
                expect(page.locator('#chat-session')).to_contain_text('已登录：fixtureclient')
                report['checks'].append('native refresh-cookie rotation restores expired in-memory access token')

                # Server-side authorization, independent of H5 disabling controls.
                forbidden = call(context, 'POST', '/pg/chat/completions', {
                    'model': 'h5-private', 'group': 'private',
                    'messages': [{'role': 'user', 'content': 'Not authorized'}]}, token, success=False)
                assert forbidden.status == 403
                anonymous = browser.new_context()
                rejected = call(anonymous, 'POST', '/pg/chat/completions', {
                    'model': MODEL, 'messages': [{'role': 'user', 'content': 'Anonymous'}]}, success=False)
                assert rejected.status == 401
                report['checks'].append('backend rejects anonymous calls and unauthorized group/model')
                anonymous.close()

                call(admin_context, 'PUT', '/api/option/', {'key': 'QuotaForNewUser', 'value': '0'}, admin_bundle['access_token'])
                other_context = browser.new_context(locale='en-US')
                other_password = secrets.token_urlsafe(24)
                call(other_context, 'POST', '/api/user/register', {'username': 'fixtureempty', 'password': other_password})
                other_customer = login(other_context.new_page(), 'fixtureempty', other_password)
                other_token = other_customer['access_token']
                provider_count = len(Provider.requests)
                insufficient = call(other_context, 'POST', '/pg/chat/completions', {
                    'model': MODEL, 'messages': [{'role': 'user', 'content': 'No balance'}],
                    'max_tokens': 1024}, other_token, success=False)
                assert insufficient.status == 403 and len(Provider.requests) == provider_count
                foreign_key = call(other_context, 'POST', f'/api/token/{key_id}/key', token=other_token, success=False)
                assert foreign_key.json().get('success') is False
                other_logs = call(other_context, 'GET', '/api/log/self/?p=1&page_size=20', token=other_token)
                assert not other_logs['items']
                other_context.close()
                report['checks'].append('zero-balance rejection before upstream, cross-account Key and log isolation')
                # Execute the exact downloadable examples with fixture-only credentials.
                sample_env = {**os.environ, 'PLATFORM_BASE_URL': base + '/v1',
                              'PLATFORM_API_KEY': key, 'PLATFORM_MODEL': MODEL}
                quota_before_samples = call(context, 'GET', '/api/user/self', token=token)['quota']
                count_before_samples = len(Provider.requests)
                for executable, sample in [(sys.executable, 'chat.py'), ('node', 'chat.mjs')]:
                    run = subprocess.run([executable, str(ROOT / 'h5/examples' / sample)],
                                         env=sample_env, capture_output=True, text=True, timeout=75)
                    assert run.returncode == 0 and 'FIXTURE ONLY' in run.stdout, f'{sample} fixture call failed'
                    assert key not in run.stdout + run.stderr
                request_body = json.loads((ROOT / 'h5/examples/request.json').read_text())
                request_body['model'] = MODEL
                run = subprocess.run(['curl', '--fail-with-body', '--silent', '--show-error', '--max-time', '60',
                    '--request', 'POST', base + '/v1/chat/completions', '--header', '@-',
                    '--header', 'Content-Type: application/json', '--data-binary', json.dumps(request_body)],
                    input='Authorization: Bearer ' + key + '\n', capture_output=True, text=True, timeout=75)
                assert run.returncode == 0 and 'FIXTURE ONLY' in run.stdout, 'cURL fixture call failed'
                assert key not in run.stdout + run.stderr
                assert len(Provider.requests) == count_before_samples + 3
                assert quota_before_samples - call(context, 'GET', '/api/user/self', token=token)['quota'] == 420
                # Both language examples fail without reaching a supplier for an invalid Key.
                count_before_samples = len(Provider.requests)
                for executable, sample in [(sys.executable, 'chat.py'), ('node', 'chat.mjs')]:
                    run = subprocess.run([executable, str(ROOT / 'h5/examples' / sample)],
                        env={**sample_env, 'PLATFORM_API_KEY': 'fixture-invalid-key'},
                        capture_output=True, text=True, timeout=75)
                    assert run.returncode != 0
                    assert 'fixture-invalid-key' not in run.stdout + run.stderr
                assert len(Provider.requests) == count_before_samples
                report['checks'].append('exact Python/Node/cURL tutorial examples debit the same wallet; invalid Key fails without inference or secret output')

                for width in [360, 390, 430, 1024, 1440]:
                    page.set_viewport_size({'width': width, 'height': 844})
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    heights = page.locator('#chat > .actions .btn').evaluate_all(
                        'buttons => buttons.map(button => button.getBoundingClientRect().height)')
                    assert all(44 <= height <= 66 for height in heights), heights
                    page.evaluate('window.scrollTo(0, 0)')
                    page.screenshot(path=str(output / f'fixture-chat-{width}.png'), full_page=True)
                expect(page.locator('.workspace-sidebar')).to_be_visible()
                page.locator('.side-nav [data-tab=models]').click()
                expect(page.locator('.workspace-sidebar')).to_be_hidden()
                expect(page.locator('.public-nav')).to_be_visible()
                page.locator('#catalog-group').select_option('vip')
                expect(page.locator('#model-list article')).to_have_count(1)
                expect(page.locator('#model-list')).to_contain_text('vip：输入 USD 1.2')
                expect(page.locator('#model-list')).not_to_contain_text('default：')
                page.locator('#catalog-search').fill('no-such-model')
                expect(page.locator('#catalog-filter-state')).to_contain_text('显示 0')
                expect(page.locator('#model-select')).to_have_value(MODEL)
                page.locator('#catalog-search').fill(MODEL)
                expect(page.locator('#model-list article')).to_have_count(1)
                page.evaluate('window.scrollTo(0, 0)')
                page.screenshot(path=str(output / 'fixture-catalog-1440.png'), full_page=True)
                assert call(context, 'GET', '/api/user/self', token=token)['group'] == 'default'
                page.locator('.public-nav [data-tab=chat]').click()
                page.locator('#sidebar-history button').first.click()
                expect(page.locator('#chat')).to_be_visible()
                expect(page.locator('#chat-messages article')).not_to_have_count(0)
                report['checks'].append('desktop sidebar/history, group price/search filters do not switch billing group or selected model')
                storage = page.evaluate('({local:Object.keys(localStorage),session:Object.keys(sessionStorage)})')
                assert not any('access' in key.lower() or 'token' in key.lower() for key in storage['local'] + storage['session'])
                report['checks'].append('three mobile and two desktop widths, no access-token storage')
                # A customer cannot reveal administrator data by navigating to the hash directly.
                page.evaluate("location.hash = 'operations'")
                expect(page.locator('#operations-gate')).to_contain_text('不是管理员')
                expect(page.locator('#operations-content')).to_be_hidden()
                assert page.locator('#operations-content a[href]').count() == 0
                page.locator('.side-nav [data-tab=chat]').click()
                # Malformed telemetry must be an explicit error, never a healthy-looking fallback.
                admin_page.route('**/api/perf-metrics/summary?hours=24', lambda route:
                    route.fulfill(json={'success': True, 'data': {'models': [{'model_name': MODEL, 'success_rate': -1}]}}))
                admin_page.locator('#operations-refresh').click()
                expect(admin_page.locator('#operations-state')).to_contain_text('统计格式异常')
                expect(admin_page.locator('#operations-models tr')).to_have_count(0)
                admin_page.unroute('**/api/perf-metrics/summary?hours=24')
                # Late in-flight data must not repopulate a signed-out administrator's panel.
                pending_metrics = []
                admin_page.route('**/api/perf-metrics/summary?hours=24', lambda route: pending_metrics.append(route))
                with admin_page.expect_request(lambda request: '/api/perf-metrics/summary?' in request.url):
                    admin_page.locator('#operations-refresh').click()
                call(admin_context, 'POST', '/api/user/auth/logout', token=admin_bundle['access_token'])
                admin_page.evaluate("""() => onSessionEvent({kind:'signed_out',
                    sid:authBundle.session.sid,timestamp:Date.now()})""")
                assert len(pending_metrics) == 1
                pending_metrics[0].fulfill(json={'success': True, 'data': {'models': [{
                    'model_name': 'late-fixture', 'success_rate': 100, 'avg_latency_ms': 1, 'avg_tps': 1}]}})
                expect(admin_page.locator('#operations-content')).to_be_hidden()
                expect(admin_page.locator('#operations-models tr')).to_have_count(0)
                assert not admin_errors, admin_errors
                report['checks'].append('client admin-route denial, telemetry validation and signed-out late-response isolation')
                # Native logout + native sync event must purge the H5 messages immediately.
                call(context, 'POST', '/api/user/auth/logout', token=token)
                other = context.new_page()
                other.goto(base + '/h5/')
                other.evaluate("""() => { const c = new BroadcastChannel('new-api:auth-session');
                    c.postMessage({kind:'signed_out',sid:'unused',timestamp:Date.now()}); c.close(); }""")
                # The event SID must match; an unrelated session must not clear this session.
                assert page.locator('#chat-messages article').count() > 0
                other.evaluate("""sid => { const c = new BroadcastChannel('new-api:auth-session');
                    c.postMessage({kind:'signed_out',sid,timestamp:Date.now()}); c.close(); }""", customer['session']['sid'])
                expect(page.locator('#chat-messages article')).to_have_count(0)
                expect(page.locator('#chat-send')).to_be_disabled()
                page.locator('#session-refresh').click()
                expect(page.locator('#chat-session')).to_contain_text('未登录')
                expect(page.locator('#chat [data-tab="login"]')).to_have_text('登录账户')
                revoked = call(context, 'GET', '/api/user/self', token=token, success=False)
                assert revoked.status == 401
                report['checks'].append('native logout revocation, cross-tab identity isolation and chat purge')
                assert not errors, errors
                report['page_errors'] = errors
                report['completed'] = True
                browser.close()
    finally:
        if provider:
            provider.shutdown()
            provider.server_close()
        cleanup_errors = []
        for name in reversed(containers):
            result = subprocess.run(['docker', 'rm', '-f', name], capture_output=True, text=True)
            if result.returncode:
                cleanup_errors.append(name)
        for network in reversed(networks):
            result = subprocess.run(['docker', 'network', 'rm', network], capture_output=True, text=True)
            if result.returncode:
                cleanup_errors.append(network)
        report['cleanup_errors'] = cleanup_errors
        (output / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if cleanup_errors:
            raise RuntimeError('Fixture cleanup failed: ' + ', '.join(cleanup_errors))


if __name__ == '__main__':
    main()
