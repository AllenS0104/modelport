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
IMAGE = 'modelport-new-api:auth-session-limits-v1'


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    source = ROOT / 'upstream'
    assert subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip() == UPSTREAM
    assert not subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'], text=True).strip()
    work = ROOT / '.backend-build'
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
    patch = (ROOT / 'backend/auth-session-limits.patch').read_text()
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
    shutil.copytree(ROOT / 'console-dist', tree / 'web/dist')
    shutil.copytree(ROOT / 'backend', tree / 'modelport-backend')
    shutil.copy2(ROOT / 'backend/Dockerfile', tree / 'Dockerfile.modelport')
    shutil.copy2(ROOT / 'backend/Dockerfile.dockerignore', tree / 'Dockerfile.modelport.dockerignore')
    subprocess.run(['docker', 'build', '--platform', 'linux/amd64', '-f', 'Dockerfile.modelport',
                    '-t', IMAGE, '.'], cwd=tree, check=True)
    image_id = subprocess.check_output(['docker', 'image', 'inspect', '--format', '{{.Id}}', IMAGE], text=True).strip()
    output = ROOT / 'backend-dist'
    output.mkdir(exist_ok=True)
    manifest = {
        'upstream_commit': UPSTREAM, 'image': IMAGE, 'image_id': image_id,
        'source_sha256': {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in (ROOT / 'backend').rglob('*') if p.is_file()},
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
            bundle.add(ROOT / name, arcname=name)
    archive.unlink()
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
