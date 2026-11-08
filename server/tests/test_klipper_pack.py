"""`filament-kit klipper pack`: the printer-pack install command, pinned to the running version and checked
against the signed SHA256SUMS (review 2026-11-08 B2)."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from filament_kit import klipper_cli, release, updates
from test_updates import _cfg, env, key, srv  # noqa: F401  (fixtures)

PACK = "fk-printer-pack.tar.gz"
PACK_BYTES = b"not really a tarball, only hashed"
PACK_SHA = hashlib.sha256(PACK_BYTES).hexdigest()


def _keep(env, fr, version="1.0.0", files=(release.SUMS, release.SIG)) -> Path:
    """Copy a fake release's signed files into the kept-release folder, as the updater leaves them."""
    d = env / "opt" / "releases" / version
    d.mkdir(parents=True)
    for n in files:
        (d / n).write_bytes(fr.files[n])
    return d


class NoNet(release.Fetcher):
    def __init__(self):
        super().__init__("http://127.0.0.1")
        self.calls = 0

    def release(self, *a, **kw):
        self.calls += 1
        raise release.ReleaseError("cannot reach api.github.com: offline")

    def get(self, *a, **kw):
        self.calls += 1
        raise release.ReleaseError("cannot reach api.github.com: offline")


def _run(env, fetcher, capsys):
    rc = klipper_cli.pack(_cfg(env), fetcher=fetcher)
    out, err = capsys.readouterr()
    return rc, out, err


def _no_command(out):
    assert "curl" not in out and "sha256sum" not in out and "fk-printer-pack.sh" not in out


def _check_command(out, sha, repo=release.REPO):
    url = f"https://github.com/{repo}/releases/download/v1.0.0/{PACK}"
    assert "Run this on the printer (as its normal user, not root):" in out
    assert "signed" in out
    assert f"curl -fsSLo {PACK} {url}" in out
    line = next(ln for ln in out.splitlines() if "sha256sum" in ln).strip()
    assert line == (f'echo "{sha}  {PACK}" | sha256sum -c - && tar xzf {PACK} '
                    f"&& sh fk-printer-pack/fk-printer-pack.sh install")
    assert "latest" not in out


def test_kept_release_needs_no_network(env, srv, key, capsys):
    fr = srv.add("1.0.0", extra={PACK: PACK_BYTES})
    _keep(env, fr)
    net = NoNet()
    rc, out, err = _run(env, net, capsys)
    assert rc == 0, err
    assert net.calls == 0
    _check_command(out, PACK_SHA)


def test_network_fallback_when_nothing_kept(env, srv, key, capsys):
    srv.add("1.0.0", extra={PACK: PACK_BYTES})
    srv.add("2.0.0", extra={PACK: b"a newer pack"})     # `latest` is 2.0.0: the command must still pin 1.0.0
    rc, out, err = _run(env, srv.fetcher(), capsys)
    assert rc == 0, err
    _check_command(out, PACK_SHA)


def test_network_fallback_when_kept_folder_lacks_the_signature(env, srv, key, capsys):
    fr = srv.add("1.0.0", extra={PACK: PACK_BYTES})
    _keep(env, fr, files=(release.SUMS,))
    rc, out, err = _run(env, srv.fetcher(), capsys)
    assert rc == 0, err
    _check_command(out, PACK_SHA)


def test_bad_local_signature_is_an_error_not_a_fallback(env, srv, key, capsys):
    bad = srv.add("1.0.0", extra={PACK: PACK_BYTES}, tamper_sig=True)
    d = _keep(env, bad)
    srv.add("1.0.0", extra={PACK: PACK_BYTES})          # the server now answers a good release
    rc, out, err = _run(env, srv.fetcher(), capsys)    # the network copy would verify: it must not be used
    assert rc == 1
    _no_command(out)
    assert "signature" in err and str(d) in err


def test_network_bad_signature(env, srv, key, capsys):
    srv.add("1.0.0", extra={PACK: PACK_BYTES}, tamper_sig=True)
    rc, out, err = _run(env, srv.fetcher(), capsys)
    assert rc == 1
    _no_command(out)
    assert "signature" in err


def test_pack_missing_from_sums(env, srv, key, capsys):
    fr = srv.add("1.0.0", unlisted={PACK: PACK_BYTES})
    _keep(env, fr)
    rc, out, err = _run(env, NoNet(), capsys)
    assert rc == 1
    _no_command(out)
    assert PACK in err


def test_fetch_failure(env, key, capsys):
    rc, out, err = _run(env, NoNet(), capsys)
    assert rc == 1
    _no_command(out)
    assert "offline" in err and "1.0.0" in err


def test_no_such_release(env, srv, key, capsys):
    srv.add("2.0.0", extra={PACK: PACK_BYTES})          # no v1.0.0 (a dev build, say)
    rc, out, err = _run(env, srv.fetcher(), capsys)
    assert rc == 1
    _no_command(out)
    assert "1.0.0" in err


def test_dev_version_is_refused(env, key, capsys, monkeypatch):
    monkeypatch.setattr(updates, "current_version", lambda: "0.3.0.dev1")
    net = NoNet()
    rc, out, err = _run(env, net, capsys)
    assert rc == 1 and net.calls == 0
    _no_command(out)


