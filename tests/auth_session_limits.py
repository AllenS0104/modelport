#!/usr/bin/env python3
"""Exercise real account switching and login throttling in a disposable backend only."""
import argparse
import http.cookiejar
import json
import secrets
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener

from chat_integration import docker

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api-image', required=True)
    parser.add_argument('--output', default='evidence/auth-session-limits')
    args = parser.parse_args()
    output = (ROOT / args.output).resolve()
    assert output.is_relative_to(ROOT)
    output.mkdir(parents=True, exist_ok=True)
    name = 'auth-limits-' + secrets.token_hex(4)
    report = {'production_writes': 0, 'paid_calls': 0, 'critical_limit': '20 per 1200 seconds'}
    docker('run', '-d', '--name', name, '-p', '127.0.0.1::3000', '--log-driver', 'none',
           '--user', '1000:1000', '--read-only', '--cap-drop', 'ALL',
           '--security-opt', 'no-new-privileges:true', '--memory', '1g', '--cpus', '2',
           '--tmpfs', '/tmp:rw,nosuid,size=256m,mode=1777',
           '-e', 'SQLITE_PATH=/tmp/fixture.db', '-e', 'SESSION_COOKIE_SECURE=false',
           '-e', 'TRUSTED_PROXIES=none', '-e', 'BATCH_UPDATE_ENABLED=false',
           args.api_image, '--port', '3000', '--log-dir', '/tmp/logs')
    try:
        port = docker('port', name, '3000/tcp').rsplit(':', 1)[1]
        base = 'http://127.0.0.1:' + port
        admin = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
        client = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
        anonymous = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))

        def call(opener, method, path, data=None, token=None):
            headers = {'Content-Type': 'application/json', 'Origin': base}
            if token:
                headers['Authorization'] = 'Bearer ' + token
            body = json.dumps(data).encode() if data is not None else None
            request = Request(base + path, method=method, data=body, headers=headers)
            try:
                response = opener.open(request, timeout=10)
            except HTTPError as error:
                response = error
            with response:
                raw = response.read()
                return response.status, dict(response.headers), json.loads(raw) if raw else {}

        def success(opener, method, path, data=None, token=None):
            status, _, body = call(opener, method, path, data, token)
            assert status == 200 and body.get('success') is True, f'{method} {path}: HTTP {status}'
            return body.get('data')

        for attempt in range(60):
            try:
                success(anonymous, 'GET', '/api/setup')
                break
            except (URLError, OSError):
                if attempt == 59:
                    raise
                time.sleep(0.2)
        password = secrets.token_urlsafe(24)
        success(admin, 'POST', '/api/setup', {
            'username': 'fixtureadmin', 'password': password, 'confirmPassword': password})
        root = success(admin, 'POST', '/api/user/login', {'username': 'fixtureadmin', 'password': password})
        for key in ['RegisterEnabled', 'PasswordRegisterEnabled']:
            success(admin, 'PUT', '/api/option/', {'key': key, 'value': 'true'}, root['access_token'])
        success(admin, 'PUT', '/api/option/', {'key': 'EmailVerificationEnabled', 'value': 'false'}, root['access_token'])
        for username in ['fixturea', 'fixtureb']:
            success(anonymous, 'POST', '/api/user/register', {'username': username, 'password': password})

        for _ in range(25):
            status, _, _ = call(anonymous, 'POST', '/api/user/auth/refresh')
            assert status == 401, f'Anonymous restore consumed login budget: HTTP {status}'
        switches = []
        for index in range(6):
            username = ['fixturea', 'fixtureb'][index % 2]
            bundle = success(client, 'POST', '/api/user/login', {'username': username, 'password': password})
            assert bundle['user']['username'] == username
            for _ in range(5):
                bundle = success(client, 'POST', '/api/user/auth/refresh')
                assert bundle['user']['username'] == username
                profile = success(client, 'GET', '/api/user/self', token=bundle['access_token'])
                assert profile['username'] == username
            switches.append(username)
            if index < 5:
                success(client, 'POST', '/api/user/auth/logout', token=bundle['access_token'])
                assert call(client, 'POST', '/api/user/auth/refresh')[0] == 401

        blocked = False
        for _ in range(21):
            status, headers, _ = call(anonymous, 'POST', '/api/user/login', {
                'username': 'fixturea', 'password': 'wrong-fixture-password'})
            if status == 429:
                assert headers.get('Retry-After') == '1200'
                blocked = True
                break
        assert blocked, 'Credential-guessing protection was weakened or disabled'
        bundle = success(client, 'POST', '/api/user/auth/refresh')
        assert bundle['user']['username'] == 'fixtureb'
        success(client, 'POST', '/api/user/auth/logout', token=bundle['access_token'])
        assert call(client, 'POST', '/api/user/auth/refresh')[0] == 401
        report.update({'completed': True, 'account_switches': len(switches),
                       'anonymous_restores': 25, 'authenticated_restores': 31,
                       'login_throttles': True, 'refresh_and_logout_work_when_login_throttled': True})
    finally:
        docker('rm', '-f', name)
        (output / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
