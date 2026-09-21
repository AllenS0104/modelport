#!/usr/bin/env python3
"""Operate an extracted release locally; never enables public access or migrates production."""
import argparse
import json
import os
import re
import secrets
import sqlite3
import subprocess
import time
from pathlib import Path

from release import ROOT, digest, docker, verify


def initialize(root, project, port):
    manifest = verify(root)
    if not re.fullmatch(r"modelport-[a-z0-9][a-z0-9_-]{0,39}", project):
        raise ValueError("Use a distinct Compose project named modelport-<environment>")
    if project == "modelport-local" or not 0 <= port <= 65535:
        raise ValueError("Use a new project and a valid loopback port; 0 chooses an ephemeral port")
    if not hasattr(os, "geteuid") or os.geteuid() not in {0, 1000}:
        raise PermissionError("Initialize on Linux as UID 1000 or root; the container runs as UID 1000")
    for name in ["data", ".runtime.env", "compose.runtime.json"]:
        if (root / name).exists():
            raise FileExistsError(f"Initialization never overwrites existing runtime state: {name}")
    config = json.loads(docker("compose", "-f", str(root / "compose.yaml"), "config", "--format", "json"))
    config["name"] = project
    for network in config["networks"].values():
        network.pop("name", None)
    for service, image in manifest["images"].items():
        config["services"][service]["image"] = image["tag"]
        config["services"][service]["pull_policy"] = "never"
        config["services"][service]["restart"] = "unless-stopped"
    api = config["services"]["new-api"]
    api["environment"].update({
        "SESSION_SECRET": "${SESSION_SECRET:?Missing protected session secret}",
        "CRYPTO_SECRET": "${CRYPTO_SECRET:?Missing protected encryption secret}",
        "NODE_NAME": project,
    })
    config["services"]["ingress"]["ports"] = [{
        "host_ip": "127.0.0.1", "target": 8080, "published": str(port), "protocol": "tcp",
    }]
    data = root / "data"
    data.mkdir(mode=0o700)
    if os.geteuid() == 0:
        os.chown(data, 1000, 1000)
    descriptor = os.open(root / ".runtime.env", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(f"SESSION_SECRET={secrets.token_hex(32)}\nCRYPTO_SECRET={secrets.token_hex(32)}\n")
    with (root / "compose.runtime.json").open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(config, indent=2) + "\n")
    print(f"Initialized {project}; secrets saved privately, not displayed. No services started.")


def allowed_image_ids(image):
    values = {image["origin_image_id"], "sha256:" + image["config_sha256"]}
    if image.get("export_manifest_id"):
        values.add(image["export_manifest_id"])
    return values


def check_images(root, load=False):
    manifest = verify(root)
    if load:
        # Refuse local tag replacement, even though no production tag is used.
        for image in manifest["images"].values():
            existing = subprocess.run(["docker", "image", "inspect", image["tag"]],
                                      capture_output=True, text=True)
            if existing.returncode == 0:
                info = json.loads(existing.stdout)[0]
                if info["Id"] not in allowed_image_ids(image):
                    raise ValueError(f"Release tag already exists with another image: {image['tag']}")
        subprocess.run(["docker", "image", "load", "--input", str(root / "images.tar")], check=True)
    for image in manifest["images"].values():
        info = json.loads(docker("image", "inspect", image["tag"]))[0]
        if (info["Os"], info["Architecture"], info["RootFS"]["Layers"]) != (
                "linux", "amd64", image["diff_ids"]):
            raise ValueError(f"Loaded image content/platform differs: {image['tag']}")
        if info["Id"] not in allowed_image_ids(image):
            raise ValueError(f"Loaded image configuration differs: {image['tag']}")
    print("Both release images verified; no services started.")


def backup(database, destination):
    database, destination = database.resolve(), destination.absolute()
    if database == destination or not database.is_file():
        raise ValueError("Source must be an existing database and destination must be different")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt" and destination.parent.stat().st_mode & 0o077:
        raise PermissionError("Backup destination directory must be private (chmod 700)")
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    try:
        started = time.monotonic()

        def progress(status, remaining, total):
            if time.monotonic() - started > 120:
                raise TimeoutError("Online backup exceeded 120 seconds; retry during a quieter period")

        source = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
        target = sqlite3.connect(destination)
        try:
            source.execute("PRAGMA query_only=ON")
            source.backup(target, pages=256, progress=progress)
            if target.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ValueError("Backup integrity check failed")
        finally:
            target.close()
            source.close()
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    print(json.dumps({"integrity": "ok", "sha256": digest(destination),
                      "contains_sensitive_data": True, "upload_to_github": False}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--project", default="modelport-staging")
    init.add_argument("--port", type=int, default=13000)
    commands.add_parser("load-images")
    commands.add_parser("check-images")
    copy = commands.add_parser("backup")
    copy.add_argument("--database", type=Path, required=True)
    copy.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "init":
        initialize(args.root.resolve(), args.project, args.port)
    elif args.command in {"load-images", "check-images"}:
        check_images(args.root.resolve(), args.command == "load-images")
    else:
        backup(args.database, args.output)


if __name__ == "__main__":
    main()
