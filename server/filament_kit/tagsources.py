"""Newest NFC tag read across every reader the kit knows (merge-ops spec section 3).

Sources: each `tag_sources[*].url` (a lasttag service such as the SV08's, shape
`{status, nfc_id, read_at_unix, age_seconds, held?}`) plus the intake station's `/last-tag` when `station.url`
is set (reader name "station"). The newest tag is the one with the smallest age. A source that fails is skipped
for 60 s, so a dead reader costs one connect timeout a minute, not one per call (same idea as station_client).

For a label read (ops intake.py): `fresh_unknown_tag` is the newest tag when it was tapped within TAG_FRESH
seconds (or is held on the station's panel) and no spool has it yet, i.e. the user is opening the pictured spool;
`scale_weight` is the station's last stable weight under the same freshness rule.
"""
from __future__ import annotations

import http.client
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import tags

TIMEOUT = 4
BACKOFF = 60
TAG_FRESH = 300  # a tap or a weight this recent (seconds) belongs to the spool in the photos

MAX_BYTES = 64 * 1024  # a lasttag reply is a few hundred bytes; refuse anything past this

_failed: dict[str, float] = {}  # url -> monotonic time of its last failure
_lock = threading.Lock()


class _WebRedirects(urllib.request.HTTPRedirectHandler):
    """Follow redirects only to http(s): urllib would also follow a 30x to ftp: (FB-078)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme.lower() not in ("http", "https"):
            raise urllib.error.HTTPError(req.full_url, code, "redirect to a non-http(s) URL refused", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_WebRedirects)


def _fetch(url: str) -> dict | None:
    """One source's tag, or None for no tag / a failure (which also starts its back-off)."""
    with _lock:
        failed = _failed.get(url)
    if failed is not None and time.monotonic() - failed < BACKOFF:
        return None
    try:
        with _opener.open(url, timeout=TIMEOUT) as resp:
            if resp.status != 200:
                raise ValueError(f"status {resp.status}")
            raw = resp.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError("response too large")
            data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("not an object")
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError):
        with _lock:
            _failed[url] = time.monotonic()
        return None
    with _lock:
        _failed.pop(url, None)
    return data


def _web(url: str) -> bool:
    """Only http(s): urllib would also open file: and ftp: URLs from the config (A-M2)."""
    return urllib.parse.urlsplit(url).scheme.lower() in ("http", "https")


def _sources(cfg: dict) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for s in cfg.get("tag_sources") or []:
        if isinstance(s, dict) and s.get("url") and _web(str(s["url"])):
            out.append((str(s.get("name") or s["url"]), str(s["url"])))
    st = (cfg.get("station") or {}).get("url")
    if st and _web(str(st)):
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


def fresh_unknown_tag(cfg: dict, sm) -> dict | None:
    """The newest tag `{nfc_id, age_seconds, reader, held}` if it is fresh (or held) and on no spool, else None."""
    t = latest(cfg)
    if not t or (t["age_seconds"] > TAG_FRESH and not t.get("held")):
        return None
    try:
        uid = tags.normalize_uid(str(t["nfc_id"]))
    except ValueError:
        return None
    if any(tags.stored(s) == uid for s in sm.get("spool?allow_archived=true")):
        return None
    return {"nfc_id": uid, "age_seconds": t["age_seconds"], "reader": t["reader"], "held": bool(t.get("held"))}


def scale_weight(station_state: dict | None) -> dict | None:
    """The station's `last_weight` (`{grams, age_seconds, held}` from GET /state) if it was read within TAG_FRESH
    seconds or is held on the panel (until Discard or the next scan), else None."""
    w = (station_state or {}).get("last_weight")
    if not isinstance(w, dict) or not w.get("grams"):
        return None
    age = w.get("age_seconds")
    return w if w.get("held") or (isinstance(age, (int, float)) and age <= TAG_FRESH) else None
