"""alerts.xml: the eight switches, thresholds, the state-folder file, what is an alert (R80 section 3)."""
import os
import stat

import pytest

from filament_kit import alerts, config


@pytest.fixture(autouse=True)
def state(tmp_path, monkeypatch):
    d = tmp_path / "state"
    d.mkdir()
    monkeypatch.setenv("FK_STATE", str(d))
    alerts.reset()
    yield d
    alerts.reset()


def test_defaults_are_the_ruled_ones():
    s = alerts.load()
    assert s["types"] == {"runout": True, "paused": True, "failed": True, "printer_error": True, "finished": False,
                          "storage": True, "running_low": True, "device_down": False}
    assert (s["running_low_g"], s["last_spool_only"]) == (150, False)
    assert (s["storage_warn_percent"], s["storage_bad_percent"]) == (85, 95)
    assert list(s["types"]) == ["runout", "paused", "failed", "printer_error", "finished", "storage", "running_low",
                                "device_down"]
    assert alerts.problem() is None


def test_save_writes_xml_in_the_state_folder_and_reads_back(state):
    alerts.save({"types": {"finished": True, "runout": False}, "running_low_g": 200, "last_spool_only": True,
                 "storage_warn_percent": 80})
    f = state / "alerts.xml"
    text = f.read_text(encoding="utf-8")
    assert text.startswith("<?xml") and '<type key="finished" on="yes"' in text and 'grams="200"' in text
    assert "{" not in text                                   # XML, not JSON
    alerts.reset()
    s = alerts.load()
    assert s["types"]["finished"] is True and s["types"]["runout"] is False and s["types"]["paused"] is True
    assert (s["running_low_g"], s["last_spool_only"], s["storage_warn_percent"]) == (200, True, 80)
    assert "<device" not in text                              # no per-device entries (R80 E4)


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_the_file_has_the_state_files_mode(state):
    alerts.save({"running_low_g": 100})
    assert stat.S_IMODE((state / "alerts.xml").stat().st_mode) == 0o644


@pytest.mark.parametrize("bad", [{"running_low_g": 9}, {"running_low_g": 2001}, {"running_low_g": 150.5},
                                 {"running_low_g": True}, {"running_low_g": "150"},
                                 {"storage_warn_percent": 0}, {"storage_bad_percent": 101},
                                 {"storage_warn_percent": 96}, {"types": {"nope": True}}, {"types": {"runout": 1}},
                                 {"last_spool_only": "yes"}])
def test_save_refuses_what_is_not_allowed_and_writes_nothing(state, bad):
    with pytest.raises(alerts.AlertsError):
        alerts.save(bad)
    assert not (state / "alerts.xml").exists()
    assert alerts.load() == alerts.defaults()


def test_the_limits_of_the_threshold_are_accepted():
    assert alerts.save({"running_low_g": 10})["running_low_g"] == 10
    assert alerts.save({"running_low_g": 2000})["running_low_g"] == 2000


def test_a_file_that_cannot_be_read_gives_the_defaults_and_a_problem(state):
    (state / "alerts.xml").write_text("<alerts><type", encoding="utf-8")
    assert alerts.load() == alerts.defaults()
    kind, why = alerts.problem()
    assert kind == "unreadable" and why


def test_a_value_out_of_range_in_the_file_is_unreadable(state):
    (state / "alerts.xml").write_text('<alerts version="1"><running-low grams="5"/></alerts>', encoding="utf-8")
    assert alerts.load() == alerts.defaults()
    assert alerts.problem()[0] == "unreadable"


def test_an_unknown_type_key_in_the_file_is_skipped(state):
    (state / "alerts.xml").write_text('<alerts version="1"><type key="later" on="yes"/><type key="runout" on="no"/>'
                                      '</alerts>', encoding="utf-8")
    s = alerts.load()
    assert s["types"]["runout"] is False and alerts.problem() is None


def test_the_file_changed_by_another_process_is_read_again(state):
    alerts.save({"running_low_g": 100})
    assert alerts.load()["running_low_g"] == 100
    (state / "alerts.xml").write_bytes(alerts.to_xml({**alerts.defaults(), "running_low_g": 300}))
    assert alerts.load()["running_low_g"] == 300


