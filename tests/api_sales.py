#!/usr/bin/env python3
"""API-only acceptance in disposable containers; no production data or paid calls."""
import argparse
import email
import email.header
import hashlib
import json
import os
from pathlib import Path
import secrets
import socketserver
import threading
import time
from http.server import ThreadingHTTPServer
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright
from chat_integration import docker, IMAGES, Provider, MODEL

ROOT = Path(__file__).resolve().parents[1]


class SMTPHandler(socketserver.StreamRequestHandler):
    def handle(self):
        self.wfile.write(b'220 fixture ESMTP\r\n')
        recipients = []
        while line := self.rfile.readline():
            verb = line.split(b' ', 1)[0].strip().upper()
            if verb in (b'EHLO', b'HELO'):
                self.wfile.write(b'250 fixture\r\n')
            elif verb == b'MAIL':
                recipients = []
                self.wfile.write(b'250 OK\r\n')
            elif verb == b'RCPT':
                recipients.append(line.decode().strip())
                self.wfile.write(b'250 OK\r\n')
            elif verb == b'DATA':
                self.wfile.write(b'354 send data\r\n')
                content = bytearray()
                while (part := self.rfile.readline()) not in (b'.\r\n', b''):
                    content.extend(part)
                if self.server.reject:
                    self.wfile.write(b'550 fixture rejection\r\n')
                else:
                    self.server.messages.append((recipients[:], email.message_from_bytes(content)))
                    self.wfile.write(b'250 accepted\r\n')
            elif verb == b'QUIT':
                self.wfile.write(b'221 bye\r\n')
                break
            else:
                self.wfile.write(b'250 OK\r\n')


class SMTPServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api-image', default='modelport-new-api:api-sales-v1')
    parser.add_argument('--site-root', default='.api-sales-stage')
    parser.add_argument('--console-dist', default='.console-build/web/dist')
    parser.add_argument('--output', default='evidence/api-sales')
    parser.add_argument('--extended-scenarios', action='store_true')
    parser.add_argument('--upstream-issues', action='store_true')
    args = parser.parse_args()
    output, site, dist = [(ROOT / value).resolve() for value in
                          (args.output, args.site_root, args.console_dist)]
    assert all(path.is_relative_to(ROOT) for path in (output, site, dist))
    output.mkdir(parents=True, exist_ok=True)
    os.environ['TMPDIR'] = '/tmp'
    tag = 'api-sales-' + secrets.token_hex(4)
    containers, networks, servers = [], [], []
    report = {'completed': False, 'production_writes': 0, 'paid_calls': 0,
              'smtp': 'isolated SMTP receiver; NOT external inbox delivery', 'checks': []}
    report['api_image'] = args.api_image
    report['console_manifest_sha256'] = hashlib.sha256((dist / 'build-manifest.json').read_bytes()).hexdigest()
    try:
        for name, internal in [(tag, True), (tag + '-edge', False)]:
            docker('network', 'create', *(['--internal'] if internal else []), name)
            networks.append(name)
        gateway = json.loads(docker('network', 'inspect', tag))[0]['IPAM']['Config'][0]['Gateway']
        smtp = SMTPServer((gateway, 0), SMTPHandler)
        smtp.messages, smtp.reject = [], False
        provider = ThreadingHTTPServer((gateway, 0), Provider)
        Provider.requests = []
        for server in (smtp, provider):
            threading.Thread(target=server.serve_forever, daemon=True).start()
            servers.append(server)
        for component in ('api', 'ingress'):
            name = tag + '-' + component
            cmd = ['run', '-d', '--name', name, '--network', tag, '--log-driver', 'none',
                   '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
                   '--user', '1000:1000', '--read-only', '--tmpfs', '/tmp:rw,nosuid,size=256m,mode=1777',
                   '--memory', '1g', '--cpus', '2']
            if component == 'api':
                cmd += ['--network-alias', 'new-api', '-e', 'SQLITE_PATH=/tmp/fixture.db',
                        '-e', 'SESSION_COOKIE_SECURE=false', '-e', 'BATCH_UPDATE_ENABLED=false',
                        '-e', 'CRITICAL_RATE_LIMIT=200', args.api_image, '--port', '3000', '--log-dir', '/tmp/logs']
            else:
                cmd += ['--network', tag + '-edge', '-p', '127.0.0.1::8080',
                        '-v', f'{site / "nginx.conf"}:/etc/nginx/nginx.conf:ro',
                        '-v', f'{site / "h5"}:/srv/h5:ro',
                        '-v', f'{dist}:/srv/modelport-console:ro',
                        '--entrypoint', 'nginx', IMAGES['ingress'], '-g', 'daemon off;']
            docker(*cmd)
            containers.append(name)
        base = 'http://127.0.0.1:' + docker('port', containers[-1], '8080/tcp').rsplit(':', 1)[1]
        for attempt in range(60):
            try:
                with urlopen(base + '/api/setup', timeout=2) as response:
                    if json.load(response)['success']:
                        break
            except OSError:
                if attempt == 59:
                    raise
                time.sleep(0.5)
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path='/usr/bin/google-chrome', headless=True,
                                        chromium_sandbox=True, args=['--disable-gpu'])
            root = browser.new_context(locale='en-US', viewport={'width': 1440, 'height': 1000})
            user = browser.new_context(locale='en-US', viewport={'width': 1440, 'height': 1000})
            password = secrets.token_urlsafe(24)

            def call(ctx, method, path, data=None, token=None):
                headers = {'Origin': base}
                if token:
                    headers['Authorization'] = 'Bearer ' + token
                return ctx.request.fetch(base + path, method=method, data=data, headers=headers)

            def ok(ctx, method, path, data=None, token=None):
                response = call(ctx, method, path, data, token)
                body = response.json()
                assert response.ok and body.get('success') is True, (
                    method, path, response.status, body.get('message'), body.get('code'))
                return body.get('data')

            ok(root, 'POST', '/api/setup', {'username': 'fixture_root', 'password': password, 'confirmPassword': password})
            rt = ok(root, 'POST', '/api/user/login', {'username': 'fixture_root', 'password': password})['access_token']
            ok(root, 'POST', '/api/user/', {'username': 'fixture_user', 'password': password, 'role': 1}, rt)

            def option(key, value):
                ok(root, 'PUT', '/api/option/', {'key': key, 'value': value}, rt)

            for key, value in [('ModelRatio', json.dumps({MODEL: 1, 'private-fixture': 1, 'delete-fixture': 1})),
                               ('CompletionRatio', json.dumps({MODEL: 2})),
                               ('GroupRatio', json.dumps({'default': 1, 'private': 1})), ('RetryTimes', '0')]:
                option(key, value)
            for name, group, models in [('public', 'default', MODEL + ',delete-fixture'),
                                         ('private', 'private', 'private-fixture')]:
                ok(root, 'POST', '/api/channel/', {'mode': 'single', 'channel': {
                    'name': name, 'type': 1, 'key': 'fixture-not-a-real-provider-key',
                    'base_url': f'http://{gateway}:{provider.server_port}', 'models': models,
                    'group': group, 'status': 1, 'weight': 1}}, rt)

            def login(ctx, name):
                page = ctx.new_page()
                page.goto(base + '/sign-in')
                page.locator('input[name=username]').fill(name)
                page.locator('input[name=password]').fill(password)
                with page.expect_response(lambda r: r.url.split('?')[0].endswith('/api/user/login') and r.request.method == 'POST') as result:
                    page.locator('form button[type=submit]').click()
                token = result.value.json()['data']['access_token']
                page.wait_for_url(base + '/dashboard/models')
                return page, token

            page, ut = login(user, 'fixture_user')
            expect(page.get_by_text('常规', exact=True)).to_be_visible()
            for label in ['数据看板', '概览', 'API 密钥', '使用日志', '任务日志']:
                expect(page.locator('[data-sidebar="menu-button"]').filter(has_text=label)).to_be_visible()
            expect(page.get_by_role('link', name='审计日志', exact=True)).to_have_count(0)
            assert not page.locator('a[href^="/chat"],a[href^="/playground"]').count()
            report['checks'].append('en-US browser defaults to Chinese; ordinary navigation contains the five requested links and no chat/audit')
            page.goto(base + '/usage-logs/audit')
            page.wait_for_url(base + '/usage-logs/common')
            for path in ['/chat/test', '/chat2link', '/playground', '/h5/#chat']:
                page.goto(base + path)
                page.wait_for_url(base + '/dashboard/models')
            for path in ['/pg/chat/completions', '/pg/anything']:
                response = call(user, 'POST', path, {}, ut)
                assert response.status == 403 and response.json()['code'] == 'WEB_CHAT_DISABLED'
            assert call(user, 'DELETE', '/api/user/self', token=ut).status == 403
            assert call(user, 'POST', '/api/models/channel-only/delete', {'model_name': MODEL}, ut).status == 403
            report['checks'].append('legacy chat and user audit routes redirect; web relay/self-deletion/admin mutation forbidden')

            page.goto(base + '/profile')
            page.locator('#notifyEmail').fill('saved-recipient@example.test')
            page.locator('#threshold').fill('500')
            with page.expect_response(lambda r: r.url.endswith('/api/user/setting') and r.request.method == 'PUT') as saved:
                page.get_by_role('button', name='保存设置', exact=True).click()
            assert saved.value.json()['success']
            readiness = ok(user, 'GET', '/api/user/notification/email', token=ut)
            assert readiness == {'configured': False, 'recipient_configured': True}
            assert call(user, 'POST', '/api/user/notification/email/test', {}, ut).status == 503
            expect(page.get_by_role('button', name='发送测试邮件', exact=True)).to_be_disabled()
            for key, value in [('SMTPServer', gateway), ('SMTPPort', str(smtp.server_address[1])),
                               ('SMTPFrom', 'sender@example.test'), ('SMTPSSLEnabled', 'false'),
                               ('SMTPStartTLSEnabled', 'false')]:
                option(key, value)
            page.reload()
            expect(page.locator('#notifyEmail')).to_have_value('saved-recipient@example.test')
            with page.expect_response(lambda r: r.url.endswith('/api/user/notification/email/test')) as sent:
                page.get_by_role('button', name='发送测试邮件', exact=True).click()
            assert sent.value.json()['data']['accepted'] is True
            assert len(smtp.messages) == 1 and smtp.messages[0][0] == ['RCPT TO:<saved-recipient@example.test>']
            ut = ok(user, 'POST', '/api/user/auth/refresh')['access_token']
            ok(user, 'POST', '/api/user/notification/email/test', {'email': 'injected@example.test'}, ut)
            assert len(smtp.messages) == 2 and smtp.messages[-1][0] == smtp.messages[0][0]
            smtp.reject = True
            response = call(user, 'POST', '/api/user/notification/email/test', {}, ut)
            assert response.status == 502 and response.json()['code'] == 'NOTIFICATION_EMAIL_FAILED'
            smtp.reject = False
            report['checks'].append('profile UI persists email/threshold; actual SMTP receives saved-recipient tests; forged recipient ignored and SMTP rejection fails explicitly')

            root.clear_cookies()
            admin_page, rt = login(root, 'fixture_root')
            expect(admin_page.get_by_role('link', name='审计日志', exact=True)).to_be_visible()
            admin_page.goto(base + '/models')
            row = admin_page.get_by_role('row').filter(has=admin_page.get_by_text('delete-fixture', exact=True))
            row.get_by_role('button', name='删除', exact=True).click()
            dialog = admin_page.get_by_role('alertdialog')
            expect(dialog.get_by_role('checkbox', name='同时从所有渠道移除')).to_be_checked()
            with admin_page.expect_response(lambda r: r.url.endswith('/api/models/channel-only/delete')) as deleted:
                dialog.get_by_role('button', name='删除', exact=True).click()
            assert deleted.value.json()['success']
            expect(row).to_have_count(0)
            channels = ok(root, 'GET', '/api/channel/?p=1&page_size=10', token=rt)
            channel_items = channels['items']
            assert next(c for c in channel_items if c['name'] == 'public')['models'] == MODEL
            assert next(c for c in channel_items if c['name'] == 'private')['models'] == 'private-fixture'
            assert not call(root, 'POST', '/api/models/channel-only/delete', {'model_name': 'delete-fixture'}, rt).json()['success']
            ok(root, 'POST', '/api/models/', {'model_name': MODEL, 'name_rule': 0, 'status': 1}, rt)
            assert not call(root, 'POST', '/api/models/channel-only/delete', {'model_name': MODEL}, rt).json()['success']
            models = ok(root, 'GET', '/api/models/?p=1&page_size=100', token=rt)['items']
            metadata = next(m for m in models if m['model_name'] == MODEL)
            ok(root, 'DELETE', '/api/models/' + str(metadata['id']), token=rt)
            assert next(c for c in ok(root, 'GET', '/api/channel/?p=1&page_size=10', token=rt)['items']
                        if c['name'] == 'public')['models'] == MODEL
            report['checks'].append('real Chinese delete confirmation removes channel-derived model; other channel/models preserved; metadata conflict rejected and existing metadata deletion retained')

            profile = ok(user, 'GET', '/api/user/self', token=ut)
            ok(root, 'POST', '/api/user/manage', {'id': profile['id'], 'action': 'add_quota',
                'mode': 'add', 'value': 1000000}, rt)
            ok(user, 'PUT', '/api/user/setting', {'notify_type': 'email',
                'notification_email': 'saved-recipient@example.test', 'quota_warning_threshold': 999900}, ut)
            ok(user, 'POST', '/api/token/', {'name': 'fixture-client', 'remain_quota': 100000,
                'expired_time': -1, 'unlimited_quota': False, 'model_limits_enabled': True,
                'model_limits': MODEL + ',private-fixture', 'group': 'default'}, ut)
            tokens = ok(user, 'GET', '/api/token/?p=1&size=10', token=ut)['items']
            customer_key = ok(user, 'POST', f'/api/token/{tokens[0]["id"]}/key', token=ut)['key']
            before = ok(user, 'GET', '/api/user/self', token=ut)['quota']
            response = call(user, 'POST', '/v1/chat/completions',
                {'model': MODEL, 'messages': [{'role': 'user', 'content': 'fixture'}]}, 'sk-' + customer_key)
            assert response.status == 200, ('customer API', response.status, response.json())
            assert response.json()['usage']['total_tokens'] == 120
            after = ok(user, 'GET', '/api/user/self', token=ut)['quota']
            assert before - after == 140, (before, after)
            for _ in range(50):
                if len(smtp.messages) > 2:
                    break
                time.sleep(0.1)
            assert len(smtp.messages) == 3 and smtp.messages[-1][0] == smtp.messages[0][0]
            assert '您的额度即将用尽' in str(email.header.make_header(email.header.decode_header(smtp.messages[-1][1]['Subject'])))
            report['checks'].append('real customer API charge crossing saved threshold sends low-balance notification over SMTP')
            count = len(Provider.requests)
            response = call(user, 'POST', '/v1/chat/completions',
                {'model': 'private-fixture', 'messages': [{'role': 'user', 'content': 'forbidden'}]}, 'sk-' + customer_key)
            assert response.status != 200 and len(Provider.requests) == count
            report['checks'].append('customer Key /v1 works and deducts exact 140 quota; inaccessible group model cannot be purchased merely by editing Key model limits')
            home = user.new_page()
            home.goto(base + '/h5/')
            expect(home.locator('#account-entry')).to_have_text('我的账户')
            assert not home.locator('textarea').count()
            for width in (390, 1440):
                home.set_viewport_size({'width': width, 'height': 960})
                assert home.evaluate('document.documentElement.scrollWidth <= innerWidth')
                home.screenshot(path=str(output / f'api-only-home-{width}.png'), full_page=True)
            report['checks'].append('API-only public page has no composer; logged-in account entry and mobile/desktop layouts work')
            if args.extended_scenarios:
                from sales_scenarios import run_sales_scenarios
                report['scenarios'] = run_sales_scenarios(
                    browser, base, gateway, root, user, rt, ut, call, ok, Provider)
                report['all_scenarios_passed'] = all(item['passed'] for item in report['scenarios'])
            if args.upstream_issues:
                from upstream_issue_scenarios import run_upstream_issue_scenarios
                report['upstream_issues'] = run_upstream_issue_scenarios(
                    base, gateway, root, user, rt, ut, call, ok)
                report['all_upstream_issue_checks_passed'] = all(item['passed'] for item in report['upstream_issues'])
            browser.close()
        report['completed'] = True
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()
        for name in reversed(containers):
            docker('rm', '-f', name)
        for name in reversed(networks):
            docker('network', 'rm', name)
        (output / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False))
    if args.extended_scenarios and not report['all_scenarios_passed']:
        raise SystemExit(1)
    if args.upstream_issues and not report['all_upstream_issue_checks_passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
