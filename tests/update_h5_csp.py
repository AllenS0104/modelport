#!/usr/bin/env python3
"""Update only /h5/ CSP hashes and script integrity after inspecting current config; does not reload."""
import argparse
import base64
import hashlib
import re
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    path = ROOT / 'nginx.conf'
    original = path.read_text(encoding='utf-8')
    html_path = ROOT / 'h5/index.html'
    html_original = html_path.read_text(encoding='utf-8')
    digest = lambda data: 'sha256-' + base64.b64encode(hashlib.sha256(data).digest()).decode()
    script_hash = digest((ROOT / 'h5/features.js').read_bytes())
    style_hash = digest(re.search(r'<style>(.*?)</style>', html_original, re.S)[1].encode())
    html = re.sub(r'<script src="features.js"[^>]*></script>', f'<script src="features.js" integrity="{script_hash}" defer></script>', html_original)
    start = original.index('        location /h5/ {')
    end = original.index('        # Isolated read-only preview', start)
    block = original[start:end]
    # Preserve every other directive, including operator-added security restrictions.
    for directive, value in [('script-src', script_hash), ('style-src', style_hash)]:
        pattern = rf"({directive} )'sha256-[A-Za-z0-9+/=]+'"
        block, count = re.subn(pattern, lambda m: m[1] + "'" + value + "'", block)
        assert count == 1, f'{directive}: expected one existing hash; inspect config manually, do not replace policy'
    updated = original[:start] + block + original[end:]
    assert path.read_text(encoding='utf-8') == original and html_path.read_text(encoding='utf-8') == html_original, 'concurrent modification; stop'
    # Hashes must describe the emitted UTF-8 bytes on Windows as well as Linux.
    html_path.write_bytes(html.encode('utf-8'))
    path.write_bytes(updated.encode('utf-8'))
    print('Updated /h5/ exact script/style hashes only. Run nginx -t before reload.')

if __name__ == '__main__':
    main()
