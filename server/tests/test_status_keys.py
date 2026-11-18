"""EA3 (a): every status row has a stable key, the same whether the row is OK or needs a look, and unique in a run;
the watcher's Checks use it instead of guessing from the first words of the text (R475 LOW 1)."""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from test_console_core import owned  # noqa: F401
from test_setup_page import env  # noqa: F401

from filament_kit import cli, config, event_sink, events, status, watch


def _rows_with_everything(monkeypatch):
    monkeypatch.setattr(cli.Spoolman, "missing_fields", lambda self: ["nfc_id"])
    cfg = config.load()
    cfg["modules"].update(presets=True, library=True, printers=True, ai_intake=True, station=True)
    config.save(cfg)
    return status.collect(config.load())


def test_every_row_is_made_with_a_key():
    """The source: no `Row(` in status.py (or the one cli.py makes) leaves the key out."""
    for name in ("status.py", "cli.py"):
        tree = ast.parse((Path(status.__file__).parent / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) == "Row" \
                    and getattr(getattr(node.func, "value", None), "id", "") in ("", "status_rows", "status"):
                if isinstance(node.func, ast.Attribute) and node.func.value.id == "menu_ui":
                    continue
                assert any(k.arg == "key" for k in node.keywords), f"{name}:{node.lineno} Row without a key"


def test_the_keys_of_a_whole_run_are_unique_and_shaped(owned, monkeypatch):
    got = _rows_with_everything(monkeypatch)
    keys = [r.key for r in got]
    assert len(got) > 10 and all(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*(?:\.[a-z0-9-]+)+", k) for k in keys), keys
    assert len(set(keys)) == len(keys), [k for k in keys if keys.count(k) > 1]
    assert [r.key for r in _rows_with_everything(monkeypatch)] == keys          # the same run again: the same keys


def test_a_row_keeps_its_key_when_its_words_change(owned, monkeypatch):
    """OK and needs a look read differently ("Spoolman reachable" / "Spoolman not reachable"): one key."""
    ok = next(r for r in status.collect(config.load()) if r.key == "spoolman.reachable")
    assert ok.state == status.OK

    def down(self):
        raise cli.SpoolmanError("refused")
    monkeypatch.setattr(cli.Spoolman, "ping", down)
    bad = next(r for r in status.collect(config.load()) if r.key == "spoolman.reachable")
    assert bad.state == status.FAIL and bad.text.split()[:2] != ok.text.split()[:2]


@pytest.fixture
def store(env):  # noqa: F811
    return events.EventStore()


def test_two_rows_with_the_same_first_words_do_not_collide(store):
    """Before: both were `hub.spoolman-reachable`; the later one hid the other and the check flapped."""
    sink = event_sink.StoreSink(store)
    ok = status.Row(status.OK, "Spoolman reachable at http://a (v1)", group="Spoolman", key="spoolman.reachable")
    bad = status.Row(status.FAIL, "Spoolman reachable but missing fields", "fix", group="Spoolman",
                     key="spoolman.fields")
    watch.check_rows(sink, [ok, bad])
    watch.check_rows(sink, [ok, bad])
    evs = store.read(0)["events"]
    assert [e["kind"] for e in evs] == ["check.failed"]
    assert [c["condition"]["key"] for c in store.conditions()] == ["check:spoolman.fields"]
    watch.check_rows(sink, [ok, status.Row(status.OK, "Spoolman has its fields", group="Spoolman",
                                           key="spoolman.fields")])
    assert [e["kind"] for e in store.read(0)["events"]] == ["check.failed", "check.ok"] and not store.conditions()


def test_an_ok_and_a_fail_text_of_one_row_are_one_check(store):
    sink = event_sink.StoreSink(store)
    watch.check_rows(sink, [status.Row(status.FAIL, "Spoolman not reachable at x", "f", key="spoolman.reachable")])
    watch.check_rows(sink, [status.Row(status.OK, "Spoolman reachable at x (v1)", key="spoolman.reachable")])
    assert [e["kind"] for e in store.read(0)["events"]] == ["check.failed", "check.ok"]      # not feature_off


def test_a_row_that_needs_a_look_is_not_hidden_by_a_duplicate_key(store):
    sink = event_sink.StoreSink(store)
    watch.check_rows(sink, [status.Row(status.FAIL, "a", "f", key="x.y"), status.Row(status.OK, "b", key="x.y")])
    assert [e["kind"] for e in store.read(0)["events"]] == ["check.failed"]
