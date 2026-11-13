"""Spool Sync 2.0 against a stub `orca` module (run with any Python 3.12: `python -m pytest integrations/orca-spool-sync`)."""
import importlib.util
import sys
import types
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1] / "spool_sync.py"


class Preset:
    def __init__(self, name, vendor, ftype, user=False, notes=""):
        self.name, self.is_default, self.is_visible, self.is_compatible = name, False, True, True
        self._cfg = {"filament_vendor": f'"{vendor}"', "filament_type": f'"{ftype}"', "filament_notes": notes}
        self._user = user

    def label(self):
        return self.name

    def config_value(self, k):
        return self._cfg.get(k)

    def is_user(self):
        return self._user


class Printer:
    def config_value(self, k):
        return {"host_type": "moonraker", "print_host": "printer.home.arpa"}.get(k)


class Bundle:
    def __init__(self, presets, slots):
        self.presets, self.slots = {p.name: p for p in presets}, slots
        self.filaments = types.SimpleNamespace(preset_names=lambda: list(self.presets),
                                               find_preset=lambda n: self.presets.get(n))

    def current_printer_preset(self):
        return Printer()

    def current_filament_preset_names(self):
        return list(self.slots)


@pytest.fixture
def plugin(tmp_path, monkeypatch):
    orca = types.ModuleType("orca")
    orca.selected = []
    orca.host = types.SimpleNamespace(
        preset_bundle=lambda: orca.bundle,
        preset=types.SimpleNamespace(filament=types.SimpleNamespace(
            begin_update=lambda slot, name: orca.selected.append((slot, name)))),
        plugin=types.SimpleNamespace(storage=lambda: str(tmp_path)),
        ui=None)
    orca.pages = types.SimpleNamespace(PagesPluginCapabilityBase=object)
    orca.script = types.SimpleNamespace(ScriptPluginCapabilityBase=object)
    orca.plugin = lambda cls: cls
    orca.base = object
    monkeypatch.setitem(sys.modules, "orca", orca)
    spec = importlib.util.spec_from_file_location("spool_sync", PLUGIN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.orca_stub = orca
    return mod


SPOOLS = {
    3: {"id": 3, "filament": {"id": 31, "name": "PLA+ Grey", "material": "PLA", "color_hex": "8a8c8e",
                              "vendor": {"name": "SUNLU"}}},
    9: {"id": 9, "filament": {"id": 91, "name": "PETG Basic", "material": "PETG", "color_hex": "ff0000",
                              "vendor": {"name": "Bambu Lab"}}},
}
PRESETS = [Preset("SUNLU PLA+ @M1D", "SUNLU", "PLA", user=True), Preset("Generic PETG", "Generic", "PETG"),
           Preset("Bambu PETG Basic @M1D", "Bambu Lab", "PETG", user=True),
           Preset("Published PETG @M1D", "Other", "PETG", user=True)]


def fake_http(lanes=None, active=None):
    def http_json(url, body=None):
        if "namespace=lane_data" in url:
            if lanes is None:
                import urllib.error
                raise urllib.error.HTTPError(url, 404, "nope", {}, None)
            return {"result": {"value": lanes}}
        if url.endswith("/server/spoolman/spool_id"):
            return {"result": {"spool_id": active}}
        if url.endswith("/server/spoolman/proxy"):
            sid = int(body["path"].rsplit("/", 1)[1])
            return {"result": {"response": SPOOLS[sid]}}
        raise AssertionError(url)
    return http_json


def test_multi_slot_from_lane_data(plugin, monkeypatch):
    plugin.orca_stub.bundle = Bundle(PRESETS, ["a", "b", "c"])
    lanes = {"lane0": {"lane": "0", "spool_id": 3}, "lane1": {"lane": "1", "spool_id": None},
             "lane2": {"lane": "2", "spool_id": 9}, "lane9": {"lane": "9", "spool_id": 3}}
    monkeypatch.setattr(plugin, "http_json", fake_http(lanes))
    ok, text = plugin.run_sync()
    assert ok, text
    assert plugin.orca_stub.selected == [(1, "SUNLU PLA+ @M1D"), (3, "Bambu PETG Basic @M1D")]
    assert "Slot 2: no spool" in text


def test_published_preset_wins_when_orca_has_it(plugin, monkeypatch):
    plugin.orca_stub.bundle = Bundle(PRESETS, ["a", "b"])
    lanes = {"lane1": {"lane": "1", "spool_id": 9, "preset": "Published PETG @M1D"},
             "lane0": {"lane": "0", "spool_id": 3, "preset": "Not In Orca"}}
    monkeypatch.setattr(plugin, "http_json", fake_http(lanes))
    ok, text = plugin.run_sync()
    assert ok, text
    assert dict(plugin.orca_stub.selected) == {1: "SUNLU PLA+ @M1D", 2: "Published PETG @M1D"}


def test_single_falls_back_to_active_spool(plugin, monkeypatch):
    plugin.orca_stub.bundle = Bundle(PRESETS, ["a"])
    monkeypatch.setattr(plugin, "http_json", fake_http(None, active=3))
    ok, text = plugin.run_sync()
    assert ok and plugin.orca_stub.selected == [(1, "SUNLU PLA+ @M1D")]


def test_no_spool_anywhere(plugin, monkeypatch):
    plugin.orca_stub.bundle = Bundle(PRESETS, ["a"])
    monkeypatch.setattr(plugin, "http_json", fake_http(None, active=None))
    ok, text = plugin.run_sync()
    assert not ok and "No active spool" in text


def test_hosts_from_preset_and_file(plugin, tmp_path):
    plugin.orca_stub.bundle = Bundle(PRESETS, ["a"])
    (tmp_path / "hosts.txt").write_text("# printers\nprinter2.home.arpa\nhttp://192.0.2.10/\n")
    assert plugin.printer_hosts() == ["http://192.0.2.10", "http://printer.home.arpa", "http://printer2.home.arpa"]


def test_a_second_sync_is_refused_while_one_runs(plugin, monkeypatch):
    plugin.orca_stub.bundle = Bundle(PRESETS, ["a"])
    monkeypatch.setattr(plugin, "http_json", fake_http(None, active=3))
    assert plugin._sync_lock.acquire(blocking=False)
    try:
        assert plugin.run_sync() == (False, "A sync is already running")
    finally:
        plugin._sync_lock.release()
    assert plugin.orca_stub.selected == []
    assert plugin.run_sync()[0]      # and the lock was not left held by the refused call


def test_lanes_that_fit_no_slot_say_so(plugin, monkeypatch):
    plugin.orca_stub.bundle = Bundle(PRESETS, ["a"])
    monkeypatch.setattr(plugin, "http_json", fake_http({"lane5": {"lane": "5", "spool_id": 3}}))
    ok, text = plugin.run_sync()
    assert not ok and "lists no slot" in text and plugin.orca_stub.selected == []


def test_an_unexpected_error_comes_back_as_text_not_a_raise(plugin, monkeypatch):
    plugin.orca_stub.bundle = Bundle(PRESETS, ["a"])

    def boom(url, body=None):
        raise RuntimeError("moonraker fell over")
    monkeypatch.setattr(plugin, "http_json", boom)
    assert plugin.run_sync() == (False, "RuntimeError: moonraker fell over")
    assert plugin._sync_lock.acquire(blocking=False)      # released on the error path
    plugin._sync_lock.release()


def test_a_remembered_pick_beats_the_ranking(plugin, monkeypatch, tmp_path):
    plugin.orca_stub.bundle = Bundle(PRESETS, ["a"])
    (tmp_path / "picks.json").write_text('{"91": "Generic PETG"}')
    monkeypatch.setattr(plugin, "http_json", fake_http(None, active=9))
    ok, text = plugin.run_sync()
    assert ok and plugin.orca_stub.selected == [(1, "Generic PETG")] and "remembered pick" in text


def test_a_remembered_pick_for_a_preset_that_is_gone_is_ignored(plugin, monkeypatch, tmp_path):
    plugin.orca_stub.bundle = Bundle(PRESETS, ["a"])
    (tmp_path / "picks.json").write_text('{"91": "Deleted Preset"}')
    monkeypatch.setattr(plugin, "http_json", fake_http(None, active=9))
    ok, text = plugin.run_sync()
    assert ok and plugin.orca_stub.selected == [(1, "Bambu PETG Basic @M1D")]


@pytest.mark.parametrize("content", ["{not json", "[1, 2", ""])
def test_a_corrupt_picks_file_is_treated_as_no_picks(plugin, monkeypatch, tmp_path, content):
    plugin.orca_stub.bundle = Bundle(PRESETS, ["a"])
    (tmp_path / "picks.json").write_text(content)
    assert plugin.load_picks() == {}
    monkeypatch.setattr(plugin, "http_json", fake_http(None, active=3))
    ok, text = plugin.run_sync()
    assert ok and plugin.orca_stub.selected == [(1, "SUNLU PLA+ @M1D")]


def test_a_tie_keeps_the_current_preset_and_remembers_it(plugin, monkeypatch, tmp_path):
    twins = [Preset("SUNLU PLA A", "SUNLU", "PLA"), Preset("SUNLU PLA B", "SUNLU", "PLA")]
    plugin.orca_stub.bundle = Bundle(twins, ["SUNLU PLA B"])
    monkeypatch.setattr(plugin, "http_json", fake_http(None, active=3))
    ok, text = plugin.run_sync()
    assert ok and "kept" in text and plugin.orca_stub.selected == [(1, "SUNLU PLA B")]
    assert plugin.load_picks() == {"31": "SUNLU PLA B"}


def test_a_tie_with_no_current_choice_names_the_candidates(plugin, monkeypatch, tmp_path):
    twins = [Preset("SUNLU PLA A", "SUNLU", "PLA"), Preset("SUNLU PLA B", "SUNLU", "PLA")]
    plugin.orca_stub.bundle = Bundle(twins, ["something else"])
    monkeypatch.setattr(plugin, "http_json", fake_http(None, active=3))
    ok, text = plugin.run_sync()
    assert not ok and "2 presets match equally" in text and "SUNLU PLA A, SUNLU PLA B" in text
    assert plugin.orca_stub.selected == [] and plugin.load_picks() == {}


def test_no_compatible_preset_for_the_material_is_a_reported_failure(plugin, monkeypatch):
    plugin.orca_stub.bundle = Bundle([Preset("Only ABS", "X", "ABS")], ["a"])
    monkeypatch.setattr(plugin, "http_json", fake_http(None, active=3))
    ok, text = plugin.run_sync()
    assert not ok and "no compatible PLA filament preset" in text and plugin.orca_stub.selected == []
