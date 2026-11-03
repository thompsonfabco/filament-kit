"""P2 through the connection: the slot command for externals, module codes from get_version, a 16-unit + HT +
two-external printer through the slot test and a load, hardware errors in the printer status."""
import copy
import json
import threading
import time

import pytest

from filament_kit import config
from filament_kit.bridge import ams, connection, layout, loading, registry, slottest
from filament_kit.bridge.connection import Manager, slot_setting
from filament_kit.bridge.registry import Printer
from fakes.fake_paho import FakeClient, FakePrinter
from test_loading import FakePresets

SERIAL = "S16"
SETTING = {"tray_info_idx": "GFL99", "tray_color": "ff0000ff", "tray_type": "PLA", "nozzle_temp_min": "190",
           "nozzle_temp_max": "230"}


def tray(i, n):
    return {"id": str(i), "tray_type": "PLA", "tray_color": f"{n:02X}{i:02X}10FF", "tray_info_idx": "GFA00",
            "nozzle_temp_min": "190", "nozzle_temp_max": "230", "tray_sub_brands": ""}


def big_report():
    units = [{"id": str(u), "tray": [tray(i, u) for i in range(4)]} for u in range(16)]
    units += [{"id": str(128 + h), "tray": [tray(0, 128 + h)]} for h in range(8)]
    return {"gcode_state": "IDLE",
            "ams": {"ams": units, "tray_now": "255", "tray_exist_bits": "ffffffff"},
            "vir_slot": [dict(tray(0, 254), id="254"), dict(tray(0, 255), id="255")]}


# ---------------------------------------------------------------- the command


def test_external_slot_command_by_kind_and_model_addressing():
    for ext in (254, 255):
        pr = slot_setting(ext, 0, SETTING, kind="ext", addressing="tray-is-ams")["print"]
        assert (pr["ams_id"], pr["tray_id"], pr["slot_id"]) == (ext, ext, 0)
        pr = slot_setting(ext, 0, SETTING, kind="ext", addressing="legacy")["print"]
        assert (pr["ams_id"], pr["tray_id"]) == (ext, 0) and "slot_id" not in pr
    pr = slot_setting(254, 0, SETTING)["print"]                     # no kind: never the external rule
    assert (pr["ams_id"], pr["tray_id"]) == (254, 0) and "slot_id" not in pr
    from filament_kit.bridge import hardware
    hw = hardware.load()
    assert hw.model("O1D").external_addressing == "tray-is-ams"
    others = ("P1S", "X1C", "A1", "O1E", "O1C", "N6", "nope")
    assert {hw.model(c).external_addressing for c in others} == {"legacy"}


def test_ams_slot_command_unchanged():
    pr = slot_setting(3, 2, SETTING, kind="ams", addressing="tray-is-ams")["print"]
    assert (pr["ams_id"], pr["tray_id"]) == (3, 2) and "slot_id" not in pr
    pr = slot_setting(129, 0, SETTING, kind="ams_ht", addressing="tray-is-ams")["print"]
    assert (pr["ams_id"], pr["tray_id"]) == (129, 0) and "slot_id" not in pr


# ---------------------------------------------------------------- live rig


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_STATE", str(tmp_path / "state"))
    monkeypatch.setattr(connection, "PUSHALL_AFTER_COMMAND", 0.05)
    monkeypatch.setattr(connection, "COMMAND_TIMEOUT", 1.0)
    monkeypatch.setattr(slottest, "CONFIRM_TIMEOUT", 2.0)
    monkeypatch.setattr(loading, "CONFIRM_TIMEOUT", 1.0)
    monkeypatch.setattr(connection, "VERSION_GAP", 0.0)


