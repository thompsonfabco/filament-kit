"""S2.1: every status row carries its group (also in `G overview`), `G state` reports the Cloud reads used today and the
limit, and one live summary line for each navigation section. The CLI's `status` words are held by
test_console_cli_snapshots.py."""
from __future__ import annotations

import json
import time

import pytest
from test_console_core import PLANTED, app, helper, owned  # noqa: F401
from test_setup_page import client, env, post  # noqa: F401

from filament_kit import config, intake_history, status
from filament_kit.setup_console import summaries

GROUPS = {"Hub", "Spoolman", "Label Reader", "Weigh Station", "Devices", "Printers", "Slicer presets", "Filament Catalog"}


def _state(app) -> dict:
    r = client(app).get("/setup/api/state")
    assert r.status_code == 200
    return r.json()


def test_every_overview_row_has_a_group_of_the_design(app, owned):
    rows = client(app).get("/setup/api/overview").json()["rows"]
    assert rows and all(r["group"] in GROUPS for r in rows)
    by = {r["text"].split(" ")[0]: r["group"] for r in rows}
    assert by["Spoolman"] == "Spoolman" and by["certificate"] == "Hub"
    assert next(r for r in rows if r["text"].startswith("paired devices"))["group"] == "Devices"
    assert next(r for r in rows if r["text"].startswith("reads used today"))["group"] == "Label Reader"
    assert next(r for r in rows if r["text"].startswith("station not answering"))["group"] == "Weigh Station"


def test_the_whole_overview_carries_the_groups_too(app, owned, helper):
    rows = post(client(app), "overview", {}).json()["rows"]
    assert rows and all(x["group"] in GROUPS for x in rows)


def test_collect_files_every_kind_of_row_under_a_group(owned, monkeypatch):
    from filament_kit import cli
    monkeypatch.setattr(cli.Spoolman, "missing_fields", lambda self: ["nfc_id"])
    cfg = config.load()
    cfg["modules"].update(presets=True, library=True, printers=True, ai_intake=True, station=True)
    config.save(cfg)
    got = status.collect(config.load())
    assert got and all(r.group in GROUPS for r in got)
    assert {r.group for r in got} >= {"Hub", "Spoolman", "Label Reader", "Devices", "Printers", "Slicer presets",
                                      "Filament Catalog"}
    assert next(r for r in got if r.action == "ensure_fields").group == "Spoolman"


def test_the_group_is_not_part_of_what_the_command_line_prints(capsys):
    assert status.print_rows([status.Row("ok", "a", group="Hub"), status.Row("fail", "b", "do c", group="Spoolman")]) is False
    assert capsys.readouterr().out == "OK   a\nFAIL b\n     fix: do c\n"


def test_state_reports_the_cloud_reads_used_and_the_limit(app, owned):
    now = time.time()
    (config.paths().state / "reads.json").write_text(json.dumps([now - 10, now - 20, now - 90000]), encoding="utf-8")
    cfg = config.load()
    cfg["reads_per_day"] = 40
    config.save(cfg)
    assert _state(app)["cloud_reads"] == {"used": 2, "limit": 40}


def test_state_has_one_summary_for_each_navigation_section(app, owned):
    sums = _state(app)["summaries"]
    assert list(sums) == ["overview", "printers", "recent", "devices", "presets", "features", "settings", "flash",
                          "updates", "logs"]
    assert all(v is None or (isinstance(v, str) and v) for v in sums.values())
    assert sums["printers"] == "1 connected · 0 offline"
    assert sums["devices"] == "0 paired · 0 Tag Readers"
    assert sums["features"] == "Setup: Custom"      # the Hub plus Web access
    cfg = config.load()
    cfg["modules"]["web"] = False
    config.save(cfg)
    assert _state(app)["summaries"]["features"] == "Setup: Hub"
    assert sums["settings"] == "9 groups"
    assert sums["logs"].endswith(" services")
    assert sums["updates"].endswith(" · up to date")
    assert sums["overview"] is None              # no Overview read yet: no check runs for `G state`
    assert sums["recent"] is None and sums["presets"] == "No build yet"


def test_the_overview_summary_follows_the_last_overview_read(app, owned):
    c = client(app)
    rows = c.get("/setup/api/overview").json()["rows"]
    bad = sum(1 for r in rows if r["state"] == "fail")
    want = f"{bad} need a look" if bad else "All checks OK"
    assert _state(app)["summaries"]["overview"] == want


def test_the_recent_and_presets_summaries(app, owned):
    cfg = config.load()
    cfg["modules"]["presets"] = True
    config.save(cfg)
    rid = intake_history.record_save([{"values": {"vendor": "Acme", "name": "Red"}, "spool_ids": [214], "filament_id": 3}],
                                     source="phone")
    assert rid
    sums = _state(app)["summaries"]
    assert sums["recent"] == "Newest: spool 214, just now"
    assert sums["presets"] == "No build yet"


def test_no_summary_holds_an_address_a_serial_or_a_secret(app, owned):
    c = client(app)
    c.get("/setup/api/overview")
    intake_history.record_save([{"values": {"vendor": "Acme", "name": "Red"}, "spool_ids": [214], "filament_id": 3}],
                               source="phone")
    sums = _state(app)["summaries"]
    text = json.dumps(sums)
    for v in (*PLANTED, "kit.local", "sk-ant", "http"):
        assert v not in text, v


@pytest.mark.parametrize("seconds,want", [(5, "just now"), (60, "1 minute ago"), (300, "5 minutes ago"),
                                          (3600, "1 hour ago"), (7200, "2 hours ago"), (86400 * 3, "3 days ago")])
def test_relative_times(seconds, want):
    assert summaries.ago(1000.0, 1000.0 + seconds) == want
