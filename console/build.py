#!/usr/bin/env python3
"""Build the branded frontend from a pinned clean upstream without editing it."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = '385d2dfd10d821b25c8a6766bd16eea248cb1652'


def run(*args, cwd=None):
    subprocess.run(args, cwd=cwd or ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    source = ROOT / 'upstream'
    work = ROOT / '.console-build/web'
    assert subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip() == UPSTREAM
    assert not subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'], text=True).strip()
    # Reuse only the dedicated build directory; never clean the upstream or user data.
    if not work.exists():
        work.parent.mkdir(exist_ok=True)
        archive = work.parent / 'web-source.tar'
        run('git', '-C', str(source), 'archive', '--output', str(archive), 'HEAD', 'web', 'pkg')
        with tarfile.open(archive) as bundle:
            bundle.extractall(work.parent, filter='data')
        archive.unlink()
    overlays = ROOT / 'console/overrides'
    for path in overlays.rglob('*'):
        if path.is_file():
            destination = work / path.relative_to(overlays)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
    if args.prepare_only:
        return
    run('npm', 'exec', '--yes', '--package=bun@1.4.2', '--', 'bun', 'run', 'build:check', cwd=work)
    dist = work / 'dist'
    # Serve only actual frontend route families. All API/relay prefixes keep the existing proxy.
    routes = (work / 'src/routeTree.gen.ts').read_text()
    match = re.search(r'export interface FileRoutesByFullPath \{(.*?)\n\}', routes, re.S)
    if not match:
        raise RuntimeError('Generated route map missing; inspect upstream before deploying')
    paths = re.findall(r"^\s+'(/[^']*)':", match[1], re.M)
    legacy = (work / 'src/lib/legacy-route.ts').read_text()
    legacy_paths = re.findall(r"'(/[a-z][a-z0-9/-]*)'", legacy)
    families = sorted({path.split('/')[1] for path in paths + legacy_paths if path != '/'})
    assert families and all(re.fullmatch(r'[a-zA-Z0-9_-]+', name) for name in families)
    assert not set(families) & {'api', 'v1', 'v1beta', 'pg', 'mj', 'suno', 'h5', 'preview'}
    route_config = (
        '# Generated from the pinned native frontend route tree.\n'
        'location ~ ^/(' + '|'.join(families) + ')(/|$) {\n'
        '    root /srv/modelport-console;\n'
        '    try_files /index.html =404;\n'
        '    limit_except GET HEAD { deny all; }\n'
        '    add_header Cache-Control "no-store" always;\n'
        '    add_header X-Content-Type-Options nosniff always;\n'
        '    add_header Referrer-Policy no-referrer always;\n'
        '    add_header X-Frame-Options DENY always;\n'
        '}\n'
    )
    (dist / 'routes.conf').write_text(route_config)
    archive = work / 'upstream-source.tar'
    run('git', '-C', str(source), 'archive', '--prefix=upstream/', '--output', str(archive), 'HEAD')
    with tarfile.open(dist / 'modelport-source.tar.gz', 'w:gz') as bundle:
        with tarfile.open(archive) as original:
            for member in original:
                bundle.addfile(member, original.extractfile(member) if member.isfile() else None)
        for name in ['console', 'backend']:
            bundle.add(ROOT / name, arcname=name)
    archive.unlink()
    manifest = {
        'upstream_commit': UPSTREAM,
        'frontend_only': True,
        'routes': families,
        'files': {str(p.relative_to(dist)): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in dist.rglob('*') if p.is_file() and p.name != 'build-manifest.json'},
    }
    (dist / 'build-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'dist': str(dist), 'routes': families, 'files': len(manifest['files'])}))


if __name__ == '__main__':
    main()
