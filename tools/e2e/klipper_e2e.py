"""The kit-side half of tools/e2e/klipper.sh: drive the Klipper bridge against a real Klipper + Moonraker.

usage: klipper_e2e.py single|toolchanger PRINTER_DATA   (FK_STATE / FK_ETC point at scratch folders; Moonraker on
127.0.0.1:$FK_E2E_MOONRAKER_PORT and a fake Spoolman on 127.0.0.1:$FK_E2E_SPOOLMAN_PORT are running, by default 7125
and 7912). Exits non-zero on the first failed check.
"""
import json
import logging
import os
import sys
import time
import urllib.request
from pathlib import Path

from filament_kit.bridge import registry
from filament_kit.bridge.klipper.manager import KlipperFamily
from filament_kit.spoolman import Spoolman

MR_PORT = int(os.environ.get("FK_E2E_MOONRAKER_PORT") or 7125)
SM_PORT = int(os.environ.get("FK_E2E_SPOOLMAN_PORT") or 7912)
MR = f"http://127.0.0.1:{MR_PORT}"


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


def klippy_ready():
    return mr("/printer/info")["state"] == "ready"


def console(since):
    """Console lines (Moonraker's gcode store) newer than `since` (a time.time())."""
    return [g["message"] for g in mr("/server/gcode_store?count=200")["gcode_store"] if g["time"] >= since]


def gcode(script):
    return mr("/printer/gcode/script", {"script": script})


def spool_check(sm, data, pid, fam):
    """Review A2/A3: the print-start spool check on real Klipper (gcode_shell_command: the e2e stand-in)."""
    v = sm.post("vendor", {"name": 'Silk #2 "Co"; M112'})
    f = sm.post("filament", {"name": "Red;M112", "vendor_id": v["id"], "material": "PETG", "color_hex": "ff0000"})
    odd = sm.post("spool", {"filament_id": f["id"], "location": "Shelf C"})
    gcode(f"SET_ACTIVE_SPOOL ID={odd['id']}")
    wait_for(lambda: mr("/server/spoolman/spool_id")["spool_id"] == odd["id"], what="the odd spool active")
    gcode("FK_SPOOL_CHECK MODE=warn")
    t = time.time()
    canary = Path(data) / "fk-e2e-pwn"        # in this run's folder: a file left by an earlier run cannot fail the check
    canary.unlink(missing_ok=True)
    # a quote, $( ) and backticks in the sliced vendor: before the fix shlex raised and Klipper shut down
    gcode(f'_FK_SPOOL_CHECK FILAMENT="PLA" VENDOR="Jayo\'s $(touch {canary}) `id`"')
    assert klippy_ready(), mr("/printer/info")
    out = console(t)
    assert any("Spool mismatch" in m for m in out), out
    assert not canary.exists()
    ok("spool check, warn: a vendor with a quote, $( ) and backticks; Klipper stays ready, the mismatch is shown")
    gcode("FK_SPOOL_CHECK MODE=cancel")
    gcodes = Path(data) / "gcodes"
    (gcodes / "check.gcode").write_text('_FK_SPOOL_CHECK FILAMENT="PLA" VENDOR="SUNLU"\n' + "G4 P1000\n" * 30)
    t = time.time()
    mr("/printer/print/start?filename=check.gcode", {})
    wait_for(lambda: mr("/printer/objects/query?print_stats=state")["status"]["print_stats"]["state"] == "cancelled",
             45, "the mismatched print to be cancelled")
    assert klippy_ready(), mr("/printer/info")
    out = console(t)
    err = [m for m in out if m.startswith("!! Spool mismatch")]
    assert err, out
    assert not any("Red;M112" in m or '"Co"' in m for m in out), out      # the Spoolman names, never raw
    ok("spool check, cancel: the print was cancelled through Moonraker; only safe characters reached gcode")
    gcode("FK_SPOOL_CHECK MODE=warn")
    gcode("CLEAR_ACTIVE_SPOOL")


def main(variant, data):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    sm = Spoolman(f"http://127.0.0.1:{SM_PORT}")
    sm.ensure_fields()
    v = sm.post("vendor", {"name": "SUNLU"})
    f = sm.post("filament", {"name": "PLA+ Grey", "vendor_id": v["id"], "material": "PLA", "color_hex": "8a8c8e"})
    a = sm.post("spool", {"filament_id": f["id"], "location": "Shelf A"})
    b = sm.post("spool", {"filament_id": f["id"], "location": "Shelf B"})
    pid = registry.add_klipper("E2E", "127.0.0.1", MR_PORT).serial
    fam = KlipperFamily(sm, backoff=(0.5, 4.0))
    fam.start()
    try:
        state = fam.wait_settled(pid, 20)
        want = "connected" if variant == "toolchanger" else "unknown_model"
        assert state == want, f"state {state}, wanted {want}"
        ok(f"connected to real Moonraker, state {state}, verified={fam.verified(pid)}")
        # a Moonraker restart: the bridge notices, and only this reconnect sets up again
        conn = fam._conns[pid]
        wait_for(lambda: conn.sub.connected, what="the websocket")
        setups, setup = [], conn._setup
        conn._setup = lambda: setups.append(1) or setup()
        mr("/server/restart", {})
        wait_for(lambda: not conn.sub.connected, 30, "the websocket to drop")
        wait_for(lambda: conn.sub.connected and setups and fam.state(pid) == state, 60, "the bridge to come back")
        conn._setup = setup
        ok(f"Moonraker restarted: reconnected and set up again ({len(setups)} set-up)")
        st = fam.status(pid)
        assert st["gcode_state"] == "IDLE", st["gcode_state"]
        # real Moonraker's own answer, and the kit agrees where it points: the printer here is on the kit's machine
        connected = mr("/server/spoolman/status")["spoolman_connected"]
        assert isinstance(connected, bool), connected
        want_warning = "Moonraker cannot reach its Spoolman: usage is not getting there" if not connected else None
        assert st["spoolman_warning"] == want_warning, st["spoolman_warning"]
        ok(f"Moonraker's Spoolman is the kit's; Moonraker says connected={connected}")
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
            spool_check(sm, data, pid, fam)
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
            # a tag scan. This printer has no extruder, so no tool is active: the spool just becomes the active one
            gcode(f"_FK_TAG_SPOOL ID={b['id']}")
            wait_for(lambda: mr("/server/spoolman/spool_id")["spool_id"] == b["id"], what="the tagged spool active")
            ok("a tag scan with no active tool sets the active spool")
            # what it sends when a tool is active (render_tag_macro.py, in klipper.sh), and that it lasts a tool change
            c = sm.post("spool", {"filament_id": f["id"], "location": "Shelf C"})
            gcode(f"FK_SET_TOOL_SPOOL TOOL=2 ID={c['id']}")
            gcode("_FK_TOOL_CHANGED T=2")
            wait_for(lambda: mr("/server/spoolman/spool_id")["spool_id"] == c["id"], what="tool 2's spool active")
            gcode("_FK_TOOL_CHANGED T=2")
            time.sleep(1)
            assert mr("/server/spoolman/spool_id")["spool_id"] == c["id"], "a tool change lost the spool"
            ok("a spool in the tool table lasts a tool change")
    finally:
        fam.stop()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
