import copy
import json
import pathlib
import threading

import pytest

from filament_kit import profiles
from filament_kit.bridge import ams, connection, loading, registry, slottest
from filament_kit.bridge.connection import Manager, PrinterOffline, UnknownPrinter
from filament_kit.bridge.registry import Printer
from filament_kit.spoolman import Spoolman
from fakes.fake_paho import FakeClient, FakePrinter

SERIAL = "S1"
NAME = "Office H2D"
LOC_A2 = "Office H2D – AMS A2"
REPORT = {
    "gcode_state": "IDLE",
    "ams": {"ams": [
        {"id": "0", "tray": [
            {"id": "0", "tray_type": "PLA", "tray_color": "FF0000FF", "tray_info_idx": "Pa111111",
             "nozzle_temp_min": "190", "nozzle_temp_max": "230", "tray_sub_brands": ""},
            {"id": "1", "tray_type": "PETG", "tray_color": "1A1A1AFF", "tray_info_idx": "Pa735293",
             "nozzle_temp_min": "235", "nozzle_temp_max": "250", "tray_sub_brands": ""},
            {"id": "2"},
            {"id": "3"},
        ]},
        {"id": "128", "tray": [{"id": "0"}]},
    ]},
    "vt_tray": {"id": "254", "tray_type": "TPU", "tray_color": "FFFFFFFF", "tray_info_idx": "Pa444444",
                "nozzle_temp_min": "220", "nozzle_temp_max": "240", "tray_sub_brands": ""},
}


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_STATE", str(tmp_path / "state"))
    monkeypatch.setattr(connection, "PUSHALL_AFTER_COMMAND", 0.05)
    monkeypatch.setattr(connection, "COMMAND_TIMEOUT", 1.0)
    monkeypatch.setattr(loading, "CONFIRM_TIMEOUT", 1.0)


CAPTURE = json.loads((pathlib.Path(__file__).parent / "data" / "h2d_pushall.json").read_text(encoding="utf-8"))
H2D_IDLE = {**copy.deepcopy(CAPTURE["print"]), "gcode_state": "IDLE"}   # the real capture, idle; no nozzle field


@pytest.fixture
def report():
    return REPORT


@pytest.fixture
def rig(report):
    clients = []

    def factory(cid):
        c = FakeClient(cid)
        clients.append(c)
        return c
    m = Manager(client_factory=factory)
    registry.upsert(Printer(SERIAL, NAME, "O1D", "10.0.0.5", "13572468", True))
    m.sync()
    printer = FakePrinter(clients[0], report)
    clients[0].connected(0)
    assert m.wait_report(SERIAL, lambda r: "ams" in r, 2) is not None
    yield m, printer, clients[0]
    m.stop()


@pytest.fixture
def sm(spoolman_url):
    s = Spoolman(spoolman_url)
    s.ensure_fields()
    return s


@pytest.fixture
def fil(sm):
    v = sm.post("vendor", {"name": "SUNLU"})
    return sm.post("filament", {"name": "PLA+ Grey", "vendor_id": v["id"], "material": "PLA",
                                "color_hex": "8a8c8e", "density": 1.24})


def spool(sm, fil, location, prev=None):
    extra = {} if prev is None else {"prev_location": json.dumps(prev)}
    return sm.post("spool", {"filament_id": fil["id"], "location": location, "extra": extra})


PRESET = profiles.PresetRef(filament_id="P8a1b2c3", name="SUNLU PLA+ Grey @Bambu Lab H2D 0.4 nozzle",
                            nozzle_temp_min=200, nozzle_temp_max=230, filament_type="PLA", setting_id="PFUS9")


class FakePresets:
    def __init__(self, preset=PRESET):
        self.preset = preset
        self.calls = []

    def __call__(self, filament, model, nozzle_mm):
        self.calls.append((filament["id"], model, nozzle_mm))
        return self.preset


