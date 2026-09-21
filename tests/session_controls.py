#!/usr/bin/env python3
"""Session-aware H5 controls; all identity/API traffic is intercepted, never production accounts."""
import argparse
import json
import time
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', help='Read deployed H5 assets only; all API requests remain mocked')
    parser.add_argument('--output', default='evidence/session-controls')
    args = parser.parse_args()
    output = (ROOT / args.output).resolve()
    assert output.is_relative_to(ROOT)
    output.mkdir(parents=True, exist_ok=True)
    base = (args.base_url or 'http://127.0.0.1:19455').rstrip('/')
    checks = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel='chrome', headless=True,
                                             args=['--no-sandbox', '--disable-dev-shm-usage'])
        for width, role in [(390, 1), (1440, 10)]:
            context = browser.new_context(viewport={'width': width, 'height': 900})
            state = {'status': 200, 'hold': True}
            pending, unexpected, errors = [], [], []
            user = {'id': 2, 'username': 'fixture-client', 'group': 'default', 'role': role}

            def respond_identity(route):
                if state['status'] != 200:
                    route.fulfill(status=state['status'], json={'success': False})
                elif urlsplit(route.request.url).path.endswith('/refresh'):
                    route.fulfill(json={'success': True, 'data': {
                        'access_token': 'inert-browser-fixture', 'token_type': 'Bearer',
                        'access_expires_at': time.time() + 3600, 'user': user,
                        'session': {'sid': 'fixture-session', 'current': True}}})
                else:
                    route.fulfill(json={'success': True, 'data': user})

            def intercept(route):
                path = urlsplit(route.request.url).path
                if urlsplit(route.request.url).netloc != urlsplit(base).netloc:
                    unexpected.append('external request')
                    route.abort()
                elif path in ['/h5/', '/h5/features.js']:
                    if args.base_url:
                        route.continue_()
                    else:
                        filename = 'index.html' if path.endswith('/') else 'features.js'
                        route.fulfill(body=(ROOT / 'h5' / filename).read_bytes(),
                                      content_type='text/html' if filename.endswith('html') else 'text/javascript')
                elif path == '/api/status':
                    route.fulfill(json={'success': True, 'data': {
                        'register_enabled': True, 'password_login_enabled': True}})
                elif path == '/api/setup':
                    route.fulfill(json={'success': True, 'data': {'status': True}})
                elif path in ['/api/pricing', '/api/user/models']:
                    route.fulfill(json={'success': True, 'data': []})
                elif path in ['/api/user/auth/refresh', '/api/user/self']:
                    if state['hold']:
                        pending.append(route)
                    else:
                        respond_identity(route)
                elif path == '/security':
                    route.fulfill(body='<h1>Fixture account settings</h1>', content_type='text/html')
                else:
                    unexpected.append(path)
                    route.abort()

            context.route('**/*', intercept)
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base + '/h5/#home')
            page.wait_for_function('setup?.status === true && !checking')
            assert not pending, 'Hintless public pages must not make unnecessary session requests'
            page.evaluate("navigate('chat')")
            page.wait_for_function('Boolean(sessionPromise)')
            entry = page.locator('#chat [data-tab="login"]')
            # A held refresh must not flash a misleading login action.
            expect(entry).to_have_text('正在确认账户…')
            expect(page.locator('#chat-account-hint')).to_have_text('正在确认账户与模型权限…')
            expect(entry).to_be_disabled()
            state['hold'] = False
            for route in pending:
                respond_identity(route)
            pending.clear()
            expect(page.locator('#chat-session')).to_contain_text('已登录：fixture-client')
            expect(entry).to_have_text('账户与安全')
            expect(entry).to_be_enabled()
            expect(page.locator('#session-refresh')).to_have_text('刷新权限')
            expect(page.locator('#chat-account-hint')).to_have_text('手动选择当前分组获准的模型。')
            for tab in ['home', 'developer', 'account', 'operations', 'register', 'login', 'chat']:
                page.evaluate('name => navigate(name)', tab)
                assert page.locator('[data-tab="register"]:visible, #register-continue:visible').count() == 0
                for item in page.locator('[data-tab="login"]:visible, #native-login:visible').all():
                    expect(item).to_have_text('账户与安全')
                assert page.locator('body').evaluate('(el) => el.scrollWidth <= innerWidth')
            page.screenshot(path=str(output / f'authenticated-{width}.png'), full_page=True)
            checks.append(f'{width}px role={role}: all account surfaces reflect verified session')

            # Reload restores the account controls using a server-verified session.
            page.reload()
            expect(entry).to_have_text('账户与安全')
            state['status'] = 503
            page.locator('#session-refresh').click()
            expect(page.locator('#chat-session')).to_contain_text('HTTP 503')
            expect(entry).to_have_text('重新确认账户')
            expect(page.locator('#chat-account-hint')).to_have_text('请重新确认账户，再选择模型。')
            expect(page.locator('[data-session-label]').first).to_have_text('登录状态待确认')
            state['status'] = 200
            entry.click()
            expect(entry).to_have_text('账户与安全')

            state['status'] = 401
            context.add_cookies([{'name': 'new_api_has_session', 'value': '1', 'url': base}])
            page.locator('#session-refresh').click()
            expect(entry).to_have_text('登录账户')
            expect(page.locator('#chat-account-hint')).to_contain_text('先登录')
            expect(page.locator('#chat-session')).to_contain_text('会话已失效')
            entry.click()
            expect(page).to_have_url(base + '/h5/#login')
            expect(page.locator('#native-login')).to_have_attribute('href', '/sign-in?redirect=%2Fh5%2F%23chat')
            expect(page.locator('#login [data-tab="register"]')).to_be_visible()
            state['status'] = 200
            page.evaluate("navigate('chat')")
            page.locator('#session-refresh').click()
            expect(entry).to_have_text('账户与安全')

            # Native cross-tab logout clears controls; late identity responses cannot restore them.
            state['hold'] = True
            page.locator('#session-refresh').click()
            page.wait_for_function('Boolean(sessionPromise)')
            other = context.new_page()
            other.goto(base + '/security')
            other.evaluate("""() => {
                const channel = new BroadcastChannel('new-api:auth-session');
                channel.postMessage({kind:'signed_out', sid:'fixture-session', timestamp:Date.now()});
                channel.close();
            }""")
            expect(page.locator('#chat-session')).to_contain_text('其他页面')
            state['hold'] = False
            for route in pending:
                respond_identity(route)
            pending.clear()
            page.wait_for_function('sessionPromise === null')
            expect(entry).to_have_text('登录账户')
            other.evaluate("""() => {
                const channel = new BroadcastChannel('new-api:auth-session');
                channel.postMessage({kind:'authenticated', sid:'fixture-session', timestamp:Date.now()});
                channel.close();
            }""")
            expect(entry).to_have_text('重新确认账户')
            entry.click()
            expect(entry).to_have_text('账户与安全')
            entry.click()
            expect(page).to_have_url(base + '/security')
            expect(page.locator('h1')).to_have_text('Fixture account settings')
            checks.append(f'{width}px: reload, 503 retry, 401 despite hint cookie, cross-tab login/logout, late response, account navigation')
            assert not errors, errors
            assert not unexpected, unexpected
            context.close()
        browser.close()
    report = {'completed': True, 'identity': 'browser fixture only', 'production_writes': 0, 'checks': checks}
    (output / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