def test_cli_entry_uses_the_updaters_fetcher(env, srv, key, capsys, monkeypatch):
    srv.add("1.0.0", extra={PACK: PACK_BYTES})
    _cfg(env)
    monkeypatch.setattr(updates, "default_fetcher", lambda cfg: srv.fetcher())
    assert klipper_cli.main(["pack"]) == 0
    _check_command(capsys.readouterr().out, PACK_SHA)


def test_no_latest_url_in_the_module():
    src = Path(klipper_cli.__file__).read_text(encoding="utf-8")
    assert not re.search(r"latest", src)


def test_the_docs_show_the_pinned_checked_command():
    """docs/klipper.md shows the command's shape, never a fixed `latest` line to copy (review B2 follow-up)."""
    doc = (Path(__file__).resolve().parents[2] / "docs" / "klipper.md").read_text(encoding="utf-8")
    assert not re.search(r"releases/latest/download/" + re.escape(PACK), doc)
    assert not re.search(re.escape(PACK) + r"\s*\|\s*tar", doc)
    assert "releases/download/v<version>/" + PACK in doc
    assert f'echo "<sha256>  {PACK}" | sha256sum -c - && tar xzf {PACK}' in doc
    assert "sudo filament-kit klipper pack" in doc


def test_a_repo_override_names_the_same_repo_in_the_url(env, srv, key, capsys):
    """The hash and the URL come from one repo setting (updates.repo), so they always name the same release."""
    srv.add("1.0.0", extra={PACK: PACK_BYTES})
    rc = klipper_cli.pack(_cfg(env, updates={"repo": "example/filament-kit-fork"}), fetcher=srv.fetcher())
    out, err = capsys.readouterr()
    assert rc == 0, err
    _check_command(out, PACK_SHA, repo="example/filament-kit-fork")


# ---------- pack_info (the web console's data; console-printers stage) and the CLI's output, pinned ----------

def test_cli_output_is_unchanged(env, srv, key, capsys):
    """The exact text `klipper pack` printed before pack_info existed (snapshot, 2026-11-08)."""
    fr = srv.add("1.0.0", extra={PACK: PACK_BYTES})
    _keep(env, fr)
    rc, out, err = _run(env, NoNet(), capsys)
    url = f"https://github.com/{release.REPO}/releases/download/v1.0.0/{PACK}"
    assert (rc, err) == (0, "")
    assert out == (
        "Run this on the printer (as its normal user, not root):\n"
        f"  curl -fsSLo {PACK} {url}\n"
        f'  echo "{PACK_SHA}  {PACK}" | sha256sum -c - && tar xzf {PACK} '
        "&& sh fk-printer-pack/fk-printer-pack.sh install\n"
        "The hash is the one in the signed SHA256SUMS of release v1.0.0 (checked here against the filament-kit "
        "release key); nothing is unpacked or run unless the download matches it.\n")


def test_cli_error_output_is_unchanged(env, key, capsys):
    rc, out, err = _run(env, NoNet(), capsys)
    assert (rc, out) == (1, "")
    assert err == (
        "error: cannot give a verified printer-pack command for filament-kit 1.0.0: cannot reach api.github.com: "
        "offline\n"
        "error: the pack's hash comes only from the signed release of this exact version (a development build has "
        "none); nothing to run\n")


@pytest.mark.parametrize("repo", ["x/y$(id)", "x", "a/b/c", "x/y z", "x/y\n", 5])
def test_a_bad_repo_setting_gives_no_command(env, srv, key, capsys, repo):
    """Checked before the kept copy is used: that path never reaches the fetcher's own check."""
    _keep(env, srv.add("1.0.0", extra={PACK: PACK_BYTES}))
    cfg = _cfg(env, updates={"repo": repo})
    with pytest.raises(release.ReleaseError, match="owner/name"):
        klipper_cli.pack_info("1.0.0", cfg, fetcher=NoNet())
    rc = klipper_cli.pack(cfg, fetcher=NoNet())
    out, err = capsys.readouterr()
    assert rc == 1 and "owner/name" in err
    _no_command(out)


def test_pack_info_returns_the_checked_command(env, srv, key):
    fr = srv.add("1.0.0", extra={PACK: PACK_BYTES})
    _keep(env, fr)
    info = klipper_cli.pack_info("1.0.0", _cfg(env), fetcher=NoNet())
    url = f"https://github.com/{release.REPO}/releases/download/v1.0.0/{PACK}"
    assert info == {"version": "1.0.0", "sha256": PACK_SHA, "url": url, "lines": [
        f"curl -fsSLo {PACK} {url}",
        f'echo "{PACK_SHA}  {PACK}" | sha256sum -c - && tar xzf {PACK} '
        "&& sh fk-printer-pack/fk-printer-pack.sh install"]}


@pytest.mark.parametrize("case", ["bad_sig", "unlisted", "offline", "dev"])
def test_pack_info_raises_release_error_and_gives_no_command(env, srv, key, case):
    version = "1.0.0"
    if case == "bad_sig":
        fr = srv.add("1.0.0", extra={PACK: PACK_BYTES})
        d = _keep(env, fr)
        (d / release.SIG).write_bytes(b"not a signature")
    elif case == "unlisted":
        _keep(env, srv.add("1.0.0", unlisted={PACK: PACK_BYTES}))
    elif case == "dev":
        version = "0.3.0.dev1"
    with pytest.raises(release.ReleaseError):
        klipper_cli.pack_info(version, _cfg(env), fetcher=NoNet())