def settings(client):
    return [b["print"] for _, b in client.published if b.get("print", {}).get("command") == "ams_filament_setting"]


def at(sm, location):
    return [s for s in sm.get("spool") if s.get("location") == location]


def prev(s):
    v = (s.get("extra") or {}).get("prev_location")
    return None if v is None else json.loads(v)


def test_load_writes_the_slot_then_spoolman(rig, sm, fil):
    m, printer, client = rig
    printer.push({"nozzle_diameter": "0.6",            # not in the real capture: added here; a top-level value
                  "device": {"nozzle": {"info": [{"id": 0, "diameter": 0.2}]}}})   # wins over the per-nozzle list
    s = spool(sm, fil, "Rack 1")
    presets = FakePresets()
    r = loading.load(m, sm, SERIAL, "A2", s["id"], False, preset_for=presets)
    assert presets.calls == [(fil["id"], "O1D", 0.6)]
    assert r["nozzle_mm"] == 0.6 and r["nozzle_assumed"] is False
    (w,) = settings(client)
    assert (w["ams_id"], w["tray_id"]) == (0, 1)
    assert w["tray_info_idx"] == "P8a1b2c3" and w["tray_color"] == "8A8C8EFF" and w["tray_type"] == "PLA"
    assert (w["nozzle_temp_min"], w["nozzle_temp_max"]) == (200, 230)
    assert w["setting_id"] == "PFUS9"
    t = printer.tray(0, 1)
    assert t["tray_info_idx"] == "P8a1b2c3" and t["tray_color"] == "8A8C8EFF"
    got = sm.get(f"spool/{s['id']}")
    assert got["location"] == LOC_A2 and prev(got) == "Rack 1"
    assert r["confirmed"] is True and r["dry_run"] is False
    assert r["spool"]["id"] == s["id"] and r["spool"]["location"] == LOC_A2
    assert r["slot"] == {"label": "A2", "ams_id": 0, "tray_id": 1, "location": LOC_A2}
    assert r["preset"]["filament_id"] == "P8a1b2c3" and r["preset"]["name"] == PRESET.name
    assert r["preset"]["filament_type"] == "PLA"


def test_tray_type_is_the_preset_type(rig, sm, fil):
    """tray_type is the preset's Bambu filament_type, not the Spoolman material; temps are the preset's ints."""
    m, printer, client = rig
    s = spool(sm, fil, "Rack 1")
    ref = profiles.PresetRef(filament_id="P8a1b2c3", name="SUNLU PLA+ Grey @Bambu Lab H2D 0.4 nozzle",
                             nozzle_temp_min=190, nozzle_temp_max=230, filament_type="PLA-CF", setting_id="")
    r = loading.load(m, sm, SERIAL, "A2", s["id"], True, preset_for=FakePresets(ref))
    cmd = r["command"]
    assert cmd["tray_type"] == "PLA-CF" and cmd["setting_id"] == ""
    assert (cmd["nozzle_temp_min"], cmd["nozzle_temp_max"]) == (190, 230)
    assert type(cmd["nozzle_temp_min"]) is int and type(cmd["nozzle_temp_max"]) is int


def test_dry_run_writes_nothing(rig, sm, fil, spoolman_fake_store):
    m, printer, client = rig
    s = spool(sm, fil, "Rack 1")
    other = spool(sm, fil, LOC_A2, prev="Storage box 1")
    before = copy.deepcopy(spoolman_fake_store["spools"])
    r = loading.load(m, sm, SERIAL, "A2", s["id"], True, preset_for=FakePresets())
    assert settings(client) == [] and printer.writes == []
    assert spoolman_fake_store["spools"] == before
    assert r["dry_run"] is True and r["confirmed"] is None
    assert r["spool"]["location"] == LOC_A2 and prev(r["spool"]) == "Rack 1"
    assert r["command"]["tray_info_idx"] == "P8a1b2c3"
    assert r["moved_back"] == [{"id": other["id"], "location": "Storage box 1"}]


