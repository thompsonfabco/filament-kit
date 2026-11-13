"""Tests for ota_publish.py's pure parts (no build, no network, no ssh).

    py -m pytest -q reader/tools
"""
import base64
import hashlib
import json
import shlex
import subprocess
import sys
import types
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


def test_sig2_signs_the_build_number_with_the_hash(tmp_path):
    key = op.load_or_create_key(tmp_path / "k.pem", create=True)
    image = b"\xe9" + bytes(range(256)) * 40
    m = op.sign_image(image, key, 1793600000)
    pub = serialization.load_pem_public_key(op.public_pem(key).encode())
    sha = hashlib.sha256(image).digest()
    pre = ec.ECDSA(utils.Prehashed(hashes.SHA256()))
    # what a reader from FA-027 on checks: prefix || sha256 || build (8 bytes big-endian)
    want = hashlib.sha256(b"fk-reader-ota\x01" + sha + (1793600000).to_bytes(8, "big")).digest()
    pub.verify(base64.b64decode(m["sig2"]), want, pre)
    # the same image under a higher build number (a downgrade replay) does not verify
    from cryptography.exceptions import InvalidSignature
    with pytest.raises(InvalidSignature):
        pub.verify(base64.b64decode(m["sig2"]), op.build_digest(sha, 1793600001), pre)
    # the old signature (hash only) is kept so readers flashed earlier still install it
    pub.verify(base64.b64decode(m["sig"]), sha, pre)


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


# Owner-specific values are not in the repository: they live in the local, untracked ban file (the path in
# $FK_OWNER_BANS, else <repo root>/.owner-bans.local; the "ota_plain" list). Without it this test skips, and with
# FK_REQUIRE_OWNER_BANS=1 a missing file fails (the premerge check). The same loader is in server/tests/test_readme.py.
def _ota_bans():
    import json
    import os
    path = Path(os.environ.get("FK_OWNER_BANS") or Path(__file__).resolve().parents[2] / ".owner-bans.local")
    if not path.is_file():
        msg = "no local owner-ban file ($FK_OWNER_BANS or <repo root>/.owner-bans.local); the owner-specific check is not run"
        if os.environ.get("FK_REQUIRE_OWNER_BANS") == "1":
            pytest.fail(msg + " and FK_REQUIRE_OWNER_BANS=1 requires it")
        pytest.skip(msg)
    return json.loads(path.read_text(encoding="utf-8"))["ota_plain"]


def test_no_owner_specific_defaults():
    bans = _ota_bans()
    assert bans, "the ban file lists no ota_plain entries"
    src = (Path(__file__).resolve().parent / "ota_publish.py").read_text(encoding="utf-8")
    for i, owner_bit in enumerate(bans):
        assert owner_bit not in src, f"ota_publish.py holds ota_plain ban {i}"


def test_live_check_does_not_follow_redirects():
    """The token must never be forwarded: a redirect from the manifest URL is an error."""
    import http.server
    import threading
    import urllib.error

    hits = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append((self.path, self.headers.get("X-Auth-Token")))
            if self.path.startswith("/fw/"):
                self.send_response(302)
                self.send_header("Location", "/elsewhere")
                self.end_headers()
            else:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"build": 1}')

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        with pytest.raises(urllib.error.HTTPError):
            op.fetch_manifest(base, "tok")
        assert [p for p, _ in hits] == ["/fw/manifest.json"]   # /elsewhere never requested
    finally:
        srv.shutdown()


def test_make_stage_uses_a_private_mktemp_folder(monkeypatch):
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return types.SimpleNamespace(stdout="/tmp/tmp.Ab12Cd\n")

    monkeypatch.setattr(op.subprocess, "run", fake_run)
    assert op.make_stage("srv") == "/tmp/tmp.Ab12Cd"
    assert calls == [["ssh", "srv", "mktemp -d"]]      # not a predictable /tmp/reader-fw-<time> path


@pytest.mark.parametrize("out", ["", "relative\n", "/tmp/a\n/tmp/b\n"])
def test_make_stage_refuses_an_unusable_reply(monkeypatch, out):
    monkeypatch.setattr(op.subprocess, "run", lambda cmd, **kw: types.SimpleNamespace(stdout=out))
    with pytest.raises(SystemExit):
        op.make_stage("srv")


@pytest.mark.parametrize("failing", ["scp", "ssh"])
def test_a_failed_upload_or_install_still_removes_the_stage(monkeypatch, tmp_path, failing):
    key = tmp_path / "k.pem"
    op.load_or_create_key(key, create=True)
    build_dir = tmp_path / "pio" / ".pio" / "build" / "env"
    build_dir.mkdir(parents=True)
    monkeypatch.setattr(op, "READER", tmp_path / "pio")
    ran = []

    def fake_run(cmd, **kw):     # subprocess.run: mktemp -d and the cleanup
        ran.append(cmd)
        return types.SimpleNamespace(stdout="/tmp/tmp.Ab12Cd\n")

    def run(cmd, **kw):          # ota_publish.run: the build, the scp, the install
        if cmd[0] == sys.executable:
            (build_dir / "firmware.bin").write_bytes(b"\xe9" * 64)
            (build_dir / "fw_build.txt").write_text(kw["env"]["FW_BUILD"])
        elif cmd[0] == failing:
            raise subprocess.CalledProcessError(1, cmd)
    monkeypatch.setattr(op, "run", run)
    monkeypatch.setattr(op.subprocess, "run", fake_run)
    with pytest.raises(subprocess.CalledProcessError):
        op.main(["--host", "srv", "--key", str(key), "--env", "env"])
    assert ["ssh", "srv", "rm -rf /tmp/tmp.Ab12Cd"] in ran


def test_live_problem_reports_instead_of_raising(monkeypatch):
    import urllib.error

    def boom(exc):
        def f(base, token):
            raise exc
        return f

    for exc in (urllib.error.HTTPError("u", 502, "Bad Gateway", {}, None),
                urllib.error.URLError("refused"), TimeoutError("timed out"),
                json.JSONDecodeError("bad", "x", 0)):
        monkeypatch.setattr(op, "fetch_manifest", boom(exc))
        msg = op.live_problem("https://h", "tok", 5)
        assert msg and type(exc).__name__ in msg
    monkeypatch.setattr(op, "fetch_manifest", lambda b, t: {"build": 4})
    assert "build 4" in op.live_problem("https://h", "tok", 5)
    monkeypatch.setattr(op, "fetch_manifest", lambda b, t: [1])
    assert op.live_problem("https://h", "tok", 5)
    monkeypatch.setattr(op, "fetch_manifest", lambda b, t: {"build": 5})
    assert op.live_problem("https://h", "tok", 5) is None
