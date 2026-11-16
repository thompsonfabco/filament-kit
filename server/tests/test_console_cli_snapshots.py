"""The CLI's words stay as they were when `status`, `web status` and `update --check` moved onto functions that
return data (status.py, updates.check_info): the console reads the data, the terminal prints these rows. Since S5.1 the
rows come under their group's heading with a glyph and a state word; `old_rows` gives them back as the old lines."""
from __future__ import annotations

import json

import pytest

from conftest import old_rows
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
    return old_rows(capsys.readouterr().out)


def test_status_lines_on_a_server(cfg, capsys, monkeypatch):
    monkeypatch.setattr(cli.pairing, "fingerprint", lambda pem: "AB" * 32)
    (config.paths().etc / "cert.pem").write_text("x", encoding="utf-8")
    assert cli.main(["status"]) == 0
    assert lines(capsys) == [
        "--   service checks skipped (FK_NO_SYSTEMD=1)",
        f"OK   certificate present, fingerprint {' '.join(('AB' * 32)[i:i + 4] for i in range(0, 64, 4))}",
        "--   display name: Workshop",
        f"OK   Spoolman reachable at {DEAD} (v1.2.3)",
        f"--   reads used today: 0 of {cfg['reads_per_day']}",
        "--   paired devices: 0",
        "--   Filament Catalog version 7 (bundled), 1 local addition",
    ]


def test_status_lines_when_things_fail(cfg, capsys, monkeypatch):
    def down(self):
        raise cli.SpoolmanError("no answer")
    monkeypatch.setattr(cli.Spoolman, "ping", down)

    class Station:      # no real request to a made-up address: it only has to be unreachable
        def __init__(self, url, backoff=0):
            pass

        def state(self):
            raise cli.StationUnreachable("no")
    monkeypatch.setattr(cli, "StationClient", Station)
    cfg["station"] = {**cfg["station"], "url": "http://192.0.2.30:5003"}
    cfg["modules"]["ai_intake"] = True
    config.save(cfg)
    assert cli.main(["status"], client_factory=lambda k: None) == 1
    assert lines(capsys) == [
        "--   service checks skipped (FK_NO_SYSTEMD=1)",
        f"FAIL certificate missing ({config.paths().etc / 'cert.pem'})",
        "     fix: run: sudo spoolwarden cert",
        "--   display name: Workshop",
        f"FAIL Spoolman not reachable at {DEAD}: no answer",
        "     fix: check that the remote Spoolman is running and spoolman_url is right",
        f"FAIL Anthropic key missing ({config.paths().etc / 'anthropic_key'})",
        "     fix: run: sudo spoolwarden config  (option 4)",
        f"--   reads used today: 0 of {cfg['reads_per_day']}",
        "FAIL Weigh Station not answering at http://192.0.2.30:5003",
        "     fix: check the Weigh Station machine: sudo systemctl status filament-kit-station  (url http://192.0.2.30:5003)",
        "--   paired devices: 0",
        "--   Filament Catalog version 7 (bundled), 1 local addition",
    ]


def test_web_status_lines(cfg, capsys, monkeypatch):
    cfg["modules"]["web"] = True
    cfg["web"] = {**cfg["web"], "public_url": "https://printer.example.com/filament"}
    config.save(cfg)
    monkeypatch.setattr(cli, "_web_health", lambda port: (True, "ok"))
    assert cli.main(["web", "status"]) == 0
    port = cfg["web"]["port"]
    out = capsys.readouterr().out
    assert out.splitlines() == [                      # no group, so no heading and no summary
        "  + OK            Web access is on",
        "  + OK            public URL https://printer.example.com/filament",
        "                  connector: https://printer.example.com/filament/mcp   web",
        "                  app: https://printer.example.com/filament/intake",
        "  * note          sign-in passphrase not set: the Claude connector cannot sign",
        "                  in until sudo spoolwarden web passphrase",
        f"  + OK            web unit answers on 127.0.0.1:{port}",
        "                  connectors: none signed in yet",
        "                  printer slots: none; tag readers: 0 + no Weigh Station",
    ]


class Fetcher:
    def __init__(self, version):
        self.version = version

    def release(self, repo, version=None):
        return {"version": self.version, "assets": {}, "notes": "What changed."}


def raw_lines(capsys):
    return capsys.readouterr().out.splitlines()


def test_update_check_lines(cfg, capsys, monkeypatch):
    monkeypatch.setattr(updates, "current_version", lambda: "0.5.0")
    assert updates.check(cfg, fetcher=Fetcher("0.5.0")) == 0
    off = "Not checked by itself: the Automatic updates feature is off."
    assert raw_lines(capsys) == ["Installed: 0.5.0.", "Latest release: 0.5.0 (up to date).", off]
    assert updates.check(cfg, fetcher=Fetcher("0.6.0")) == 0
    assert raw_lines(capsys) == ["Installed: 0.5.0.", "Latest release: 0.6.0.", off]
    updates._write_state(held="0.6.0")
    assert updates.check(cfg, fetcher=Fetcher("0.6.0")) == 0
    lines = raw_lines(capsys)
    assert lines[:2] == ["Installed: 0.5.0.", "Latest release: 0.6.0."] and lines[-1] == off
    assert " ".join(lines[2:-1]) == ("0.6.0 was rolled back. Automatic updates skip it; sudo spoolwarden update "
                                     "installs it.")


def test_update_check_failure_line(cfg, capsys):
    class Down:
        def release(self, repo, version=None):
            raise updates.ReleaseError("cannot reach api.github.com: no route")
    assert updates.check(cfg, fetcher=Down()) == 1
    assert "Error: cannot reach api.github.com: no route" in capsys.readouterr().err
    assert json.dumps(updates._read_state().get("latest")) == "null"