def test_no_preset_refuses_and_sends_nothing(rig, sm, fil, spoolman_fake_store):
    m, printer, client = rig
    s = spool(sm, fil, "Rack 1")
    before = copy.deepcopy(spoolman_fake_store["spools"])
    with pytest.raises(loading.NoPreset):
        loading.load(m, sm, SERIAL, "A2", s["id"], False, preset_for=FakePresets(None))
    with pytest.raises(loading.NoPreset):        # the real preset_for: no build yet, so no preset
        loading.load(m, sm, SERIAL, "A2", s["id"], False)
    assert settings(client) == [] and spoolman_fake_store["spools"] == before


def test_preset_for_without_a_build_returns_none():
    assert profiles.preset_for({"id": 1}, "O1D", 0.4) is None


@pytest.mark.parametrize("report", [H2D_IDLE])
@pytest.mark.parametrize("dry", [True, False])
def test_real_h2d_capture_without_nozzle_assumes_0_4(rig, sm, fil, dry):
    m, printer, client = rig
    assert "nozzle_diameter" not in CAPTURE["print"] and "nozzle" not in CAPTURE["print"].get("device", {})
    s = spool(sm, fil, "Rack 1")
    presets = FakePresets()
    r = loading.load(m, sm, SERIAL, "A3", s["id"], dry, preset_for=presets)
    assert presets.calls == [(fil["id"], "O1D", 0.4)]
    assert r["nozzle_mm"] == 0.4 and r["nozzle_assumed"] is True
    assert r["slot"]["ams_id"] == 0 and r["slot"]["tray_id"] == 2
    if not dry:
        assert r["confirmed"] is True and sm.get(f"spool/{s['id']}")["location"] == "Office H2D – AMS A3"


TWO_NOZZLES = copy.deepcopy(REPORT)
TWO_NOZZLES["device"] = {"nozzle": {"info": [{"id": 1, "diameter": "0.6"}, {"id": 0, "diameter": 0.4}]}}
TWO_NOZZLES["ams"]["ams"][0]["info"] = "1103"     # bits 8-11 = 1: unit A feeds extruder 1
TWO_NOZZLES["ams"]["ams"][1]["info"] = "0003"     # HT-A feeds extruder 0


@pytest.mark.parametrize("report", [TWO_NOZZLES])
def test_per_extruder_nozzle_follows_the_slots_unit(rig, sm, fil):
    m, printer, client = rig
    s = spool(sm, fil, "Rack 1")
    presets = FakePresets()
    a = loading.load(m, sm, SERIAL, "A2", s["id"], True, preset_for=presets)
    ht = loading.load(m, sm, SERIAL, "HT-A", s["id"], True, preset_for=presets)
    ext = loading.load(m, sm, SERIAL, "Ext-L", s["id"], True, preset_for=presets)   # unit unknown: nozzle id 0
    assert [c[2] for c in presets.calls] == [0.6, 0.4, 0.4]
    assert not (a["nozzle_assumed"] or ht["nozzle_assumed"] or ext["nozzle_assumed"])


def test_no_unit_info_uses_nozzle_0(rig, sm, fil):
    m, printer, client = rig
    printer.push({"device": {"nozzle": {"info": [{"id": 1, "diameter": 0.8}, {"id": 0, "diameter": "0.2"}]}}})
    s = spool(sm, fil, "Rack 1")
    presets = FakePresets()
    r = loading.load(m, sm, SERIAL, "A2", s["id"], True, preset_for=presets)
    assert presets.calls[0][2] == 0.2 and r["nozzle_assumed"] is False


@pytest.mark.parametrize("dry", [False, True])
def test_busy_refuses(rig, sm, fil, dry):
    m, printer, client = rig
    printer.push({"gcode_state": "RUNNING"})
    assert m.wait_report(SERIAL, lambda r: r.get("gcode_state") == "RUNNING", 2)
    s = spool(sm, fil, "Rack 1")
    with pytest.raises(slottest.PrinterBusy):
        loading.load(m, sm, SERIAL, "A2", s["id"], dry, preset_for=FakePresets())
    assert settings(client) == [] and sm.get(f"spool/{s['id']}")["location"] == "Rack 1"