class VirPrinter(FakePrinter):
    tray_is_ams = True             # the model's external addressing (O1D); False: legacy (tray_id 0, no slot_id)
    """FakePrinter plus `vir_slot[]` holders and a get_version answer (`modules`: list of (name, hw_ver))."""

    def __init__(self, client, report, modules=None):
        super().__init__(client, report)
        self.modules = modules
        self.version_asks = 0

    def respond(self, topic, body):
        info = body.get("info")
        if isinstance(info, dict) and info.get("command") == "get_version":
            self.version_asks += 1
            if self.modules is None:
                return None
            return {"info": {"command": "get_version", "sequence_id": info.get("sequence_id"),
                             "module": [{"name": n, "hw_ver": v, "sn": "X", "sw_ver": "1"} for n, v in self.modules]}}
        return super().respond(topic, body)

    def _apply(self, key, pr):
        ams_id, tray_id = key
        with self.lock:
            for t in self.report.get("vir_slot", []):
                if str(t.get("id")) == str(ams_id):
                    if self.tray_is_ams:
                        assert tray_id == ams_id and pr.get("slot_id") == 0, pr   # the H2D's external rule
                    else:
                        assert tray_id == 0 and "slot_id" not in pr, pr          # legacy addressing
                    self._set(t, pr)
                    return {"vir_slot": copy.deepcopy(self.report["vir_slot"])}
        return super()._apply(key, pr)


def make_rig(report, model="O1D", modules=None):
    clients = []

    def factory(cid):
        c = FakeClient(cid)
        clients.append(c)
        return c
    m = Manager(client_factory=factory)
    registry.upsert(Printer(SERIAL, "Lab", model, "10.0.0.5", "13572468", True))
    m.sync()
    printer = VirPrinter(clients[0], report, modules)
    printer.tray_is_ams = model == "O1D"
    clients[0].connected(0)
    assert m.wait_report(SERIAL, lambda r: "gcode_state" in r, 2) is not None
    return m, printer, clients[0]


def test_get_version_asked_once_per_connect_and_module_codes_reach_status():
    m, printer, c = make_rig(big_report(), modules=[("ota", "N/A"), ("n3f/0", "N3F05"), ("n3s/128", "N3S05"),
                                                      ("n3f/1", "Z9Q01"), ("ahb", "AHB03")])
    try:
        assert m.wait_report(SERIAL, lambda r: layout.MODULES in r, 2) is not None
        asks = [b for t, b in c.published if b.get("info", {}).get("command") == "get_version"]
        assert len(asks) == 1
        st = m.status(SERIAL)
        by = {u["unit"]: u for u in st["ams"]}
        assert by[0]["kind"] == "ams_2pro" and by[128]["kind"] == "ams_ht"
        assert by[1]["kind"] == "generic" and any("Z9Q01" in n for n in st["notes"])
        assert [u["label"] for u in st["ams"]][-2:] == ["Ext-L", "Ext-R"]
        # a later pushall (list replaced) keeps the module codes
        c.deliver({"print": {"ams": copy.deepcopy(big_report()["ams"])}})
        assert m.status(SERIAL)["ams"][0]["kind"] == "ams_2pro"
        # reconnect: asked again
        c.dropped()
        c.connected(0)
        assert m.wait_report(SERIAL, lambda r: True, 1) is not None
        asks = [b for t, b in c.published if b.get("info", {}).get("command") == "get_version"]
        assert len(asks) == 2
    finally:
        m.stop()


def test_printer_without_get_version_answer_resolves_by_id_range():
    m, printer, c = make_rig(big_report(), modules=None)
    try:
        st = m.status(SERIAL)
        assert [u["kind"] for u in st["ams"]][:2] == ["ams", "ams"] and st["ams"][16]["kind"] == "ams_ht"
    finally:
        m.stop()


