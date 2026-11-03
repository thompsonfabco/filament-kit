"""Signed releases: the ed25519 verifier, SHA256SUMS, the download client, unpacking, sign_release.py, get.sh."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from filament_kit import release
from filament_kit.release import ReleaseError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import sign_release  # noqa: E402


def _pub(priv) -> str:
    raw = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode()


# ---------------------------------------------------------------- ed25519

def test_rfc8032_vector_1():
    pub = bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
    sig = bytes.fromhex("e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e3970"
                        "1cf9b46bd25bf5f0595bbe24655141438e7a100b")
    assert release.ed25519_verify(pub, b"", sig)
    assert not release.ed25519_verify(pub, b"x", sig)


def test_verifier_agrees_with_cryptography():
    for i in range(25):
        priv = ed25519.Ed25519PrivateKey.generate()
        pub = base64.b64decode(_pub(priv))
        msg = os.urandom(i * 7)
        sig = priv.sign(msg)
        assert release.ed25519_verify(pub, msg, sig)
        bad = bytearray(sig)
        bad[i % 64] ^= 1 << (i % 8)
        assert not release.ed25519_verify(pub, msg, bytes(bad))
        assert not release.ed25519_verify(pub, msg + b"!", sig)
        other = base64.b64decode(_pub(ed25519.Ed25519PrivateKey.generate()))
        assert not release.ed25519_verify(other, msg, sig)


def test_verifier_rejects_non_canonical_s_and_bad_lengths():
    priv = ed25519.Ed25519PrivateKey.generate()
    pub = base64.b64decode(_pub(priv))
    sig = priv.sign(b"m")
    s = int.from_bytes(sig[32:], "little") + release._L      # same point, S not reduced
    assert not release.ed25519_verify(pub, b"m", sig[:32] + s.to_bytes(32, "little"))
    assert not release.ed25519_verify(pub[:31], b"m", sig)
    assert not release.ed25519_verify(pub, b"m", sig[:63])
    assert not release.ed25519_verify(b"\xff" * 32, b"m", sig)


# ---------------------------------------------------------------- sums and signature

def test_parse_sums():
    h = "a" * 64
    assert release.parse_sums(f"{h}  filament-kit-1.2.3.tar.gz\n{h} *get.sh\n".encode()) == {
        "filament-kit-1.2.3.tar.gz": h, "get.sh": h}
    for bad in (b"", f"{h}  ../x\n".encode(), f"{h}  a\n{h}  a\n".encode(), b"zz  a\n", f"{h} a\n".encode()):
        with pytest.raises(ReleaseError):
            release.parse_sums(bad)


def test_verify_sums_needs_a_key_and_a_good_signature():
    priv = ed25519.Ed25519PrivateKey.generate()
    sums = f"{'b' * 64}  get.sh\n".encode()
    sig = base64.b64encode(priv.sign(sums)) + b"\n"
    assert release.verify_sums(sums, sig, _pub(priv)) == {"get.sh": "b" * 64}
    with pytest.raises(ReleaseError, match="no release public key"):
        release.verify_sums(sums, sig, "")
    with pytest.raises(ReleaseError, match="signature"):
        release.verify_sums(sums.replace(b"b", b"c"), sig, _pub(priv))
    with pytest.raises(ReleaseError, match="signature"):
        release.verify_sums(sums, b"not base64!", _pub(priv))
    with pytest.raises(ReleaseError, match="signature"):
        release.verify_sums(sums, sig, _pub(ed25519.Ed25519PrivateKey.generate()))


def test_version_names():
    assert release.parse_version("1.20.3") == (1, 20, 3)
    assert release.tarball_name("0.3.0") == "filament-kit-0.3.0.tar.gz"
    for bad in ("1.2", "v1.2.3", "1.2.3-rc1", "1.100.0", "01.2.3", "1.2.3/../x"):
        with pytest.raises(ReleaseError):
            release.parse_version(bad)


# ---------------------------------------------------------------- a fake release server

def make_tarball(version: str, *, extra: tarfile.TarInfo | None = None, top: str | None = None) -> bytes:
    top = top or f"filament-kit-{version}"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data, mode in ((f"{top}/install.sh", b"#!/bin/bash\necho installed\n", 0o755),
                                 (f"{top}/install/README", b"x\n", 0o644)):
            ti = tarfile.TarInfo(name)
            ti.size, ti.mode = len(data), mode
            tf.addfile(ti, io.BytesIO(data))
        if extra is not None:
            tf.addfile(extra, io.BytesIO(b"evil") if extra.isfile() else None)
    return buf.getvalue()


class FakeRelease:
    """A GitHub API look-alike on 127.0.0.1: /repos/o/r/releases/{latest,tags/vX}, assets served from
    /repos/o/r/releases/assets/<n> through a 302 (as GitHub does). Records every request's headers."""

    def __init__(self, priv, version="1.2.3", *, tamper_sig=False, tamper_tar=False, tarball=None):
        self.version = version
        tar = tarball if tarball is not None else make_tarball(version)
        sums = (f"{hashlib.sha256(tar).hexdigest()}  filament-kit-{version}.tar.gz\n"
                f"{'0' * 64}  get.sh\n").encode()
        sig = priv.sign(sums)
        if tamper_sig:
            sig = bytes([sig[0] ^ 1]) + sig[1:]
        if tamper_tar:
            tar = tar[:-1] + bytes([tar[-1] ^ 1])
        self.files = {f"filament-kit-{version}.tar.gz": tar, "SHA256SUMS": sums,
                      "SHA256SUMS.sig": base64.b64encode(sig) + b"\n"}
        self.requests: list[tuple[str, dict]] = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                outer.requests.append((self.path, dict(self.headers)))
                names = list(outer.files)
                base = f"http://127.0.0.1:{self.server.server_address[1]}"
                if self.path in ("/repos/o/r/releases/latest", f"/repos/o/r/releases/tags/v{outer.version}"):
                    body = json.dumps({"tag_name": f"v{outer.version}", "assets": [
                        {"name": n, "url": f"{base}/repos/o/r/releases/assets/{i}"} for i, n in enumerate(names)]})
                    return self._send(200, body.encode())
                if self.path.startswith("/repos/o/r/releases/assets/"):
                    i = int(self.path.rsplit("/", 1)[1])
                    self.send_response(302)
                    self.send_header("Location", f"{base}/dl/{names[i]}")
                    self.end_headers()
                    return None
                if self.path.startswith("/dl/") and self.path[4:] in outer.files:
                    return self._send(200, outer.files[self.path[4:]])
                return self._send(404, b"{}")

            def _send(self, code, body):
                self.send_response(code)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.api = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def key():
    return ed25519.Ed25519PrivateKey.generate()


