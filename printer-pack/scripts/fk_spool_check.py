#!/usr/bin/env python3
"""filament-kit printer pack: compare the sliced filament with the active Spoolman spool (print start).

Run by Klipper (RUN_SHELL_COMMAND CMD=fk_spool_check) from _FK_SPOOL_CHECK. Klipper waits for this script, so it
only reads and prints. In cancel mode it starts a detached copy of itself (`--cancel MSG`) that, once the start macro
has released the gcode queue, posts the mismatch message and then asks Moonraker to cancel the print
(/printer/print/cancel), checking each reply; a failure is logged to printer_data/logs/fk_spool_check.log. Only
characters in SAFE ever reach gcode: Spoolman names are reduced to them. Python 3.9+, standard library only.

usage: fk_spool_check.py MODE TYPE [VENDOR]
  MODE    warn | cancel  (cancel only acts on a confirmed mismatch)
  TYPE    sliced filament type, e.g. PETG ('_' for spaces and other characters; '_' alone = none)
  VENDOR  sliced filament vendor, the same way; empty or Generic skips it
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

MOONRAKER = "http://localhost:7125"
SAFE = re.compile(r"[^A-Za-z0-9 .,:()+/_-]")     # what a gcode message may hold (no quote, ; # * { } or newline)
LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
                   "logs", "fk_spool_check.log")   # <printer_data>/config/filament-kit/scripts/this -> <printer_data>/logs


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


def safe(text, limit=200):
    """`text` with every character a gcode message may not hold turned into '_' (and at most `limit` long)."""
    return SAFE.sub("_", str(text or ""))[:limit]


def log(msg):
    try:
        with open(LOG, "a") as f:
            f.write("{} {}\n".format(time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except OSError:
        pass


def post_json(path, body, timeout=120):
    req = urllib.request.Request(MOONRAKER + path, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def start_cancel(msg):
    """The detached `--cancel` copy: Klipper is waiting for this process, so the requests must outlive it."""
    subprocess.Popen([sys.executable, os.path.abspath(__file__), "--cancel", safe(msg)],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def cancel(msg, tries=3, wait=5.0):
    """Post the message, then cancel through Moonraker; every reply is checked, failures are logged."""
    try:
        post_json("/printer/gcode/script", {"script": '_FK_SPOOL_MISMATCH MSG="{}"'.format(safe(msg))})
    except Exception as exc:  # noqa: BLE001 - the cancel matters more than the message
        log("mismatch message not shown: {}".format(exc))
    for n in range(tries):
        try:
            if post_json("/printer/print/cancel", {}).get("result") == "ok":
                log("print cancelled: " + safe(msg))
                return 0
            log("cancel: unexpected reply")
        except Exception as exc:  # noqa: BLE001 - HTTPError (no print, Klipper busy), URLError ...
            log("cancel failed (try {}): {}".format(n + 1, exc))
        time.sleep(wait)
    return 1


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--cancel"]:
        return cancel(argv[1] if len(argv) > 1 else "Spool mismatch")
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
        ", ".join(problems), sliced_vendor, sliced_type, loaded)
    print("!! " + safe(msg, 400))
    if mode == "cancel":
        print("!! Cancelling the print (spool check mode cancel)")
        start_cancel(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
