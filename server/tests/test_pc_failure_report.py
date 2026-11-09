"""What the server shows of a failed PC sync run: its own words for a class the PC sends, never the PC's detail."""
from __future__ import annotations

import json

import pytest

from filament_kit import cli, config, modules
from filament_kit.profiles import builds




def _heartbeat(outcome, device="dev42", at=100.0):
    d = builds._dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / builds.HEARTBEAT).write_text(json.dumps({"device_id": device, "at": at, "outcome": outcome,
                                                  "waiting_since": None, "app": None}), encoding="utf-8")


@pytest.mark.parametrize("outcome", sorted(builds.PC_FAILURES))
def test_a_reported_failure_shows_in_the_servers_own_words(outcome):
    _heartbeat(outcome)
    view = builds._pc_view("dev42", {}, [])
    assert view["failure"] == {"class": outcome, "text": builds.PC_FAILURES[outcome], "at": 100.0}


def test_another_devices_or_an_ordinary_heartbeat_is_no_failure():
    _heartbeat("error_crash", device="dev7")
    assert "failure" not in builds._pc_view("dev42", {}, [])
    _heartbeat("up_to_date")
    assert "failure" not in builds._pc_view("dev42", {}, [])


def test_an_unknown_class_shows_nothing_rather_than_its_text():
    _heartbeat("error_whatever")
    assert "failure" not in builds._pc_view("dev42", {}, [])


def test_the_words_hold_no_path_or_id():
    for text in builds.PC_FAILURES.values():
        assert "/" not in text and "\\" not in text and not any(c.isdigit() for c in text)


def test_status_prints_it(monkeypatch, capsys):
    monkeypatch.setenv("FK_NO_SYSTEMD", "1")
    c = config.load()
    c["modules"] = {n: n in {"presets", "library"} for n in modules.MODULES}
    config.save(c)
    monkeypatch.setattr(builds, "status", lambda: {"build": None, "pc": {
        "device_id": "dev42", "last_upload": None,
        "failure": {"class": "error_crash", "text": builds.PC_FAILURES["error_crash"], "at": 100.0}}})
    cli.main(["status"])
    assert builds.PC_FAILURES["error_crash"] in capsys.readouterr().out
