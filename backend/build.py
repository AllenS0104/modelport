#!/usr/bin/env python3
"""Build a pinned, minimally patched New API image without editing upstream or deploying."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = '385d2dfd10d821b25c8a6766bd16eea248cb1652'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', default='modelport-new-api:upstream-bugfixes-v1')
    parser.add_argument('--console-dist', default='.console-build/web/dist')
    parser.add_argument('--output', default='backend-dist/upstream-bugfixes-v1')
    parser.add_argument('--work-dir', default='.backend-build')
    args = parser.parse_args()
    console_dist = (ROOT / args.console_dist).resolve()
    output = (ROOT / args.output).resolve()
    assert console_dist.is_relative_to(ROOT) and output.is_relative_to(ROOT)
    source = ROOT / 'upstream'
    assert subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip() == UPSTREAM
    assert not subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'], text=True).strip()
    work = (ROOT / args.work_dir).resolve()
    assert work.is_relative_to(ROOT) and work.name.startswith('.backend-')
    if work.exists():
        raise FileExistsError('Use a fresh .backend-build directory; inspect and remove only a previous owned build first')
    work.mkdir()
    archive = work / 'upstream.tar'
    subprocess.run(['git', '-C', str(source), 'archive', '--output', str(archive), 'HEAD'], check=True)
    tree = work / 'src'
    tree.mkdir()
    with tarfile.open(archive) as bundle:
        bundle.extractall(tree, filter='data')
    archive.unlink()
    # A parent workspace repository can otherwise cause git apply to skip this nested tree.
    subprocess.run(['git', 'init', '--quiet'], cwd=tree, check=True)
    for name in ['auth-session-limits.patch', 'account-security.patch', 'api-sales.patch', 'upstream-bugfixes.patch']:
        patch = (ROOT / 'backend' / name).read_text()
        subprocess.run(['git', 'apply', '--check', '-'], input=patch, text=True, cwd=tree, check=True)
        subprocess.run(['git', 'apply', '-'], input=patch, text=True, cwd=tree, check=True)
    route_source = (tree / 'router/api-router.go').read_text()
    assert route_source.count('middleware.SessionLifecycleRateLimit("refresh")') == 1
    assert route_source.count('middleware.SessionLifecycleRateLimit("logout")') == 1
    for path in (ROOT / 'backend/overrides').rglob('*'):
        if path.is_file():
            target = tree / path.relative_to(ROOT / 'backend/overrides')
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    # Reuse the already verified frontend, with its own maintained source overlays.
    shutil.copytree(console_dist, tree / 'web/dist')
    shutil.copytree(ROOT / 'backend', tree / 'modelport-backend', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copy2(ROOT / 'backend/Dockerfile', tree / 'Dockerfile.modelport')
    shutil.copy2(ROOT / 'backend/Dockerfile.dockerignore', tree / 'Dockerfile.modelport.dockerignore')
    subprocess.run(['docker', 'build', '--platform', 'linux/amd64', '-f', 'Dockerfile.modelport',
                    '-t', args.image, '.'], cwd=tree, check=True)
    image_id = subprocess.check_output(['docker', 'image', 'inspect', '--format', '{{.Id}}', args.image], text=True).strip()
    output.mkdir(parents=True, exist_ok=True)
    manifest = {
        'upstream_commit': UPSTREAM, 'image': args.image, 'image_id': image_id,
        'console_dist': str(console_dist.relative_to(ROOT)),
        'account_security_policy': 'admin-managed settings; password and authentication unchanged',
        'source_sha256': {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in (ROOT / 'backend').rglob('*') if p.is_file() and '__pycache__' not in p.parts},
        'console_manifest_sha256': hashlib.sha256((console_dist / 'build-manifest.json').read_bytes()).hexdigest(),
        'session_requests_per_minute': 120, 'critical_limit_unchanged': True,
    }
    (output / 'build-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    archive = work / 'source.tar'
    subprocess.run(['git', '-C', str(source), 'archive', '--prefix=upstream/',
                    '--output', str(archive), 'HEAD'], check=True)
    with tarfile.open(output / 'modelport-source.tar.gz', 'w:gz') as bundle:
        with tarfile.open(archive) as original:
            for member in original:
                bundle.addfile(member, original.extractfile(member) if member.isfile() else None)
        for name in ['console', 'backend']:
            bundle.add(ROOT / name, arcname=name,
                       filter=lambda info: None if '__pycache__' in Path(info.name).parts else info)
        for name in ['tests/account_security_restrictions.py', 'tests/auth_session_limits.py',
                     'tests/api_sales.py', 'tests/sales_scenarios.py', 'tests/upstream_issue_scenarios.py',
                     'tests/fixtures/issue_7498_test.go',
                     'tests/chat_integration.py', 'tests/console_interface.py', 'tests/public_site.py',
                     'ACCOUNT-SECURITY-RESTRICTIONS.zh-CN.md']:
            if (ROOT / name).is_file():
                bundle.add(ROOT / name, arcname=name)
    archive.unlink()
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
