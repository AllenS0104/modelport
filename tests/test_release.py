import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy"))
import release
import runtime


class ReleaseTests(unittest.TestCase):
    def test_rejects_unsafe_names(self):
        for name in ["../escape", "/absolute", "data/users.db", ".env", "a/.env.local",
                     "backups/copy", "a/private.pem", "C:/escape", "a\\b", "a//b",
                     "a/./b", ".git/config", "evidence/account.json", "keys/token.key"]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                release.safe_name(name)
        self.assertEqual(str(release.safe_name("console/overrides/src/index.tsx")),
                         "console/overrides/src/index.tsx")
        self.assertEqual(str(release.safe_name("upstream/web/src/features/usage-logs/data")),
                         "upstream/web/src/features/usage-logs/data")

    def test_export_excludes_runtime_data_and_requires_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input"
            source.mkdir()
            for name in release.FILES:
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fixture\n")
            for name in ["data/one-api.db", "backups/customer.txt", ".env",
                         "evidence/customer.json", "HANDOFF.zh-CN.md", "scripts/secret.py"]:
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("must-not-be-exported")
            output = root / "output"
            release.copy_sources(source, output)
            for path in output.rglob("*"):
                if path.is_file():
                    self.assertNotIn(b"must-not-be-exported", path.read_bytes())
            self.assertTrue((output / ".gitignore").is_file())
            self.assertIn(b"* -text", (output / ".gitattributes").read_bytes())
            with self.assertRaises(FileExistsError):
                release.copy_sources(source, output)
            (source / "compose.yaml").unlink()
            with self.assertRaises(ValueError):
                release.source_files(source)

    @unittest.skipIf(os.name == "nt", "Requires Linux symlink permissions")
    def test_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "original").write_text("fixture")
            (root / "link").symlink_to(root / "original")
            with self.assertRaises(ValueError):
                release.checked_file(root, "link")

    def test_verify_detects_tampering_and_missing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = root / "payload.txt"
            payload.write_text("fixture")
            manifest = {"schema": 1, "contains_business_data": False,
                        "files": {"payload.txt": release.digest(payload)}}
            (root / "release-manifest.json").write_text(json.dumps(manifest))
            self.assertEqual(release.verify(root), manifest)
            payload.write_text("changed")
            with self.assertRaises(ValueError):
                release.verify(root)
            payload.unlink()
            with self.assertRaises(ValueError):
                release.verify(root)

    def test_rejects_wrong_backend_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "file.py").write_text("current")
            manifest = {"upstream_commit": release.UPSTREAM,
                        "source_sha256": {"file.py": hashlib.sha256(b"old").hexdigest()}}
            with self.assertRaises(ValueError):
                release.verify_sources(root, manifest)

    def test_export_cannot_recurse_into_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                release.copy_sources(root, root / "backend" / "nested")

    def test_seal_refuses_runtime_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data").mkdir()
            with self.assertRaises(ValueError):
                release.seal_build(root)

    def test_oci_platform_manifest_and_classic_config_identity(self):
        image = {"origin_image_id": "sha256:index", "config_sha256": "config",
                 "export_manifest_id": "sha256:platform", "tag": "fixture:v1",
                 "diff_ids": ["sha256:layer"]}
        with patch.object(runtime, "verify", return_value={"images": {"new-api": image}}):
            for identity in ["sha256:index", "sha256:platform", "sha256:config"]:
                info = {"Id": identity, "Os": "linux", "Architecture": "amd64",
                        "RootFS": {"Layers": ["sha256:layer"]}}
                with patch.object(runtime, "docker", return_value=json.dumps([info])), \
                        contextlib.redirect_stdout(io.StringIO()):
                    runtime.check_images(Path("."))
            info["Id"] = "sha256:unrelated"
            with patch.object(runtime, "docker", return_value=json.dumps([info])), \
                    self.assertRaises(ValueError):
                runtime.check_images(Path("."))

    def test_source_archive_rejects_unexpected_data(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "source.tar.gz"
            with tarfile.open(archive, "w:gz") as output:
                for name in ["upstream/LICENSE", "backend/auth-session-limits.patch",
                             "console/build.py", "data/one-api.db"]:
                    member = tarfile.TarInfo(name)
                    member.size = 7
                    output.addfile(member, io.BytesIO(b"fixture"))
            with self.assertRaises(ValueError):
                release.archive_sources_ok(archive)

    def test_source_archive_allows_only_selected_regressions(self):
        required = ["upstream/LICENSE", "backend/auth-session-limits.patch", "console/build.py"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "source.tar.gz"
            for extra in ["tests/api_sales.py", "tests/sales_scenarios.py",
                          "tests/fixtures/issue_7498_test.go", "tests/private-customer.json"]:
                names = required + [extra]
                with tarfile.open(archive, "w:gz") as output:
                    for name in names:
                        path = root / name
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(b"fixture")
                        member = tarfile.TarInfo(name)
                        member.size = 7
                        output.addfile(member, io.BytesIO(b"fixture"))
                if extra in release.SOURCE_ARCHIVE_FILES:
                    release.archive_sources_ok(archive, root)
                    (root / extra).write_bytes(b"modified")
                    with self.assertRaises(ValueError):
                        release.archive_sources_ok(archive, root)
                else:
                    with self.assertRaises(ValueError):
                        release.archive_sources_ok(archive, root)

    def test_export_includes_api_only_fixtures_and_website_plan(self):
        self.assertTrue({
            "tests/api_sales.py", "tests/sales_scenarios.py",
            "tests/upstream_issue_scenarios.py", "tests/account_security_restrictions.py",
            "tests/fixtures/issue_7498_test.go", "docs/WEBSITE-CONTENT-PLAN.zh-CN.md",
        } <= release.FILES)

    def test_initialize_secrets_and_isolation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = {
                "name": "api-sales-platform-local",
                "networks": {"isolated": {"internal": True, "name": "production-isolated"},
                             "ingress": {"name": "production-ingress"}},
                "services": {
                    "new-api": {"environment": {"TRUSTED_PROXIES": "none"}},
                    "ingress": {"ports": [{"published": "13000"}]},
                },
            }
            manifest = {"images": {"new-api": {"tag": "fixture-api:v1"},
                                   "ingress": {"tag": "fixture-ingress:v1"}}}
            with patch.object(runtime, "verify", return_value=manifest), \
                    patch.object(runtime, "docker", return_value=json.dumps(config)), \
                    patch.object(runtime.os, "geteuid", return_value=1000, create=True), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                runtime.initialize(root, "modelport-fixture", 0)
                secrets_before = (root / ".runtime.env").read_bytes()
                with self.assertRaises(FileExistsError):
                    runtime.initialize(root, "modelport-fixture", 0)
            effective = json.loads((root / "compose.runtime.json").read_text())
            self.assertEqual(effective["name"], "modelport-fixture")
            self.assertNotIn("name", effective["networks"]["isolated"])
            self.assertTrue(effective["networks"]["isolated"]["internal"])
            self.assertEqual(effective["services"]["ingress"]["ports"],
                             [{"host_ip": "127.0.0.1", "target": 8080,
                               "published": "0", "protocol": "tcp"}])
            self.assertNotIn("ports", effective["services"]["new-api"])
            environment = effective["services"]["new-api"]["environment"]
            self.assertEqual(environment["TRUSTED_PROXIES"], "none")
            self.assertTrue(environment["SESSION_SECRET"].startswith("${"))
            values = [line.split("=", 1)[1] for line in secrets_before.decode().splitlines()]
            self.assertEqual(len(set(values)), 2)
            for value in values:
                self.assertEqual(len(value), 64)
                self.assertNotIn(value, output.getvalue())
                self.assertNotIn(value, json.dumps(effective))
            self.assertEqual((root / ".runtime.env").read_bytes(), secrets_before)
            if os.name != "nt":
                self.assertEqual((root / ".runtime.env").stat().st_mode & 0o777, 0o600)

    def test_online_backup_includes_wal_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "live.db"
            source = sqlite3.connect(database)
            try:
                source.execute("PRAGMA journal_mode=WAL")
                source.execute("CREATE TABLE fixture (value TEXT)")
                source.execute("INSERT INTO fixture VALUES ('fixture-ledger-entry')")
                source.commit()
                self.assertTrue(Path(str(database) + "-wal").exists())
                destination = root / "private" / "snapshot.db"
                with contextlib.redirect_stdout(io.StringIO()):
                    runtime.backup(database, destination)
                connection = sqlite3.connect(destination)
                try:
                    self.assertEqual(connection.execute("SELECT value FROM fixture").fetchall(),
                                     [("fixture-ledger-entry",)])
                finally:
                    connection.close()
                before = release.digest(destination)
                with self.assertRaises(FileExistsError):
                    runtime.backup(database, destination)
                self.assertEqual(release.digest(destination), before)
                restored = root / "restored" / "one-api.db"
                with contextlib.redirect_stdout(io.StringIO()):
                    runtime.backup(destination, restored)
                connection = sqlite3.connect(restored)
                try:
                    self.assertEqual(connection.execute("SELECT count(*) FROM fixture").fetchone(), (1,))
                    self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone(), ("ok",))
                finally:
                    connection.close()
            finally:
                source.close()

    def test_invalid_database_leaves_no_success_shaped_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "invalid.db"
            source.write_bytes(b"not a database")
            destination = root / "private" / "snapshot.db"
            with self.assertRaises(sqlite3.DatabaseError):
                runtime.backup(source, destination)
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