@pytest.fixture
def serve(key):
    made = []

    def make(**kw):
        fr = FakeRelease(key, **kw)
        made.append(fr)
        return fr
    yield make
    for fr in made:
        fr.close()


def test_fetch_good_release(serve, key, tmp_path):
    fr = serve()
    ver, tar = release.fetch(tmp_path / "dl", repo="o/r", fetcher=release.Fetcher(fr.api, token="SECRET"),
                             pubkey_b64=_pub(key))
    assert ver == "1.2.3" and tar.read_bytes() == fr.files[tar.name]
    assert (tmp_path / "dl" / "SHA256SUMS.sig").is_file()
    # a token is never sent to a host outside api.github.com / objects.githubusercontent.com
    assert fr.requests and all("Authorization" not in h for _, h in fr.requests)
    root = release.extract(tar, ver, tmp_path / "x")
    assert (root / "install.sh").read_bytes().startswith(b"#!/bin/bash")
    assert release.verify_dir(tmp_path / "dl", ver, _pub(key)) == tar


def test_fetch_by_version(serve, key, tmp_path):
    fr = serve(version="0.4.0")
    ver, _ = release.fetch(tmp_path, repo="o/r", version="0.4.0", fetcher=release.Fetcher(fr.api),
                           pubkey_b64=_pub(key))
    assert ver == "0.4.0" and fr.requests[0][0] == "/repos/o/r/releases/tags/v0.4.0"
    with pytest.raises(ReleaseError, match="HTTP 404"):
        release.fetch(tmp_path, repo="o/r", version="0.5.0", fetcher=release.Fetcher(fr.api), pubkey_b64=_pub(key))


def test_bad_signature_downloads_no_tarball(serve, key, tmp_path):
    fr = serve(tamper_sig=True)
    with pytest.raises(ReleaseError, match="signature"):
        release.fetch(tmp_path, repo="o/r", fetcher=release.Fetcher(fr.api), pubkey_b64=_pub(key))
    assert not any("tar.gz" in p for p, _ in fr.requests)
    assert list(tmp_path.iterdir()) == []