def test_offline_refuses(rig, sm, fil):
    m, printer, client = rig
    client.dropped()
    s = spool(sm, fil, "Rack 1")
    with pytest.raises(PrinterOffline):
        loading.load(m, sm, SERIAL, "A2", s["id"], False, preset_for=FakePresets())
    assert sm.get(f"spool/{s['id']}")["location"] == "Rack 1"


def test_not_found(rig, sm, fil):
    m, printer, client = rig
    s = spool(sm, fil, "Rack 1")
    with pytest.raises(UnknownPrinter):
        loading.load(m, sm, "NOPE", "A2", s["id"], False, preset_for=FakePresets())
    with pytest.raises(loading.NotFound):
        loading.load(m, sm, SERIAL, "Z9", s["id"], False, preset_for=FakePresets())
    with pytest.raises(loading.NotFound):
        loading.load(m, sm, SERIAL, "A2", 9999, False, preset_for=FakePresets())
    with pytest.raises(UnknownPrinter):
        loading.unload(m, sm, "NOPE", "A2", False)
    with pytest.raises(loading.NotFound):              # nothing in that slot
        loading.unload(m, sm, SERIAL, "A2", False)
    assert settings(client) == []


def test_previous_occupants_go_back(rig, sm, fil):
    m, printer, client = rig
    s = spool(sm, fil, "Rack 1")
    a = spool(sm, fil, LOC_A2, prev="Storage box 1")
    b = spool(sm, fil, LOC_A2)                        # no prev_location: sealed stock
    keep = spool(sm, fil, "Office H2D – AMS A1", prev="Rack 1")
    r = loading.load(m, sm, SERIAL, "A2", s["id"], False, preset_for=FakePresets())
    assert sm.get(f"spool/{a['id']}")["location"] == "Storage box 1"
    assert sm.get(f"spool/{b['id']}")["location"] == "Sealed stock"
    assert prev(sm.get(f"spool/{a['id']}")) == ""
    assert sm.get(f"spool/{keep['id']}")["location"] == "Office H2D – AMS A1"
    assert [x["id"] for x in at(sm, LOC_A2)] == [s["id"]]
    assert sorted(x["id"] for x in r["moved_back"]) == sorted([a["id"], b["id"]])


def test_slot_to_slot_move_keeps_original_prev_location(rig, sm, fil):
    m, printer, client = rig
    s = spool(sm, fil, "Office H2D – AMS A1", prev="Rack 1")
    loading.load(m, sm, SERIAL, "A2", s["id"], False, preset_for=FakePresets())
    got = sm.get(f"spool/{s['id']}")
    assert got["location"] == LOC_A2 and prev(got) == "Rack 1"


def test_reload_same_spool_keeps_prev_location(rig, sm, fil):
    m, printer, client = rig
    s = spool(sm, fil, "Rack 1")
    loading.load(m, sm, SERIAL, "A2", s["id"], False, preset_for=FakePresets())
    loading.load(m, sm, SERIAL, "A2", s["id"], False, preset_for=FakePresets())
    got = sm.get(f"spool/{s['id']}")
    assert got["location"] == LOC_A2 and prev(got) == "Rack 1"


def test_unconfirmed_write_is_reported_not_raised(rig, sm, fil):
    m, printer, client = rig
    printer.frozen = True
    s = spool(sm, fil, "Rack 1")
    r = loading.load(m, sm, SERIAL, "A2", s["id"], False, preset_for=FakePresets())
    assert r["confirmed"] is False and r["problems"]
    assert sm.get(f"spool/{s['id']}")["location"] == LOC_A2


