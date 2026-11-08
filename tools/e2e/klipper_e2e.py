"""The kit-side half of tools/e2e/klipper.sh: drive the Klipper bridge against a real Klipper + Moonraker.

usage: klipper_e2e.py single|toolchanger PRINTER_DATA   (FK_STATE / FK_ETC point at scratch folders; Moonraker on
127.0.0.1:7125 and a fake Spoolman on 127.0.0.1:7912 are running). Exits non-zero on the first failed check.
"""
import json
import logging
import sys
import time
import urllib.request
from pathlib import Path

from filament_kit.bridge import registry
from filament_kit.bridge.klipper.manager import KlipperFamily
from filament_kit.spoolman import Spoolman

MR = "http://127.0.0.1:7125"


def ok(msg):
    print(f"ok: {msg}", flush=True)


def wait_for(pred, timeout=20.0, what="condition"):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return
        time.sleep(0.2)
    raise SystemExit(f"FAILED: timed out waiting for {what}")


def mr(path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(MR + path, data=data, method="POST" if data is not None else "GET",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)["result"]


def main(variant, data):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    sm = Spoolman("http://127.0.0.1:7912")
    sm.ensure_fields()
    v = sm.post("vendor", {"name": "SUNLU"})
    f = sm.post("filament", {"name": "PLA+ Grey", "vendor_id": v["id"], "material": "PLA", "color_hex": "8a8c8e"})
    a = sm.post("spool", {"filament_id": f["id"], "location": "Shelf A"})
    b = sm.post("spool", {"filament_id": f["id"], "location": "Shelf B"})
    pid = registry.add_klipper("E2E", "127.0.0.1", 7125).serial
    fam = KlipperFamily(sm, backoff=(0.5, 4.0))
    fam.start()
    try:
        state = fam.wait_settled(pid, 20)
        want = "connected" if variant == "toolchanger" else "unknown_model"
        assert state == want, f"state {state}, wanted {want}"
        ok(f"connected to real Moonraker, state {state}, verified={fam.verified(pid)}")
        st = fam.status(pid)
        assert st["gcode_state"] == "IDLE", st["gcode_state"]
        if variant == "single":
            r = fam.load(sm, pid, "T0", a["id"], False, sealed_location="Sealed stock")
            assert r["confirmed"] is True, r["problems"]
            assert mr("/server/spoolman/spool_id")["spool_id"] == a["id"]
            assert sm.get(f"spool/{a['id']}")["location"] == "E2E – T0"
            ok("load T0: SET_ACTIVE_SPOOL confirmed by Moonraker, Spoolman location moved")
            mr("/printer/gcode/script", {"script": f"SET_ACTIVE_SPOOL ID={b['id']}"})
            wait_for(lambda: sm.get(f"spool/{b['id']}")["location"] == "E2E – T0", what="follow mode")
            assert sm.get(f"spool/{a['id']}")["location"] == "Shelf A"
            ok("tap (SET_ACTIVE_SPOOL on the printer): follow mode moved the spools")
            gcodes = Path(data) / "gcodes"
            # long enough for Moonraker's history to see it print (a print of a second or two can be missed)
            (gcodes / "e2e.gcode").write_text("M117 filament-kit e2e\n" + "G4 P1000\n" * 8 + "M117 done\n")
            mr("/printer/print/start?filename=e2e.gcode", {})
            wait_for(lambda: fam.status(pid)["gcode_state"] == "FINISH", 60, "the print to finish")
            wait_for(lambda: fam.usage(pid, 1), 30, "a usage entry")
            e = fam.usage(pid, 1)[0]
            assert e["source"] == "moonraker" and e["status"] == "completed", e
            ok(f"print finished: usage entry {e['id']} ({e['status']}, spool {e['spool_id']})")
        else:
            r = fam.load(sm, pid, "C1", a["id"], False, sealed_location="Sealed stock")
            assert r["confirmed"] is True, r["problems"]
            tools = mr("/printer/objects/query?gcode_macro%20_FK_TOOL_SPOOLS")["status"]["gcode_macro _FK_TOOL_SPOOLS"]
            assert tools["t1"] == a["id"], tools
            ok("load C1: FK_SET_TOOL_SPOOL ran on real Klipper, tool 1 holds the spool")
            wait_for(lambda: (mr("/server/database/item?namespace=lane_data")["value"].get("lane1") or {})
                     .get("spool_id") == a["id"], what="lane_data")
            ok("lane_data lane1 published to Moonraker's database")
            sv = (Path(data) / "config" / "variables.cfg").read_text()
            assert "fk_t1" in sv, sv
            ok("the tool spool is saved in save_variables")
    finally:
        fam.stop()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
