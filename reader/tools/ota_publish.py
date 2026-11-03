"""Build, sign and publish a reader firmware image for OTA.

    py ota_publish.py            # build + sign + upload to the VM
    py ota_publish.py --dry-run  # build + sign only (writes .pio/.../manifest.json)

Then hold the reader's knob for 2 s: it fetches the manifest over HTTPS, and if the
build is newer, downloads, verifies (size, SHA-256, ECDSA signature) and installs it.

The signing key lives in ~/.h2d-ota/ota_signing_key.pem (ECDSA P-256) and never
leaves this PC; the reader has the matching public key compiled in. Images go to
/srv/h2d-fw/ on the VM, served at https://mcp.example.com/h2d/fw/ behind
the same X-Auth-Token as /set-slot (the image embeds Wi-Fi creds and the token).
"""
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils

ENV = "esp32-c3-supermini"
HERE = Path(__file__).resolve().parent
BUILD_DIR = HERE / ".pio" / "build" / ENV
KEY = Path.home() / ".h2d-ota" / "ota_signing_key.pem"
VM = "spoolman-vm"
REMOTE_DIR = "/srv/h2d-fw"
MANIFEST_URL = "https://mcp.example.com/h2d/fw/manifest.json"


def run(cmd, **kw):
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True, **kw)


def main():
    dry = "--dry-run" in sys.argv
    build = int(time.time())
    run([sys.executable, "-m", "platformio", "run", "-e", ENV], cwd=HERE,
        env={**os.environ, "FW_BUILD": str(build)})
    stamped = int((BUILD_DIR / "fw_build.txt").read_text())
    if stamped != build:
        sys.exit(f"build stamp mismatch: {stamped} != {build}")

    image = (BUILD_DIR / "firmware.bin").read_bytes()
    digest = hashlib.sha256(image).digest()
    key = serialization.load_pem_private_key(KEY.read_bytes(), password=None)
    sig = key.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
    key.public_key().verify(sig, digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
    manifest = {"build": build, "size": len(image), "sha256": digest.hex(),
                "sig": base64.b64encode(sig).decode()}
    (BUILD_DIR / "manifest.json").write_text(json.dumps(manifest))
    print(f"build {build}: {len(image)} bytes, sha256 {digest.hex()[:16]}..., signed")
    if dry:
        return

    stage = f"/tmp/h2d-fw-{build}"
    run(["ssh", VM, f"mkdir -p {stage}"])
    run(["scp", "-q", str(BUILD_DIR / "firmware.bin"), str(BUILD_DIR / "manifest.json"), f"{VM}:{stage}/"])
    # image first, manifest last, so a reader never sees a manifest for a missing image
    run(["ssh", VM,
         f"sudo install -o root -g www-data -m 0640 {stage}/firmware.bin {REMOTE_DIR}/firmware.bin && "
         f"sudo install -o root -g www-data -m 0640 {stage}/manifest.json {REMOTE_DIR}/manifest.json && "
         f"rm -rf {stage}"])

    # confirm it's live over HTTPS (token read from the firmware source, never printed)
    token = re.search(r'AUTH_TOKEN\s*=\s*"([^"]+)"', (HERE / "src" / "secrets.h").read_text()).group(1)
    req = urllib.request.Request(MANIFEST_URL, headers={"X-Auth-Token": token})
    live = json.load(urllib.request.urlopen(req, timeout=15))
    if live.get("build") != build:
        sys.exit(f"published, but the server still reports build {live.get('build')}")
    print(f"published build {build}. Hold the reader's knob for 2 s to install it.")


if __name__ == "__main__":
    main()
