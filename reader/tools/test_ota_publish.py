"""Tests for ota_publish.py's pure parts (no build, no network, no ssh).

    py -m pytest -q reader/tools
"""
import base64
import hashlib
import shlex
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ota_publish as op  # noqa: E402


def test_sign_image_manifest_verifies_with_public_key(tmp_path):
    key = op.load_or_create_key(tmp_path / "k.pem", create=True)
    image = b"\xe9" + bytes(range(256)) * 40
    m = op.sign_image(image, key, 1793600000)
    assert m["build"] == 1793600000
    assert m["size"] == len(image)
    assert m["sha256"] == hashlib.sha256(image).hexdigest()
    pub = serialization.load_pem_public_key(op.public_pem(key).encode())
    # what the reader does: verify the DER signature over the raw SHA-256
    pub.verify(base64.b64decode(m["sig"]), hashlib.sha256(image).digest(),
               ec.ECDSA(utils.Prehashed(hashes.SHA256())))


def test_key_file_is_created_once_and_reused(tmp_path):
    p = tmp_path / "sub" / "k.pem"
    k1 = op.load_or_create_key(p, create=True)
    k2 = op.load_or_create_key(p, create=True)
    assert op.public_pem(k1) == op.public_pem(k2)
    if sys.platform != "win32":
        assert (p.stat().st_mode & 0o777) == 0o600


def test_missing_key_without_init_exits(tmp_path):
    with pytest.raises(SystemExit):
        op.load_or_create_key(tmp_path / "none.pem", create=False)


def test_public_pem_fits_secrets_h(tmp_path):
    pem = op.public_pem(op.load_or_create_key(tmp_path / "k.pem", create=True))
    assert pem.startswith("-----BEGIN PUBLIC KEY-----")
    assert pem.rstrip().endswith("-----END PUBLIC KEY-----")


def test_secrets_value(tmp_path):
    s = tmp_path / "secrets.h"
    s.write_text('static const char* READER_BASE = "https://h.example/filament/reader";\n'
                 'static const char* READER_TOKEN = "abc";\n', encoding="utf-8")
    assert op.secrets_value("READER_BASE", s) == "https://h.example/filament/reader"
    assert op.secrets_value("READER_TOKEN", s) == "abc"
    assert op.secrets_value("WIFI_PASS", s) is None
    assert op.secrets_value("READER_BASE", tmp_path / "missing.h") is None


def test_manifest_url():
    assert op.manifest_url("https://h/filament/reader/") == "https://h/filament/reader/fw/manifest.json"
    assert op.manifest_url("https://h/filament/reader") == "https://h/filament/reader/fw/manifest.json"


def test_remote_install_cmd_quotes_and_orders():
    cmd = op.remote_install_cmd("/tmp/reader-fw-1", "/srv/my fw", "root", "filament-kit")
    parts = cmd.split(" && ")
    assert parts[0].startswith("sudo install -d")
    assert "firmware.bin" in parts[1] and "manifest.json" in parts[2]  # image before manifest
    assert shlex.quote("/srv/my fw/firmware.bin") in parts[1]
    assert "-m 0640" in parts[1] and "-m 0640" in parts[2]
    assert parts[-1] == "rm -rf /tmp/reader-fw-1"
    assert "sudo" not in op.remote_install_cmd("/tmp/x", "/d", "u", "g", sudo=False)


def test_args_need_host_unless_dry_run_or_init():
    with pytest.raises(SystemExit):
        op.parse_args([])
    assert op.parse_args(["--dry-run"]).dry_run
    assert op.parse_args(["--init-key"]).init_key
    a = op.parse_args(["--host", "srv"])
    assert a.host == "srv" and a.remote_dir == op.DEFAULT_REMOTE_DIR


def test_no_owner_specific_defaults():
    src = (Path(__file__).resolve().parent / "ota_publish.py").read_text(encoding="utf-8")
    for owner_bit in ("thompsonfabco", "spoolman-vm", "h2d-fw", ".h2d-ota"):
        assert owner_bit not in src
