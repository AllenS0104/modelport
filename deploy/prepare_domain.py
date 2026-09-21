#!/usr/bin/env python3
"""Render INACTIVE single-host domain drafts. Never deploys or changes active configuration."""
import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


def normalize_origin(raw):
    if not raw.startswith("https://") or any(char.isspace() for char in raw):
        raise ValueError("Supply an exact HTTPS origin without whitespace.")
    url = urlsplit(raw)
    if (not url.hostname or url.username is not None or url.password is not None or
            url.query or url.fragment or url.path not in ("", "/")):
        raise ValueError("Origin must contain only https://hostname and an optional port.")
    host = url.hostname.lower()
    label = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    if len(host) > 253 or not re.fullmatch(rf"(?:{label}\.)+[a-z](?:[a-z0-9-]{{0,61}}[a-z0-9])?", host):
        raise ValueError("Use a DNS hostname in ASCII/punycode; IPs and wildcards are not accepted.")
    port = url.port
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("Invalid HTTPS port.")
    if url.netloc.endswith(":"):
        raise ValueError("An explicit port cannot be empty.")
    origin = "https://" + host + (f":{port}" if port and port != 443 else "")
    return origin, host, port or 443


def render_draft(raw_origin, destination, root=ROOT):
    origin, host, port = normalize_origin(raw_origin)
    root = root.resolve()
    destination = Path(destination).resolve()
    if not destination.is_relative_to(root / "deploy") or destination == root / "deploy":
        raise ValueError("Draft output must be a new subdirectory under this project's deploy directory.")
    backend = (root / "nginx.conf").read_text(encoding="utf-8")
    host_line = "server_name localhost 127.0.0.1;"
    if backend.count(host_line) != 1:
        raise ValueError("Expected one unchanged local Host allowlist; review the current ingress first.")
    backend = backend.replace(host_line, f"server_name localhost 127.0.0.1 {host};")
    tls = (root / "deploy/domain-nginx.conf.example").read_text(encoding="utf-8")
    if "sales.example.invalid" not in tls or tls.count("listen 443 ssl;") != 1:
        raise ValueError("TLS template contract changed; review before rendering.")
    tls = tls.replace("sales.example.invalid", host).replace("listen 443 ssl;", f"listen {port} ssl;")
    overlay = {
        "services": {
            "new-api": {
                "environment": {
                    "SESSION_COOKIE_SECURE": "true",
                    "SESSION_COOKIE_TRUSTED_URL": origin,
                    "SESSION_SECRET": "${SESSION_SECRET:?Inject a protected stable session secret before activation}",
                },
            },
            "ingress": {
                "volumes": [{
                    "type": "bind",
                    "source": str(destination / "backend-nginx.conf"),
                    "target": "/etc/nginx/nginx.conf",
                    "read_only": True,
                }],
            },
        },
    }
    sources = ["nginx.conf", "compose.yaml", "h5/index.html", "h5/features.js",
               "console-dist/build-manifest.json", "console-dist/routes.conf",
               "backend-dist/build-manifest.json",
               "deploy/domain-nginx.conf.example"]
    manifest = {
        "origin": origin,
        "approved_for_production": False,
        "scope": "single Linux host; reviewed TLS reverse proxy on the same host",
        "source_sha256": {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in sources},
        "remaining": [
            "Approve cloud provider/account/region/budget and actual DNS/certificate ownership.",
            "Replace certificate paths; do not enable this draft before authentication and billing acceptance.",
            "Inject stable secrets; initialize administrators privately; validate trusted proxy and client-IP handling.",
            "Use persistent storage and rehearse SQLite backup/restore; no multi-replica SQLite deployment.",
            "Approve restricted supplier egress, limits, logging retention, alerts and applicable filings.",
            "Verify actual HTTPS, Secure cookies, Origin rejection, SSE, timeouts and rollback.",
        ],
    }
    # New directory only: never overwrite an operator's active config or previous draft.
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    for name, text in {
        "backend-nginx.conf": backend,
        "tls-nginx.conf.example": tls,
        "compose.domain-draft.json": json.dumps(overlay, indent=2) + "\n",
        "readiness.json": json.dumps(manifest, indent=2) + "\n",
    }.items():
        (destination / name).write_bytes(text.encode("utf-8"))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", required=True, help="Exact HTTPS origin; no path, query, credentials or wildcard.")
    parser.add_argument("--output", required=True, type=Path, help="New directory under deploy/; no files are activated.")
    args = parser.parse_args()
    try:
        manifest = render_draft(args.origin, args.output)
    except (ValueError, OSError) as error:
        parser.exit(2, f"Draft not generated: {error}\n")
    print(f"INACTIVE draft for {manifest['origin']}; production approval, certificates and validation are still required.")


if __name__ == "__main__":
    main()
