"""Read-only client for an intake station's `GET /state` (filament-ops station/intake_station.py).

The state comes back as the station sent it: `{"tag": {...}, "scale": {...}|null, "last_weight": {...}|null,
"panel": ...}` ("held" sits inside "tag" and "last_weight"). After a failure the client refuses straight away
for `backoff` seconds, so a dead station costs the app one quick 503 per call instead of a connect timeout (same
policy as filament-mcp).
"""
from __future__ import annotations

import http.client
import json
import threading
import time
import urllib.error
import urllib.request


class StationUnreachable(Exception):
    pass


class StationClient:
    def __init__(self, url: str | None, timeout: float = 3, backoff: float = 60):
        self.url = url.rstrip("/") if url else None
        self.timeout = timeout
        self.backoff = backoff
        self._failed_at: float | None = None
        self._lock = threading.Lock()

    def state(self) -> dict:
        if not self.url:
            raise StationUnreachable("no station url")
        with self._lock:
            failed = self._failed_at
        if failed is not None and time.monotonic() - failed < self.backoff:
            raise StationUnreachable("station unreachable (backing off)")
        try:
            with urllib.request.urlopen(f"{self.url}/state", timeout=self.timeout) as resp:
                if resp.status != 200:
                    raise StationUnreachable(f"station answered {resp.status}")
                data = json.loads(resp.read())
            if not isinstance(data, dict):
                raise ValueError("not an object")
        except StationUnreachable:
            self._fail()
            raise
        except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as e:
            self._fail()
            raise StationUnreachable(f"station at {self.url}: {e}") from e
        with self._lock:
            self._failed_at = None
        return data

    def _fail(self) -> None:
        with self._lock:
            self._failed_at = time.monotonic()


REACH_KEEP = 30         # seconds a reachability answer is reused: the Hub page and `devices` must not wait on a dead station each time
_reach: dict[str, tuple[float, bool]] = {}


def station_reach(devs: list[dict], url: str | None) -> dict[str, bool]:
    """{device id: does the Weigh Station answer at `url`} for the one station pairing. A station only calls the Hub when
    someone uses it, so "last seen" alone makes an idle one look dead; this asks it instead (its `GET /state`, which every
    station version has). Empty when no station address is set or the station pairing is not exactly one (which
    pairing the address belongs to would be a guess)."""
    ids = [d["id"] for d in devs if d.get("type") == "station"]
    if not url or len(ids) != 1:
        return {}
    now = time.monotonic()
    hit = _reach.get(url)
    if hit is None or now - hit[0] > REACH_KEEP:
        try:
            StationClient(url, timeout=2, backoff=0).state()
            hit = (now, True)
        except StationUnreachable:
            hit = (now, False)
        _reach[url] = hit
    return {ids[0]: hit[1]}