def test_refused_write_leaves_spoolman_untouched(rig, sm, fil, spoolman_fake_store):
    m, printer, client = rig
    printer.refuse[(0, 1)] = {"result": "fail", "reason": "nope"}
    s = spool(sm, fil, "Rack 1")
    before = copy.deepcopy(spoolman_fake_store["spools"])
    with pytest.raises(loading.SlotWriteFailed):
        loading.load(m, sm, SERIAL, "A2", s["id"], False, preset_for=FakePresets())
    assert spoolman_fake_store["spools"] == before


def test_external_and_ht_slots(rig, sm, fil):
    m, printer, client = rig
    s1 = spool(sm, fil, "Rack 1")
    s2 = spool(sm, fil, "Rack 1")
    assert loading.load(m, sm, SERIAL, "Ext-L", s1["id"], False, preset_for=FakePresets())["confirmed"]
    assert loading.load(m, sm, SERIAL, "HT-A", s2["id"], False, preset_for=FakePresets())["confirmed"]
    # an external holder: tray_id = ams_id, slot_id 0 (P2, the H2D rule); an AMS HT slot as before
    assert [(w["ams_id"], w["tray_id"], w.get("slot_id")) for w in settings(client)] == [(254, 254, 0), (128, 0, None)]
    assert sm.get(f"spool/{s1['id']}")["location"] == "Office H2D – AMS Ext-L"
    assert sm.get(f"spool/{s2['id']}")["location"] == "Office H2D – AMS HT-A"


def test_calibrated_slot_map_address_is_used(rig, sm, fil):
    m, printer, client = rig
    ams.save_map(SERIAL, ams.SlotMap(slots={"A2": {"ams_id": 0, "tray_id": 2, "global_id": 2}},
                                     calibrated=True))
    s = spool(sm, fil, "Rack 1")
    r = loading.load(m, sm, SERIAL, "A2", s["id"], False, preset_for=FakePresets())
    (w,) = settings(client)
    assert (w["ams_id"], w["tray_id"]) == (0, 2) and r["confirmed"] is True


def test_concurrent_loads_into_one_slot(rig, sm, fil):
    m, printer, client = rig
    fils = [fil, sm.post("filament", {"name": "PLA Red", "vendor_id": fil["vendor"]["id"], "material": "PLA",
                                      "color_hex": "CC0000"})]
    spools = [spool(sm, f, "Rack 1") for f in fils]
    errors = []
    start = threading.Barrier(2)

    def go(sid):
        try:
            start.wait()
            loading.load(m, sm, SERIAL, "A2", sid, False, preset_for=FakePresets())
        except Exception as e:  # pragma: no cover - reported below
            errors.append(e)
    ts = [threading.Thread(target=go, args=(s["id"],)) for s in spools]
    for t in ts:
        t.start()
    for t in ts:
        t.join(15)
    assert not errors
    (winner,) = at(sm, LOC_A2)
    assert printer.tray(0, 1)["tray_color"] == winner["filament"]["color_hex"].upper() + "FF"
    loser = next(s for s in spools if s["id"] != winner["id"])
    assert sm.get(f"spool/{loser['id']}")["location"] == "Rack 1"


def test_unload_moves_spool_back_without_mqtt(rig, sm, fil):
    m, printer, client = rig
    s = spool(sm, fil, LOC_A2, prev="Storage box 1")
    n = len(client.published)
    r = loading.unload(m, sm, SERIAL, "A2", False)
    assert len(client.published) == n and printer.writes == []
    got = sm.get(f"spool/{s['id']}")
    assert got["location"] == "Storage box 1" and prev(got) == ""
    assert r["spool"]["id"] == s["id"] and r["spool"]["location"] == "Storage box 1"
    assert r["slot"]["label"] == "A2" and r["slot"]["location"] == LOC_A2 and r["preset"] is None


