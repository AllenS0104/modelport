#!/usr/bin/env python3
"""Create and verify an allowlisted, data-free ModelPort release."""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = "385d2dfd10d821b25c8a6766bd16eea248cb1652"
NGINX = "nginx@sha256:9874b7a098bbd4e9454941c9e3f87600d7a6e2bb081a06f453202933fe7520d1"
DIRECTORIES = {"backend", "console", "h5", "preview"}
FILES = {
    "compose.yaml", "nginx.conf", "LICENSE.new-api", "NOTICE.new-api",
    "THIRD-PARTY-LICENSES.new-api.md", "version-lock.json",
    "deploy/release.py", "deploy/runtime.py", "deploy/README.zh-CN.md",
    "deploy/MIGRATION.zh-CN.md", "deploy/release.gitignore",
    "deploy/prepare_domain.py", "deploy/domain-nginx.conf.example",
    "deploy/DOMAIN-PLAN.zh-CN.md", "tests/test_release.py",
    "tests/auth_session_limits.py", "tests/chat_integration.py",
    "tests/console_interface.py", "tests/public_site.py",
    "tests/session_controls.py", "tests/features_registration_model.py",
    "tests/domain_preparation.py", "tests/update_h5_csp.py",
    "tests/api_sales.py", "tests/sales_scenarios.py", "tests/upstream_issue_scenarios.py",
    "tests/account_security_restrictions.py", "tests/fixtures/issue_7498_test.go",
    "ACCOUNT-SECURITY-RESTRICTIONS.zh-CN.md", "docs/WEBSITE-CONTENT-PLAN.zh-CN.md",
}
SOURCE_ARCHIVE_FILES = {
    "ACCOUNT-SECURITY-RESTRICTIONS.zh-CN.md",
    "tests/account_security_restrictions.py", "tests/auth_session_limits.py",
    "tests/api_sales.py", "tests/sales_scenarios.py", "tests/upstream_issue_scenarios.py",
    "tests/fixtures/issue_7498_test.go", "tests/chat_integration.py",
    "tests/console_interface.py", "tests/public_site.py",
}
FORBIDDEN = {
    ".git", ".env", "data", "backups", "evidence", "node_modules",
    "__pycache__", ".console-build", ".backend-build", "secrets",
}


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def safe_name(name):
    path = PurePosixPath(name)
    if (not name or "\\" in name or path.is_absolute() or ":" in name
            or any(part in {"", ".", ".."} for part in name.split("/"))
            or path.parts[0] in {"data", "backups", "evidence"}
            or any(part in FORBIDDEN - {"data", "backups", "evidence"}
                   or part.startswith(".env") for part in path.parts)
            or path.suffix.lower() in {".db", ".sqlite", ".sqlite3", ".env", ".pem", ".key", ".log"}):
        raise ValueError(f"Unsafe release member: {name}")
    return path


def checked_file(root, name):
    safe_name(name)
    path = root / name
    if any(parent.is_symlink() for parent in [path, *path.parents] if parent != root.parent):
        raise ValueError(f"Symlinks are not release inputs: {name}")
    if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Missing or escaped release input: {name}")
    return path


def source_files(root):
    names = set(FILES)
    for directory in DIRECTORIES:
        for path in (root / directory).rglob("*"):
            if "__pycache__" in path.parts:
                continue
            if path.is_symlink():
                raise ValueError(f"Symlink in source directory: {path.name}")
            if path.is_file():
                names.add(path.relative_to(root).as_posix())
    return {name: checked_file(root, name) for name in sorted(names)}


def verify_sources(root, manifest):
    if manifest["upstream_commit"] != UPSTREAM:
        raise ValueError("Unexpected upstream commit")
    for name, expected in manifest["source_sha256"].items():
        if digest(checked_file(root, name)) != expected:
            raise ValueError(f"Backend build source mismatch: {name}")


def copy_sources(root, destination):
    if destination.resolve().is_relative_to(root.resolve()):
        raise ValueError("Export into a new directory outside the source tree")
    destination.mkdir(parents=True, exist_ok=False)
    for name, source in source_files(root).items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    shutil.copyfile(root / "deploy/README.zh-CN.md", destination / "README.md")
    shutil.copyfile(root / "deploy/release.gitignore", destination / ".gitignore")
    # Release manifests and CSP bind exact bytes, including existing mixed line endings.
    (destination / ".gitattributes").write_bytes(b"* -text\n*.gz binary\n*.tar binary\n")


