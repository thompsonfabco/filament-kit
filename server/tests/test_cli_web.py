"""`filament-kit web passphrase` and `web status`."""
from __future__ import annotations

import os
import stat

import pytest

from conftest import free_port
from filament_kit import cli, config, modules, secret_input

pytest.importorskip("mcp")

from fakes import readers_fake  # noqa: E402
from starlette.applications import Starlette  # noqa: E402
from starlette.responses import PlainTextResponse  # noqa: E402
from starlette.routing import Route  # noqa: E402

from filament_kit.web import auth  # noqa: E402

PASS = "a long enough passphrase"


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    for k, d in (("ETC", "etc"), ("STATE", "state"), ("OPT", "opt"), ("BACKUPS", "bk")):
        monkeypatch.setenv(f"FK_{k}", str(tmp_path / d))
    (tmp_path / "etc").mkdir()
    (tmp_path / "state").mkdir()
    return tmp_path


@pytest.fixture
def chown(monkeypatch):
    calls = []
    monkeypatch.setattr(cli.shutil, "chown", lambda path, user=None, group=None: calls.append((user, group)))
    return calls


def _prompts(monkeypatch, *answers):
    it = iter(answers)
    asked = []

    def getpass(prompt=""):
        asked.append(prompt)
        return next(it)
    monkeypatch.setattr(secret_input, "ask", getpass)
    return asked


def test_web_passphrase_needs_root(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_is_root", lambda: False)
    assert cli.main(["web", "passphrase"]) == 1
    assert "root" in capsys.readouterr().err
    assert not (config.paths().etc / "web_passphrase").exists()


def test_web_passphrase_writes_640_root_group(monkeypatch, chown, capsys):
    monkeypatch.setattr(cli, "_is_root", lambda: True)
    modes = []
    real_chmod = os.chmod
    monkeypatch.setattr(cli.os, "chmod", lambda p, m: (modes.append(m), real_chmod(p, m)))
    asked = _prompts(monkeypatch, PASS, PASS)
    assert cli.main(["web", "passphrase"]) == 0
    f = config.paths().etc / "web_passphrase"
    assert auth.check_passphrase(PASS, f) is True
    assert len(asked) == 2 and "passphrase" in asked[0]           # typed through the masked prompt (stars)
    assert modes == [0o640] and chown == [("root", "filament-kit")]
    if os.name != "nt":
        assert stat.S_IMODE(f.stat().st_mode) == 0o640
    out = capsys.readouterr().out
    assert PASS not in out and "saved" in out.lower()


def test_web_passphrase_mismatch_or_short(monkeypatch, chown, capsys):
    monkeypatch.setattr(cli, "_is_root", lambda: True)
    _prompts(monkeypatch, PASS, PASS + "x")
    assert cli.main(["web", "passphrase"]) == 1
    assert "do not match" in capsys.readouterr().err
    _prompts(monkeypatch, "short", "short")
    assert cli.main(["web", "passphrase"]) == 1
    assert "at least 12" in capsys.readouterr().err
    assert not (config.paths().etc / "web_passphrase").exists() and chown == []


def test_web_status(monkeypatch, capsys):
    port = free_port()
    app = Starlette(routes=[Route("/health", lambda r: PlainTextResponse("ok"))])
    mods = {n: True for n in modules.MODES["server"]}
    mods["web"] = True
    config.save({"modules": mods, "web": {"port": port, "public_url": "https://mcp.example.test/filament"}})
    assert cli.main(["web", "status"]) == 1          # no passphrase, nothing answering
    out = capsys.readouterr().out
    assert "FAIL" in out and "filament-kit web passphrase" in out
    (config.paths().etc / "web_passphrase").write_text(auth.hash_passphrase(PASS), encoding="utf-8")
    with readers_fake.Served(app, port):
        assert cli.main(["web", "status"]) == 0
    out = capsys.readouterr().out
    assert "https://mcp.example.test/filament/mcp" in out and "FAIL" not in out
    assert "https://mcp.example.test/filament/intake" in out


def test_web_status_effective_port_and_unreadable_oauth(monkeypatch, capsys):
    mods = {n: True for n in modules.MODES["server"]}
    mods["web"] = True
    config.save({"modules": mods, "web": {"public_url": "https://mcp.example.test/filament"}})
    cli.main(["web", "status"])
    out = capsys.readouterr().out
    assert "127.0.0.1:8101" in out and "None" not in out
    f = config.paths().web / "oauth.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("{}", encoding="utf-8")
    real = cli.Path.read_text

    def denied(self, *a, **kw):
        if self.name == "oauth.json":
            raise PermissionError(13, "Permission denied")
        return real(self, *a, **kw)
    monkeypatch.setattr(cli.Path, "read_text", denied)
    cli.main(["web", "status"])
    assert "cannot read (run as root)" in capsys.readouterr().out


def test_web_passphrase_without_the_group(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_is_root", lambda: True)

    def no_group(path, user=None, group=None):
        raise LookupError(f"no such group: {group!r}")
    monkeypatch.setattr(cli.shutil, "chown", no_group)
    _prompts(monkeypatch, PASS, PASS)
    assert cli.main(["web", "passphrase"]) == 1
    err = capsys.readouterr().err
    assert "filament-kit" in err and "fix:" in err and "Traceback" not in err
    etc = config.paths().etc
    assert not (etc / "web_passphrase").exists() and not list(etc.glob("web_passphrase*"))
