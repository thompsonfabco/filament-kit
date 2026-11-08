"""bridge.klipper.lanes: publishing the kit's slots to Moonraker lane_data (multi-tool Spool Sync, spec §6)."""
import pytest

from filament_kit.bridge import registry
from filament_kit.bridge.klipper import adapters, lanes
from filament_kit.bridge.klipper.adapters.base import SlotState, UnitState


def P(mode="auto"):
    return registry.Printer("p", family="klipper", lane_data=mode)


def test_never_on_afc_even_if_on():
    assert lanes.should_publish(P("on"), adapters.get("afc")) is False
    assert lanes.should_publish(P("on"), adapters.get("lanedata")) is False


def test_auto_single_off():
    assert lanes.should_publish(P("auto"), adapters.get("single")) is False
    assert lanes.should_publish(P("on"), adapters.get("single")) is True


def test_auto_toolchanger_on():
    assert lanes.should_publish(P("auto"), adapters.get("toolchanger")) is True
    assert lanes.should_publish(P("off"), adapters.get("toolchanger")) is False


SPOOL = {"id": 9, "filament": {"name": "PLA+ Grey", "material": "PLA", "color_hex": "8a8c8e",
                              "settings_extruder_temp": 215, "settings_bed_temp": 60, "vendor": {"name": "SUNLU"}}}


def units():
    return [UnitState(0, "L", "toolhead", [SlotState("L", spool_id=9)]),
            UnitState(1, "C1", "toolhead", [SlotState("C1", spool_id=None)])]


def test_payload_shape_matches_orca_fields():
    pl = lanes.payload(units(), {9: SPOOL}, {"L": "SUNLU PLA+ Grey @Sovol M1D 0.4 nozzle"})
    assert set(pl) == {"lane0", "lane1"}
    a = pl["lane0"]
    assert a == {"lane": "0", "material": "PLA", "color": "#8A8C8E", "nozzle_temp": 215, "bed_temp": 60,
                 "spool_id": 9, "vendor": "SUNLU", "name": "PLA+ Grey",
                 "preset": "SUNLU PLA+ Grey @Sovol M1D 0.4 nozzle", "source": "filament-kit"}
    assert pl["lane1"] == {"lane": "1", "material": "", "color": "", "nozzle_temp": None, "bed_temp": None,
                           "spool_id": None, "vendor": "", "name": "", "preset": None,
                           "source": "filament-kit"}


def test_only_changed_lanes_posted():
    posted = []

    class C:
        def db_post(self, ns, key, value):
            posted.append((ns, key, value))
    last = {}
    pl = lanes.payload(units(), {9: SPOOL}, {})
    lanes.publish(C(), pl, last)
    assert [k for _, k, _ in posted] == ["lane0", "lane1"] and posted[0][0] == "lane_data"
    posted.clear()
    lanes.publish(C(), pl, last)
    assert posted == []
    pl2 = lanes.payload([units()[0], UnitState(1, "C1", "toolhead", [SlotState("C1", spool_id=9)])], {9: SPOOL}, {})
    lanes.publish(C(), pl2, last)
    assert [k for _, k, _ in posted] == ["lane1"]


def test_lane_data_mode_saved_in_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_STATE", str(tmp_path))
    p = registry.add_klipper("M1D", "m1d.home.arpa")
    assert registry.load()[p.serial].lane_data == "auto"
    assert registry.set_lane_data(p.serial, "off") is True
    assert registry.load()[p.serial].lane_data == "off"
    with pytest.raises(ValueError):
        registry.set_lane_data(p.serial, "sometimes")


# ---- wired into KlipperFamily ------------------------------------------------------------------------------------
import json
import time
from pathlib import Path

from filament_kit.bridge.klipper import hardware as kh
from filament_kit.bridge.klipper.manager import KlipperFamily
from filament_kit.spoolman import Spoolman

DATA = Path(__file__).parent / "data" / "klipper"


def wait_for(pred, timeout=8.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.03)
    return False


@pytest.fixture
def env(tmp_path, monkeypatch):
    for name in ("etc", "state"):
        (tmp_path / name).mkdir(exist_ok=True)
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    kh._reset_cache()
    yield
    kh._reset_cache()


@pytest.fixture
def sm(spoolman_url):
    s = Spoolman(spoolman_url)
    s.ensure_fields()
    return s


def _spool(sm):
    v = sm.post("vendor", {"name": "SUNLU"})
    f = sm.post("filament", {"name": "PLA+ Grey", "vendor_id": v["id"], "material": "PLA", "color_hex": "8a8c8e",
                             "settings_extruder_temp": 215, "settings_bed_temp": 60})
    return sm.post("spool", {"filament_id": f["id"], "location": "Shelf 1"})


def test_toolchanger_load_publishes_lane_data(env, moonraker, sm):
    moonraker.objects = ["print_stats", "toolhead", "extruder", "extruder1", "heater_bed", "virtual_sdcard",
                         "gcode_macro FK_UNVERIFIED_M1D", "gcode_macro _FK_TOOL_SPOOLS"]
    moonraker.status["gcode_macro _FK_TOOL_SPOOLS"] = {f"t{i}": 0 for i in range(7)}
    pid = registry.add_klipper("M1D", moonraker.host, moonraker.port).serial
    fam = KlipperFamily(sm, backoff=(0.1, 0.4))
    fam.start()
    try:
        assert fam.wait_settled(pid, 8) == "connected"
        s = _spool(sm)
        r = fam.load(sm, pid, "C1", s["id"], False, sealed_location="Sealed stock")
        assert r["confirmed"] is True, r["problems"]
        assert wait_for(lambda: (moonraker.db.get("lane_data") or {}).get("lane1", {}).get("spool_id") == s["id"])
        lane = moonraker.db["lane_data"]["lane1"]
        assert (lane["lane"], lane["material"], lane["color"]) == ("1", "PLA", "#8A8C8E")
        assert moonraker.db["lane_data"]["lane0"]["spool_id"] is None
    finally:
        fam.stop()


def test_single_SV08_never_writes_lane_data(env, moonraker, sm):
    moonraker.objects = json.loads((DATA / "SV08-MAX" / "objects.json").read_text())["objects"]
    moonraker.status = json.loads((DATA / "SV08-MAX" / "status.json").read_text())
    moonraker.hostname = "SV08MAX"
    pid = registry.add_klipper("SV08 MAX", moonraker.host, moonraker.port).serial
    fam = KlipperFamily(sm, backoff=(0.1, 0.4))
    fam.start()
    try:
        assert fam.wait_settled(pid, 8) == "connected"
        s = _spool(sm)
        assert fam.load(sm, pid, "T0", s["id"], False, sealed_location="Sealed stock")["confirmed"] is True
        time.sleep(0.5)
        assert "lane_data" not in moonraker.db
    finally:
        fam.stop()
