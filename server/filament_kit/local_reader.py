"""The local label reader (the `local_intake` module): a separate program, on this machine or another one on the
network, that reads spool label photos without the cloud. The kit only talks to it over HTTP; this file is the
whole of that conversation, so a change to the reader's API changes this file and nothing else.

    GET  <url>/v1/health                       -> {"status": "ok", "api_version": 1, "version": "...",
                                                   "tiers": {"cpu": true, "gpu": false}}
    POST <url>/v1/read?format=filament-kit     <- {"api_version", "tier", "hint", "images_b64", "filaments",
                                                   "vendors", "tag", "orders"}
                                               -> {"items": [...], "questions": [...], "confidence": 0..1,
                                                   "unsure": bool, "tier": "cpu"|"gpu", "usage": {...}}

The items have the cloud reader's shape (intake.SCHEMA); intake.py does all post-processing for both readers.
`local_intake.url` may name another machine (a DNS name is fine): the GPU tier wants a GPU the kit server usually
lacks. Protecting that link is the owner's choice; nothing here sends a secret.
"""
from __future__ import annotations

import base64
import http.client
import json
import socket
import urllib.error
import urllib.request
from urllib.parse import urlparse

DEFAULT_URL = "http://127.0.0.1:7915"
API_VERSIONS = (1, 1)            # the reader API versions this kit speaks (min, max)
TIERS = ("auto", "cpu", "gpu")
MIN_CONFIDENCE = 0.78            # below this a local answer is "unsure" (the reader's own escalation threshold)
TIMEOUT = 60                     # seconds for one read: the GPU tier on a cold start is slow
HEALTH_TIMEOUT = 5
CONNECT_TIMEOUT = 3              # a reader that is down (or a machine that is off) is known in seconds, not after TIMEOUT


