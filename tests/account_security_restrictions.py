#!/usr/bin/env python3
"""Account-security acceptance: disposable Go backend, in-memory credentials, no production writes.

Uses existing Docker/Playwright fixture conventions; never mounts production data.
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import struct
import tempfile
import time
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright
from chat_integration import docker, IMAGES

ROOT = Path(__file__).resolve().parents[1]
POLICY = 'ACCOUNT_SECURITY_MANAGED_BY_ADMIN'
BLOCKED = [
    ('DELETE', '/api/user/sessions/fixture'),
    ('POST', '/api/user/sessions/revoke-others'),
    ('GET', '/api/user/token'), ('POST', '/api/user/token'), ('DELETE', '/api/user/token'),
    ('POST', '/api/user/passkey/register/begin'), ('POST', '/api/user/passkey/register/finish'),
    ('DELETE', '/api/user/passkey'),
    ('POST', '/api/user/2fa/setup'), ('POST', '/api/user/2fa/enable'),
    ('POST', '/api/user/2fa/disable'), ('POST', '/api/user/2fa/backup_codes'),
    ('DELETE', '/api/user/oauth/bindings/1'),
    ('POST', '/api/oauth/email/bind/start'), ('POST', '/api/oauth/email/bind/resend'),
    ('POST', '/api/oauth/email/bind'), ('POST', '/api/oauth/wechat/bind'),
]


def totp(secret):
    key = base64.b32decode(secret + '=' * ((-len(secret)) % 8))
    digest = hmac.new(key, struct.pack('>Q', int(time.time()) // 30), hashlib.sha1).digest()
    offset = digest[-1] & 15
    return str((struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7fffffff) % 1000000).zfill(6)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api-image', default='modelport-new-api:account-security-v1')
    parser.add_argument('--console-dist', default='.console-build/web/dist')
    parser.add_argument('--output', default='evidence/account-security-restrictions/http-browser')
    args = parser.parse_args()
    output = (ROOT / args.output).resolve()
    dist = (ROOT / args.console_dist).resolve()
    assert output.is_relative_to(ROOT) and dist.is_relative_to(ROOT)
    output.mkdir(parents=True, exist_ok=True)
    tag = 'account-security-' + secrets.token_hex(4)
    containers, networks = [], []
    report = {'completed': False, 'production_writes': 0, 'paid_calls': 0,
              'checks': [], 'blocked_endpoints': [], 'fixture_critical_rate_limit': 200}
    def check(name):
        report['checks'].append(name)
    os.environ['TMPDIR'] = '/tmp'
    try:
        for name, internal in [(tag, True), (tag + '-edge', False)]:
            docker('network', 'create', *(['--internal'] if internal else []), name)
            networks.append(name)
        for component in ['api', 'ingress']:
            name = tag + '-' + component
            cmd = ['run', '-d', '--name', name, '--network', tag, '--log-driver', 'none',
                   '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
                   '--user', '1000:1000', '--read-only',
                   '--tmpfs', '/tmp:rw,nosuid,size=256m,mode=1777', '--memory', '1g', '--cpus', '2']
            if component == 'api':
                cmd += ['--network-alias', 'new-api', '-e', 'SQLITE_PATH=/tmp/fixture.db',
                        '-e', 'SESSION_COOKIE_SECURE=false', '-e', 'TRUSTED_PROXIES=none',
                        '-e', 'BATCH_UPDATE_ENABLED=false', '-e', 'CRITICAL_RATE_LIMIT=200',
                        args.api_image, '--port', '3000', '--log-dir', '/tmp/logs']
            else:
                cmd += ['--network', tag + '-edge', '-p', '127.0.0.1::8080',
                        '-v', f'{ROOT / "nginx.conf"}:/etc/nginx/nginx.conf:ro',
                        '-v', f'{ROOT / "h5"}:/srv/h5:ro',
                        '-v', f'{dist}:/srv/modelport-console:ro', '--entrypoint', 'nginx',
                        IMAGES['ingress'], '-g', 'daemon off;']
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
            browser = p.chromium.launch(executable_path='/usr/bin/google-chrome',
                headless=True, chromium_sandbox=True, args=['--disable-gpu'])
            root = browser.new_context(locale='en-US')
            user = browser.new_context(locale='en-US', reduced_motion='reduce')
            admin = browser.new_context(locale='en-US', reduced_motion='reduce')
            other = browser.new_context(locale='en-US')
            anon = browser.new_context(locale='en-US')
            for context in [root, user, admin, other, anon]:
                context.add_init_script("localStorage.setItem('i18nextLng', 'en')")
            password, new_password = secrets.token_urlsafe(24), secrets.token_urlsafe(24)

            def call(ctx, method, path, data=None, token=None, headers=None):
                h = {'Origin': base, **(headers or {})}
                if token:
                    h['Authorization'] = 'Bearer ' + token
                response = ctx.request.fetch(base + path, method=method, data=data, headers=h)
                body = response.json() if response.body() else {}
                return response.status, body

            def ok(ctx, method, path, data=None, token=None, headers=None):
                status, body = call(ctx, method, path, data, token, headers)
                assert status == 200 and body.get('success') is True, f'{method} {path}: HTTP {status}, code={body.get("code", "none")}'
                return body.get('data')

            ok(root, 'POST', '/api/setup', {'username': 'fixture_root', 'password': password, 'confirmPassword': password})
            root_bundle = ok(root, 'POST', '/api/user/login', {'username': 'fixture_root', 'password': password})
            rt = root_bundle['access_token']
            for name, role in [('fixture_user', 1), ('fixture_admin', 10)]:
                ok(root, 'POST', '/api/user/', {'username': name, 'display_name': name, 'password': password, 'role': role}, rt)
            def browser_login(ctx, name, pw):
                page = ctx.new_page()
                page.goto(base + '/sign-in?redirect=%2Fsecurity')
                page.locator('input[name=username]').fill(name)
                page.locator('input[name=password]').fill(pw)
                with page.expect_response(lambda r: r.url.split('?')[0].endswith('/api/user/login') and r.request.method == 'POST') as result:
                    page.locator('form button[type=submit]').click()
                bundle = result.value.json().get('data')
                assert bundle and bundle.get('access_token'), 'fixture browser login failed'
                page.wait_for_url(base + '/security')
                expect(page.get_by_role('button', name='Change Password', exact=True)).to_be_visible()
                return page, bundle

            page, bundle = browser_login(user, 'fixture_user', password)
            ut = bundle['access_token']
            for width in [390, 1440]:
                page.set_viewport_size({'width': width, 'height': 960})
                page.reload()
                expect(page.get_by_role('button', name='Change Password', exact=True)).to_be_visible()
                for text in ['Account Bindings', 'Sessions & Access', 'Passkey Login', 'Two-Factor Authentication', 'Record IP Address', 'Access Token', 'Delete Account']:
                    expect(page.get_by_text(text, exact=True)).to_have_count(0)
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(output / f'user-security-{width}.png'), full_page=True)
            check('compiled ordinary-user page: only password card, 390/1440, refresh retained')
            # Browser refresh rotates access tokens, so obtain an independent valid HTTP session.
            bundle = ok(user, 'POST', '/api/user/auth/refresh')
            ut = bundle['access_token']
            forged = {'X-Role': '100', 'New-Api-User': str(root_bundle['user']['id']), 'X-Admin': 'true'}
            for method, path in BLOCKED:
                status, body = call(user, method, path, {'role': 100, 'admin': True}, ut, forged)
                assert status == 403 and body.get('code') == POLICY, f'policy {method} {path}: {status}'
                report['blocked_endpoints'].append({'method': method, 'path': path, 'status': status})
            for provider in ['github', 'oidc', 'telegram', 'custom-fixture']:
                status, body = call(user, 'POST', '/api/oauth/state', {'intent': 'bind', 'provider': provider, 'role': 100}, ut, forged)
                assert status == 403 and body.get('code') == POLICY
            settings = {'notify_type': 'email', 'quota_warning_threshold': 500}
            before = ok(user, 'GET', '/api/user/self', token=ut)
            privacy = bool(json.loads(before.get('setting') or '{}').get('record_ip_log'))
            status, body = call(user, 'PUT', '/api/user/setting', {**settings, 'record_ip_log': not privacy}, ut, forged)
            assert status == 403 and body.get('code') == POLICY
            ok(user, 'PUT', '/api/user/setting', settings, ut)
            ok(user, 'PUT', '/api/user/setting', {**settings, 'record_ip_log': privacy}, ut)
            ok(user, 'PUT', '/api/user/self', {'language': 'en', 'role': 100}, ut)
            assert ok(user, 'GET', '/api/user/self', token=ut)['role'] == 1
            assert call(user, 'GET', '/api/user/', token=ut, headers=forged)[0] == 403
            pieces = ut.split('.')
            claims = json.loads(base64.urlsafe_b64decode(pieces[1] + '=' * (-len(pieces[1]) % 4)))
            claims['role'] = 100
            pieces[1] = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=')
            assert call(user, 'POST', '/api/user/2fa/setup', {}, '.'.join(pieces))[0] == 401
            check('17 forbidden mutation routes + OAuth bind + privacy: direct HTTP 403; forged headers/body/JWT cannot escalate')
            for path in ['/api/user/self', '/api/user/2fa/status', '/api/user/passkey', '/api/verify/methods?scope=account.password.change']:
                ok(user, 'GET', path, token=ut)
            for path in ['/api/user/login/2fa', '/api/user/login/verify', '/api/user/login/passkey/begin', '/api/user/login/passkey/finish', '/api/user/passkey/login/begin', '/api/user/passkey/login/finish', '/api/user/passkey/verify/begin', '/api/user/passkey/verify/finish', '/api/user/reset']:
                status, body = call(user, 'POST', path, {}, ut)
                assert status != 404 and body.get('code') != POLICY, path
            status, body = call(anon, 'GET', '/api/reset_password?email=invalid')
            assert status != 404 and body.get('code') != POLICY
            check('auth/recovery/passkey verification routes reachable; invalid input rejected by original handlers (not successful recovery)')
            for path in ['/api/user/self', '/api/user/self/', '/api//user/self', '/api/user/%73elf?fixture=1']:
                status, body = call(user, 'DELETE', path, token=ut)
                assert status == 403 and body.get('code') == 'SELF_ACCOUNT_DELETION_DISABLED'
            check('existing ingress self-deletion prohibition incl normalized URI variants')
            second = ok(other, 'POST', '/api/user/login', {'username': 'fixture_user', 'password': password})
            # Reload gives the browser its own current token before using the native password dialog.
            page.reload()
            page.get_by_role('button', name='Change Password', exact=True).click()
            dialog = page.get_by_role('dialog', name='Change Password')
            dialog.get_by_label('Current Password', exact=True).fill(password)
            dialog.get_by_label('New Password', exact=True).fill(new_password)
            dialog.get_by_label('Confirm New Password', exact=True).fill(new_password)
            with page.expect_response(lambda r: r.url.endswith('/api/user/self') and r.request.method == 'PUT') as changed:
                dialog.get_by_role('button', name='Change Password', exact=True).click()
            result = changed.value.json()
            assert result.get('success') is True, 'password change failed'
            expect(dialog).not_to_be_visible()
            ut = result['data']['access_token']
            ok(user, 'GET', '/api/user/self', token=ut)
            assert call(other, 'GET', '/api/user/self', token=second['access_token'])[0] == 401
            assert call(other, 'POST', '/api/user/auth/refresh')[0] == 401
            assert call(anon, 'POST', '/api/user/login', {'username': 'fixture_user', 'password': password})[1].get('success') is not True
            ok(anon, 'POST', '/api/user/login', {'username': 'fixture_user', 'password': new_password})
            ok(user, 'POST', '/api/user/auth/refresh')
            page.reload()
            expect(page.get_by_role('button', name='Change Password', exact=True)).to_be_visible()
            page.locator('button:has([data-slot="avatar"]):visible').last.click()
            page.get_by_role('menuitem', name='Sign out', exact=True).click()
            with page.expect_response(lambda r: r.url.endswith('/api/user/auth/logout')) as logged_out:
                page.get_by_role('alertdialog', name='Sign out').get_by_role('button', name='Sign out', exact=True).click()
            assert logged_out.value.json().get('success') is True
            page.wait_for_url(base + '/sign-in')
            assert call(user, 'POST', '/api/user/auth/refresh')[0] == 401
            check('native browser password change succeeds; old password and other-session token/refresh revoked; current refresh/logout unchanged')

            ap, ab = browser_login(admin, 'fixture_admin', password)
            at = ab['access_token']
            for text in ['Account Bindings', 'Sessions & Access', 'Passkey Login', 'Two-Factor Authentication', 'Record IP Address']:
                expect(ap.get_by_text(text, exact=True).first).to_be_visible()
            ap.screenshot(path=str(output / 'admin-security.png'), full_page=True)
            ok(admin, 'PUT', '/api/user/setting', {**settings, 'record_ip_log': True}, at)
            for method, path in BLOCKED:
                status, body = call(admin, method, path, {}, at)
                assert body.get('code') != POLICY, f'admin blocked {method} {path}'
            # A complete admin MFA setup proves this is still functional, not merely a different error.
            proof = ok(admin, 'POST', '/api/verify', {'scope': '2fa.setup', 'method': 'password', 'password': password}, at)
            setup = ok(admin, 'POST', '/api/user/2fa/setup', {}, at, {'X-Security-Proof': proof['proof_token']})
            rotation = ok(admin, 'POST', '/api/user/2fa/enable', {'flow_token': setup['flow_token'], 'code': totp(setup['secret'])}, at)
            at = rotation['access_token']
            assert ok(admin, 'GET', '/api/user/2fa/status', token=at)['enabled']
            check('role-10 admin retains cards and settings endpoints; real privacy save + MFA enrollment succeeded')
            # Convert this disposable admin into a common user using root management, preserving MFA.
            # This yields an existing-factor customer without ever granting customers enrollment rights.
            account = ok(root, 'GET', f'/api/user/{ab["user"]["id"]}', token=rt)
            ok(root, 'POST', '/api/user/manage', {'id': account['id'], 'action': 'demote'}, rt)
            challenge = ok(other, 'POST', '/api/user/login', {'username': 'fixture_admin', 'password': password})
            assert 'access_token' not in challenge and challenge.get('flow_token'), 'MFA unexpectedly bypassed'
            # A setup TOTP may already have been consumed: use a single-use recovery code from the fixture.
            verified = ok(other, 'POST', '/api/user/login/verify', {'flow_token': challenge['flow_token'], 'method': '2fa', 'code': setup['backup_codes'][0]})
            ct = verified['access_token']
            assert verified['user']['role'] == 1
            assert ok(other, 'GET', '/api/user/2fa/status', token=ct)['enabled']
            status, body = call(other, 'POST', '/api/user/2fa/disable', {}, ct)
            assert status == 403 and body.get('code') == POLICY
            assert ok(other, 'GET', '/api/user/2fa/status', token=ct)['enabled']
            ok(other, 'POST', '/api/user/auth/refresh')
            ok(other, 'POST', '/api/user/auth/logout')
            check('existing-MFA common-user login requires challenge; real recovery-code challenge completes; forbidden disable preserves factor')
            browser.close()
        report['completed'] = True
    finally:
        for name in reversed(containers):
            docker('rm', '-f', name)
        for name in reversed(networks):
            docker('network', 'rm', name)
        (output / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