def archive_sources_ok(path, root=None):
    with tarfile.open(path) as archive:
        names = set()
        for member in archive:
            # This is a public, pinned upstream example, not an operator's .env.
            if member.name != "upstream/.env.example":
                safe_name(member.name.rstrip("/"))
            if not member.isfile() and not member.isdir():
                raise ValueError("Corresponding source contains a non-regular member")
            top = PurePosixPath(member.name).parts[0]
            if top not in {"upstream", "backend", "console"} and member.name not in SOURCE_ARCHIVE_FILES:
                raise ValueError("Unexpected corresponding-source directory")
            names.add(member.name)
            if root and member.isfile() and (top in {"backend", "console"} or member.name in SOURCE_ARCHIVE_FILES):
                source = checked_file(root, member.name)
                if hashlib.sha256(archive.extractfile(member).read()).hexdigest() != digest(source):
                    raise ValueError(f"Corresponding source differs from maintained source: {member.name}")
        if not {"upstream/LICENSE", "backend/auth-session-limits.patch", "console/build.py"} <= names:
            raise ValueError("Corresponding source is incomplete")


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True).strip()


def build(root, output, version):
    if output.is_relative_to(root):
        raise ValueError("Release output must be outside the source tree")
    if not re.fullmatch(r"v[0-9][a-zA-Z0-9_.-]{0,63}", version):
        raise ValueError("Version must be a Docker-compatible version tag beginning with v and a digit")
    backend = json.loads((root / "backend-dist/build-manifest.json").read_text())
    frontend = json.loads((root / "console-dist/build-manifest.json").read_text())
    verify_sources(root, backend)
    if frontend["upstream_commit"] != UPSTREAM or frontend.get("backend_image_id") != backend["image_id"]:
        raise ValueError("Frontend and backend must be a jointly verified release")
    for name, expected in frontend["files"].items():
        if digest(checked_file(root / "console-dist", name)) != expected:
            raise ValueError(f"Frontend artifact mismatch: {name}")
    archive_sources_ok(root / "console-dist/modelport-source.tar.gz", root)
    output.mkdir(parents=True, exist_ok=False)
    bundle = output / "modelport"
    copy_sources(root, bundle)
    for folder, names in [
        ("console-dist", [*frontend["files"], "build-manifest.json"]),
        ("backend-dist", ["build-manifest.json"]),
    ]:
        for name in names:
            target = bundle / folder / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(checked_file(root / folder, name), target)
    images = {}
    for service, reference in [("new-api", backend["image"]), ("ingress", NGINX)]:
        info = json.loads(docker("image", "inspect", reference))[0]
        if (info["Os"], info["Architecture"]) != ("linux", "amd64"):
            raise ValueError("Only the verified linux/amd64 platform is supported")
        if service == "new-api" and info["Id"] != backend["image_id"]:
            raise ValueError("Running-release image ID does not match the build manifest")
        alias = f"modelport-release-{service}:{version}"
        existing = subprocess.run(["docker", "image", "inspect", alias], capture_output=True, text=True)
        if existing.returncode == 0 and json.loads(existing.stdout)[0]["Id"] != info["Id"]:
            raise ValueError(f"Refusing to replace an existing release image: {alias}")
        docker("image", "tag", reference, alias)
        images[service] = {"tag": alias, "origin": reference, "origin_image_id": info["Id"],
                           "platform": "linux/amd64"}
    docker("image", "save", "--platform", "linux/amd64", "--output",
           str(bundle / "images.tar"), *(image["tag"] for image in images.values()))
    # Docker Engine versions may identify OCI indexes differently. Lock the exported config too.
    with tarfile.open(bundle / "images.tar") as archive:
        records = json.load(archive.extractfile("manifest.json"))
        index = json.load(archive.extractfile("index.json")) if "index.json" in archive.getnames() else None
        for image in images.values():
            record, = [record for record in records if image["tag"] in (record.get("RepoTags") or [])]
            config = archive.extractfile(record["Config"]).read()
            image["config_sha256"] = hashlib.sha256(config).hexdigest()
            image["diff_ids"] = json.loads(config)["rootfs"]["diff_ids"]
            if index:
                descriptor, = [
                    entry for entry in index["manifests"]
                    if entry.get("annotations", {}).get("io.containerd.image.name")
                    == "docker.io/library/" + image["tag"]
                ]
                manifest_bytes = archive.extractfile(
                    "blobs/sha256/" + descriptor["digest"].removeprefix("sha256:")).read()
                exported = json.loads(manifest_bytes)
                if (hashlib.sha256(manifest_bytes).hexdigest() != descriptor["digest"].removeprefix("sha256:")
                        or exported["config"]["digest"] != "sha256:" + image["config_sha256"]):
                    raise ValueError("Exported OCI manifest/config binding is invalid")
                image["export_manifest_id"] = descriptor["digest"]
    manifest = {
        "schema": 1, "version": version, "upstream_commit": UPSTREAM,
        "platform": "linux/amd64", "contains_business_data": False,
        "public_cloud_approved": False, "images": images,
        "files": {p.relative_to(bundle).as_posix(): digest(p)
                  for p in sorted(bundle.rglob("*")) if p.is_file()},
    }
    (bundle / "release-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    verify(bundle)
    source = output / "source"
    copy_sources(root, source)
    shutil.copyfile(bundle / "release-manifest.json", source / "release-lock.json")
    package = output / f"modelport-{version}-linux-amd64.tar.gz"
    with tarfile.open(package, "w:gz", compresslevel=6) as archive:
        for path in sorted(bundle.rglob("*")):
            if path.is_file():
                info = archive.gettarinfo(str(path), "modelport/" + path.relative_to(bundle).as_posix())
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                info.mode = 0o644
                with path.open("rb") as stream:
                    archive.addfile(info, stream)
    shutil.copyfile(bundle / "release-manifest.json", output / "release-manifest.json")
    (output / "SHA256SUMS").write_text(
        "".join(f"{digest(output / name)}  {name}\n" for name in [package.name, "release-manifest.json"]),
        encoding="ascii")
    print(json.dumps({"version": version, "files": len(manifest["files"]),
                      "archive": package.name, "bytes": package.stat().st_size}))


def verify(root):
    manifest = json.loads((root / "release-manifest.json").read_text())
    if manifest["schema"] != 1 or manifest["contains_business_data"] is not False:
        raise ValueError("Unexpected release schema or data policy")
    for name, expected in manifest["files"].items():
        if digest(checked_file(root, name)) != expected:
            raise ValueError(f"Release integrity failure: {name}")
    return manifest


def seal_build(root):
    if (root / "data").exists():
        raise ValueError("Seal only an offline build workspace, never a runtime/data directory")
    backend = json.loads((root / "backend-dist/build-manifest.json").read_text())
    frontend = json.loads((root / "console-dist/build-manifest.json").read_text())
    verify_sources(root, backend)
    if docker("image", "inspect", "--format", "{{.Id}}", backend["image"]) != backend["image_id"]:
        raise ValueError("Built image tag has changed")
    if frontend["upstream_commit"] != UPSTREAM:
        raise ValueError("Unexpected frontend upstream")
    for name, expected in frontend["files"].items():
        if digest(checked_file(root / "console-dist", name)) != expected:
            raise ValueError(f"Unverified frontend change: {name}")
    source = root / "backend-dist/modelport-source.tar.gz"
    archive_sources_ok(source, root)
    checks = [
        ("auth_session_limits.py", []),
        ("account_security_restrictions.py", ["--console-dist", "console-dist"]),
        ("api_sales.py", ["--site-root", ".", "--console-dist", "console-dist",
                         "--extended-scenarios", "--upstream-issues"]),
    ]
    for test, options in checks:
        subprocess.run([sys.executable, str(root / "tests" / test),
                        "--api-image", backend["image_id"], *options], cwd=root, check=True)
    shutil.copyfile(source, root / "console-dist/modelport-source.tar.gz")
    frontend["backend_image_id"] = backend["image_id"]
    frontend["frontend_only"] = False
    frontend["files"]["modelport-source.tar.gz"] = digest(source)
    (root / "console-dist/build-manifest.json").write_text(
        json.dumps(frontend, indent=2) + "\n", encoding="utf-8")
    print("Offline build sealed after isolated API-only, account, limiter, billing and upstream-issue regressions.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    commands = parser.add_subparsers(dest="command", required=True)
    build_parser = commands.add_parser("build")
    build_parser.add_argument("--output", type=Path, required=True)
    build_parser.add_argument("--version", required=True)
    commands.add_parser("verify")
    commands.add_parser("seal-build")
    export = commands.add_parser("export-source")
    export.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "build":
        build(args.root.resolve(), args.output.resolve(), args.version)
    elif args.command == "export-source":
        copy_sources(args.root.resolve(), args.output.resolve())
    elif args.command == "seal-build":
        seal_build(args.root.resolve())
    else:
        manifest = verify(args.root.resolve())
        print(f"Verified {manifest['version']}: {len(manifest['files'])} files")


if __name__ == "__main__":
    main()