def test_wrong_key_refused(serve, tmp_path):
    fr = serve()
    other = _pub(ed25519.Ed25519PrivateKey.generate())
    with pytest.raises(ReleaseError, match="signature"):
        release.fetch(tmp_path, repo="o/r", fetcher=release.Fetcher(fr.api), pubkey_b64=other)


def test_bad_hash_deletes_the_tarball(serve, key, tmp_path):
    fr = serve(tamper_tar=True)
    with pytest.raises(ReleaseError, match="does not match its hash"):
        release.fetch(tmp_path, repo="o/r", fetcher=release.Fetcher(fr.api), pubkey_b64=_pub(key))
    assert list(tmp_path.iterdir()) == []


def test_no_key_no_download(serve, tmp_path):
    fr = serve()
    with pytest.raises(ReleaseError, match="no release public key"):
        release.fetch(tmp_path, repo="o/r", fetcher=release.Fetcher(fr.api), pubkey_b64="")
    assert fr.requests == []


@pytest.mark.parametrize("extra", ["../evil", "/abs", "filament-kit-1.2.3/link", "other/x"])
def test_extract_refuses_odd_entries(serve, key, tmp_path, extra):
    ti = tarfile.TarInfo(extra)
    if extra.endswith("link"):
        ti.type, ti.linkname = tarfile.SYMTYPE, "/etc/passwd"
    else:
        ti.size = 4
    tar = tmp_path / "filament-kit-1.2.3.tar.gz"
    tar.write_bytes(make_tarball("1.2.3", extra=ti))
    with pytest.raises(ReleaseError, match="unexpected entry"):
        release.extract(tar, "1.2.3", tmp_path / "x")
    assert not (tmp_path / "x").exists()


def test_extract_needs_the_versions_folder(tmp_path):
    tar = tmp_path / "filament-kit-1.2.3.tar.gz"
    tar.write_bytes(make_tarball("1.2.3", top="filament-kit-9.9.9"))
    with pytest.raises(ReleaseError):
        release.extract(tar, "1.2.3", tmp_path / "x")


# ---------------------------------------------------------------- the token

class _Capture:
    def __init__(self):
        self.reqs = []

    def open(self, req, timeout=None):
        self.reqs.append(req)
        raise OSError("offline")


def test_token_only_to_github_hosts_over_https():
    cap = _Capture()
    f = release.Fetcher(token="T0KEN", opener=cap)
    for url in ("https://api.github.com/repos/o/r/releases/latest",
                "https://objects.githubusercontent.com/x",
                "http://api.github.com/x", "https://evil.example/x", "https://api.github.com.evil.example/x",
                "https://api.github.com:8443/x"):
        with pytest.raises(ReleaseError):
            f.get(url, 10)
    auth = [r.unredirected_hdrs.get("Authorization") for r in cap.reqs]
    assert auth == ["Bearer T0KEN", "Bearer T0KEN", None, None, None, None]
    # never as a redirectable header: urllib does not carry unredirected headers to the redirect target
    assert all("Authorization" not in r.headers for r in cap.reqs)


def test_read_token(tmp_path, monkeypatch):
    monkeypatch.delenv("FK_GITHUB_TOKEN", raising=False)
    assert release.read_token(None) is None
    monkeypatch.setenv("FK_GITHUB_TOKEN", " envtok \n")
    assert release.read_token(None) == "envtok"
    f = tmp_path / "t"
    f.write_text("filetok\n")
    assert release.read_token(str(f)) == "filetok"
    with pytest.raises(ReleaseError, match="cannot read"):
        release.read_token(str(tmp_path / "missing"))


def test_cli_prints_only_the_folder_and_never_the_token(serve, key, tmp_path, monkeypatch, capsys):
    fr = serve()
    monkeypatch.setattr(release, "PUBKEY", _pub(key))
    tok = tmp_path / "tok"
    tok.write_text("ghp_SECRETVALUE\n")
    rc = release.main(["fetch", "--dest", str(tmp_path / "w"), "--repo", "o/r", "--api", fr.api,
                       "--token-file", str(tok), "--keep", str(tmp_path / "keep")])
    out, err = capsys.readouterr()
    assert rc == 0
    assert Path(out.strip()) == tmp_path / "w" / "unpacked" / "filament-kit-1.2.3"
    assert "SECRETVALUE" not in out + err
    assert release.verify_dir(tmp_path / "keep" / "1.2.3", "1.2.3", _pub(key)).is_file()


