"""Read-only client for an intake station's `GET /state` (filament-ops station/intake_station.py).

The state comes back as the station sent it: `{"tag": {...}|null, "scale": {...}|null, "last_weight": {...}|null,
"held": ...}`. After a failure the client refuses straight away for `backoff` seconds, so a dead station costs
the app one quick 503 per call instead of a connect timeout (same policy as filament-mcp).
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
