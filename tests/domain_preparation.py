#!/usr/bin/env python3
"""Read-only preparation tests. Generated configurations are never activated."""
import json
import http.client
import os
import secrets
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy"))
from prepare_domain import normalize_origin, render_draft


class DomainPreparation(unittest.TestCase):
    def test_self_deletion_policy(self):
        # This ingress points at its own empty loopback, never at a real New API service.
        name = 'self-delete-policy-' + secrets.token_hex(4)
        subprocess.run([
            'docker', 'run', '-d', '--name', name, '--add-host', 'new-api:127.0.0.1',
            '-p', '127.0.0.1::8080', '--user', '1000:1000', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges:true', '--read-only',
            '--tmpfs', '/tmp:rw,nosuid', '--log-driver', 'none',
            '-v', f'{ROOT / "nginx.conf"}:/etc/nginx/nginx.conf:ro',
            '-v', f'{ROOT / "h5"}:/srv/h5:ro',
            '-v', f'{ROOT / "console-dist"}:/srv/modelport-console:ro',
            '--entrypoint', 'nginx',
            'nginx@sha256:9874b7a098bbd4e9454941c9e3f87600d7a6e2bb081a06f453202933fe7520d1',
            '-g', 'daemon off;',
        ], check=True, capture_output=True)
        try:
            address = subprocess.check_output(['docker', 'port', name, '8080/tcp'], text=True).strip()
            port = int(address.rsplit(':', 1)[1])
            for attempt in range(40):
                connection = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
                try:
                    connection.request('GET', '/h5/')
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200)
                    response.read()
                    break
                except OSError:
                    if attempt == 39:
                        raise
                    time.sleep(0.1)
                finally:
                    connection.close()
            for path in [
                '/api/user/self', '/api/user/self/', '/api/user/self?confirm=true',
                '/api/user/%73elf', '/api//user/self', '/api/user/other/../self',
                '/api%2fuser%2fself', '/API/USER/SELF', '//api/user/self',
            ]:
                with self.subTest(path=path):
                    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
                    try:
                        connection.request('DELETE', path, headers={'X-Security-Proof': 'fixture-only'})
                        response = connection.getresponse()
                        self.assertEqual(response.status, 403)
                        self.assertEqual(response.getheader('Content-Type'), 'application/json')
                        self.assertEqual(response.getheader('Cache-Control'), 'no-store')
                        result = json.loads(response.read())
                        self.assertFalse(result['success'])
                        self.assertEqual(result['code'], 'SELF_ACCOUNT_DELETION_DISABLED')
                    finally:
                        connection.close()
            for method, path in [
                ('GET', '/api/user/self'), ('PUT', '/api/user/self'),
                ('DELETE', '/api/user/123'), ('DELETE', '/api/user/sessions/fixture'),
                ('DELETE', '/api/user/token'), ('DELETE', '/api/token/123'),
            ]:
                with self.subTest(method=method, path=path):
                    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
                    try:
                        connection.request(method, path)
                        response = connection.getresponse()
                        # The deliberately absent upstream proves these requests still use the proxy.
                        self.assertEqual(response.status, 502)
                        response.read()
                    finally:
                        connection.close()
        finally:
            subprocess.run(['docker', 'rm', '-f', name], check=True, capture_output=True)

    def test_exact_origins(self):
        self.assertEqual(normalize_origin("https://Models.Example.test:443/"),
                         ("https://models.example.test", "models.example.test", 443))
        self.assertEqual(normalize_origin("https://models.example.test:8443")[0],
                         "https://models.example.test:8443")
        for value in [
            "http://models.example.test", "https://*.example.test", "https://user:pass@example.test",
            "https://example.test/api", "https://example.test?next=x", "https://example.test#x",
            "https://example.test\nserver_name evil;", "https://127.0.0.1", "https://example.test:",
            "https://example.test:99999", "https://evil;name.test", "https://-bad.example.test",
        ]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_origin(value)

    def test_draft_does_not_change_active_files(self):
        active = {name: (ROOT / name).read_bytes() for name in ["nginx.conf", "compose.yaml"]}
        with tempfile.TemporaryDirectory(prefix=".domain-test-", dir=ROOT / "deploy") as temporary:
            output = Path(temporary) / "draft"
            manifest = render_draft("https://models.example.test:8443", output)
            self.assertFalse(manifest["approved_for_production"])
            self.assertIn("backend-dist/build-manifest.json", manifest["source_sha256"])
            self.assertIn("server_name localhost 127.0.0.1 models.example.test;",
                          (output / "backend-nginx.conf").read_text())
            self.assertIn('SELF_ACCOUNT_DELETION_DISABLED', (output / "backend-nginx.conf").read_text())
            tls = (output / "tls-nginx.conf.example").read_text()
            self.assertIn("listen 8443 ssl;", tls)
            self.assertIn("/REPLACE_WITH_PROTECTED_CERT_PATH/", tls)
            self.assertIn("Connection $api_platform_upgrade", tls)
            self.assertNotIn('Connection "upgrade"', tls)
            with self.assertRaises(FileExistsError):
                render_draft("https://models.example.test", output)
            overlay = json.loads((output / "compose.domain-draft.json").read_text())
            environment = overlay["services"]["new-api"]["environment"]
            self.assertEqual(environment["SESSION_COOKIE_SECURE"], "true")
            self.assertEqual(environment["SESSION_COOKIE_TRUSTED_URL"], manifest["origin"])
            self.assertTrue(environment["SESSION_SECRET"].startswith("${SESSION_SECRET:?"))
            # Compose validation only, with an in-memory fixture secret. Nothing is started.
            result = subprocess.run(
                ["docker", "compose", "-f", str(ROOT / "compose.yaml"), "-f",
                 str(output / "compose.domain-draft.json"), "config", "--format", "json"],
                env={**os.environ, "SESSION_SECRET": "fixture-only-not-a-real-production-secret"},
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, "Compose rejected the inactive domain overlay")
            effective = json.loads(result.stdout)
            ingress = effective["services"]["ingress"]
            self.assertEqual(ingress["ports"][0]["host_ip"], "127.0.0.1")
            self.assertTrue(effective["networks"]["isolated"]["internal"])
            self.assertEqual(effective["services"]["new-api"]["environment"]["TRUSTED_PROXIES"], "none")
            # Ephemeral test certificate only; validate both Nginx drafts without listening on a port.
            cert_dir = Path(temporary)
            cert = subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                "-keyout", str(cert_dir / "privkey.pem"), "-out", str(cert_dir / "fullchain.pem"),
                "-days", "1", "-subj", "/CN=models.example.test"], capture_output=True)
            self.assertEqual(cert.returncode, 0, "Could not generate the ephemeral parser-test certificate")
            tls = tls.replace("/REPLACE_WITH_PROTECTED_CERT_PATH", "/test-certs")
            wrapper = ("pid /tmp/nginx.pid;\nerror_log stderr warn;\nevents {}\nhttp {\n"
                       "client_body_temp_path /tmp/client_temp;\nproxy_temp_path /tmp/proxy_temp;\n"
                       "fastcgi_temp_path /tmp/fastcgi_temp;\nuwsgi_temp_path /tmp/uwsgi_temp;\n"
                       "scgi_temp_path /tmp/scgi_temp;\n" + tls + "\n}\n")
            (output / "tls-parser-test.conf").write_text(wrapper)
            for configuration in ["backend-nginx.conf", "tls-parser-test.conf"]:
                parsed = subprocess.run(["docker", "run", "--rm", "--network", "none",
                    "--add-host", "new-api:127.0.0.1", "--user", "1000:1000", "--cap-drop", "ALL",
                    "--security-opt", "no-new-privileges:true", "--read-only", "--tmpfs", "/tmp:rw,nosuid",
                    "-v", f"{output / configuration}:/etc/nginx/nginx.conf:ro",
                    "-v", f"{cert_dir}:/test-certs:ro", "--entrypoint", "nginx",
                    "-v", f"{ROOT / 'console-dist'}:/srv/modelport-console:ro",
                    "nginx@sha256:9874b7a098bbd4e9454941c9e3f87600d7a6e2bb081a06f453202933fe7520d1",
                    "-t"], capture_output=True, text=True)
                self.assertEqual(parsed.returncode, 0, f"Nginx rejected {configuration}: {parsed.stderr}")
        for name, data in active.items():
            self.assertEqual((ROOT / name).read_bytes(), data)

    def test_reject_output_outside_deploy(self):
        with self.assertRaises(ValueError):
            render_draft("https://models.example.test", ROOT / "data")


if __name__ == "__main__":
    unittest.main()