def test_unload_without_prev_goes_to_sealed_stock_and_dry_run(rig, sm, fil, spoolman_fake_store):
    m, printer, client = rig
    s = spool(sm, fil, LOC_A2)
    before = copy.deepcopy(spoolman_fake_store["spools"])
    r = loading.unload(m, sm, SERIAL, "A2", True)
    assert spoolman_fake_store["spools"] == before and r["spool"]["location"] == "Sealed stock"
    loading.unload(m, sm, SERIAL, "A2", False)
    assert sm.get(f"spool/{s['id']}")["location"] == "Sealed stock"


def test_unload_works_while_printer_offline_or_busy(rig, sm, fil):
    m, printer, client = rig
    printer.push({"gcode_state": "RUNNING"})
    s = spool(sm, fil, LOC_A2, prev="Rack 1")
    client.dropped()
    loading.unload(m, sm, SERIAL, "A2", False)
    assert sm.get(f"spool/{s['id']}")["location"] == "Rack 1"


# ---------------------------------------------------------------- I1: one writer per printer (load vs mapping)

from filament_kit.bridge import mapping  # noqa: E402


class FakeFcntl:
    """flock semantics for one lock file, shared by every fd (the tests use one printer): `other` is what another
    process holds ('sh' / 'ex' / None)."""
    LOCK_SH, LOCK_EX, LOCK_NB, LOCK_UN = 1, 2, 4, 8

    def __init__(self):
        self.other = None
        self.mine: dict[int, int] = {}
        self.ops: list[int] = []

    def flock(self, fd, op):
        self.ops.append(op)
        if op & self.LOCK_UN:
            self.mine.pop(fd, None)
            return
        want_ex = bool(op & self.LOCK_EX)
        held = [m for f, m in self.mine.items() if f != fd] + ([self.LOCK_EX if self.other == 'ex' else self.LOCK_SH]
                                                                if self.other else [])
        if held and (want_ex or self.LOCK_EX in held):
            raise BlockingIOError("locked")
        self.mine[fd] = self.LOCK_EX if want_ex else self.LOCK_SH


def test_load_refused_while_a_mapping_job_runs(rig, sm, fil, monkeypatch):
    m, printer, c = rig
    s = spool(sm, fil, "Shelf 1")
    gate, started = threading.Event(), threading.Event()

    def st_run(manager, serial, on_step, should_stop=None):
        started.set()
        gate.wait(5)
        return slottest.SlotTestResult()
    monkeypatch.setattr(slottest, "run", st_run)
    mp = mapping.Mapper(m)
    mp.start(SERIAL)
    try:
        assert started.wait(5)
        with pytest.raises(mapping.AlreadyRunning):
            loading.load(m, sm, SERIAL, "A2", s["id"], False, preset_for=FakePresets())
        assert settings(c) == []
    finally:
        gate.set()
        mp.shutdown(5)


def test_mapping_refused_while_a_load_writes(rig, sm, fil, monkeypatch):
    m, printer, c = rig
    s = spool(sm, fil, "Shelf 1")
    in_write, gate = threading.Event(), threading.Event()
    real = m.set_slot

    def slow(*a, **k):
        in_write.set()
        gate.wait(5)
        return real(*a, **k)
    monkeypatch.setattr(m, "set_slot", slow)
    t = threading.Thread(target=loading.load, args=(m, sm, SERIAL, "A2", s["id"], False),
                         kwargs={"preset_for": FakePresets()})
    t.start()
    try:
        assert in_write.wait(5)
        with pytest.raises(mapping.AlreadyRunning) as e:
            mapping.Mapper(m).start(SERIAL)
        assert isinstance(e.value, mapping.LoadRunning) and "loaded" in e.value.message
    finally:
        gate.set()
        t.join(5)
    assert not mapping.Mapper(m).in_progress(SERIAL)


def test_two_loads_on_one_printer_do_not_refuse_each_other(rig, sm, fil):
    m, printer, c = rig
    a, b = spool(sm, fil, "Shelf 1"), spool(sm, fil, "Shelf 2")
    with mapping.load_guard(SERIAL):
        r = loading.load(m, sm, SERIAL, "A1", b["id"], False, preset_for=FakePresets())
    assert r["confirmed"] is True
    loading.load(m, sm, SERIAL, "A2", a["id"], False, preset_for=FakePresets())