class LocalReaderError(Exception):
    """The local reader could not answer. `code`: unreachable | bad_answer | version | refused."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def settings(cfg: dict) -> dict:
    """`local_intake` settings with defaults and sane bounds."""
    raw = cfg.get("local_intake") if isinstance(cfg.get("local_intake"), dict) else {}
    url = str(raw.get("url") or DEFAULT_URL).strip().rstrip("/")
    tier = str(raw.get("tier") or "auto").lower()
    try:
        conf = float(raw.get("min_confidence") if raw.get("min_confidence") is not None else MIN_CONFIDENCE)
    except (TypeError, ValueError):
        conf = MIN_CONFIDENCE
    try:
        timeout = int(raw.get("timeout") or TIMEOUT)
    except (TypeError, ValueError):
        timeout = TIMEOUT
    return {"url": url, "tier": tier if tier in TIERS else "auto", "min_confidence": min(max(conf, 0.0), 1.0),
            "timeout": min(max(timeout, 5), 600)}


def check_url(url: str) -> str | None:
    """Error text for a bad `local_intake.url`, or None."""
    u = urlparse(str(url or "").strip())
    if u.scheme not in ("http", "https") or not u.hostname:
        return "Give the reader's address, e.g. http://127.0.0.1:7915 or http://gpu-box.example:7915"
    if u.path not in ("", "/") or u.query or u.fragment:
        return "Give only the reader's address (scheme, host, port), no path"
    return None


def _reachable(url: str) -> None:
    """Connect once with a short timeout: an address that drops packets would otherwise hold a read for `timeout`."""
    u = urlparse(url)
    try:
        socket.create_connection((u.hostname, u.port or (443 if u.scheme == "https" else 80)),
                                 timeout=CONNECT_TIMEOUT).close()
    except OSError as e:
        raise LocalReaderError("unreachable", f"the local reader at {u.netloc} does not answer ({e})") from None


def _request(url: str, *, body: dict | None, timeout: float) -> dict:
    _reachable(url)
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="GET" if body is None else "POST",
                                 headers={"Accept": "application/json",
                                          **({"Content-Type": "application/json"} if body is not None else {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:       # noqa: S310 - the owner's own address
            raw = resp.read()
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = str((json.loads(e.read().decode("utf-8")) or {}).get("error") or "")[:200]
        except (ValueError, OSError, AttributeError):
            pass
        code = "refused" if e.code in (400, 413, 415, 422) else "bad_answer"
        raise LocalReaderError(code, f"the local reader answered HTTP {e.code}" + (f": {detail}" if detail else "")) \
            from None
    except (urllib.error.URLError, http.client.HTTPException, OSError) as e:
        reason = getattr(e, "reason", None) or e
        raise LocalReaderError("unreachable", f"the local reader at {urlparse(url).netloc} does not answer "
                                              f"({reason})") from None
    try:
        out = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise LocalReaderError("bad_answer", "the local reader's answer is not JSON") from None
    if not isinstance(out, dict):
        raise LocalReaderError("bad_answer", "the local reader's answer is not an object")
    return out


def _version_ok(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and API_VERSIONS[0] <= v <= API_VERSIONS[1]


def health(cfg: dict, timeout: float = HEALTH_TIMEOUT) -> dict:
    """{ok, url, api_version, version, tiers, error}: never raises."""
    s = settings(cfg)
    out = {"ok": False, "url": s["url"], "api_version": None, "version": None, "tiers": {}, "error": None}
    try:
        h = _request(f"{s['url']}/v1/health", body=None, timeout=timeout)
    except LocalReaderError as e:
        out["error"] = str(e)
        return out
    out.update(api_version=h.get("api_version"), version=h.get("version"),
               tiers={k: bool(v) for k, v in (h.get("tiers") or {}).items()} if isinstance(h.get("tiers"), dict)
               else {})
    if h.get("status") != "ok":
        out["error"] = f"the local reader is not ready ({h.get('status')!r})"
    elif not _version_ok(h.get("api_version")):
        out["error"] = (f"the local reader speaks API version {h.get('api_version')!r}; this kit speaks "
                        f"{API_VERSIONS[0]}..{API_VERSIONS[1]}: update the one that is older")
    else:
        out["ok"] = True
    return out


def catalog(fils: list[dict], vendors: list[dict], line_of) -> tuple[list[dict], list[dict]]:
    """What the reader gets of Spoolman: only the fields the cloud reader's catalog block has (no comments, no
    prices, no spool data)."""
    fl = [{"id": f.get("id"), "vendor": (f.get("vendor") or {}).get("name"), "name": f.get("name"),
           "material": f.get("material"), "weight": f.get("weight"), "spool_weight": f.get("spool_weight"),
           "density": f.get("density"), "color_hex": f.get("color_hex"), "line": line_of(f) or None}
          for f in fils]
    vl = [{"name": v.get("name"), "empty_spool_weight": v.get("empty_spool_weight")} for v in vendors]
    return fl, vl


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0


# a field the reader left out gets this, and its name goes into the item's `estimates` (as the cloud reader marks
# its own guesses), so the result screen says it was not read
GUESS = {"net": 1000, "tare": 200, "density": 1.24}
DENSITY = {"PLA": 1.24, "PETG": 1.27, "ABS": 1.04, "ASA": 1.07, "TPU": 1.21, "PC": 1.20, "PA": 1.14}


def _complete(it: dict, vendors: list[dict], n_photos: int) -> None:
    """Give a local item every field of the cloud reader's schema (intake.ITEM_PROPS), so the app, the station and
    the post-processing see one shape whichever reader answered."""
    for k in ("vendor", "name", "material"):
        it[k] = str(it.get(k) or "").strip() or ("Unknown" if k == "vendor" else "")
    est = [str(x) for x in it.get("estimates") or [] if isinstance(x, (str, int, float))]
    for k, default in GUESS.items():
        if not _num(it.get(k)):
            if k == "tare":
                v = next((x.get("empty_spool_weight") for x in vendors
                          if str(x.get("name") or "").lower() == it["vendor"].lower()), None)
                default = v if _num(v) else default
            elif k == "density":
                default = DENSITY.get(it["material"].upper().split()[0] if it["material"] else "", default)
            it[k] = default
            est.append(k)
    it["estimates"] = est
    it["count"] = it.get("count") if isinstance(it.get("count"), int) and not isinstance(it["count"], bool) else 1
    if not isinstance(it.get("photos"), list):
        it["photos"] = list(range(n_photos))
    for k in ("existing_filament_id", "nozzle", "bed"):
        if not isinstance(it.get(k), int) or isinstance(it.get(k), bool):
            it[k] = None
    for k in ("color_hex", "nozzle_range", "bed_range", "lot"):
        if not isinstance(it.get(k), str):
            it[k] = None
    for k in ("note", "line"):
        if not isinstance(it.get(k), str):
            it[k] = ""
    if not isinstance(it.get("sealed"), bool):
        it["sealed"], it["sealed_reason"] = True, "unsure"
    elif not isinstance(it.get("sealed_reason"), str):
        it["sealed_reason"] = ""


def read(cfg: dict, images: list[bytes], hint: str, fils: list[dict], vendors: list[dict], tag: dict | None,
         orders: list[dict] | None) -> dict:
    """One read. Returns {items, questions, confidence, unsure, tier, usage}; raises LocalReaderError."""
    s = settings(cfg)
    body = {"api_version": API_VERSIONS[1], "tier": s["tier"], "hint": hint or "",
            "images_b64": [base64.standard_b64encode(b).decode("ascii") for b in images],
            "filaments": fils, "vendors": vendors, "tag": tag, "orders": orders}
    out = _request(f"{s['url']}/v1/read?format=filament-kit", body=body, timeout=s["timeout"])
    if "api_version" in out and not _version_ok(out["api_version"]):
        raise LocalReaderError("version", f"the local reader answered with API version {out['api_version']!r}; "
                                          f"this kit speaks {API_VERSIONS[0]}..{API_VERSIONS[1]}")
    items = out.get("items")
    if not isinstance(items, list) or not all(isinstance(it, dict) for it in items):
        raise LocalReaderError("bad_answer", "the local reader's answer has no item list")
    for it in items:
        _complete(it, vendors, len(images))
    conf = out.get("confidence")
    if not isinstance(conf, (int, float)) or isinstance(conf, bool):
        per = [it.get("confidence") for it in items
               if isinstance(it.get("confidence"), (int, float)) and not isinstance(it.get("confidence"), bool)]
        conf = min(per) if per else None
    conf = None if conf is None else round(min(max(float(conf), 0.0), 1.0), 3)
    unsure = (out.get("unsure") is True or not items or conf is None or conf < s["min_confidence"]
              or any(it["vendor"].lower() == "unknown" for it in items))
    q = out.get("questions")
    tier = str(out.get("tier") or s["tier"])
    usage = out.get("usage") if isinstance(out.get("usage"), dict) else {}
    return {"items": items, "questions": [str(x) for x in q] if isinstance(q, list) else [],
            "confidence": conf, "unsure": unsure, "tier": tier,
            "usage": {"model": str(usage.get("model") or f"local reader ({tier})"), "input_tokens": 0, "cached": 0,
                      "output_tokens": 0, "ms": usage.get("ms") if isinstance(usage.get("ms"), int) else None}}
