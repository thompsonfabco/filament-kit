"""USB HID postal scale (DYMO M10/M25/S-series, vendor 0922) read from /dev/hidraw* (Linux only: select on the fd)."""
from __future__ import annotations

import glob
import logging
import os
import select
import time

from . import state as st

log = logging.getLogger("intake-station")

SCALE_VENDOR = "00000922"  # DYMO (hidraw uevent HID_ID is bus:vendor:product, zero-padded hex)
UNITS = {2: 1.0, 11: 28.349523125, 12: 453.59237}  # grams, ounces, pounds -> grams
STATUS = {1: "fault", 2: "zero", 3: "moving", 4: "stable", 5: "negative", 6: "overload", 7: "calibrate", 8: "re-zero"}


def find_scale() -> str | None:
    for dev in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            uevent = open(os.path.join(dev, "device/uevent")).read()
        except OSError:
            continue
        if f":{SCALE_VENDOR}:" in uevent:
            return "/dev/" + os.path.basename(dev)
    return None


def parse_report(report: bytes) -> dict | None:
    """DYMO/USB-POS scale data report: id 3, status, unit, signed power-of-ten exponent, weight (little-endian).
    `unit` is the raw unit byte; /state has always carried it."""
    if len(report) < 6 or report[0] != 3:
        return None
    exp = report[3] - 256 if report[3] > 127 else report[3]
    grams = (report[4] | report[5] << 8) * 10 ** exp * UNITS.get(report[2], 1.0)
    if report[1] == 5:
        grams = -grams
    status = STATUS.get(report[1], str(report[1]))
    return {"grams": round(grams, 1), "status": status, "unit": report[2], "stable": status == "stable"}


def scale_loop():
    while True:
        path = find_scale()
        if not path:
            time.sleep(3)
            continue
        try:
            fd = os.open(path, os.O_RDONLY)
            log.info("scale open: %s", path)
            try:
                while True:
                    if not select.select([fd], [], [], 5)[0]:
                        continue  # no change (or the scale switched itself off)
                    r = parse_report(os.read(fd, 64))
                    if not r:
                        continue
                    now = time.time()
                    with st.lock:
                        st.state.update(scale=r, scale_at=now)
                        if r["status"] == "stable" and r["grams"] >= st.MIN_GRAMS:
                            st.state.update(last=r["grams"], last_at=now)
                    st.panel_dirty.set()
            finally:
                os.close(fd)
        except OSError as e:  # unplugged
            log.warning("scale %s: %s", path, e)
            time.sleep(3)
