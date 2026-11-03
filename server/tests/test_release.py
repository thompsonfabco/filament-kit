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


RFC8032_1024_MSG = (
    "08b8b2b733424243760fe426a4b54908632110a66c2f6591eabd3345e3e4eb98fa6e264bf09efe12ee50f8f54e9f77b1e355f6c50544e2"
    "3fb1433ddf73be84d879de7c0046dc4996d9e773f4bc9efe5738829adb26c81b37c93a1b270b20329d658675fc6ea534e0810a4432826b"
    "f58c941efb65d57a338bbd2e26640f89ffbc1a858efcb8550ee3a5e1998bd177e93a7363c344fe6b199ee5d02e82d522c4feba15452f80"
    "288a821a579116ec6dad2b3b310da903401aa62100ab5d1a36553e06203b33890cc9b832f79ef80560ccb9a39ce767967ed628c6ad573c"
    "b116dbefefd75499da96bd68a8a97b928a8bbc103b6621fcde2beca1231d206be6cd9ec7aff6f6c94fcd7204ed3455c68c83f4a41da4af"
    "2b74ef5c53f1d8ac70bdcb7ed185ce81bd84359d44254d95629e9855a94a7c1958d1f8ada5d0532ed8a5aa3fb2d17ba70eb6248e594e1a"
    "2297acbbb39d502f1a8c6eb6f1ce22b3de1a1f40cc24554119a831a9aad6079cad88425de6bde1a9187ebb6092cf67bf2b13fd65f27088"
    "d78b7e883c8759d2c4f5c65adb7553878ad575f9fad878e80a0c9ba63bcbcc2732e69485bbc9c90bfbd62481d9089beccf80cfe2df16a2"
    "cf65bd92dd597b0707e0917af48bbb75fed413d238f5555a7a569d80c3414a8d0859dc65a46128bab27af87a71314f318c782b23ebfe80"
    "8b82b0ce26401d2e22f04d83d1255dc51addd3b75a2b1ae0784504df543af8969be3ea7082ff7fc9888c144da2af58429ec96031dbcad3"
    "dad9af0dcbaaaf268cb8fcffead94f3c7ca495e056a9b47acdb751fb73e666c6c655ade8297297d07ad1ba5e43f1bca32301651339e229"
    "04cc8c42f58c30c04aafdb038dda0847dd988dcda6f3bfd15c4b4c4525004aa06eeff8ca61783aacec57fb3d1f92b0fe2fd1a85f672451"
    "7b65e614ad6808d6f6ee34dff7310fdc82aebfd904b01e1dc54b2927094b2db68d6f903b68401adebf5a7e08d78ff4ef5d63653a65040c"
    "f9bfd4aca7984a74d37145986780fc0b16ac451649de6188a7dbdf191f64b5fc5e2ab47b57f7f7276cd419c17a3ca8e1b939ae49e488ac"
    "ba6b965610b5480109c8b17b80e1b7b750dfc7598d5d5011fd2dcc5600a32ef5b52a1ecc820e308aa342721aac0943bf6686b64b257937"
    "6504ccc493d97e6aed3fb0f9cd71a43dd497f01f17c0e2cb3797aa2a2f256656168e6c496afc5fb93246f6b1116398a346f1a641f3b041"
    "e989f7914f90cc2c7fff357876e506b50d334ba77c225bc307ba537152f3f1610e4eafe595f6d9d90d11faa933a15ef1369546868a7f3a"
    "45a96768d40fd9d03412c091c6315cf4fde7cb68606937380db2eaaa707b4c4185c32eddcdd306705e4dc1ffc872eeee475a64dfac86ab"
    "a41c0618983f8741c5ef68d3a101e8a3b8cac60c905c15fc910840b94c00a0b9d0")

# RFC 8032 section 7.1: (secret key, public key, message, signature). The secret keys are kept so the test also
# checks the vectors themselves against `cryptography` (ed25519 signing is deterministic).
RFC8032 = [
    ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
     "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", "72",
     "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da"
     "085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
    ("c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7",
     "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025", "af82",
     "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac"
     "18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a"),
    ("f5e5767cf153319517630f226876b86c8160cc583bc013744c6bf255f5cc0ee5",
     "278117fc144c72340f67d0f2316e8386ceffbf2b2428c9c51fef7c597f1d426e", RFC8032_1024_MSG,
     "0aab4c900501b3e24d7cdf4663326a3a87df5e4843b2cbdb67cbf6e460fec350"
     "aa5371b1508f9f4528ecea23c436d94b5e8fcd4f681e30a6ac00a9704a188a03"),
]


@pytest.mark.parametrize("sk,pk,msg,sig", RFC8032, ids=["test2", "test3", "test1024"])
def test_rfc8032_vectors(sk, pk, msg, sig):
    pub, m, s = bytes.fromhex(pk), bytes.fromhex(msg), bytes.fromhex(sig)
    priv = ed25519.Ed25519PrivateKey.from_private_bytes(bytes.fromhex(sk))
    assert base64.b64decode(_pub(priv)) == pub and priv.sign(m) == s    # the vector is copied right
    assert len(m) == {"72": 1, "af82": 2}.get(msg, 1023)
    assert release.ed25519_verify(pub, m, s)
    assert not release.ed25519_verify(pub, m[:-1] + bytes([m[-1] ^ 1]), s)
    release.check_public_key(pub)


def _enc(y: int, sign: int = 0) -> bytes:
    return (y | sign << 255).to_bytes(32, "little")


def test_y_not_below_p_is_refused_in_r_and_a():
    priv = ed25519.Ed25519PrivateKey.generate()
    pub = base64.b64decode(_pub(priv))
    sig = priv.sign(b"m")
    for y in (release._P, release._P + 1, 2 ** 255 - 1):        # non-canonical y encodings
        assert not release.ed25519_verify(_enc(y), b"m", sig)
        assert not release.ed25519_verify(pub, b"m", _enc(y) + sig[32:])
        with pytest.raises(ReleaseError):
            release.check_public_key(_enc(y))


# small-order points: the identity (y=1), the point of order 2 (y=-1), points of order 4 (y=0)
SMALL_ORDER = [_enc(1), _enc(release._P - 1), _enc(0), _enc(0, 1)]


@pytest.mark.parametrize("raw", SMALL_ORDER, ids=["identity", "order2", "order4", "order4-neg"])
def test_small_order_keys_refused(raw, tmp_path):
    assert release._decompress(raw) is not None              # on the curve, so only the order check stops it
    assert release.small_order(release._decompress(raw))
    b64 = base64.b64encode(raw).decode()
    with pytest.raises(ReleaseError, match="small-order"):
        release.public_key(b64)
    with pytest.raises(ReleaseError, match="small-order"):
        release.verify_sums(b"x", base64.b64encode(b"\0" * 64), b64)
    assert sign_release.main(["--root", str(_tree(tmp_path)), "set-pubkey", b64]) == 1


def test_a_real_key_is_not_small_order():
    assert not release.small_order(release._decompress(base64.b64decode(_pub(ed25519.Ed25519PrivateKey.generate()))))


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