def test_slot_test_confirms_every_slot_of_16_units_ht_and_two_externals():
    m, printer, c = make_rig(big_report())
    try:
        res = slottest.run(m, SERIAL, lambda s: None)
        assert res.restored and not res.problems, res.problems
        assert len(res.confirmed) == 16 * 4 + 8 + 2
        assert res.confirmed["Ext-R"] == {"ams_id": 255, "tray_id": 0}
        assert res.confirmed["P4"] == {"ams_id": 15, "tray_id": 3}
        assert res.confirmed["HT-H"] == {"ams_id": 135, "tray_id": 0}
        ext_writes = [w for w in printer.writes if w["ams_id"] in (254, 255)]
        assert ext_writes and all(w["tray_id"] == w["ams_id"] and w["slot_id"] == 0 for w in ext_writes)
        keep = ("tray_type", "tray_color", "tray_info_idx")
        put_back = [{k: t[k] for k in keep} for t in printer.report["vir_slot"]]
        assert put_back == [{k: t[k] for k in keep} for t in big_report()["vir_slot"]]
    finally:
        m.stop()


def test_load_into_the_right_external_holder(spoolman_url):
    from filament_kit.spoolman import Spoolman
    sm = Spoolman(spoolman_url)
    sm.ensure_fields()
    v = sm.post("vendor", {"name": "Acme"})
    f = sm.post("filament", {"name": "TPU", "material": "TPU", "vendor_id": v["id"], "color_hex": "00ff00",
                             "density": 1.2, "diameter": 1.75})
    s = sm.post("spool", {"filament_id": f["id"], "location": "Rack 1"})
    m, printer, c = make_rig(big_report())
    try:
        out = loading.load(m, sm, SERIAL, "Ext-R", s["id"], False, preset_for=FakePresets())
        assert out["confirmed"], out
        w = printer.writes[-1]
        assert (w["ams_id"], w["tray_id"], w["slot_id"]) == (255, 255, 0)
        assert sm.get(f"spool/{s['id']}")["location"] == "Lab – AMS Ext-R"
    finally:
        m.stop()


def test_unit_set_change_asks_get_version_again_and_drops_codes_of_gone_units():
    m, printer, c = make_rig(big_report(), modules=[("n3f/0", "N3F05"), ("n3f/1", "N3F05")])
    try:
        assert m.wait_report(SERIAL, lambda r: layout.MODULES in r, 2) is not None

        def asks():
            return len([b for t, b in c.published if b.get("info", {}).get("command") == "get_version"])
        assert asks() == 1
        rep = big_report()
        del rep["ams"]["ams"][1]                                   # AMS B unplugged
        printer.modules = [("n3f/0", "N3F05")]
        c.deliver({"print": {"ams": copy.deepcopy(rep["ams"])}})
        assert m.wait_report(SERIAL, lambda r: "1" not in r.get(layout.MODULES, {}), 2) is not None
        assert asks() == 2
        c.deliver({"print": {"ams": copy.deepcopy(rep["ams"]), "mc_percent": 3}})   # same units: no new ask
        assert asks() == 2
    finally:
        m.stop()



def test_single_holder_printer_sends_legacy_external_command():
    rep = {"gcode_state": "IDLE", "ams": {"ams": [{"id": "0", "tray": [tray(i, 0) for i in range(4)]}]},
           "vt_tray": dict(tray(0, 254), id="254")}
    m, printer, c = make_rig(rep, model="P1S")
    try:
        res = slottest.run(m, SERIAL, lambda s: None)
        assert res.restored and "Ext" in res.confirmed, res.problems
        ext = [w for w in printer.writes if w["ams_id"] == 254]
        assert ext and all(w["tray_id"] == 0 and "slot_id" not in w for w in ext)
    finally:
        m.stop()


def test_get_version_rate_limited_with_a_trailing_ask(monkeypatch):
    monkeypatch.setattr(connection, "VERSION_GAP", 0.6)
    m, printer, c = make_rig(big_report(), modules=[("n3f/0", "N3F05")])
    try:
        def asks():
            return len([b for t, b in c.published if b.get("info", {}).get("command") == "get_version"])
        rep = big_report()
        for n in range(3):                              # three unit changes inside the gap
            r = copy.deepcopy(rep)
            del r["ams"]["ams"][n]
            c.deliver({"print": {"ams": r["ams"]}})
        assert asks() == 1                              # the connect ask; the rest waits for the gap
        deadline = time.monotonic() + 3
        while asks() < 2 and time.monotonic() < deadline:
            time.sleep(0.05)
        time.sleep(0.8)
        assert asks() == 2                              # one trailing ask for all of them
    finally:
        m.stop()


