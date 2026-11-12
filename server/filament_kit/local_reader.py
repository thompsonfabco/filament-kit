"""The local label reader (the `local_intake` module): a separate program (filament-kit-image, its own repository and
release), on this machine or another one on the network, that reads spool label photos without the cloud. The kit
only talks to it over HTTP; this file is the whole of that conversation, so a change to the reader's API changes
this file and nothing else.

Contract v1 (the module's `docs/api-contract.md` and the kit's KIT-INTEGRATION-INSTRUCTIONS section 2.1; where the
two write a field differently, both forms are accepted):

    GET  <url>/v1/health   -> {"status": "ok"|"degraded", "api_version": "1.0" (or 1), "module_version",
                               "tiers": {"cpu": {"usable": true, "reason": null} (or true), ...}, "revise": bool,
                               "auth_required": bool, "last_read_at": ...}
    POST <url>/v1/read     <- {"api_version": "1.0", "tier", "images_b64", "hint", "filaments", "vendors", "tag"}
                           -> {"api_version", "items": [... + "confidence", "field_confidence"], "questions",
                               "reader": {"tier_used", "escalated", "latency_ms", ...}, "usage"}
    POST <url>/v1/revise   <- the read request + "previous" (the item as first read) + "note"
                           -> the corrected item ("item", or "items"[0])
    errors                 -> {"error": {"code", "message"}} (or {"error": code, "message"})

The items have the cloud reader's shape (intake.ITEM_PROPS); intake.py does all post-processing for both readers.
The kit sends no order history, prices, comments or spool data. `local_intake.url` may name another machine (the
GPU tier wants a GPU the kit server usually lacks); an optional bearer token (`<etc>/local_intake_token`) protects
that link, and it is sent on reads only, never logged.
"""
from __future__ import annotations

import base64
import http.client
import json
import socket
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from . import config

DEFAULT_URL = "http://127.0.0.1:7915"
API_MAJOR = 1                    # the reader API major version this kit speaks; any 1.x is accepted
API_SENT = "1.0"
TIERS = ("auto", "cpu", "gpu")
MIN_CONFIDENCE = 0.78            # an item below this makes a local answer "unsure" (the contract's default)
TIMEOUT = 120                    # seconds for one read: the GPU tier's first read after idle loads the model
HEALTH_TIMEOUT = 3
CONNECT_TIMEOUT = 3              # a reader that is down (or a machine that is off) is known in seconds, not after TIMEOUT
BUSY_WAIT_MAX = 30               # a `503 busy` is retried once after its Retry-After, if that is at most this
TOKEN_FILE = "local_intake_token"


class LocalReaderError(Exception):
    """The local reader could not answer. `code`: unreachable | bad_answer | version | refused | unauthorized |
    busy | tier_unavailable | revise_unsupported."""

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


