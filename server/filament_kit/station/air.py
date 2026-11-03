"""Room air from the panel's BME280, or a BMP280 + AHT20 board: the panel sends `AIR <C> <RH%|-> <hPa|->` every
10 s; /state shows the latest as "air" and drops it a minute after the panel goes quiet."""
from __future__ import annotations

import time

from . import state as st


def on_air(line):
    """ "AIR <C> <RH%|-> <hPa|->" from the panel's BME280 or BMP280 + AHT20 ("-": that sensor isn't fitted)."""
    try:
        t, rh, hpa = line.decode().split()[1:4]
        air = {"temp_c": float(t), "rh": None if rh == "-" else float(rh), "hpa": None if hpa == "-" else float(hpa)}
    except ValueError:
        return
    with st.lock:
        st.state.update(air=air, air_at=time.time())
