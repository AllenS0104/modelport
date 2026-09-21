"""Exercise the compiled customer/admin UI using an isolated real backend session."""
from pathlib import Path

from playwright.sync_api import expect


def verify_console_pages(context, base, output: Path, admin=False):
    output.mkdir(parents=True, exist_ok=True)
    page = context.new_page()
    errors = []
    refresh_statuses = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('response', lambda response: refresh_statuses.append(response.status)
            if response.url.endswith('/api/user/auth/refresh') else None)
    routes = ['/channels', '/usage-logs/audit', '/security'] if admin else ['/keys', '/wallet', '/usage-logs/common', '/security', '/pricing']
    checks = []
    for width in [390, 1440]:
        page.set_viewport_size({'width': width, 'height': 960})
        for route in routes:
            page.goto(base + route)
            expect(page.locator('[data-platform-brand]:visible').first).to_contain_text('模港 ModelPort')
            expect(page, f'Console navigation; refresh HTTP statuses: {refresh_statuses}').to_have_url(base + route)
            expect(page.locator('body')).not_to_contain_text('Something went wrong')
            assert page.locator('input[name=password]').count() == 0
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (route, width)
            assert '模港 ModelPort' in page.title()
            if not admin:
                assert page.locator('a[href="/channels"]:visible').count() == 0
            if route == '/security':
                expect(page.get_by_role('button', name='Change Password', exact=True)).to_be_visible()
                expect(page.get_by_role('button', name='Delete Account', exact=True)).to_have_count(0)
                expect(page.locator('#security-account')).to_have_count(0)
            page.evaluate('new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
            page.screenshot(path=str(output / f'{route.strip("/").replace("/", "-")}-{width}.png'), full_page=True)
            checks.append({'route': route, 'width': width})
        # The brand always leaves the native SPA and opens the actual product homepage.
        page.locator('a:has([data-platform-brand])').first.click()
        expect(page).to_have_url(base + '/h5/')
        expect(page.locator('#home')).to_be_visible()
    assert not errors, errors
    page.close()
    return checks


def verify_auth_pages(browser, base, output: Path, anonymous_read_only=False):
    output.mkdir(parents=True, exist_ok=True)
    context = browser.new_context(locale='zh-CN', reduced_motion='reduce')
    blocked = []
    if anonymous_read_only:
        def guard(route):
            request = route.request
            if request.url == base + '/api/user/auth/refresh':
                route.fulfill(status=401, content_type='application/json',
                              body='{"success":false,"code":"AUTH_REFRESH_MISSING"}')
            elif not request.url.startswith(base + '/') or request.method not in ['GET', 'HEAD']:
                blocked.append({'url': request.url.split('?')[0], 'method': request.method})
                route.abort()
            else:
                route.continue_()
        context.route('**/*', guard)
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    for width in [360, 1440]:
        page.set_viewport_size({'width': width, 'height': 960})
        for route in ['/sign-in', '/sign-up', '/forgot-password']:
            page.goto(base + route)
            expect(page.locator('[data-platform-brand]')).to_contain_text('模港 ModelPort')
            expect(page.locator('.modelport-attribution')).to_contain_text('New API contributors')
            expect(page.locator('a[href="/console-assets/modelport-source.tar.gz"]')).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (route, width)
            page.evaluate('new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
            page.screenshot(path=str(output / f'{route[1:]}-{width}.png'), full_page=True)
        page.locator('.modelport-auth-header a[href="/h5/#guide"]').click()
        expect(page).to_have_url(base + '/h5/#guide')
        expect(page.locator('#guide')).to_be_visible()
    assert not errors, errors
    assert not blocked, blocked
    context.close()


if __name__ == '__main__':
    import argparse
    import json
    import os
    from playwright.sync_api import sync_playwright

    parser = argparse.ArgumentParser(description='Read-only live account UI; no login or registration submissions.')
    parser.add_argument('--base', default='http://127.0.0.1:13000')
    parser.add_argument('--output', default='evidence/unified-interface-live')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = (root / args.output).resolve()
    assert output.is_relative_to(root)
    os.environ['TMPDIR'] = '/tmp'
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path='/usr/bin/google-chrome',
            headless=True, chromium_sandbox=True, args=['--disable-gpu'])
        verify_auth_pages(browser, args.base.rstrip('/'), output, anonymous_read_only=True)
        browser.close()
    report = {'completed': True, 'widths': [360, 1440], 'business_writes': 0,
              'anonymous_refresh': 'intercepted as unauthenticated; no live cookies or login submitted'}
    (output / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))
