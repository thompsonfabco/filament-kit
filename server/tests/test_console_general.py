"""The Settings tab's whitelist: the helper's table is the only list of what the page may write into config.json."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from test_setup_page import Helper, client, env, make, post  # noqa: F401

from filament_kit import cli, config, remote, setup_helper
from filament_kit.setup_console import general_tab

STATIC = Path(cli.__file__).parent / "setup_static"


class Mgr:
    def sync(self):
        pass

    def state(self, serial):
        return None


@pytest.fixture
def app(env):  # noqa: F811
    return make(env, Helper(), Mgr())


@pytest.fixture
def restarts(env, monkeypatch):  # noqa: F811
    seen = []
    monkeypatch.setattr(setup_helper, "_restart_kit", lambda: seen.append(True))
    return seen


@pytest.fixture
def applies(env, monkeypatch):  # noqa: F811
    seen = []
    monkeypatch.setattr(setup_helper, "_start_apply", lambda checked=False: seen.append(True))
    return seen


def _set(app, key, value):
    return post(client(app), "settings/general", {"key": key, "value": value})


@pytest.mark.parametrize("key,value,read", [
    ("server_name", "  Workshop ", lambda c: c["server_name"] == "Workshop"),
    ("model", "claude-sonnet-5-5", lambda c: c["model"] == "claude-sonnet-5-5"),
    ("reads_per_day", 25, lambda c: c["reads_per_day"] == 25),
    ("locations", ["Rack 1", " Shelf "], lambda c: c["locations"] == ["Rack 1", "Shelf"]),
    ("placement.pla_location", "Rack 2", lambda c: c["placement"]["pla_location"] == "Rack 2"),
    ("placement.box_prefix", "Box ", lambda c: c["placement"]["box_prefix"] == "Box "),
    ("placement.box_count", 0, lambda c: c["placement"]["box_count"] == 0),
    ("placement.overflow", "Floor", lambda c: c["placement"]["overflow"] == "Floor"),
    ("station.tts", "espeak", lambda c: c["station"]["tts"] == "espeak"),
    ("intake.reader", "cloud-then-local", lambda c: c["intake"]["reader"] == "cloud-then-local"),
    ("local_intake.url", "http://gpu-box.example:7915/", lambda c: c["local_intake"]["url"] == "http://gpu-box.example:7915"),
    ("local_intake.tier", "gpu", lambda c: c["local_intake"]["tier"] == "gpu"),
    ("web.printer_changes", True, lambda c: c["web"]["printer_changes"] is True),
    ("web.printer_changes", False, lambda c: c["web"]["printer_changes"] is False),
    ("setup.hosts", "Kit.Example.Test, other.example.test.", lambda c: c["setup"]["hosts"] == ["kit.example.test", "other.example.test"]),
    ("setup.hosts", [], lambda c: c["setup"]["hosts"] == []),
    ("server_name", "x" * 100, lambda c: c["server_name"] == "x" * 100),             # the accepted maximums
    ("reads_per_day", 100000, lambda c: c["reads_per_day"] == 100000),
    ("placement.box_count", 999, lambda c: c["placement"]["box_count"] == 999),
])
def test_each_key_saves(app, restarts, applies, key, value, read):
    r = _set(app, key, value)
    assert r.status_code == 200, r.text
    assert read(config.load())


@pytest.mark.parametrize("key,value", [
    ("server_name", ""), ("server_name", "x" * 101), ("server_name", "a\nb"), ("server_name", 5),
    ("model", ""), ("model", "has space"), ("model", "x/../y"),
    ("reads_per_day", 0), ("reads_per_day", -1), ("reads_per_day", "25"), ("reads_per_day", True), ("reads_per_day", 1.5),
    ("locations", []), ("locations", "Rack"), ("locations", [""]), ("locations", [5]), ("locations", ["x"] * 51),
    ("placement.box_count", -1), ("placement.box_count", 1000), ("placement.box_prefix", ""),
    ("station.tts", "other"),
    ("intake.reader", "fastest"), ("intake.reader", None),
    ("local_intake.url", "gpu-box:7915"), ("local_intake.url", "http://h:7915/v1/read"), ("local_intake.url", "file:///x"),
    ("local_intake.tier", "tpu"),
    ("web.printer_changes", "true"), ("web.printer_changes", 1), ("web.printer_changes", None), ("web.printer_changes", "yes"),
    ("setup.hosts", "192.0.2.5"), ("setup.hosts", "bad_name!"), ("setup.hosts", [5]), ("setup.hosts", ["a.example.test"] * 21),
    ("setup.hosts", 5),
    ("reads_per_day", 100001),
])
def test_a_bad_value_is_refused_and_nothing_saved(app, restarts, applies, key, value):
    before = config.load()
    assert _set(app, key, value).status_code == 400
    assert config.load() == before and not restarts and not applies


@pytest.mark.parametrize("key", ["port", "spoolman_url", "station.allow", "orders.file", "modules", "web.lan", "web.public_url",
                                 "placement", "__class__", None, 5])
def test_nothing_outside_the_table_is_written(app, key):
    before = config.load()
    assert _set(app, key, "x").status_code == 400
    assert config.load() == before


def test_it_needs_the_code(app):
    before = config.load()
    assert post(client(app), "settings/general", {"key": "server_name", "value": "x"}, code=None).status_code in (401, 403)
    assert post(client(app), "settings/general", {"key": "server_name", "value": "x"}, code="0000-0000").status_code == 403
    assert config.load() == before


def test_what_is_read_once_at_the_start_restarts_the_server(app, restarts, applies):
    assert _set(app, "reads_per_day", 5).json()["restarts"] is True
    assert _set(app, "model", "m1").json()["restarts"] is True
    assert len(restarts) == 2 and not applies


def test_what_is_read_each_time_restarts_nothing(app, restarts, applies):
    r = _set(app, "server_name", "Shop").json()
    assert r["restarts"] is False and r["applies"] is False and not restarts and not applies
    for key, value in (("intake.reader", "local"), ("local_intake.url", "http://10.0.0.5:7915"),
                       ("local_intake.tier", "cpu")):         # read on every label read
        r = _set(app, key, value).json()
        assert r["restarts"] is False and r["applies"] is False
    assert not restarts and not applies


def test_the_station_voice_goes_through_an_apply(app, restarts, applies):
    assert _set(app, "station.tts", "espeak").json()["applies"] is True
    assert applies and not restarts


def test_restart_is_no_block_and_only_the_kit(env, monkeypatch):  # noqa: F811
    monkeypatch.delenv("FK_NO_SYSTEMD")
    calls = []
    monkeypatch.setattr(setup_helper.subprocess, "run", lambda cmd, **k: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0))
    setup_helper._restart_kit()
    assert calls == [["systemctl", "restart", "--no-block", "filament-kit.service"]]


def test_the_view_needs_no_code_and_hides_the_spoolman_address(app):
    cfg = config.load()
    cfg["spoolman_url"] = "http://192.0.2.77:7912"
    config.save(cfg)
    r = client(app).get("/setup/api/settings/general")
    assert r.status_code == 200 and "192.0.2.77" not in r.text
    assert set(r.json()["values"]) == set(setup_helper.GENERAL)


def _external(monkeypatch, answers=True):
    cfg = config.load()
    cfg["modules"]["spoolman"] = False
    cfg["spoolman_url"] = "http://spoolman.example:7912"
    config.save(cfg)
    asked = []

    class Fake:
        def __init__(self, url, timeout=15):
            asked.append(url)

        def ping(self):
            if not answers:
                raise general_tab.SpoolmanError("connection refused")
            return "ok"
    monkeypatch.setattr(general_tab, "Spoolman", Fake)
    return asked


def test_spoolman_address_is_saved_after_it_answers_and_applies(app, monkeypatch, applies):
    asked = _external(monkeypatch)
    r = post(client(app), "settings/spoolman", {"url": "http://new.example:7912/"})
    assert r.status_code == 200, r.text
    assert asked == ["http://new.example:7912"] and config.load()["spoolman_url"] == "http://new.example:7912" and applies


def test_a_spoolman_that_does_not_answer_changes_nothing(app, monkeypatch, applies):
    _external(monkeypatch, answers=False)
    r = post(client(app), "settings/spoolman", {"url": "http://new.example:7912"})
    assert r.status_code == 400 and "nothing was changed" in r.json()["error"]
    assert config.load()["spoolman_url"] == "http://spoolman.example:7912" and not applies


def test_spoolman_address_is_not_probed_without_the_code(app, monkeypatch):
    asked = _external(monkeypatch)
    assert post(client(app), "settings/spoolman", {"url": "http://new.example:7912"}, code="0000-0000").status_code == 403
    assert asked == []


def test_the_helper_refuses_a_spoolman_address_with_the_module_on(env):  # noqa: F811
    with pytest.raises(setup_helper.Refused):
        setup_helper._spoolman_url({"url": "http://new.example:7912"})


def test_remote_issue_is_a_job_running_the_command():
    assert setup_helper.JOBS["remote_issue"] == ("remote", "issue") and "remote_issue" in setup_helper.BUSY


def test_firewall_text_takes_the_code_and_the_module(app, monkeypatch):
    assert post(client(app), "remote/firewall", {}).status_code == 409
    cfg = config.load()
    cfg["modules"]["remote"] = True
    config.save(cfg)
    monkeypatch.setattr(remote, "settings", lambda c: {"x": 1})
    monkeypatch.setattr(remote, "firewall_text", lambda s, p: "the rules")
    assert post(client(app), "remote/firewall", {}, code="0000-0000").status_code == 403
    assert post(client(app), "remote/firewall", {}).json() == {"text": "the rules"}


def test_the_settings_tab_has_the_cards():
    src = (STATIC / "setup.js").read_text(encoding="utf-8")
    assert "generalCard()" in src and "remoteCard()" in src
    tabs = (STATIC / "setup_tabs.js").read_text(encoding="utf-8")
    assert "function generalCard(" in tabs and "function remoteCard(" in tabs and '"remote_issue"' in tabs
