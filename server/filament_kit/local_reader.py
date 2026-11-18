"""The local label reader (the `local_intake` module): a separate program (spoolwarden-vision, its own repository and
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

    API 1.1 (opt-in correction queue, the "Share corrections" feature; bearer token like /v1/read):
    GET  <url>/v1/feedback               -> {"opt_in", "endpoint_configured", "count", "bundle_mb", "entries": [...]}
    POST <url>/v1/feedback               <- {"images_b64", "predicted", "corrected", "note"} (+ "source", "record")
    DELETE <url>/v1/feedback/<id>        GET <url>/v1/feedback/bundle.zip     POST <url>/v1/feedback/submit
    The upload address is the reader's own and never the kit's business: no call here sends one (`endpoint`,
    `feedback_endpoint` or any URL).

The items have the cloud reader's shape (intake.ITEM_PROPS); intake.py does all post-processing for both readers.
The kit sends no order history, prices, comments or spool data. `local_intake.url` may name another machine (the
GPU tier wants a GPU the kit server usually lacks); an optional bearer token (`<etc>/local_intake_token`) protects
that link, and it is sent on reads only, never logged.

HTTPS (R82 section 2 point 6): a reader on another machine is to be at an https address. The Hub pins its certificate
at Test (`test`: trust on first use, the fingerprint in the result) and every call after that accepts only that
certificate (a changed one: `LocalReaderError("cert_changed")`; Test again with `trust=True` takes the new one). The
reader's own repository has to serve HTTPS first (R82 section 10 point 6; ruled 2026-11-17 21:12). While
`ENFORCE_HTTPS` is False an `http://` address on another machine is accepted and used as today and `https_row` gives
the one Checks row (state note, no fix). From the release that turns it on, saving such an address is refused
(`check_url`), a stored one keeps working and its row becomes "needs a look" with a fix. Not a setting.
"""
from __future__ import annotations

import base64
import http.client
import json
import socket
import time
import urllib.error
import urllib.request
from urllib.parse import quote, urlparse

from . import config, station_client

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
FEEDBACK_TIMEOUT = 30            # list, add, delete: the reader strips and shrinks the photos, nothing more
BUNDLE_TIMEOUT = 120
BUNDLE_CAP = 40 * 1048576        # the reader's own bundle limit is 25 MB; more than this is not a bundle of ours
SUBMIT_TIMEOUT = 600             # the upload plus the reader's proof of work (a few seconds of CPU, more on a slow box)
ENFORCE_HTTPS = False            # True once the reader serves HTTPS: an http:// address on another machine is then refused
TEXT_NEEDS_HTTPS = "A Label Reader on another machine needs an https address."
TEXT_NOT_HTTPS_NOTE = "The Label Reader at {address} is not using HTTPS. A later Label Reader version adds it."
TEXT_NOT_HTTPS_ROW = "The Label Reader at {address} is not using HTTPS."      # with the switch on
TEXT_NOT_HTTPS_FIX = ("Update the Label Reader on that machine, then change its address to https:// in "
                      "Settings > Label Reader.")
ROW_GROUP = "Label Reader"
TEXT_CERT_CHANGED = "The Label Reader at {address} presents a different certificate than the one the Hub trusts."
TEXT_CERT_FIX = "Press Test in Settings > Label Reader to trust the new certificate."
PIN_KIND = "reader"
FORBIDDEN_FIELDS = ("endpoint", "feedback_endpoint", "url", "address")     # never in a request body (plan section 8)


class LocalReaderError(Exception):
    """The local reader could not answer. `code`: unreachable | bad_answer | version | refused | unauthorized |
    busy | tier_unavailable | revise_unsupported | cert_changed."""

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
    try:
        u.port
    except ValueError:
        return "The port in the reader's address must be a number from 1 to 65535"
    if u.path not in ("", "/") or u.query or u.fragment:
        return "Give only the reader's address (scheme, host, port), no path"
    if ENFORCE_HTTPS and needs_https(url):
        return TEXT_NEEDS_HTTPS
    return None


