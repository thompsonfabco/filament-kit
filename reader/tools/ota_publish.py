"""Build, sign and publish a reader firmware image for OTA.

    py tools/ota_publish.py --init-key                      # once: make the signing key, print the public key
    py tools/ota_publish.py --dry-run                       # build + sign only (writes .pio/.../manifest.json)
    py tools/ota_publish.py --host my-server                # build + sign + upload + check it is live

Run from anywhere; paths are relative to the reader/ folder. Then hold the reader's
knob for 4 s: it fetches <READER_BASE>/fw/manifest.json over HTTPS and, if the build
is newer, downloads, verifies (size, SHA-256, ECDSA signature) and installs it.

The signing key (ECDSA P-256) lives on the PC that builds (default
~/.filament-kit/reader-ota-key.pem) and never leaves it; the reader has the matching
public key compiled in (OTA_PUBKEY in src/secrets.h). The upload goes over ssh/scp to
--host, into --remote-dir, which the filament-kit server serves as <READER_BASE>/fw/
behind the reader token (the image embeds the Wi-Fi password and the token, so it is
installed mode 0640, not world-readable).

The live check reads READER_BASE and READER_TOKEN from src/secrets.h (or --base-url and
the READER_TOKEN environment variable). The token is sent as a header, never printed.
"""
import argparse
import base64
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

READER = Path(__file__).resolve().parent.parent
DEFAULT_ENV = "esp32-c3-supermini"
DEFAULT_KEY = Path.home() / ".filament-kit" / "reader-ota-key.pem"
DEFAULT_REMOTE_DIR = "/var/lib/filament-kit/reader-fw"


def run(cmd, **kw):
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True, **kw)


def secrets_value(name, path=None):
    """A string constant from src/secrets.h (static const char* NAME = "..."), or None."""
    p = Path(path) if path else READER / "src" / "secrets.h"
    if not p.exists():
        return None
    m = re.search(r'\b' + re.escape(name) + r'\s*=\s*"([^"]*)"', p.read_text(encoding="utf-8"))
    return m.group(1) if m else None


def manifest_url(base):
    return base.rstrip("/") + "/fw/manifest.json"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects: following one would send the reader token to wherever it points."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # the 3xx then surfaces as an HTTPError


def fetch_manifest(base, token, timeout=15):
    """GET <base>/fw/manifest.json with the token, never following a redirect."""
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(manifest_url(base), headers={"X-Auth-Token": token})
    with opener.open(req, timeout=timeout) as r:
        return json.load(r)


def load_or_create_key(path, create):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    path = Path(path)
    if path.exists():
        return serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not create:
        sys.exit(f"no signing key at {path}; run with --init-key first")
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption())
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(pem)
    print(f"created signing key {path} (keep it on this PC; back it up privately)")
    return key


def public_pem(key):
    from cryptography.hazmat.primitives import serialization

    return key.public_key().public_bytes(serialization.Encoding.PEM,
                                         serialization.PublicFormat.SubjectPublicKeyInfo).decode()


