#!/usr/bin/env python3
"""filament-kit printer pack: post a spool's load temperature back to Klipper as _FK_SPOOL_TEMP ID= TEMP=.

Started in the background by fk_load_temp.sh (RUN_SHELL_COMMAND CMD=fk_load_temp from _FK_LOAD_LOOKUP), so Klipper
never waits on the network. The temperature is, in order: the filament's filament-kit `nozzle_range` extra field (its
middle), Spoolman's `settings_extruder_temp`, a material default (PLA 220, PETG/PCTG/TPU 235, ABS/ASA 250), else 0
(unknown: the load macro asks). Python 3.9+, standard library only.

usage: fk_load_temp.py SPOOL_ID
"""
import json
import re
import sys
import urllib.request

MOONRAKER = "http://localhost:7125"
DEFAULTS = (("PLA", 220), ("PETG", 235), ("PCTG", 235), ("TPU", 235), ("ABS", 250), ("ASA", 250))


def get_json(url, timeout=5):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.load(resp)


def spoolman_url():
    cfg = get_json(MOONRAKER + "/server/config", 3)["result"]["config"]
    return cfg["spoolman"]["server"].rstrip("/")


def post_gcode(script):
    req = urllib.request.Request(MOONRAKER + "/printer/gcode/script", data=json.dumps({"script": script}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    urllib.request.urlopen(req, timeout=30).read()


def temp_for(filament):
    extra = filament.get("extra") or {}
    rng = extra.get("nozzle_range")
    if isinstance(rng, str):
        try:
            rng = json.loads(rng)
        except ValueError:
            rng = None
    if isinstance(rng, str):
        nums = [int(n) for n in re.findall(r"\d{3}", rng)]
        if nums:
            return (min(nums) + max(nums)) // 2
    t = filament.get("settings_extruder_temp")
    if isinstance(t, int) and 150 <= t <= 400:
        return t
    m = (filament.get("material") or "").upper()
    for prefix, temp in DEFAULTS:
        if m.startswith(prefix):
            return temp
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    spool_id = int(argv[0])
    try:
        filament = get_json("{}/api/v1/spool/{}".format(spoolman_url(), spool_id)).get("filament") or {}
        temp = temp_for(filament)
    except Exception:  # Spoolman down: unknown, the load macro asks
        temp = 0
    post_gcode("_FK_SPOOL_TEMP ID={} TEMP={}".format(spool_id, temp))
    return 0


if __name__ == "__main__":
    sys.exit(main())