def _loopback(host: str | None) -> bool:
    return (host or "").lower() in ("127.0.0.1", "localhost", "::1")


def needs_https(url: str) -> bool:
    """An `http://` address that is not this machine's own (127.0.0.1): what R82 refuses once the reader serves HTTPS."""
    u = urlparse(str(url or "").strip())
    return u.scheme == "http" and bool(u.hostname) and not _loopback(u.hostname)


def https_row(cfg: dict) -> dict | None:
    """The one Checks row for a reader on another machine at an http address, else None (127.0.0.1, localhost or an
    https address). `{"group": "Label Reader", "state": "note" | "needs_a_look", "text", "fix": str | None}`: with
    ENFORCE_HTTPS off a note with TEXT_NOT_HTTPS_NOTE and no fix; on, "needs_a_look" with TEXT_NOT_HTTPS_ROW and
    TEXT_NOT_HTTPS_FIX. The row's registration is AF5's."""
    url = settings(cfg)["url"]
    if not needs_https(url):
        return None
    address = urlparse(url).netloc
    if ENFORCE_HTTPS:
        return {"group": ROW_GROUP, "state": "needs_a_look", "text": TEXT_NOT_HTTPS_ROW.format(address=address),
                "fix": TEXT_NOT_HTTPS_FIX}
    return {"group": ROW_GROUP, "state": "note", "text": TEXT_NOT_HTTPS_NOTE.format(address=address), "fix": None}


