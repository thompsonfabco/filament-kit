"""Newest NFC tag read across every reader the kit knows (merge-ops spec section 3).

Sources: each `tag_sources[*].url` (a lasttag service such as the SV08's, shape
`{status, nfc_id, read_at_unix, age_seconds, held?}`) plus the intake station's `/last-tag` when `station.url`
is set (reader name "station"). The newest tag is the one with the smallest age. A source that fails is skipped
for 60 s, so a dead reader costs one connect timeout a minute, not one per call (same idea as station_client).

HTTPS (R82 section 2 points 2 and 5): a source at an https address is read over a connection pinned to the fingerprint
kept for it (`station_client.pin_get("tag", origin)`, in the state folder's pins.xml). The first time the Hub reads
the address it takes the certificate it meets and keeps its fingerprint (trust on first use); from then on it accepts
no other, and the fix for a changed one is to save the tag source again (`trust`, or `forget_pin` then the next
read). The station's own `/last-tag` goes to its stored port with the certificate it said in its hello (`pairing.
station_info`), plain HTTP only while it has said none. A source that answers only on plain HTTP is read as it was
(`issues` lists it for the Checks).

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

from . import station_client, tags
from .pairing import AmbiguousStation

TIMEOUT = 4
BACKOFF = 60
TAG_FRESH = 300  # a tap or a weight this recent (seconds) belongs to the spool in the photos

MAX_BYTES = 64 * 1024  # a lasttag reply is a few hundred bytes; refuse anything past this

TEXT_NOT_HTTPS = "The tag service at {address} is not using HTTPS. Update it."
TEXT_CERT_CHANGED = "The tag service at {address} presents a different certificate than the one the Hub trusts."
TEXT_CERT_FIX = "Save the tag source again to trust the new certificate."
PIN_KIND = "tag"

_failed: dict[str, float] = {}  # url -> monotonic time of its last failure
_lock = threading.Lock()


class _WebRedirects(urllib.request.HTTPRedirectHandler):
    """Follow redirects only to http(s): urllib would also follow a 30x to ftp: (FB-078)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme.lower() not in ("http", "https"):
            raise urllib.error.HTTPError(req.full_url, code, "redirect to a non-http(s) URL refused", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_WebRedirects)


def origin(url: str) -> str:
    """`scheme://host:port` of an address, as the pin is kept under it."""
    u = urllib.parse.urlsplit(url)
    return f"{u.scheme.lower()}://{(u.hostname or '').lower()}:{u.port or (443 if u.scheme.lower() == 'https' else 80)}"


def _pinned(url: str, via_station: bool) -> tuple[str, int, str | None] | None:
    """(host, port, pin) when `url` is read over a pinned HTTPS connection, else None (plain HTTP as it was). The pin
    None is a source not seen yet: the next connection keeps what it meets."""
    u = urllib.parse.urlsplit(url)
    if not u.hostname:
        return None
    if via_station:
        try:
            info = station_client._station_info()
        except AmbiguousStation as e:       # never plain: the source fails like a dead one
            raise ValueError(str(e)) from e
        return (u.hostname, info["port"], info["fp"]) if info else None
    if u.scheme.lower() == "https":
        return u.hostname, u.port or 443, station_client.pin_get(PIN_KIND, origin(url))
    return None


def _get(url: str, via_station: bool) -> bytes:
    where = _pinned(url, via_station)
    if where is None:
        with _opener.open(url, timeout=TIMEOUT) as resp:
            if resp.status != 200:
                raise ValueError(f"status {resp.status}")
            return resp.read(MAX_BYTES + 1)
    host, port, pin = where
    u = urllib.parse.urlsplit(url)
    status, raw, seen = station_client.pinned_get(host, port, (u.path or "/") + (f"?{u.query}" if u.query else ""),
                                                  pin, TIMEOUT, cap=MAX_BYTES)
    if pin is None and not via_station and status == 200:
        station_client.pin_set(PIN_KIND, origin(url), seen)       # trust on first use
    if status != 200:
        raise ValueError(f"status {status}")
    return raw


def _fetch(url: str, via_station: bool = False) -> dict | None:
    """One source's tag, or None for no tag / a failure (which also starts its back-off)."""
    with _lock:
        failed = _failed.get(url)
    if failed is not None and time.monotonic() - failed < BACKOFF:
        return None
    try:
        raw = _get(url, via_station)
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
    st = (cfg.get("station") or {}).get("url")
    station_url = str(st).rstrip("/") + "/last-tag" if st else None
    for name, url in _sources(cfg):
        d = _fetch(url, via_station=True) if url == station_url else _fetch(url)
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


def forget_pin(url: str) -> None:
    """The owner saved the tag source again: drop its pin (the next read keeps the certificate it meets) and its
    back-off. Called where a tag source is added or saved."""
    station_client.pin_set(PIN_KIND, origin(url), None)
    with _lock:
        _failed.pop(url, None)


def trust(url: str, timeout: float = TIMEOUT) -> str | None:
    """Save-time trust on first use: forget the old pin, then meet the address and keep its certificate. The
    fingerprint kept, or None for a plain-HTTP address (nothing to pin). Raises OSError when it does not answer."""
    forget_pin(url)
    u = urllib.parse.urlsplit(url)
    if u.scheme.lower() != "https" or not u.hostname:
        return None
    fp = station_client.peer_fingerprint(u.hostname, u.port or 443, timeout)
    station_client.pin_set(PIN_KIND, origin(url), fp)
    return fp


def _loopback(host: str | None) -> bool:
    return (host or "").lower() in ("127.0.0.1", "localhost", "::1")


def issues(cfg: dict, timeout: float = 2) -> list[dict]:
    """What the Checks say about the tag sources: `{"name", "url", "kind": "plain" | "changed", "text", "fix"}`. "plain":
    a source on another machine answers only at an http address (read as it was; TEXT_NOT_HTTPS). "changed": an https
    source whose certificate is not the pinned one (TEXT_CERT_CHANGED with TEXT_CERT_FIX). One that is down, or not
    pinned yet, is no issue here."""
    out = []
    for name, url in _sources({"tag_sources": cfg.get("tag_sources")}):
        u = urllib.parse.urlsplit(url)
        address = f"{u.hostname}:{u.port}" if u.port else str(u.hostname)
        if u.scheme.lower() == "http" and not _loopback(u.hostname):
            out.append({"name": name, "url": url, "kind": "plain", "text": TEXT_NOT_HTTPS.format(address=address),
                        "fix": None})
        elif u.scheme.lower() == "https" and u.hostname:
            pin = station_client.pin_get(PIN_KIND, origin(url))
            if not pin:
                continue
            try:
                seen = station_client.peer_fingerprint(u.hostname, u.port or 443, timeout)
            except OSError:
                continue
            if seen != pin:
                out.append({"name": name, "url": url, "kind": "changed",
                            "text": TEXT_CERT_CHANGED.format(address=address), "fix": TEXT_CERT_FIX})
    return out