def sign_image(image, key, build):
    """Manifest for `image`: build, size, sha256 hex, base64 DER ECDSA signature over the SHA-256."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, utils

    digest = hashlib.sha256(image).digest()
    sig = key.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
    key.public_key().verify(sig, digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
    return {"build": build, "size": len(image), "sha256": digest.hex(),
            "sig": base64.b64encode(sig).decode()}


def make_stage(host):
    """A fresh private (mode 0700) staging folder on the host: the image carries the Wi-Fi
    password and the token, so it must not sit in a predictable, world-readable /tmp path."""
    print("+ ssh", host, "mktemp -d")
    out = subprocess.run(["ssh", host, "mktemp -d"], check=True, capture_output=True, text=True).stdout
    stage = out.strip()
    if not stage.startswith("/") or "\n" in stage:
        sys.exit(f"ssh mktemp -d on {host} printed no usable folder: {out!r}")
    return stage


def remote_install_cmd(stage, remote_dir, owner, group, sudo=True):
    """Shell command run on the host: image first, manifest last, so a reader never sees
    a manifest for a missing image."""
    pre = "sudo " if sudo else ""
    q = shlex.quote
    parts = [f"{pre}install -d -m 0750 -o {q(owner)} -g {q(group)} {q(remote_dir)}"]
    for name in ("firmware.bin", "manifest.json"):
        parts.append(f"{pre}install -o {q(owner)} -g {q(group)} -m 0640 "
                     f"{q(stage + '/' + name)} {q(remote_dir + '/' + name)}")
    parts.append(f"rm -rf {q(stage)}")
    return " && ".join(parts)


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--host", help="ssh host of the filament-kit server (required unless --dry-run)")
    ap.add_argument("--base-url", help="READER_BASE for the live check (default: from src/secrets.h)")
    ap.add_argument("--remote-dir", default=DEFAULT_REMOTE_DIR,
                    help=f"directory served as <READER_BASE>/fw/ (default {DEFAULT_REMOTE_DIR})")
    ap.add_argument("--remote-owner", default="root")
    ap.add_argument("--remote-group", default="filament-kit",
                    help="group of the web process that serves /fw/ (default filament-kit)")
    ap.add_argument("--no-sudo", action="store_true", help="install without sudo on the host")
    ap.add_argument("--key", default=str(DEFAULT_KEY), help=f"signing key (default {DEFAULT_KEY})")
    ap.add_argument("--env", default=DEFAULT_ENV, help="PlatformIO environment")
    ap.add_argument("--init-key", action="store_true",
                    help="create the signing key if missing and print the public key for secrets.h")
    ap.add_argument("--dry-run", action="store_true", help="build + sign only, upload nothing")
    ap.add_argument("--no-verify", action="store_true", help="skip the live manifest check")
    args = ap.parse_args(argv)
    if not args.init_key and not args.dry_run and not args.host:
        ap.error("--host is required unless --dry-run or --init-key")
    return args


def main(argv=None):
    args = parse_args(argv)
    if args.init_key:
        key = load_or_create_key(args.key, create=True)
        print("Paste this into src/secrets.h as OTA_PUBKEY:\n")
        print(public_pem(key))
        return

    key = load_or_create_key(args.key, create=False)
    build_dir = READER / ".pio" / "build" / args.env
    build = int(time.time())
    run([sys.executable, "-m", "platformio", "run", "-e", args.env], cwd=READER,
        env={**os.environ, "FW_BUILD": str(build)})
    stamped = int((build_dir / "fw_build.txt").read_text())
    if stamped != build:
        sys.exit(f"build stamp mismatch: {stamped} != {build}")

    image = (build_dir / "firmware.bin").read_bytes()
    manifest = sign_image(image, key, build)
    (build_dir / "manifest.json").write_text(json.dumps(manifest))
    print(f"build {build}: {len(image)} bytes, sha256 {manifest['sha256'][:16]}..., signed")
    if args.dry_run:
        return

    stage = make_stage(args.host)
    run(["scp", "-q", str(build_dir / "firmware.bin"), str(build_dir / "manifest.json"),
         f"{args.host}:{stage}/"])
    run(["ssh", args.host, remote_install_cmd(stage, args.remote_dir, args.remote_owner,
                                              args.remote_group, sudo=not args.no_sudo)])
    if args.no_verify:
        print(f"published build {build}. Hold the reader's knob for 4 s to install it.")
        return

    base = args.base_url or secrets_value("READER_BASE")
    token = os.environ.get("READER_TOKEN") or secrets_value("READER_TOKEN")
    if not base or not token:
        sys.exit("uploaded, but cannot check it: no READER_BASE/READER_TOKEN (use --base-url and "
                 "the READER_TOKEN environment variable, or --no-verify)")
    live = fetch_manifest(base, token)
    if live.get("build") != build:
        sys.exit(f"published, but the server still reports build {live.get('build')}")
    print(f"published build {build}. Hold the reader's knob for 4 s to install it.")


if __name__ == "__main__":
    main()