def _token() -> str:
    try:
        return (config.paths().etc / TOKEN_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _reachable(url: str) -> None:
    """Connect once with a short timeout: an address that drops packets would otherwise hold a read for `timeout`."""
    u = urlparse(url)
    try:
        socket.create_connection((u.hostname, u.port or (443 if u.scheme == "https" else 80)),
                                 timeout=CONNECT_TIMEOUT).close()
    except OSError as e:
        raise LocalReaderError("unreachable", f"the local reader at {u.netloc} does not answer ({e})") from None


def _error_of(raw: bytes) -> tuple[str, str]:
    """(code, message) from an error body in either form; ("", "") when there is none."""
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return "", ""
    if not isinstance(body, dict):
        return "", ""
    err = body.get("error")
    if isinstance(err, dict):
        return str(err.get("code") or ""), str(err.get("message") or "")[:200]
    return str(err or ""), str(body.get("message") or "")[:200]


# HTTP errors the kit treats as a refusal of these photos (no fallback would read them better): the rest are the
# reader failing, and the kit's reader setting decides what happens next
REFUSALS = {"bad_request", "no_photos", "too_many_photos", "too_large", "bad_image"}


def _request(url: str, *, body: dict | None, timeout: float, auth: bool = False) -> dict:
    _reachable(url)
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Accept": "application/json", **({"Content-Type": "application/json"} if body is not None else {})}
    token = _token() if auth else ""
    if token:
        headers["Authorization"] = f"Bearer {token}"
    deadline = time.monotonic() + timeout
    for attempt in (1, 2):
        req = urllib.request.Request(url, data=data, method="GET" if body is None else "POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=max(1.0, deadline - time.monotonic())) as resp:  # noqa: S310
                raw = resp.read()
            break
        except urllib.error.HTTPError as e:
            code, msg = _error_of(e.read() or b"")
            what = f"the local reader answered HTTP {e.code}" + (f" ({code})" if code else "") + (
                f": {msg}" if msg else "")
            if e.code == 401 or code == "unauthorized":
                raise LocalReaderError("unauthorized", "the local reader's token is wrong or missing "
                                                       f"(<etc>/{TOKEN_FILE})") from None
            if code == "unsupported_api_version":
                raise LocalReaderError("version", "the local reader does not speak this kit's API version: "
                                                  "update the local reader") from None
            if e.code == 503 and code == "busy" and attempt == 1:
                try:
                    wait = float(e.headers.get("Retry-After") or 0)
                except (TypeError, ValueError):
                    wait = 0
                if 0 <= wait <= min(BUSY_WAIT_MAX, deadline - time.monotonic() - 1):
                    time.sleep(wait)
                    continue
            kind = ("refused" if code in REFUSALS or (not code and e.code in (400, 413, 415, 422))
                    else code if code in ("busy", "tier_unavailable") else "bad_answer")
            raise LocalReaderError(kind, what) from None
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


def _major(v) -> int | None:
    """The major version of "1.0" / "1" / 1; None when it is neither."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        head = v.strip().split(".", 1)[0]
        return int(head) if head.isdigit() else None
    return None


def _version_ok(v) -> bool:
    return _major(v) == API_MAJOR


def _tiers(raw) -> dict:
    """{name: {"usable": bool, "reason": str|None}} from either form ({"cpu": true} or {"cpu": {"usable": ...}})."""
    out = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            if isinstance(v, dict):
                out[str(k)] = {"usable": v.get("usable") is True,
                               "reason": str(v["reason"]) if v.get("reason") else None}
            else:
                out[str(k)] = {"usable": v is True, "reason": None}
    return out


def health(cfg: dict, timeout: float = HEALTH_TIMEOUT) -> dict:
    """{ok, degraded, url, api_version, version, tiers, revise, auth_required, last_read_at, error}: never raises.
    `ok`: a read can be served now (status ok, or degraded with a usable tier); `error` says why not, or what is
    degraded."""
    s = settings(cfg)
    out = {"ok": False, "degraded": False, "url": s["url"], "api_version": None, "version": None, "tiers": {},
           "revise": False, "auth_required": False, "last_read_at": None, "error": None}
    try:
        h = _request(f"{s['url']}/v1/health", body=None, timeout=timeout)
    except LocalReaderError as e:
        out["error"] = str(e)
        return out
    tiers = _tiers(h.get("tiers"))
    out.update(api_version=h.get("api_version"), version=h.get("module_version") or h.get("version"), tiers=tiers,
               revise=h.get("revise") is True, auth_required=h.get("auth_required") is True,
               last_read_at=h.get("last_read_at"))
    usable = [k for k, t in tiers.items() if t["usable"]]
    if not _version_ok(h.get("api_version")):
        major = _major(h.get("api_version"))
        out["error"] = (f"the local reader speaks API version {h.get('api_version')!r}; this kit speaks "
                        f"{API_MAJOR}.x: " + ("update the kit" if major and major > API_MAJOR
                                              else "update the local reader"))
    elif h.get("status") == "ok" or (h.get("status") == "degraded" and usable):
        out["ok"] = True
        if h.get("status") == "degraded":
            out["degraded"] = True
            out["error"] = "degraded: " + "; ".join(f"{k}: {t['reason'] or 'not usable'}"
                                                    for k, t in tiers.items() if not t["usable"])
    else:
        out["error"] = f"the local reader is not ready ({h.get('status')!r})"
    if out["auth_required"] and out["ok"] and not _token():
        out["ok"], out["error"] = False, f"the local reader needs a token: put it in <etc>/{TOKEN_FILE}"
    return out


def catalog(fils: list[dict], vendors: list[dict], line_of) -> tuple[list[dict], list[dict]]:
    """What the reader gets of Spoolman, in Spoolman's own shape but only the catalog fields the cloud reader gets
    too: no comments, prices, extra fields (except the product line) or spool data."""
    fl = []
    for f in fils:
        v = f.get("vendor") or {}
        line = line_of(f) or None
        fl.append({"id": f.get("id"), "name": f.get("name"), "vendor": {"id": v.get("id"), "name": v.get("name")},
                   "material": f.get("material"), "weight": f.get("weight"), "spool_weight": f.get("spool_weight"),
                   "density": f.get("density"), "color_hex": f.get("color_hex"), "line": line,
                   "extra": {"line": json.dumps(line)} if line else {}})
    vl = [{"id": v.get("id"), "name": v.get("name"), "empty_spool_weight": v.get("empty_spool_weight")}
          for v in vendors]
    return fl, vl


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0


def _conf(v) -> float | None:
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return None
    return round(min(max(float(v), 0.0), 1.0), 3)


# a field the reader left out gets this, and its name goes into the item's `estimates` (as the cloud reader marks
# its own guesses), so the result screen says it was not read
GUESS = {"net": 1000, "tare": 200, "density": 1.24}
DENSITY = {"PLA": 1.24, "PETG": 1.27, "ABS": 1.04, "ASA": 1.07, "TPU": 1.21, "PC": 1.20, "PA": 1.14}


def _complete(it: dict, vendors: list[dict], n_photos: int) -> None:
    """Give a local item every field of the cloud reader's schema (intake.ITEM_PROPS), so the app, the station and
    the post-processing see one shape whichever reader answered. The reader's `confidence` (0..1) and
    `field_confidence` ({field: 0..1}) stay on the item for the result screen; anything else extra is dropped."""
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
    it["confidence"] = _conf(it.get("confidence"))
    fc = it.get("field_confidence")
    it["field_confidence"] = ({str(k): c for k, v in fc.items() if (c := _conf(v)) is not None}
                              if isinstance(fc, dict) else {})
    for k in list(it):        # the module's own extras (colour name and family, source type, ...) stay there
        if k not in _KEEP:
            del it[k]


_KEEP = frozenset({"photos", "existing_filament_id", "vendor", "name", "material", "color_hex", "net", "tare",
                   "density", "count", "nozzle", "bed", "nozzle_range", "bed_range", "lot", "note", "estimates",
                   "sealed", "sealed_reason", "line", "confidence", "field_confidence"})


def _body(cfg: dict, images: list[bytes], hint: str, fils: list[dict], vendors: list[dict], tag: dict | None) -> dict:
    s = settings(cfg)
    return {"api_version": API_SENT, "tier": s["tier"], "hint": hint or "",
            "images_b64": [base64.standard_b64encode(b).decode("ascii") for b in images],
            "filaments": fils, "vendors": vendors, "tag": tag}


def _answer(cfg: dict, out: dict, vendors: list[dict], n_photos: int) -> dict:
    """{items, questions, confidence, unsure, tier, escalated, usage} from a /v1/read answer."""
    s = settings(cfg)
    if "api_version" in out and not _version_ok(out["api_version"]):
        raise LocalReaderError("version", f"the local reader answered with API version {out['api_version']!r}; "
                                          f"this kit speaks {API_MAJOR}.x")
    items = out.get("items")
    if not isinstance(items, list) or not all(isinstance(it, dict) for it in items):
        raise LocalReaderError("bad_answer", "the local reader's answer has no item list")
    for it in items:
        _complete(it, vendors, n_photos)
    per = [it["confidence"] for it in items if it["confidence"] is not None]
    conf = min(per) if per else _conf(out.get("confidence"))       # the least sure item decides
    unsure = (out.get("unsure") is True or not items or conf is None or conf < s["min_confidence"]
              or any(it["vendor"].lower() == "unknown" for it in items))
    reader = out.get("reader") if isinstance(out.get("reader"), dict) else {}
    tier = str(reader.get("tier_used") or out.get("tier") or s["tier"])
    usage = out.get("usage") if isinstance(out.get("usage"), dict) else {}
    ms = reader.get("latency_ms", usage.get("ms"))
    q = out.get("questions")
    return {"items": items, "questions": [str(x) for x in q] if isinstance(q, list) else [],
            "confidence": conf, "unsure": unsure, "tier": tier, "escalated": reader.get("escalated") is True,
            "usage": {"model": str(usage.get("model") or reader.get("model") or f"local reader ({tier})"),
                      "input_tokens": 0, "cached": 0, "output_tokens": 0,
                      "ms": round(ms) if isinstance(ms, (int, float)) and not isinstance(ms, bool) else None}}


def read(cfg: dict, images: list[bytes], hint: str, fils: list[dict], vendors: list[dict],
         tag: dict | None) -> dict:
    """One read. Returns {items, questions, confidence, unsure, tier, escalated, usage}; raises LocalReaderError."""
    s = settings(cfg)
    out = _request(f"{s['url']}/v1/read", body=_body(cfg, images, hint, fils, vendors, tag), timeout=s["timeout"],
                   auth=True)
    return _answer(cfg, out, vendors, len(images))


def revise(cfg: dict, images: list[bytes], previous: dict, note: str, fils: list[dict], vendors: list[dict]) -> dict:
    """The intake history's "correct it" on the local reader: the photos, the item as saved and the owner's note.
    Returns the read's shape with one item; raises LocalReaderError (`revise_unsupported` on a 404 or 501)."""
    s = settings(cfg)
    body = {**_body(cfg, images, note, fils, vendors, None), "previous": previous, "note": note or ""}
    try:
        out = _request(f"{s['url']}/v1/revise", body=body, timeout=s["timeout"], auth=True)
    except LocalReaderError as e:
        if e.code == "bad_answer" and ("HTTP 404" in str(e) or "HTTP 501" in str(e)):
            raise LocalReaderError("revise_unsupported", "this local reader cannot revise a reading; "
                                                         "use the cloud reader") from None
        raise
    if isinstance(out.get("item"), dict) and not isinstance(out.get("items"), list):
        out = {**out, "items": [out["item"]]}
    return _answer(cfg, out, vendors, len(images))