def test_cross_process_load_takes_a_shared_lock(rig, sm, fil, monkeypatch):
    m, printer, c = rig
    fake = FakeFcntl()
    monkeypatch.setattr(mapping, "fcntl", fake)
    s = spool(sm, fil, "Shelf 1")
    loading.load(m, sm, SERIAL, "A2", s["id"], False, preset_for=FakePresets())
    assert fake.LOCK_SH | fake.LOCK_NB in fake.ops and fake.mine == {}
    fake.other = 'ex'                                    # `filament-kit printer map` in another process
    with pytest.raises(mapping.AlreadyRunning):
        loading.load(m, sm, SERIAL, "A1", s["id"], False, preset_for=FakePresets())
    fake.other = 'sh'                                    # a load in another process: loads go on
    loading.load(m, sm, SERIAL, "A1", s["id"], False, preset_for=FakePresets())


def test_cross_process_mapping_refused_while_another_process_loads(rig, monkeypatch):
    m, printer, c = rig
    fake = FakeFcntl()
    monkeypatch.setattr(mapping, "fcntl", fake)
    fake.other = 'sh'
    with pytest.raises(mapping.AlreadyRunning):
        mapping.Mapper(m).start(SERIAL)
    assert printer.writes == []
    assert mapping.Mapper(m).in_progress(SERIAL) is False   # a load is not a mapping job


@pytest.mark.skipif(mapping.fcntl is None, reason="cross-process lock needs fcntl (Linux)")
def test_real_flock_load_refused_while_another_process_maps(rig, sm, fil, tmp_path):
    m, printer, c = rig
    import fcntl
    s = spool(sm, fil, "Shelf 1")
    d = tmp_path / "state" / "printers" / SERIAL
    d.mkdir(parents=True, exist_ok=True)
    with open(d / mapping.LOCK_FILE, "a") as other:
        fcntl.flock(other.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(mapping.AlreadyRunning):
            loading.load(m, sm, SERIAL, "A2", s["id"], False, preset_for=FakePresets())
        fcntl.flock(other.fileno(), fcntl.LOCK_UN)
    assert settings(c) == []


@pytest.mark.skipif(mapping.fcntl is None, reason="cross-process lock needs fcntl (Linux)")
def test_real_flock_mapping_refused_while_another_process_loads(rig, tmp_path):
    m, printer, c = rig
    import fcntl
    d = tmp_path / "state" / "printers" / SERIAL
    d.mkdir(parents=True, exist_ok=True)
    with open(d / mapping.LOCK_FILE, "a") as other:
        fcntl.flock(other.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
        with pytest.raises(mapping.AlreadyRunning):
            mapping.Mapper(m).start(SERIAL)
        assert mapping.Mapper(m).in_progress(SERIAL) is False
        fcntl.flock(other.fileno(), fcntl.LOCK_UN)


def test_calibrated_external_missing_from_the_report_keeps_kind_ext(rig):
    """P3 (P2 review minor): a calibrated map's external holder the live report does not list (no vir_slot entry
    right now) is still addressed as an external of the model, never as an AMS slot."""
    ams.save_map(SERIAL, ams.SlotMap(slots={"Ext-R": {"ams_id": 255, "tray_id": 0, "global_id": 255}},
                                     calibrated=True))
    assert loading._address(SERIAL, {"ams": {"ams": []}}, "Ext-R") == (255, 0, "ext", None)
    ams.save_map(SERIAL, ams.SlotMap(slots={"A9": {"ams_id": 9, "tray_id": 0, "global_id": 36}}, calibrated=True))
    assert loading._address(SERIAL, {"ams": {"ams": []}}, "A9") == (9, 0, None, None)