# ---------------------------------------------------------------- the old "Ext" label of the H2D's holder 254


def test_old_ext_location_shows_on_ext_l_and_is_moved_back(spoolman_url):
    from filament_kit.spoolman import Spoolman
    sm = Spoolman(spoolman_url)
    sm.ensure_fields()
    v = sm.post("vendor", {"name": "Acme"})
    f = sm.post("filament", {"name": "TPU", "material": "TPU", "vendor_id": v["id"], "color_hex": "00ff00",
                             "density": 1.2, "diameter": 1.75})
    old = sm.post("spool", {"filament_id": f["id"], "location": "Lab – AMS Ext",
                            "extra": {"prev_location": json.dumps("Rack 1")}})
    new = sm.post("spool", {"filament_id": f["id"], "location": "Rack 2"})
    rep = {"gcode_state": "IDLE", "ams": {"ams": []}, "vt_tray": dict(tray(0, 254), id="254")}
    m, printer, c = make_rig(rep)
    m._spoolman = sm
    try:
        st = m.status(SERIAL)
        (u,) = st["ams"]
        assert u["label"] == "Ext-L" and u["slots"][0]["spool"]["id"] == old["id"]
        out = loading.load(m, sm, SERIAL, "Ext-L", new["id"], False, preset_for=FakePresets())
        assert [s["id"] for s in out["moved_back"]] == [old["id"]]
        assert sm.get(f"spool/{old['id']}")["location"] == "Rack 1"
        assert sm.get(f"spool/{new['id']}")["location"] == "Lab – AMS Ext-L"
        out = loading.unload(m, sm, SERIAL, "Ext", False)          # the old label still names the slot
        assert out["slot"]["label"] == "Ext-L" and out["spool"]["id"] == new["id"]
    finally:
        m.stop()


def test_saved_map_key_ext_is_read_as_ext_l():
    registry.upsert(Printer(SERIAL, "Lab", "O1D", "10.0.0.5", "13572468", True))
    ams.save_map(SERIAL, ams.SlotMap(slots={"A1": {"ams_id": 0, "tray_id": 0, "global_id": 0},
                                            "Ext": {"ams_id": 254, "tray_id": 0, "global_id": 254}},
                                     calibrated=True, observe=False))
    m = ams.load_map(SERIAL)
    assert set(m.slots) == {"A1", "Ext-L"}
    from filament_kit.bridge import usage
    assert usage._labels(m)[254] == "Ext-L"                       # usage decodes 254 to Ext-L
    registry.upsert(Printer(SERIAL, "Lab", "P1S", "10.0.0.5", "13572468", True))
    assert set(ams.load_map(SERIAL).slots) == {"A1", "Ext"}       # a single-holder printer keeps "Ext"


def test_get_version_while_disconnected_does_not_use_the_rate_limit_slot(monkeypatch):
    """P3 (P2 review minor): an ask made while the printer is not connected sends nothing and must not take the
    VERSION_GAP slot, or the ask at the next connect would be delayed (or lost)."""
    monkeypatch.setattr(connection, "VERSION_GAP", 30.0)
    m, printer, c = make_rig(big_report(), modules=[("n3f/0", "N3F05")])
    try:
        conn = m._conns[SERIAL]

        def asks():
            return len([b for t, b in c.published if b.get("info", {}).get("command") == "get_version"])
        assert asks() == 1
        conn._version_at = None              # as if the gap had passed
        conn._state = "offline"
        conn.request_version()               # disconnected: nothing sent, no slot taken
        assert asks() == 1 and conn._version_at is None and conn._version_timer is None
        conn._state = "connected"
        conn.request_version()               # back: asked at once
        assert asks() == 2
    finally:
        m.stop()
