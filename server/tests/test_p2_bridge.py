"""P2 through the connection: the slot command for externals, module codes from get_version, a 16-unit + HT +
two-external printer through the slot test and a load, hardware errors in the printer status."""
import copy
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


def test_external_slot_command_uses_tray_id_ams_id_and_slot_id_0():
    for ext in (254, 255):
        pr = slot_setting(ext, 0, SETTING)["print"]
        assert (pr["ams_id"], pr["tray_id"], pr["slot_id"]) == (ext, ext, 0)
    pr = slot_setting(254, 0, SETTING, kind="ext")["print"]
    assert (pr["tray_id"], pr["slot_id"]) == (254, 0)


def test_ams_slot_command_unchanged():
    pr = slot_setting(3, 2, SETTING)["print"]
    assert (pr["ams_id"], pr["tray_id"]) == (3, 2) and "slot_id" not in pr
    pr = slot_setting(129, 0, SETTING, kind="ams_ht")["print"]
    assert (pr["ams_id"], pr["tray_id"]) == (129, 0) and "slot_id" not in pr


# ---------------------------------------------------------------- live rig


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_STATE", str(tmp_path / "state"))
    monkeypatch.setattr(connection, "PUSHALL_AFTER_COMMAND", 0.05)
    monkeypatch.setattr(connection, "COMMAND_TIMEOUT", 1.0)
    monkeypatch.setattr(slottest, "CONFIRM_TIMEOUT", 2.0)
    monkeypatch.setattr(loading, "CONFIRM_TIMEOUT", 1.0)


class VirPrinter(FakePrinter):
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
                    assert tray_id == ams_id and pr.get("slot_id") == 0, pr   # the H2D's external rule
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
        assert [{k: t[k] for k in keep} for t in printer.report["vir_slot"]] ==             [{k: t[k] for k in keep} for t in big_report()["vir_slot"]]                  # put back
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
