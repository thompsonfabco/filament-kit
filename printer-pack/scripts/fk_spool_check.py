#!/usr/bin/env python3
"""filament-kit printer pack: compare the sliced filament with the active Spoolman spool (print start).

Run by Klipper (RUN_SHELL_COMMAND CMD=fk_spool_check) from _FK_SPOOL_CHECK. Klipper waits for this script, so it
only reads and prints; in cancel mode a cancel is posted back to Moonraker in the background and runs once the start
macro releases the gcode queue. Python 3.9+, standard library only.

usage: fk_spool_check.py MODE TYPE [VENDOR]
  MODE    warn | cancel  (cancel only acts on a confirmed mismatch)
  TYPE    sliced filament type, e.g. PETG ('_' for spaces)
  VENDOR  sliced filament vendor, '_' for spaces; empty or Generic skips it
"""
import json
import re
import subprocess
import sys
import urllib.request

MOONRAKER = "http://localhost:7125"


def get_json(url):
    with urllib.request.urlopen(url, timeout=3) as resp:
        return json.load(resp)


def spoolman_url():
    """Moonraker's own [spoolman] server (so this always asks the Spoolman that Moonraker reports to)."""
    cfg = get_json(MOONRAKER + "/server/config")["result"]["config"]
    return cfg["spoolman"]["server"].rstrip("/")


def norm(text):
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def same(sliced, loaded):
    a, b = norm(sliced), norm(loaded)
    return a == b or a in b or b in a


def post_gcode(script):
    body = json.dumps({"script": script})
    subprocess.Popen(
        ["curl", "-s", "-m", "30", "-X", "POST", "-H", "Content-Type: application/json",
         "-d", body, MOONRAKER + "/printer/gcode/script"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    mode = argv[0] if argv else "warn"
    sliced_type = (argv[1] if len(argv) > 1 else "").replace("_", " ").strip()
    sliced_vendor = (argv[2] if len(argv) > 2 else "").replace("_", " ").strip()
    if norm(sliced_vendor) == "generic":
        sliced_vendor = ""

    try:
        spool_id = get_json(MOONRAKER + "/server/spoolman/spool_id")["result"]["spool_id"]
    except Exception as exc:
        print("Spool check skipped: Moonraker spool lookup failed ({})".format(exc))
        return 0
    if not spool_id:
        print("!! No active spool - this print's filament will not be tracked in Spoolman. "
              "Scan the spool tag or run SET_ACTIVE_SPOOL ID=n.")
        return 0
    try:
        spool = get_json("{}/api/v1/spool/{}".format(spoolman_url(), spool_id))
    except Exception as exc:
        print("!! Spool check skipped: Spoolman lookup for spool {} failed ({})".format(spool_id, exc))
        return 0
    filament = spool.get("filament") or {}
    loaded_type = filament.get("material") or ""
    loaded_vendor = (filament.get("vendor") or {}).get("name") or ""
    loaded = "spool {}: {} {} {}".format(spool_id, loaded_vendor, loaded_type, filament.get("name") or "").strip()

    problems = []
    if sliced_type and loaded_type and not same(sliced_type, loaded_type):
        problems.append("type {} vs {}".format(sliced_type, loaded_type))
    if sliced_vendor and loaded_vendor and not same(sliced_vendor, loaded_vendor):
        problems.append("vendor {} vs {}".format(sliced_vendor, loaded_vendor))
    if not problems:
        print("Spool check OK - " + loaded)
        return 0
    msg = "Spool mismatch ({}) - sliced for {} {}, loaded {}".format(
        "; ".join(problems), sliced_vendor, sliced_type, loaded)
    print("!! " + msg)
    if mode == "cancel":
        post_gcode('_FK_SPOOL_MISMATCH MSG="{}"'.format(msg.replace('"', "'")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