def write_token(token: str):
    """Store the reader's bearer token (root: the setup page's helper, `spoolwarden local-intake token`),
    root:filament-kit 640 like the other secrets the service reads. The value is never printed or logged. ValueError
    for one that is not a single word of printable characters."""
    import os
    import shutil
    token = (token or "").strip()
    if not token or not token.isprintable() or " " in token or len(token) > 400:
        raise ValueError("the reader's token is one word of printable characters")
    dest = config.paths().etc / TOKEN_FILE
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    try:
        if os.name == "nt":
            tmp.write_bytes((token + "\n").encode())
        else:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640)
            with os.fdopen(fd, "wb") as fh:
                os.fchmod(fh.fileno(), 0o640)
                fh.write((token + "\n").encode())
                fh.flush()
                os.fsync(fh.fileno())
            if os.geteuid() == 0:
                try:
                    shutil.chown(tmp, user="root", group="filament-kit")
                except (LookupError, OSError):
                    pass
        os.replace(tmp, dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return dest


def remove_token() -> bool:
    try:
        (config.paths().etc / TOKEN_FILE).unlink()
        return True
    except FileNotFoundError:
        return False


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
    except ValueError:      # a port outside 0-65535 or not a number
        raise LocalReaderError("unreachable", f"the local reader's address {u.netloc!r} is not usable: the port must "
                                              "be a number from 1 to 65535") from None
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


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: the reader answers at the address the owner set, and a redirect followed with the
    bearer token would hand it to another host (review R127 note 1). A 3xx is then an HTTP error like any other."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


class _PinHandler(urllib.request.HTTPSHandler):
    """https:// through a connection pinned to `fp` (station_client.PinnedConnection); with `fp` None the certificate
    met is left in `seen` for the caller to keep (trust on first use)."""

    def __init__(self, fp: str | None):
        super().__init__()
        self.fp, self.seen, self._conn = fp, None, None

    def https_open(self, req):
        def make(host, timeout=None, **_ignored):
            self._conn = station_client.PinnedConnection(host, None, self.fp, timeout)
            return self._conn
        try:
            return self.do_open(make, req)
        finally:
            self.seen = getattr(self._conn, "seen", None)


def _origin(url: str) -> str:
    u = urlparse(url)
    return f"{u.scheme.lower()}://{(u.hostname or '').lower()}:{u.port or (443 if u.scheme.lower() == 'https' else 80)}"


def _opener_for(url: str):
    """(opener, pin handler or None): plain for http, a pinned one for https."""
    if urlparse(url).scheme.lower() != "https":
        return _OPENER, None
    h = _PinHandler(station_client.pin_get(PIN_KIND, _origin(url)))
    return urllib.request.build_opener(_NoRedirect, h), h


def _request(url: str, *, body: dict | None, timeout: float, auth: bool = False, method: str | None = None,
             errors: dict | None = None, raw_cap: int | None = None) -> dict | bytes:
    """One call. `method` defaults to GET without a body, POST with one. `errors`: {reader error code or HTTP status:
    (kind, text)} tried before the generic mapping (the feedback calls' own words). `raw_cap`: the answer is bytes
    (a download) of at most that many, else `too_large`; without it the answer is a JSON object."""
    _reachable(url)
    opener, pin = _opener_for(url)
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Accept": "application/json" if raw_cap is None else "*/*",
               **({"Content-Type": "application/json"} if body is not None else {})}
    token = _token() if auth else ""
    if token:
        headers["Authorization"] = f"Bearer {token}"
    deadline = time.monotonic() + timeout
    for attempt in (1, 2):
        req = urllib.request.Request(url, data=data, method=method or ("GET" if body is None else "POST"),
                                     headers=headers)
        try:
            with opener.open(req, timeout=max(1.0, deadline - time.monotonic())) as resp:  # noqa: S310
                if raw_cap is None:
                    raw = resp.read()
                else:
                    raw = resp.read(raw_cap + 1)
                    if len(raw) > raw_cap:
                        raise LocalReaderError("too_large", f"the local reader's download is over {raw_cap // 1048576} "
                                                            "MB: not fetched")
            if pin is not None and pin.fp is None and pin.seen:
                station_client.pin_set(PIN_KIND, _origin(url), pin.seen)    # trust on first use
            break
        except urllib.error.HTTPError as e:
            code, msg = _error_of(e.read() or b"")
            what = f"the local reader answered HTTP {e.code}" + (f" ({code})" if code else "") + (
                f": {msg}" if msg else "")
            if e.code == 401 or code == "unauthorized":
                raise LocalReaderError("unauthorized", "the local reader's token is wrong or missing (set it on "
                                                       "the setup page or with sudo spoolwarden local-intake token)") from None
            if code == "unsupported_api_version":
                raise LocalReaderError("version", "the local reader does not speak this kit's API version: "
                                                  "update the local reader") from None
            own = (errors or {}).get(code) or (errors or {}).get(e.code)
            if own:
                raise LocalReaderError(own[0], own[1]) from None
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
            if isinstance(reason, station_client.PinMismatch):
                raise LocalReaderError("cert_changed", f"{TEXT_CERT_CHANGED.format(address=urlparse(url).netloc)} "
                                                       f"{TEXT_CERT_FIX}") from None
            raise LocalReaderError("unreachable", f"the local reader at {urlparse(url).netloc} does not answer "
                                                  f"({reason})") from None
    if raw_cap is not None:
        return raw
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


def _version_at_least(v, major: int, minor: int) -> bool:
    """"1.1" / "1.2" / 2 are at least 1.1; "1.0", 1, None and junk are not."""
    if isinstance(v, bool) or v is None:
        return False
    parts = str(v).strip().split(".")
    try:
        got = (int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
    except ValueError:
        return False
    return got >= (major, minor)


def _opt_bool(v) -> bool | None:
    return v if isinstance(v, bool) else None


def _count(v) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None


def _accelerator(v) -> str | None:
    if isinstance(v, dict):
        v = v.get("name") or v.get("device") or v.get("provider") or v.get("type")
    if isinstance(v, (str, int, float)) and not isinstance(v, bool):
        return str(v).strip()[:80] or None
    return None


def capabilities(h) -> dict:
    """What the reader can do, from its /v1/health answer `h` (None or anything: the "none" answer). Never raises.
        {"feedback": bool,            the 1.1 correction queue exists
         "opt_in": bool|None,         the reader's opt-in is on (None: not known until GET /v1/feedback)
         "endpoint_configured": bool|None, "count": int|None,
         "source_record": bool,       POST /v1/feedback may carry `source` and `record`
         "accelerator": str|None,     what the reader computes on, when it says
         "known_from": "health"|"api_version"|"none"}
    The reader's own `capabilities` object wins; without one, API 1.1 or later means the queue exists (the rest
    unknown) and anything older means none."""
    none = {"feedback": False, "opt_in": None, "endpoint_configured": None, "count": None, "source_record": False,
            "accelerator": None, "known_from": "none"}
    if not isinstance(h, dict):
        return none
    try:
        caps = h.get("capabilities")
        if not isinstance(caps, dict):
            if _version_at_least(h.get("api_version"), 1, 1):
                return {**none, "feedback": True, "known_from": "api_version",
                        "accelerator": _accelerator(h.get("accelerator"))}
            return {**none, "accelerator": _accelerator(h.get("accelerator"))}
        fb = caps.get("feedback")
        detail = fb if isinstance(fb, dict) else {}
        if not detail and isinstance(h.get("feedback"), dict):
            detail = h["feedback"]
        has = fb is True or (isinstance(fb, dict) and fb.get("enabled", True) is not False) or (
            fb is None and (bool(detail) or _version_at_least(h.get("api_version"), 1, 1)))
        fields = detail.get("fields")
        both = (detail.get("source") is True and detail.get("record") is True) or (
            isinstance(fields, list) and "source" in fields and "record" in fields)
        return {"feedback": has, "opt_in": _opt_bool(detail.get("opt_in")) if has else None,
                "endpoint_configured": _opt_bool(detail.get("endpoint_configured")) if has else None,
                "count": _count(detail.get("count")) if has else None, "source_record": bool(has and both),
                "accelerator": _accelerator(caps.get("accelerator", h.get("accelerator"))),
                "known_from": "health"}
    except Exception:       # an odd answer never fails the reader's status
        return none


def health(cfg: dict, timeout: float = HEALTH_TIMEOUT) -> dict:
    """{ok, degraded, url, api_version, version, tiers, revise, auth_required, last_read_at, capabilities, error}:
    never raises (`capabilities`: see capabilities()).
    `ok`: a read can be served now (status ok, or degraded with a usable tier); `error` says why not, or what is
    degraded."""
    s = settings(cfg)
    out = {"ok": False, "degraded": False, "url": s["url"], "api_version": None, "version": None, "tiers": {},
           "revise": False, "auth_required": False, "last_read_at": None, "error": None,
           "capabilities": capabilities(None)}
    try:
        h = _request(f"{s['url']}/v1/health", body=None, timeout=timeout)
    except LocalReaderError as e:
        out["error"] = str(e)
        return out
    tiers = _tiers(h.get("tiers"))
    out.update(api_version=h.get("api_version"), version=h.get("module_version") or h.get("version"), tiers=tiers,
               revise=h.get("revise") is True, auth_required=h.get("auth_required") is True,
               last_read_at=h.get("last_read_at"), capabilities=capabilities(h))
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
        out["ok"], out["error"] = False, ("the local reader needs a token: set it on the setup page (Settings, Local "
                                          "label reader) or with sudo spoolwarden local-intake token")
    return out


def test(cfg: dict, timeout: float = HEALTH_TIMEOUT, trust: bool = False) -> dict:
    """Settings > Label Reader's Test: `health(cfg)` plus `https` (bool), `fp` (the certificate's SHA-256 the reader
    presents, to show beside the result; None for http) and `pin`: "new" (kept now: trust on first use), "same",
    "changed" (not the one kept: the result says so and `trust=True` keeps the new one) or "replaced" (it was changed
    and `trust` took it). For an http address on another machine `warning` holds the row's text (`https_row`). Never
    raises."""
    u = urlparse(settings(cfg)["url"])
    out: dict = {"fp": None, "pin": None, "https": u.scheme == "https", "warning": (https_row(cfg) or {}).get("text")}
    if u.scheme == "https" and u.hostname:
        key = _origin(settings(cfg)["url"])
        known = station_client.pin_get(PIN_KIND, key)
        try:
            seen = station_client.peer_fingerprint(u.hostname, u.port or 443, CONNECT_TIMEOUT)
        except OSError:
            seen = None         # health below says it does not answer
        if seen:
            out["fp"] = seen
            if known is None or (known != seen and trust):
                station_client.pin_set(PIN_KIND, key, seen)
            out["pin"] = "new" if known is None else "same" if known == seen else "replaced" if trust else "changed"
    return {**health(cfg, timeout), **out}


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
    the post-processing see one shape whichever reader answered. The reader's `confidence` (0..1),
    `field_confidence` ({field: 0..1}), `color_name` and `color_family` stay on the item for the result screen;
    anything else extra is dropped."""
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
    for k in ("color_name", "color_family"):  # the library's colour name ("unknown" when it has none) and family
        v = it.get(k)
        it[k] = v.strip()[:60] if isinstance(v, str) and v.strip() else None
    it["confidence"] = _conf(it.get("confidence"))
    fc = it.get("field_confidence")
    it["field_confidence"] = ({str(k): c for k, v in fc.items() if (c := _conf(v)) is not None}
                              if isinstance(fc, dict) else {})
    for k in list(it):        # the module's own extras (colour name and family, source type, ...) stay there
        if k not in _KEEP:
            del it[k]


_KEEP = frozenset({"photos", "existing_filament_id", "vendor", "name", "material", "color_hex", "net", "tare",
                   "density", "count", "nozzle", "bed", "nozzle_range", "bed_range", "lot", "note", "estimates",
                   "sealed", "sealed_reason", "line", "confidence", "field_confidence", "color_name",
                   "color_family"})


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


# ---------- the correction queue (API 1.1; used by the Share corrections steps) ----------

# The reader's words for what can go wrong, by its error code (or HTTP status), in the kit's error kinds
_TOO_BIG = ("too_large", "the corrections are too big for the local reader (too many or too large photos)")
_FEEDBACK_ERRORS = {
    "feedback_disabled": ("feedback_disabled", "sharing of corrections is switched off in the local reader: switch "
                                               "it on first"),
    403: ("feedback_disabled", "the local reader refused: sharing of corrections is switched off there"),
    "empty_feedback_queue": ("empty", "there are no corrections waiting"),
    "feedback_upload_failed": ("upload_failed", "the local reader could not send the corrections; they are still "
                                                "waiting, try again later"),
    409: ("conflict", "the local reader already has this correction"),
    "too_large": _TOO_BIG,
    413: _TOO_BIG,
    404: ("not_found", "the local reader has no such correction (or is too old to keep them: update it)"),
}


def _feedback_base(cfg: dict) -> str:
    return f"{settings(cfg)['url']}/v1/feedback"


def _check_body(body: dict) -> dict:
    """The kit never names an upload address to the reader: a bug that did would fail here, not leak."""
    def keys(v):
        for k, x in (v.items() if isinstance(v, dict) else ()):
            yield k
            yield from keys(x)
    bad = [k for k in keys(body) if str(k).lower() in FORBIDDEN_FIELDS]
    if bad:
        raise ValueError(f"the kit never sends {bad[0]} to the local reader")
    return body


def feedback_list(cfg: dict) -> dict:
    """{opt_in, endpoint_configured, count, bundle_mb, entries} from GET /v1/feedback: missing fields get safe
    defaults, the entries are the reader's own summaries (id, time, predicted, corrected, thumbnail ...)."""
    out = _request(_feedback_base(cfg), body=None, timeout=FEEDBACK_TIMEOUT, auth=True, errors=_FEEDBACK_ERRORS)
    entries = out.get("entries") if isinstance(out.get("entries"), list) else out.get("items")
    mb = out.get("bundle_mb")
    entries = [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []
    count = _count(out.get("count"))
    return {"opt_in": out.get("opt_in") is True, "endpoint_configured": out.get("endpoint_configured") is True,
            "count": len(entries) if count is None else count,
            "bundle_mb": float(mb) if isinstance(mb, (int, float)) and not isinstance(mb, bool) else 0.0,
            "entries": entries}


def feedback_add(cfg: dict, images: list[bytes], predicted: dict, corrected: dict, note: str = "", *,
                 source: str | None = None, record: str | None = None, caps: dict | None = None) -> dict:
    """Queue one correction: the reader strips the photos' metadata and shrinks them. `source` ("local" | "cloud")
    and `record` (the Hub's record id) go along only when the reader advertises them (`caps`, else read from its
    health); a reader that does not know them is sent neither. Returns the reader's answer (the entry's id ...)."""
    body = {"api_version": API_SENT, "images_b64": [base64.standard_b64encode(b).decode("ascii") for b in images],
            "predicted": predicted or {}, "corrected": corrected or {}, "note": note or ""}
    if source is not None or record is not None:
        if caps is None:
            caps = health(cfg)["capabilities"]
        if caps.get("source_record"):
            if source is not None:
                body["source"] = str(source)
            if record is not None:
                body["record"] = str(record)
    return _request(_feedback_base(cfg), body=_check_body(body), timeout=FEEDBACK_TIMEOUT, auth=True,
                    errors=_FEEDBACK_ERRORS)


def feedback_delete(cfg: dict, entry_id: str) -> dict:
    """Remove one waiting correction (and its photos) from the reader."""
    eid = str(entry_id or "").strip()
    if not eid:
        raise LocalReaderError("not_found", "no such correction")
    return _request(f"{_feedback_base(cfg)}/{quote(eid, safe='')}", body=None, method="DELETE",
                    timeout=FEEDBACK_TIMEOUT, auth=True, errors=_FEEDBACK_ERRORS)


def feedback_bundle(cfg: dict, cap: int = BUNDLE_CAP) -> bytes:
    """The zip the reader would send, exactly (for the user to look at); at most `cap` bytes, else `too_large`."""
    return _request(f"{_feedback_base(cfg)}/bundle.zip", body=None, timeout=BUNDLE_TIMEOUT, auth=True,
                    errors=_FEEDBACK_ERRORS, raw_cap=cap)


def feedback_image(cfg: dict, entry_id: str, index: int = 0, cap: int = BUNDLE_CAP) -> bytes:
    """Fetch a single queued correction photo (`GET /v1/feedback/<id>/image`)."""
    eid = str(entry_id or "").strip()
    if not eid:
        raise LocalReaderError("not_found", "no such correction")
    return _request(f"{_feedback_base(cfg)}/{quote(eid, safe='')}/image?index={int(index)}", body=None,
                    timeout=FEEDBACK_TIMEOUT, auth=True, errors=_FEEDBACK_ERRORS, raw_cap=cap)


def feedback_submit(cfg: dict, *, poll_interval: float = 1.0) -> dict:
    """Ask the reader to send what is waiting to where the reader itself sends it; handles both synchronous 200 and
    v0.2.1+ asynchronous 202 + GET /v1/feedback/submit polling. No address of ours goes along, ever."""
    out = _request(f"{_feedback_base(cfg)}/submit", body=_check_body({"api_version": API_SENT}),
                   timeout=SUBMIT_TIMEOUT, auth=True, errors=_FEEDBACK_ERRORS)
    if out.get("ok") is True and out.get("status") != "running":
        return out
    if out.get("accepted") is True or out.get("status") == "running":
        deadline = time.monotonic() + SUBMIT_TIMEOUT
        while True:
            if time.monotonic() >= deadline:
                raise LocalReaderError("upload_failed", "the local reader's feedback upload timed out")
            time.sleep(poll_interval)
            st = _request(f"{_feedback_base(cfg)}/submit", body=None, method="GET", timeout=FEEDBACK_TIMEOUT,
                          auth=True, errors=_FEEDBACK_ERRORS)
            status = str(st.get("status") or "").lower()
            if status in ("running", "pending"):
                continue
            if status in ("error", "failed") or st.get("ok") is False:
                msg = str(st.get("error") or st.get("message") or "upload failed")
                raise LocalReaderError("upload_failed", f"the local reader could not send the corrections: {msg}")
            return st
    return out
