#!/usr/bin/env python3
"""Read-only visitor journeys on an uninitialized local deployment."""
import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def verify_public_site(browser, base, output):
    output.mkdir(parents=True, exist_ok=True)
    result = {'widths': [], 'unexpected_requests': [], 'page_errors': [], 'business_writes': 0}
    for width in [360, 390, 430, 1024, 1440]:
        context = browser.new_context(viewport={'width': width, 'height': 960},
            is_mobile=width < 760, has_touch=width < 760, reduced_motion='reduce', locale='zh-CN')

        def guard(route):
            request = route.request
            path = urlsplit(request.url).path
            if (not request.url.startswith(base + '/') or request.method != 'GET' or
                    path.startswith(('/pg/', '/v1/', '/api/channel', '/api/log', '/api/perf-metrics'))):
                result['unexpected_requests'].append({'path': path, 'method': request.method})
                route.abort()
            else:
                route.continue_()

        context.route('**/*', guard)
        redirect = context.request.get(base + '/', max_redirects=0)
        assert redirect.status == 302 and redirect.headers['location'] == '/h5/'
        page = context.new_page()
        page.on('pageerror', lambda error: result['page_errors'].append(str(error)))

        def layout():
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert page.locator('.panel:visible').count() == 1
            assert page.locator('[data-admin-only]:visible').count() == 0

        def screenshot(name):
            page.evaluate('window.scrollTo(0, 0)')
            page.evaluate('new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
            page.screenshot(path=str(output / f'{name}-{width}.png'), full_page=True)

        page.goto(base + '/')
        expect(page).to_have_url(base + '/h5/')
        expect(page.locator('#setup-state')).to_have_text('等待管理员初始化')
        expect(page.locator('#home')).to_be_visible()
        expect(page.locator('.app > header [data-brand-name]')).to_have_text('模港 ModelPort')
        assert '模港 ModelPort' in page.title()
        expect(page.locator('.public-nav')).to_be_visible()
        expect(page.locator('.workspace-sidebar')).to_be_hidden()
        expect(page.locator('.bottom')).to_be_hidden()
        expect(page.locator('.public-nav [data-tab=home]')).to_have_attribute('aria-current', 'page')
        assert page.locator('#home [href="/setup"]').count() == 0
        layout()
        screenshot('homepage')
        page.locator('.public-nav [data-tab=about]').click()
        expect(page.locator('#about')).to_be_visible()
        assert '平台运营者' not in page.locator('#about').inner_text()
        expect(page.locator('#about .landing-grid article')).to_have_count(2)
        assert page.locator('#about [data-tab=operations], .public-nav [data-tab=operations]').count() == 0
        expect(page.locator('.public-nav [data-tab=about]')).to_have_attribute('aria-current', 'page')
        page.locator('#about summary').first.click()
        expect(page.locator('#about details').first).to_have_attribute('open', '')
        layout()
        screenshot('introduction')
        page.reload()
        expect(page.locator('#about')).to_be_visible()
        expect(page.locator('body')).to_have_class('public-mode')
        page.go_back()
        expect(page.locator('#home')).to_be_visible()
        page.go_forward()
        expect(page.locator('#about')).to_be_visible()
        page.locator('#about [data-tab=chat]').click()
        expect(page.locator('#chat')).to_be_visible()
        expect(page.locator('#chat-send')).to_be_disabled()
        expect(page.locator('.public-nav')).to_be_hidden()
        if width >= 1024:
            expect(page.locator('.workspace-sidebar')).to_be_visible()
        layout()
        page.locator('.app > header .brand').click()
        expect(page.locator('#home')).to_be_visible()
        page.locator('.public-nav [data-tab=models]').click()
        expect(page).to_have_url(base + '/h5/#models')
        expect(page.locator('#models')).to_be_visible()
        expect(page.locator('#models-title')).to_have_text('模型与价格')
        expect(page.locator('.public-nav [data-tab=models]')).to_have_attribute('aria-current', 'page')
        expect(page.locator('.workspace-sidebar')).to_be_hidden()
        expect(page.locator('.bottom')).to_be_hidden()
        expect(page.locator('#chat-form')).to_be_hidden()
        expect(page.locator('#catalog-state')).to_contain_text('暂无可见模型')
        layout()
        screenshot('public-pricing')
        page.reload()
        expect(page.locator('#models')).to_be_visible()
        expect(page.locator('body')).to_have_class('public-mode')
        page.locator('.public-nav [data-tab=chat]').click()
        expect(page).to_have_url(base + '/h5/#chat')
        expect(page.locator('#chat-form')).to_be_visible()
        expect(page.locator('#models')).to_be_hidden()
        expect(page.locator('.public-nav')).to_be_hidden()
        if width >= 1024:
            expect(page.locator('.workspace-sidebar')).to_be_visible()
        page.go_back()
        expect(page.locator('#models')).to_be_visible()
        expect(page.locator('.public-nav')).to_be_visible()
        page.locator('.public-nav [data-tab=guide]').click()
        expect(page.locator('#guide')).to_be_visible()
        expect(page.locator('#guide-load-state')).to_contain_text('示例已就绪')
        expect(page.locator('#guide [data-api-base]')).to_have_text(base + '/v1')
        expect(page.locator('#guide-python')).to_contain_text('max_retries=0')
        expect(page.locator('#guide-node')).to_contain_text('redirect: "error"')
        expect(page.locator('.workspace-sidebar')).to_be_hidden()
        layout()
        screenshot('developer-guide')
        page.locator('.app > header .brand').click()
        page.locator('#home [data-tab=register]').click()
        expect(page.locator('#register-continue')).to_have_attribute('aria-disabled', 'true')
        assert page.locator('#register-continue').get_attribute('href') is None
        assert page.locator('#register form, #register input, #register [href="/setup"]').count() == 0
        assert '原生' not in page.locator('#register').inner_text()
        screenshot('registration')
        page.goto(base + '/h5/#operations')
        expect(page.locator('#operations-gate')).to_contain_text('未初始化')
        expect(page.locator('#operations-content')).to_be_hidden()
        assert page.locator('#operations-content [href]').count() == 0
        layout()
        result['widths'].append(width)
        context.close()
    assert not result['page_errors'], result['page_errors']
    assert not result['unexpected_requests'], result['unexpected_requests']
    result['completed'] = True
    (output / 'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='http://127.0.0.1:13000')
    parser.add_argument('--output', default='evidence/public-site')
    args = parser.parse_args()
    output = (ROOT / args.output).resolve()
    assert output.is_relative_to(ROOT)
    os.environ['TMPDIR'] = '/tmp'
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path='/usr/bin/google-chrome', headless=True,
            chromium_sandbox=True, args=['--disable-gpu'])
        print(json.dumps(verify_public_site(browser, args.base.rstrip('/'), output), ensure_ascii=False))
        browser.close()


if __name__ == '__main__':
    main()
