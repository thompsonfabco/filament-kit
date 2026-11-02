"""Newest NFC tag read across every reader the kit knows (merge-ops spec section 3).

Sources: each `tag_sources[*].url` (a lasttag service such as the SV08's, shape
`{status, nfc_id, read_at_unix, age_seconds, held?}`) plus the intake station's `/last-tag` when `station.url`
is set (reader name "station"). The newest tag is the one with the smallest age. A source that fails is skipped
for 60 s, so a dead reader costs one connect timeout a minute, not one per call (same idea as station_client).
"""
from __future__ import annotations

import http.client
import json
import threading
import time
import urllib.error
import urllib.request

TIMEOUT = 4
BACKOFF = 60

_failed: dict[str, float] = {}  # url -> monotonic time of its last failure
_lock = threading.Lock()


def _fetch(url: str) -> dict | None:
    """One source's tag, or None for no tag / a failure (which also starts its back-off)."""
    with _lock:
        failed = _failed.get(url)
    if failed is not None and time.monotonic() - failed < BACKOFF:
        return None
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as resp:
            if resp.status != 200:
                raise ValueError(f"status {resp.status}")
            data = json.loads(resp.read())
        if not isinstance(data, dict):
            raise ValueError("not an object")
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError):
        with _lock:
            _failed[url] = time.monotonic()
        return None
    with _lock:
        _failed.pop(url, None)
    return data


def _sources(cfg: dict) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for s in cfg.get("tag_sources") or []:
        if isinstance(s, dict) and s.get("url"):
            out.append((str(s.get("name") or s["url"]), str(s["url"])))
    st = (cfg.get("station") or {}).get("url")
    if st:
        out.append(("station", str(st).rstrip("/") + "/last-tag"))
    return out


def latest(cfg: dict) -> dict | None:
    """Newest `{nfc_id, read_at_unix, age_seconds, reader, held}` over all sources, or None."""
    best: dict | None = None
    for name, url in _sources(cfg):
        d = _fetch(url)
        if not d or d.get("status") != "ok" or not d.get("nfc_id"):
            continue
        age = d.get("age_seconds")
        if not isinstance(age, (int, float)) or isinstance(age, bool):
            continue
        if best is None or age < best["age_seconds"]:
            best = {"nfc_id": d["nfc_id"], "read_at_unix": d.get("read_at_unix"),
                    "age_seconds": age, "reader": name, "held": bool(d.get("held"))}
    return best
