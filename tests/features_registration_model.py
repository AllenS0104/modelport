#!/usr/bin/env python3
"""Real Chrome H5 interaction acceptance; business mocks are browser-only, labelled and never forwarded."""
import argparse
import base64
import datetime
import hashlib
import http.client
import json
import os
import re
import secrets
import time
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
BASE = 'http://127.0.0.1:13000'
WIDTHS = (360, 390, 430)
SAFE_STATUS_KEYS = ['version', 'register_enabled', 'password_register_enabled', 'password_login_enabled', 'password_login_encryption_enabled', 'email_verification', 'turnstile_check', 'user_agreement_enabled', 'privacy_policy_enabled']


def get(path):
    conn = http.client.HTTPConnection('127.0.0.1', 13000, timeout=15)
    conn.request('GET', path)
    response = conn.getresponse()
    body, headers, status = response.read(), dict(response.getheaders()), response.status
    conn.close()
    if status == 429:
        time.sleep(int(headers.get('Retry-After', '180')))
        return get(path)
    return status, headers, body


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='evidence/features-registration-model/acceptance')
    parser.add_argument('--browser', default='/usr/bin/google-chrome')
    parser.add_argument('--width', type=int, choices=WIDTHS, help='Optional single viewport for focused debugging')
    parser.add_argument('--mock-only', action='store_true', help='Skip real browser navigation (public API preflight still live)')
    args = parser.parse_args()
    out = (ROOT / args.output).resolve()
    assert out.is_relative_to(ROOT)
    out.mkdir(parents=True, exist_ok=True)
    # Chromium's Unix socket path must fit sun_path; keep temp names short and project-scoped.
    temp = ROOT / '.browser-tmp'
    temp.mkdir(exist_ok=True)
    os.environ['TMPDIR'] = str(temp)
    report = {'timestamp': datetime.datetime.now().astimezone().isoformat(), 'real': [], 'mock': [], 'offline': [], 'forwarded_business_writes': 0}
    # Save only public switch values and public anonymous directory, never cookies/tokens/auth request bodies.
    native_status = json.loads(get('/api/status')[2])
    report['real_api'] = {'status': {k: native_status['data'].get(k) for k in SAFE_STATUS_KEYS}, 'setup': json.loads(get('/api/setup')[2]), 'pricing': json.loads(get('/api/pricing')[2]), 'anonymous_self_http': get('/api/user/self')[0]}
    if not args.mock_only:
        assert report['real_api']['setup']['data']['status'] is False, 'Use --mock-only after initialization; console_interface.py provides read-only live checks.'
        assert report['real_api']['pricing']['data'] == []
    status, headers, body = get('/h5/')
    assert status == 200 and body == (ROOT / 'h5/index.html').read_bytes()
    csp = headers['Content-Security-Policy']
    style = re.search(r'<style>(.*?)</style>', body.decode(), re.S)[1].encode()
    for content in (style, (ROOT / 'h5/features.js').read_bytes()):
        assert 'sha256-' + base64.b64encode(hashlib.sha256(content).digest()).decode() in csp
    assert "'unsafe-inline'" not in csp and "connect-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert get('/h5/features.js')[1]['Content-Type'] == 'application/javascript'
    report['h5_csp'] = 'Exact SHA256, SRI, same-origin connect; no unsafe-inline; JS MIME verified'
    offline = out / 'h5-offline.html'
    html = (ROOT / 'h5/index.html').read_text()
    html = re.sub(r'<script src="features.js"[^>]*></script>', lambda _: '<script>' + (ROOT / 'h5/features.js').read_text() + '</script>', html)
    offline.write_text(html)
    assets = {}

    def static(route):
        request = route.request
        url = request.url
        if url.startswith('file:'):
            route.continue_()
            return
        assert url.startswith(BASE + '/'), 'external request prohibited'
        path = urlsplit(url).path
        if Path(path).suffix in ('.js', '.css', '.woff', '.woff2', '.ttf', '.svg', '.png', '.ico'):
            if url not in assets:
                response = route.fetch()
                if response.status == 429:
                    time.sleep(int(response.headers.get('retry-after', '180')))
                    response = route.fetch()
                assert response.status == 200, (path, response.status)
                assets[url] = (response.headers, response.body())
            headers, body = assets[url]
            route.fulfill(status=200, headers=headers, body=body)
        else:
            route.continue_()

    def metrics(page):
        actual = page.evaluate('''() => ({width: innerWidth, scroll: document.documentElement.scrollWidth,
          panels: document.querySelectorAll('.panel:not([hidden])').length,
          smallControls: [...document.querySelectorAll('button,input,select,.btn')].filter(e => e.offsetWidth && e.offsetHeight && e.getBoundingClientRect().height < 44).length})''')
        assert actual['scroll'] <= actual['width'], actual
        if page.locator('.panel').count():
            assert actual['smallControls'] == 0, actual
            assert actual['panels'] == 1
        # Unmodified native page controls are measured separately, not claimed as H5 44px passes.
        return actual

    def label_mock(page):
        page.evaluate('''() => {const note = document.querySelector('.notice');
          if(note) note.textContent = '隔离 MOCK 验收 · 虚构测试模型/响应，不代表真实账户或销售数据。';
          {let banner=document.getElementById('mock-banner'); if(!banner){banner=document.createElement('div');banner.id='mock-banner'; document.body.prepend(banner);}
            banner.textContent='隔离 MOCK 验收 · 非真实账户 / 模型';
            banner.style.cssText='position:fixed;left:0;right:0;z-index:2147483647;background:#fff1c7;color:#603c00;padding:8px;font-size:12px;text-align:center';
            if(note) banner.style.top='0'; else banner.style.bottom='0';}}''')

    def snapshot(page, name, mocked=False):
        if mocked:
            label_mock(page)
        page.screenshot(path=str(out / (name + '.png')), full_page=False, animations='disabled')

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=args.browser, headless=True, chromium_sandbox=True, args=['--disable-gpu'])
        report['browser'] = browser.version
        for width in (() if args.mock_only else ([args.width] if args.width else WIDTHS)):
            context = browser.new_context(viewport={'width': width, 'height': 844}, is_mobile=True, has_touch=True, locale='zh-CN', device_scale_factor=1)
            writes, errors = [], []
            def real_route(route):
                req = route.request
                if req.method not in ('GET', 'HEAD'):
                    writes.append(urlsplit(req.url).path)
                    route.abort()
                    return
                if not req.url.startswith(BASE + '/') and not req.url.startswith('file:'):
                    route.abort()
                    return
                static(route)
            context.route('**/*', real_route)
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(BASE + '/h5/')
            expect(page.locator('#setup-state')).to_have_text('等待管理员初始化')
            for tab in ('home', 'models', 'keys', 'wallet', 'account'):
                if tab == 'keys':
                    page.locator('#models [data-tab=developer]').click()
                page.locator(f'[data-tab="{tab}"]:visible').first.tap()
                expect(page.locator('#' + tab)).to_be_visible()
                assert page.evaluate('scrollY') == 0
                assert page.locator(f'.nav[data-tab="{tab}"]').get_attribute('aria-current') == 'page'
                metrics(page)
            page.locator('#account [data-tab="register"]').tap()
            expect(page.locator('#auth-gate')).to_contain_text('需管理员完成初始化')
            expect(page.locator('#register-continue')).to_have_attribute('aria-disabled', 'true')
            assert page.locator('#register-continue').get_attribute('href') is None
            assert page.locator('#register form, #register input, #register [href="/setup"]').count() == 0
            metrics(page)
            snapshot(page, f'real-register-{width}')
            page.reload()
            expect(page.locator('#register')).to_be_visible()
            expect(page.locator('#register-continue')).to_have_attribute('aria-disabled', 'true')
            page.locator('#register [data-tab="login"]').tap()
            expect(page.locator('#login')).to_be_visible()
            metrics(page)
            snapshot(page, f'real-login-{width}')
            page.locator('#native-login').tap()
            page.wait_for_url(BASE + '/setup')
            page.get_by_text('初始化 New API', exact=True).wait_for()
            snapshot(page, f'real-native-setup-{width}')
            page.goto(BASE + '/h5/#models')
            expect(page.locator('#catalog-state')).to_contain_text('暂无可见模型')
            expect(page.locator('#model-select')).to_be_disabled()
            expect(page.locator('#example')).to_be_hidden()
            metrics(page)
            snapshot(page, f'real-models-empty-{width}')
            assert not writes and not errors, (writes, errors)
            report['real'].append({'width': width, 'navigation_validation_gating_refresh': 'pass', 'native_login_final': '/setup', 'models': 'real empty; disabled; no example', 'business_writes': 0, 'pageerrors': []})
            page.goto(offline.as_uri())
            expect(page.locator('#service-state')).to_contain_text('离线展示')
            page.locator('#home [data-tab="register"]').tap()
            expect(page.locator('#register-continue')).to_have_attribute('aria-disabled', 'true')
            expect(page.locator('#auth-gate')).to_contain_text('离线文件不能注册')
            assert page.locator('[data-native][href]').count() == 0
            page.locator('.nav[data-tab="models"]').tap()
            expect(page.locator('#model-select')).to_be_disabled()
            metrics(page)
            snapshot(page, f'offline-models-{width}')
            report['offline'].append({'width': width, 'single_file': True, 'registration_login_models_disabled': True, 'navigation': 'pass'})
            context.close()

        for width in ([args.width] if args.width else WIDTHS):
            context = browser.new_context(viewport={'width': width, 'height': 844}, is_mobile=True, has_touch=True, locale='zh-CN', device_scale_factor=1)
            mock_status = dict(native_status['data'])
            mock_status.update(register_enabled=True, password_register_enabled=True, password_login_enabled=True, email_verification=False, turnstile_check=False, privacy_policy_enabled=False, user_agreement_enabled=False, password_login_encryption_enabled=False)
            models = [
                {'model_name': 'fixture-chat-alpha', 'quota_type': 0, 'model_ratio': 1.25, 'completion_ratio': 3, 'cache_ratio': .1, 'enable_groups': ['default'], 'supported_endpoint_types': ['openai']},
                {'model_name': 'fixture-chat-beta', 'quota_type': 1, 'model_price': .004, 'enable_groups': ['default'], 'supported_endpoint_types': ['openai']},
                {'model_name': 'fixture-dynamic', 'billing_mode': 'tiered_expr', 'billing_expr': 'fixture-only', 'enable_groups': ['default'], 'supported_endpoint_types': ['openai-response']},
            ]
            state = {'models': models.copy(), 'pricing_error': 0, 'status_error': 0, 'setup': True}
            held_register, held_login, writes, errors, console_types = [], [], [], [], []
            def fulfill(route, body, status=200, headers=None):
                route.fulfill(status=status, content_type='application/json', body=json.dumps(body), headers=headers)
            def mock_route(route):
                req = route.request
                if not req.url.startswith(BASE + '/'):
                    route.abort()
                    return
                path = urlsplit(req.url).path
                if not path.startswith('/api/'):
                    assert req.method in ('GET', 'HEAD'), 'business write outside mocked API'
                    static(route)
                    return
                # ALL API requests intercepted. Auth bodies, headers and cookies are never recorded.
                if req.method not in ('GET', 'HEAD'):
                    writes.append({'path': path, 'method': req.method, 'forwarded': False})
                if path == '/api/status':
                    fulfill(route, {'success': True, 'data': mock_status}, status=state['status_error'] or 200)
                elif path == '/api/setup':
                    fulfill(route, {'success': True, 'data': {'status': state['setup'], 'root_init': state['setup'], 'database_type': 'sqlite'}})
                elif path == '/api/pricing':
                    if state['pricing_error']:
                        fulfill(route, {'success': False}, state['pricing_error'], {'Retry-After': '2'} if state['pricing_error'] == 429 else None)
                    else:
                        fulfill(route, {'success': True, 'data': state['models'], 'group_ratio': {'default': 1}, 'usable_group': {'default': '测试分组'}, 'supported_endpoint': {}, 'vendors': []})
                elif path in ('/api/notice', '/api/about', '/api/home_page_content'):
                    fulfill(route, {'success': True, 'data': ''})
                elif path == '/api/user/register':
                    submitted = req.post_data_json
                    assert {'username', 'password'} <= set(submitted)
                    assert submitted['username'] == 'fixture_customer'
                    assert 8 <= len(submitted['password']) <= 128
                    # Values remain in memory only, not results or logs.
                    held_register.append(route)
                elif path == '/api/user/login':
                    held_login.append(route)
                elif path == '/api/user/auth/refresh':
                    fulfill(route, {'success': False, 'code': 'AUTH_REFRESH_MISSING'}, 401)
                else:
                    fulfill(route, {'success': True, 'data': {}})
            context.route('**/*', mock_route)
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('console', lambda message: console_types.append(message.text.split('\n')[0]) if message.type == 'error' and message.text.startswith(('TypeError:', 'Error:')) else None)
            page.goto(BASE + '/h5/')
            page.locator('#home [data-tab="register"]').tap()
            expect(page.locator('#register-continue')).to_have_attribute('href', '/register')
            assert page.locator('#register a[data-native]').count() == 1
            assert page.locator('#register form, #register input').count() == 0
            assert '原生' not in page.locator('#register').inner_text()
            # Every customer entry converges on the same handoff, never an alternate form.
            for tab in ('developer', 'account', 'login', 'home'):
                page.goto(BASE + '/h5/#' + tab)
                page.locator(f'#{tab} [data-tab=register]').tap()
                expect(page).to_have_url(BASE + '/h5/#register')
                expect(page.locator('#register-continue')).to_have_attribute('href', '/register')
            metrics(page)
            snapshot(page, f'mock-single-registration-{width}', True)
            assert all(w['path'] == '/api/user/auth/refresh' for w in writes)
            page.locator('#register-continue').tap()
            page.wait_for_url(BASE + '/sign-up')
            registration_submit = page.locator('form button[type="submit"]')
            registration_submit.tap()
            expect(page.locator('input[name="username"]')).to_have_attribute('aria-invalid', 'true')
            page.locator('input[name="username"]').fill('fixture_customer')
            page.locator('input[name="password"]').fill('short')
            page.locator('input[name="confirmPassword"]').fill('different')
            registration_submit.tap()
            expect(page.locator('input[name="password"]')).to_have_attribute('aria-invalid', 'true')
            expect(page.locator('input[name="confirmPassword"]')).to_have_attribute('aria-invalid', 'true')
            assert all(w['path'] == '/api/user/auth/refresh' for w in writes)
            metrics(page)
            snapshot(page, f'mock-native-register-validation-{width}', True)
            fixture_password = secrets.token_urlsafe(24)
            def fill_valid():
                page.locator('input[name="password"]').fill(fixture_password)
                page.locator('input[name="confirmPassword"]').fill(fixture_password)
            fill_valid()
            registration_submit.tap()
            expect(registration_submit).to_be_disabled()
            deadline = time.monotonic() + 10
            while not held_register and time.monotonic() < deadline:
                page.wait_for_timeout(20)
            assert held_register, 'native registration request missing'
            snapshot(page, f'mock-native-register-loading-{width}', True)
            assert len([w for w in writes if w['path'] == '/api/user/register']) == 1
            fulfill(held_register.pop(), {'success': False, 'message': 'MOCK 注册失败'})
            expect(page.get_by_text('MOCK 注册失败', exact=True)).to_be_visible()
            expect(registration_submit).to_be_enabled()
            snapshot(page, f'mock-native-register-error-{width}', True)
            registration_submit.tap()
            deadline = time.monotonic() + 10
            while not held_register and time.monotonic() < deadline:
                page.wait_for_timeout(20)
            assert held_register, 'native registration retry missing'
            fulfill(held_register.pop(), {'success': True, 'message': ''})
            page.wait_for_url('**/sign-in*')
            expect(page.locator('input[name="password"]')).to_have_value('')
            metrics(page)
            snapshot(page, f'mock-native-register-success-{width}', True)
            # Verify storage never contains a password or a fabricated user record.
            stored = page.evaluate('JSON.stringify({local:{...localStorage},session:{...sessionStorage}})')
            assert fixture_password not in stored and 'fixture_customer' not in stored
            page.goto(BASE + '/h5/#models')
            expect(page.locator('#catalog-state')).to_contain_text('3 个模型')
            expect(page.locator('#example')).to_be_hidden()
            expect(page.locator('#model-list')).to_contain_text('输入 USD 2.5 / 百万 token；输出 USD 7.5')
            expect(page.locator('#model-list')).to_contain_text('USD 0.004 / 次')
            page.locator('#model-list article').nth(0).get_by_role('button').tap()
            expect(page.locator('#example')).to_contain_text('"model": "fixture-chat-alpha"')
            page.locator('#model-select').select_option('fixture-chat-beta')
            expect(page.locator('#example')).to_contain_text('"model": "fixture-chat-beta"')
            expect(page.locator('#example')).not_to_contain_text('fixture-chat-alpha')
            metrics(page)
            page.evaluate('window.scrollTo(0,0)')
            snapshot(page, f'mock-model-selection-{width}', True)
            page.locator('#example').scroll_into_view_if_needed()
            snapshot(page, f'mock-model-example-{width}', True)
            page.reload()
            expect(page.locator('#model-select')).to_have_value('fixture-chat-beta')
            expect(page.locator('#example')).to_contain_text('"model": "fixture-chat-beta"')
            state['models'] = [models[0], models[2]]
            page.locator('#catalog-refresh').tap()
            expect(page.locator('#example-state')).to_contain_text('当前不可用')
            expect(page.locator('#selected-model')).to_have_text('fixture-chat-beta')
            expect(page.locator('#example')).to_be_hidden()
            snapshot(page, f'mock-model-unavailable-{width}', True)
            state['pricing_error'] = 500
            page.locator('#catalog-refresh').tap()
            expect(page.locator('#catalog-state')).to_contain_text('HTTP 500')
            expect(page.locator('#example')).to_be_hidden()
            snapshot(page, f'mock-model-network-error-{width}', True)
            state['pricing_error'] = 403
            page.locator('#catalog-refresh').tap()
            expect(page.locator('#catalog-state')).to_contain_text('无权访问')
            state['pricing_error'] = 0
            state['models'] = [{'model_name': 123}]
            page.locator('#catalog-refresh').tap()
            expect(page.locator('#catalog-state')).to_contain_text('目录格式异常')
            expect(page.locator('#model-select')).to_be_disabled()
            state['models'] = []
            page.locator('#catalog-refresh').tap()
            expect(page.locator('#catalog-state')).to_contain_text('暂无可见模型')
            expect(page.locator('#model-select')).to_be_disabled()
            expect(page.locator('#selected-model')).to_have_text('fixture-chat-beta')
            state['models'] = models.copy()
            page.locator('#catalog-refresh').tap()
            expect(page.locator('#model-select')).to_be_enabled()
            page.locator('#model-select').select_option('fixture-dynamic')
            expect(page.locator('#example')).to_contain_text('/v1/responses')
            expect(page.locator('#model-list')).to_contain_text('动态/分层计费')
            # Unsupported endpoints are not silently treated as chat completions.
            state['models'] = [{'model_name': 'fixture-unknown', 'supported_endpoint_types': ['anthropic'], 'enable_groups': []}]
            page.locator('#catalog-refresh').tap()
            expect(page.locator('#catalog-state')).to_contain_text('1 个模型')
            page.locator('#model-select').select_option('fixture-unknown')
            expect(page.locator('#example')).to_be_hidden()
            expect(page.locator('#example-state')).to_contain_text('未声明受支持')
            # Recheck registration switches/fail-closed states without sending a write.
            page.locator('#models [data-tab=developer]').tap()
            page.locator('.nav[data-tab="account"]').tap()
            page.locator('#account [data-tab="register"]').tap()
            mock_status['register_enabled'] = False
            page.locator('#state-refresh').tap()
            expect(page.locator('#auth-gate')).to_contain_text('尚未开放用户注册')
            expect(page.locator('#register-continue')).to_have_attribute('aria-disabled', 'true')
            assert page.locator('#register-continue').get_attribute('href') is None
            mock_status['register_enabled'] = True
            mock_status['password_register_enabled'] = False
            page.locator('#state-refresh').tap()
            expect(page.locator('#auth-gate')).to_contain_text('其他方式')
            expect(page.locator('#register-continue')).to_have_attribute('href', '/register')
            mock_status['password_register_enabled'] = True
            for key in ('email_verification', 'turnstile_check', 'user_agreement_enabled', 'privacy_policy_enabled'):
                mock_status[key] = True
                page.locator('#state-refresh').tap()
                expect(page.locator('#register-continue')).to_have_attribute('href', '/register')
                assert page.locator('#register form, #register input').count() == 0
                mock_status[key] = False
            state['status_error'] = 503
            page.locator('#state-refresh').tap()
            expect(page.locator('#setup-state')).to_have_text('注册暂不可用')
            expect(page.locator('#register-continue')).to_have_attribute('aria-disabled', 'true')
            assert page.locator('#register-continue').get_attribute('href') is None
            state['status_error'] = 0
            page.locator('#state-refresh').tap()
            expect(page.locator('#register-continue')).to_have_attribute('href', '/register')
            page.reload()
            expect(page.locator('#register-continue')).to_have_attribute('href', '/register')
            assert page.locator('#register form, #register input').count() == 0
            # Native compiled login is loaded unchanged, with all business requests still mocked.
            state['models'] = models[:2]
            page.locator('#register [data-tab="login"]').tap()
            page.locator('#native-login').tap()
            page.wait_for_url('**/sign-in?*')
            page.locator('input[name="username"]').wait_for()
            login_submit = page.locator('form button[type="submit"]')
            login_submit.tap()
            expect(page.locator('input[name="username"]')).to_have_attribute('aria-invalid', 'true')
            page.locator('input[name="username"]').fill('fixture_customer')
            page.locator('input[name="password"]').fill(fixture_password)
            login_submit.tap()
            expect(login_submit).to_be_disabled()
            while not held_login:
                page.wait_for_timeout(20)
            snapshot(page, f'mock-native-login-loading-{width}', True)
            fulfill(held_login.pop(), {'success': False, 'message': 'MOCK 登录失败'})
            expect(page.get_by_text('MOCK 登录失败', exact=True)).to_be_visible()
            expect(login_submit).to_be_enabled()
            native_metrics = metrics(page)
            snapshot(page, f'mock-native-login-error-{width}', True)
            # Mock bundle is deliberately unusable outside this isolated browser.
            login_submit.tap()
            while not held_login:
                page.wait_for_timeout(20)
            now = int(time.time())
            bundle = {'access_token': 'fixture-not-a-valid-access-token', 'token_type': 'Bearer', 'access_expires_at': now + 300,
                'user': {'id': 999999, 'username': 'fixture_customer', 'role': 1, 'status': 1, 'group': 'default'},
                'session': {'sid': 'fixture-not-a-real-session', 'current': True, 'login_method': 'password', 'ip': '127.0.0.1', 'user_agent': 'fixture', 'created_at': now, 'last_active_at': now, 'expires_at': now + 300}}
            fulfill(held_login.pop(), {'success': True, 'data': bundle})
            page.wait_for_url(BASE + '/h5/#chat')
            expect(page.locator('#chat')).to_be_visible()
            # This mock has no real refresh cookie; the returned workspace must not fabricate a session.
            expect(page.locator('#chat-send')).to_be_disabled()
            snapshot(page, f'mock-native-login-return-{width}', True)
            page.goto(BASE + '/h5/#models')
            expect(page.locator('#model-select')).to_have_value('fixture-unknown')
            metrics(page)
            assert not errors, errors
            assert not any(w['path'].startswith('/v1/') for w in writes)
            report['mock'].append({'width': width, 'registration': ['all customer entries converge', 'no H5 credential form or registration POST', 'one native registration link', 'real compiled form validation/loading/failure/success', 'native sign-in redirect', 'no credentials in storage', 'closed registration switch', 'advanced verification uses same route', 'password-disabled preserves other methods', 'state error fail-closed', 'refresh preserves single entry'], 'models': ['card tap', 'select switch updates JSON', 'group prices', 'refresh retains ID', 'removal does not substitute', 'HTTP500', 'HTTP403', 'malformed response', 'empty', 'dynamic pricing', 'unsupported endpoint'], 'native_login': ['branded compiled form', 'required validation', 'loading', 'failure', 'automatic full-document H5 return', 'mock without refresh cookie cannot fabricate session', 'H5 return preserves selection'], 'native_layout': native_metrics, 'intercepted_writes': writes, 'pageerrors': []})
            context.close()
        browser.close()
    report['summary'] = {'real_viewports': len(report['real']), 'mock_viewports': len(report['mock']), 'offline_viewports': len(report['offline']), 'screenshots': len(list(out.glob('*.png'))), 'forwarded_business_writes': 0, 'real_accounts_created': 0, 'real_models': 0}
    (out / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report['summary'], ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
