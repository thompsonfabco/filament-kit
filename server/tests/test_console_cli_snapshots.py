"""The CLI's words stay exactly as they were when `status`, `web status` and `update --check` moved onto functions that
return data (status.py, updates.check_info): the console reads the data, the terminal prints these lines."""
from __future__ import annotations

import json

import pytest

from filament_kit import cli, config, modules, updates

DEAD = "http://192.0.2.77:9"


@pytest.fixture
def cfg(monkeypatch):
    monkeypatch.setenv("FK_NO_SYSTEMD", "1")
    c = config.load()
    c["server_name"] = "Workshop"
    c["spoolman_url"] = DEAD
    c["modules"] = {n: n in {"server", "library"} for n in modules.MODULES}
    config.save(c)
    monkeypatch.setattr(cli.Spoolman, "ping", lambda self: "1.2.3")
    monkeypatch.setattr(cli.library, "status", lambda: {"source": "bundled", "version": 7, "local": 1,
                                                        "last_check": None})
    return c


def lines(capsys):
    return capsys.readouterr().out.splitlines()


def test_status_lines_on_a_server(cfg, capsys, monkeypatch):
    monkeypatch.setattr(cli.pairing, "fingerprint", lambda pem: "AB" * 32)
    (config.paths().etc / "cert.pem").write_text("x", encoding="utf-8")
    assert cli.main(["status"]) == 0
    assert lines(capsys) == [
        "--   service checks skipped (FK_NO_SYSTEMD=1)",
        f"OK   Spoolman reachable at {DEAD} (v1.2.3)",
        f"OK   certificate present, fingerprint {'AB' * 32}",
        "--   display name: Workshop",
        "--   paired devices: 0",
        f"--   reads used today: 0 of {cfg['reads_per_day']}",
        "--   library version 7 (bundled), 1 local addition",
    ]


def test_status_lines_when_things_fail(cfg, capsys, monkeypatch):
    def down(self):
        raise cli.SpoolmanError("no answer")
    monkeypatch.setattr(cli.Spoolman, "ping", down)
    cfg["station"] = {**cfg["station"], "url": "http://192.0.2.30:5003"}
    cfg["modules"]["ai_intake"] = True
    config.save(cfg)
    assert cli.main(["status"], client_factory=lambda k: None) == 1
    assert lines(capsys) == [
        "--   service checks skipped (FK_NO_SYSTEMD=1)",
        f"FAIL Spoolman not reachable at {DEAD}: no answer",
        "     fix: check that the remote Spoolman is running and spoolman_url is right",
        f"FAIL Anthropic key missing ({config.paths().etc / 'anthropic_key'})",
        "     fix: run: sudo filament-kit config  (option 4)",
        f"FAIL certificate missing ({config.paths().etc / 'cert.pem'})",
        "     fix: run: sudo filament-kit cert",
        "FAIL station not answering at http://192.0.2.30:5003",
        "     fix: check the station machine: sudo systemctl status filament-kit-station  (url http://192.0.2.30:5003)",
        "--   display name: Workshop",
        "--   paired devices: 0",
        f"--   reads used today: 0 of {cfg['reads_per_day']}",
        "--   library version 7 (bundled), 1 local addition",
    ]


def test_web_status_lines(cfg, capsys, monkeypatch):
    cfg["modules"]["web"] = True
    cfg["web"] = {**cfg["web"], "public_url": "https://printer.example.com/filament"}
    config.save(cfg)
    monkeypatch.setattr(cli, "_web_health", lambda port: (True, "ok"))
    assert cli.main(["web", "status"]) == 0
    port = cfg["web"]["port"]
    assert lines(capsys) == [
        "OK   web module is on",
        "OK   public URL https://printer.example.com/filament",
        "     connector: https://printer.example.com/filament/mcp   phone app: https://printer.example.com/filament/intake",
        "--   sign-in passphrase not set: the Claude connector cannot sign in until `sudo filament-kit web passphrase`",
        f"OK   web unit answers on 127.0.0.1:{port}",
        "     connectors: none signed in yet",
        "     printer slots: none; tag readers: 0 + no station",
    ]


class Fetcher:
    def __init__(self, version):
        self.version = version

    def release(self, repo, version=None):
        return {"version": self.version, "assets": {}, "notes": "What changed."}


def test_update_check_lines(cfg, capsys, monkeypatch):
    monkeypatch.setattr(updates, "current_version", lambda: "0.5.0")
    assert updates.check(cfg, fetcher=Fetcher("0.5.0")) == 0
    assert lines(capsys) == ["installed 0.5.0; latest release 0.5.0: up to date"]
    assert updates.check(cfg, fetcher=Fetcher("0.6.0")) == 0
    assert lines(capsys) == ["installed 0.5.0; 0.6.0 is available: sudo filament-kit update"]
    updates._write_state(held="0.6.0")
    assert updates.check(cfg, fetcher=Fetcher("0.6.0")) == 0
    assert lines(capsys) == ["installed 0.5.0; 0.6.0 is available (rolled back earlier: the timer skips it; "
                             "`sudo filament-kit update` installs it): sudo filament-kit update"]


def test_update_check_failure_line(cfg, capsys):
    class Down:
        def release(self, repo, version=None):
            raise updates.ReleaseError("cannot reach api.github.com: no route")
    assert updates.check(cfg, fetcher=Down()) == 1
    assert "error: cannot reach api.github.com: no route" in capsys.readouterr().err
    assert json.dumps(updates._read_state().get("latest")) == "null"