def test_cli_bad_signature_exit_1(serve, key, tmp_path, monkeypatch, capsys):
    fr = serve(tamper_sig=True)
    monkeypatch.setattr(release, "PUBKEY", _pub(key))
    rc = release.main(["fetch", "--dest", str(tmp_path / "w"), "--repo", "o/r", "--api", fr.api])
    out, err = capsys.readouterr()
    assert rc == 1 and out == "" and "signature" in err
    assert not (tmp_path / "w" / "unpacked").exists()


# ---------------------------------------------------------------- sign_release.py and get.sh

def _tree(tmp_path) -> Path:
    root = tmp_path / "repo"
    (root / "server" / "filament_kit").mkdir(parents=True)
    shutil.copy(ROOT / "server" / "filament_kit" / "release.py", root / "server" / "filament_kit" / "release.py")
    shutil.copy(ROOT / "get.sh", root / "get.sh")
    return root


def test_get_sh_carries_release_py_verbatim():
    text = (ROOT / "get.sh").read_text(encoding="utf-8")
    assert sign_release.embedded(text) == (ROOT / "server/filament_kit/release.py").read_text(encoding="utf-8")


def test_keygen_prints_only_the_public_key(tmp_path, capsys):
    root = _tree(tmp_path)
    out = tmp_path / "keys" / "release.pem"
    out.parent.mkdir()
    assert sign_release.main(["--root", str(root), "keygen", "--out", str(out)]) == 0
    stdout, stderr = capsys.readouterr()
    pem = out.read_bytes()
    assert b"PRIVATE KEY" in pem
    assert "PRIVATE" not in stdout and pem.decode() not in stdout + stderr
    priv = serialization.load_pem_private_key(pem, None)
    assert stdout.strip() == _pub(priv)
    if os.name == "posix":
        assert out.stat().st_mode & 0o777 == 0o600
    assert sign_release.main(["--root", str(root), "keygen", "--out", str(out)]) == 1   # never overwrites
    assert out.read_bytes() == pem
    assert sign_release.main(["--root", str(root), "keygen", "--out", str(root / "k.pem")]) == 1  # not in the repo


def test_set_pubkey_then_sign_round_trip(tmp_path, monkeypatch):
    root = _tree(tmp_path)
    priv = ed25519.Ed25519PrivateKey.generate()
    pem = priv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())
    assert sign_release.main(["--root", str(root), "set-pubkey", _pub(priv)]) == 0
    assert f'PUBKEY = "{_pub(priv)}"' in (root / "get.sh").read_text(encoding="utf-8")
    assert sign_release.embedded((root / "get.sh").read_text(encoding="utf-8")) == \
        (root / "server/filament_kit/release.py").read_text(encoding="utf-8")
    sums = tmp_path / "SHA256SUMS"
    sums.write_bytes(f"{'c' * 64}  get.sh\n".encode())
    monkeypatch.setenv("FK_RELEASE_KEY", pem.decode())
    assert sign_release.main(["--root", str(root), "sign", str(sums)]) == 0
    assert release.verify_sums(sums.read_bytes(), (tmp_path / "SHA256SUMS.sig").read_bytes(), _pub(priv))
    # another key than the one in release.py: no signature is written
    (tmp_path / "SHA256SUMS.sig").unlink()
    other = ed25519.Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    monkeypatch.setenv("FK_RELEASE_KEY", other.decode())
    assert sign_release.main(["--root", str(root), "sign", str(sums)]) == 1
    assert not (tmp_path / "SHA256SUMS.sig").exists()
    monkeypatch.delenv("FK_RELEASE_KEY")
    assert sign_release.main(["--root", str(root), "sign", str(sums)]) == 1


def test_set_pubkey_rejects_garbage(tmp_path):
    root = _tree(tmp_path)
    assert sign_release.main(["--root", str(root), "set-pubkey", "abc"]) == 1


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_get_sh_syntax_and_no_tracing():
    subprocess.run(["bash", "-n", str(ROOT / "get.sh")], check=True)
    text = (ROOT / "get.sh").read_text(encoding="utf-8")
    shell = text.replace(sign_release.embedded(text), "")
    assert "set -x" not in shell and "FK_GITHUB_TOKEN" not in shell.split("set -euo pipefail", 1)[1]
    assert shell.rstrip().endswith('fk_main "$@"')
    assert "</dev/tty" in shell and "--keep /opt/filament-kit/releases" in shell
