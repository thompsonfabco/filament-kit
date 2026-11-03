"""Final review I3 (Ruling BU): a library archive from a GitHub release is checked against the release's signed
SHA256SUMS (release.verify_sums) before it is unpacked; a custom mirror without SHA256SUMS keeps the hash-only
check with a note. Also the one GitHub-token host policy (M7): library.py uses release.py's."""
from __future__ import annotations

import base64
import hashlib
import io
import urllib.error

import pytest

from filament_kit import cli, config, library, release
from test_library import served  # noqa: F401  (fixture)
from test_library_on_request import env, fixture_files, fresh, put, tar_bytes  # noqa: F401  (fixtures)
from test_updates import key  # noqa: F401  (fixture)

REL = "https://github.com/o/r/releases/latest/download/"
URL = REL + "library.tar.gz"


def sums_for(files: dict[str, bytes]) -> bytes:
    return "".join(f"{hashlib.sha256(d).hexdigest()}  {n}\n" for n, d in files.items()).encode()


def sign(priv, sums: bytes) -> bytes:
    return base64.b64encode(priv.sign(sums)) + b"\n"


class _Resp(io.BytesIO):
    status = 200


class FakeWeb:
    """urlopen-like: serves `files` by URL; anything else is a 404."""

    def __init__(self, files: dict[str, bytes]):
        self.files = files
        self.seen: list[tuple[str, dict]] = []

    def __call__(self, req, timeout=None):
        self.seen.append((req.full_url, dict(req.header_items())))
        if req.full_url not in self.files:
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)
        return _Resp(self.files[req.full_url])


def release_web(priv, archive: bytes, *, sums_files=None, sig=None) -> FakeWeb:
    sums = sums_for(sums_files if sums_files is not None else {"library.tar.gz": archive, "get.sh": b"x"})
    return FakeWeb({URL: archive, REL + release.SUMS: sums,
                    REL + release.SIG: sign(priv, sums) if sig is None else sig})


def test_default_url_is_a_release_url():
    assert library._release_dir(library.DEFAULT_LIBRARY_URL) is not None
    assert library._release_dir(URL) == REL
    assert library._release_dir("https://github.com/o/r/releases/download/v1.2.3/library.tar.gz") == \
        "https://github.com/o/r/releases/download/v1.2.3/"
    for url in ("https://example.com/o/r/releases/latest/download/library.tar.gz",
                "https://api.github.com/repos/o/r/releases/assets/12", "http://127.0.0.1:8000/library.tar.gz"):
        assert library._release_dir(url) is None, url


def test_a_signed_release_archive_installs(fresh, key):
    archive = tar_bytes(fixture_files())
    web = release_web(key, archive)
    r = library.update(URL, opener=web)
    assert r.error is None and r.changed and r.note is None
    assert library.load().source == "updated"
    urls = [u for u, _ in web.seen]
    assert REL + release.SUMS in urls and REL + release.SIG in urls
    assert urls.index(REL + release.SIG) < urls.index(URL)          # verified before the archive is fetched


def test_a_changed_archive_is_refused(fresh, key):
    good = tar_bytes(fixture_files())
    web = release_web(key, good)
    web.files[URL] = tar_bytes({**fixture_files(), "extra.json": b"{}"})
    r = library.update(URL, opener=web)
    assert r.error and "does not match" in r.error and "SHA256SUMS" in r.error
    assert library.load().source == "none"


def test_a_bad_signature_is_refused(fresh, key):
    archive = tar_bytes(fixture_files())
    web = release_web(key, archive, sig=base64.b64encode(b"\0" * 64))
    r = library.update(URL, opener=web)
    assert r.error and "signature" in r.error
    assert library.load().source == "none"


def test_a_release_without_signed_sums_is_refused(fresh, key):
    web = FakeWeb({URL: tar_bytes(fixture_files())})
    r = library.update(URL, opener=web)
    assert r.error and release.SUMS in r.error and "not installed" in r.error
    assert library.load().source == "none"


def test_sums_that_do_not_list_the_archive_are_refused(fresh, key):
    archive = tar_bytes(fixture_files())
    web = release_web(key, archive, sums_files={"get.sh": b"x"})
    r = library.update(URL, opener=web)
    assert r.error and "does not list library.tar.gz" in r.error
    assert library.load().source == "none"


def test_no_release_key_means_no_install(fresh, monkeypatch):
    from cryptography.hazmat.primitives.asymmetric import ed25519
    monkeypatch.setattr(release, "PUBKEY", "")
    archive = tar_bytes(fixture_files())
    r = library.update(URL, opener=release_web(ed25519.Ed25519PrivateKey.generate(), archive))
    assert r.error and library.load().source == "none"


def test_a_custom_mirror_without_sums_keeps_the_hash_check_with_a_note(fresh, served):
    r = library.update(put(served, "library.tar.gz", tar_bytes(fixture_files())))
    assert r.error is None and r.changed
    assert r.note and "not signature-checked" in r.note


def test_a_custom_mirror_with_signed_sums_is_verified(fresh, served, key):
    archive = tar_bytes(fixture_files())
    sums = sums_for({"library.tar.gz": archive})
    put(served, release.SUMS, sums)
    put(served, release.SIG, sign(key, sums))
    url = put(served, "library.tar.gz", archive)
    r = library.update(url)
    assert r.error is None and r.changed and r.note is None
    put(served, "library.tar.gz", tar_bytes({**fixture_files(), "extra.json": b"{}"}))
    r = library.update(url)
    assert r.error and "does not match" in r.error


def test_cli_prints_the_note(fresh, served, capsys, monkeypatch):
    url = put(served, "library.tar.gz", tar_bytes(fixture_files()))
    cfg = config.load()
    cfg.setdefault("library", {})["url"] = url
    monkeypatch.setattr(config, "load", lambda *a, **k: cfg)
    assert cli.main(["library", "update"]) == 0
    assert "not signature-checked" in capsys.readouterr().out


# ---------- one GitHub-token host policy (final review M7) ----------

@pytest.mark.parametrize("url,sent", [
    ("https://api.github.com/repos/o/r/releases/assets/12", True),
    ("https://objects.githubusercontent.com/x", True),
    ("https://raw.githubusercontent.com/o/r/main/library.tar.gz", False),
    ("https://evil.githubusercontent.com/x", False),
    ("https://api.github.com:8443/repos/o/r/releases/assets/12", False),
])
def test_token_hosts_are_release_pys(env, url, sent):
    (env / "etc" / "github_token").write_text("tok-123\n", encoding="utf-8")
    assert ("Authorization" in library._auth_headers(url)) is sent
    assert sent == release._host_ok_for_token(url)