def test_an_xml_entity_is_refused(state):
    (state / "alerts.xml").write_text('<!DOCTYPE a [<!ENTITY x "y">]><alerts version="1"/>', encoding="utf-8")
    assert alerts.load() == alerts.defaults() and alerts.problem()[0] == "unreadable"


@pytest.mark.skipif(os.name == "nt", reason="symbolic links need rights on Windows")
def test_a_link_in_place_of_the_file_is_not_followed(state, tmp_path):
    target = tmp_path / "elsewhere.xml"
    target.write_text("keep", encoding="utf-8")
    (state / "alerts.xml").symlink_to(target)
    s = alerts.save({"running_low_g": 120})                  # refused to write through the link: kept in memory
    assert target.read_text(encoding="utf-8") == "keep"
    assert s["running_low_g"] == 120 and alerts.problem()[0] == "unsaved"


def test_a_state_folder_that_cannot_be_written_keeps_the_settings_in_memory(state, monkeypatch):
    from filament_kit import events

    def refuse(self, f, data):
        raise PermissionError(13, "Permission denied")
    with monkeypatch.context() as m:
        m.setattr(events.EventStore, "_atomic", refuse)
        alerts.save({"running_low_g": 120})
        assert alerts.load()["running_low_g"] == 120         # the defaults of the file's absence do not win
        assert alerts.problem() == ("unsaved", "Permission denied")
    alerts.save({"running_low_g": 130})                      # the next change writes it again
    assert alerts.problem() is None and (state / "alerts.xml").exists()
    alerts.reset()
    assert alerts.load()["running_low_g"] == 130


def test_which_kinds_each_type_covers():
    assert alerts.type_of("print.runout") == "runout" and alerts.type_of("print.paused") == "paused"
    assert alerts.type_of("print.failed") == "failed" and alerts.type_of("printer.error") == "printer_error"
    assert alerts.type_of("print.finished") == "finished" and alerts.type_of("storage.low") == "storage"
    assert alerts.type_of("spool.low") == "running_low"
    assert alerts.type_of("device.down") == "device_down" == alerts.type_of("printer.offline")
    for none in ("print.started", "print.resumed", "storage.ok", "spool.ok", "usage.recorded", "spool.added",
                 "device.up", "printer.online", "check.failed", "condition.cleared"):
        assert alerts.type_of(none) is None


def test_is_alert_follows_the_switches():
    ev = {"kind": "print.finished", "data": {}}
    assert not alerts.is_alert(ev)                           # off at the start
    alerts.save({"types": {"finished": True}})
    assert alerts.is_alert(ev)
    alerts.save({"types": {"runout": False}})
    assert not alerts.is_alert({"kind": "print.runout", "data": {}})
    assert not alerts.is_alert({"kind": "print.started", "data": {}})


def test_storage_low_going_down_is_never_an_alert():
    assert alerts.is_alert({"kind": "storage.low", "data": {"percent": "96"}})
    assert not alerts.is_alert({"kind": "storage.low", "data": {"percent": "90", "direction": "down"}})


def test_only_the_last_spool_limits_the_alert_not_the_event():
    low = {"kind": "spool.low", "data": {"in_stock": "2"}}
    last = {"kind": "spool.low", "data": {"in_stock": "0"}}
    assert alerts.is_alert(low) and alerts.is_alert(last)
    alerts.save({"last_spool_only": True})
    assert not alerts.is_alert(low) and alerts.is_alert(last)


def test_keep_days_setting_in_config():
    assert config.DEFAULTS["events"] == {"keep_days": 400}
    assert config.keep_days({}) == 400
    assert config.keep_days({"events": {"keep_days": 30}}) == 30
    assert config.keep_days({"events": {"keep_days": 3650}}) == 3650
    for bad in (29, 3651, "400", 40.5, True, None, 0, -5):
        assert config.keep_days({"events": {"keep_days": bad}}) == 400
    assert config.keep_days({"events": "x"}) == 400
