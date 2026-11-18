"""Read-only client for an intake station's `GET /state` (filament-ops station/intake_station.py).

The state comes back as the station sent it: `{"tag": {...}, "scale": {...}|null, "last_weight": {...}|null,
"panel": ...}` ("held" sits inside "tag" and "last_weight"). After a failure the client refuses straight away
for `backoff` seconds, so a dead station costs the app one quick 503 per call instead of a connect timeout (same
policy as filament-mcp).

HTTPS (R82 section 2): a station that has told the Hub its certificate (`pairing.station_info`: fingerprint, port,
version, from its hello call) is called over HTTPS at that port and accepts only that certificate; a changed one is
refused (`StationCertChanged`, with the Error and Fix texts below), never retried over plain HTTP. A station that sent
no fingerprint (not updated yet) is called at its configured url as before. The same pinned connection and a small
store of pins (`pins.xml` in the state folder, for the tag sources and the remote Label Reader) are here too, so
every pinned call of the Hub is one piece of code.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

# Texts for the Checks rows and the page (AF5 moves them to the catalogue).
TEXT_STATION_CERT_CHANGED = "The Weigh Station's certificate is not the one the Hub trusts."
TEXT_STATION_CERT_FIX = ("Restart the Weigh Station so it tells the Hub its new certificate "
                         "(sudo systemctl restart filament-kit-station), or pair it again.")
TEXT_STATION_NOT_HTTPS = "The Weigh Station {name} is not using HTTPS. Update it."
# the row for a station that said it could not make its certificate (R82 section 2 point 4, "plain by necessity")
TEXT_STATION_NOT_HTTPS_AT = "The Weigh Station at {address} is not using HTTPS."
TEXT_STATION_NOT_HTTPS_WHY = "The Weigh Station at {address} is not using HTTPS: it could not make its certificate ({reason})."
# a pinned station that now answers only plain HTTP or with another certificate: the same Error and Fix, no downgrade


class StationUnreachable(Exception):
    pass


class StationCertChanged(StationUnreachable):
    """The station presented a certificate other than the pinned one: refused, with the Error and the Fix to show."""
    error = TEXT_STATION_CERT_CHANGED
    fix = TEXT_STATION_CERT_FIX


class PinMismatch(ssl.SSLError):
    """The peer's certificate is not the pinned one. `got` / `expected`: their SHA-256 fingerprints."""

    def __init__(self, got: str, expected: str):
        super().__init__(f"certificate changed (fingerprint {got[:16]}..., expected {expected[:16]}...)")
        self.got, self.expected = got, expected


def _context() -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE   # trust is the pinned fingerprint, checked before anything is sent
    return ctx


class PinnedConnection(http.client.HTTPSConnection):
    """An HTTPS connection that sends nothing unless the peer's certificate has the SHA-256 `fp` (raises PinMismatch).
    With `fp` None every certificate is taken and its fingerprint is left in `.seen` (trust on first use: the caller
    decides what to keep)."""

    def __init__(self, host: str, port: int | None, fp: str | None, timeout: float):
        super().__init__(host, port, timeout=timeout, context=_context())
        self.fp, self.seen = fp, None

    def connect(self):
        super().connect()
        self.seen = hashlib.sha256(self.sock.getpeercert(binary_form=True) or b"").hexdigest()
        if self.fp is not None and self.seen != self.fp:
            self.sock.close()
            raise PinMismatch(self.seen, self.fp)


def pinned_get(host: str, port: int, path: str, fp: str | None, timeout: float, cap: int = 1 << 20,
               headers: dict | None = None) -> tuple[int, bytes, str]:
    """GET `path` over a PinnedConnection: (status, body of at most cap + 1 bytes, the certificate's fingerprint). No
    redirect is followed. Raises PinMismatch, or OSError / http.client.HTTPException."""
    c = PinnedConnection(host, port, fp, timeout)
    try:
        c.request("GET", path, headers=headers or {})
        r = c.getresponse()
        return r.status, r.read(cap + 1), c.seen
    finally:
        c.close()


def peer_fingerprint(host: str, port: int, timeout: float = 5) -> str:
    """The SHA-256 of the certificate a listener presents (the handshake only). Raises OSError."""
    c = PinnedConnection(host, port, None, timeout)
    try:
        c.connect()
        return c.seen
    finally:
        c.close()


PINS_FILE = "pins.xml"


def _pins_path():
    from . import config
    return config.paths().state / PINS_FILE


def _read_pins() -> dict[tuple[str, str], str]:
    try:
        root = ET.fromstring(_pins_path().read_bytes())
    except (OSError, ET.ParseError):
        return {}
    return {(e.get("kind") or "", e.get("key") or ""): (e.get("fp") or "").lower() for e in root.iter("pin")}


def pin_get(kind: str, key: str) -> str | None:
    """The fingerprint kept for (`kind`, `key`): "tag" with the source's address, "reader" with the reader's. None
    when none is kept."""
    return _read_pins().get((kind, key)) or None


def pin_set(kind: str, key: str, fp: str | None) -> None:
    """Keep `fp` for (`kind`, `key`), replacing the one there; None drops it (the owner saved the address again).
    State data: XML, written whole and owned like the state folder's other files."""
    from . import pairing
    with pairing._locked():
        pins = _read_pins()
        if fp:
            pins[(kind, key)] = fp.lower()
        else:
            pins.pop((kind, key), None)
        root = ET.Element("pins")
        for (k, key_), f in sorted(pins.items()):
            ET.SubElement(root, "pin", kind=k, key=key_, fp=f)
        _pins_path().parent.mkdir(parents=True, exist_ok=True)
        pairing._write_atomic(_pins_path(), ET.tostring(root, encoding="utf-8", xml_declaration=True), 0o600,
                              state_owned=True)


def _station_info() -> dict | None:
    from . import pairing
    try:
        return pairing.station_info()
    except (OSError, ValueError):
        return None


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
        info, host = _station_info(), urllib.parse.urlsplit(self.url).hostname
        try:
            if info and host:       # the station said hello with a certificate: HTTPS, that certificate only
                status, raw, _seen = pinned_get(host, info["port"], "/state", info["fp"], self.timeout)
                if status != 200:
                    raise StationUnreachable(f"station answered {status}")
                data = json.loads(raw)
            else:
                with urllib.request.urlopen(f"{self.url}/state", timeout=self.timeout) as resp:
                    if resp.status != 200:
                        raise StationUnreachable(f"station answered {resp.status}")
                    data = json.loads(resp.read())
            if not isinstance(data, dict):
                raise ValueError("not an object")
        except StationUnreachable:
            self._fail()
            raise
        except PinMismatch as e:
            self._fail()
            raise StationCertChanged(f"station at {self.url}: {e}") from e
        except ssl.SSLError as e:       # a pinned station that does not speak TLS (plain HTTP only): never called plain
            self._fail()
            raise StationCertChanged(f"station at {self.url} does not answer over HTTPS: {e}") from e
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


def station_https(url: str | None) -> str | None:
    """How the Hub reaches the Weigh Station at `url`, for the Checks: None (no url), "plain" (it has told the Hub no
    certificate: not updated; the row TEXT_STATION_NOT_HTTPS), "https" (answers with the pinned certificate),
    "changed" (a different certificate: TEXT_STATION_CERT_CHANGED with TEXT_STATION_CERT_FIX) or "unreachable"."""
    if not url:
        return None
    if _station_info() is None:
        return "plain"
    try:
        StationClient(url, timeout=2, backoff=0).state()
    except StationCertChanged:
        return "changed"
    except StationUnreachable:
        return "unreachable"
    return "https"


def station_https_row(url: str | None) -> str | None:
    """The Checks row text for a Weigh Station that is not on HTTPS, else None: `TEXT_STATION_NOT_HTTPS_WHY` when the
    station said it could not make its certificate, `TEXT_STATION_NOT_HTTPS_AT` otherwise (an older station that has
    told the Hub no certificate). Only for a url whose `station_https` is "plain"."""
    if not url or station_https(url) != "plain":
        return None
    from . import pairing
    try:
        reason = pairing.station_plain_reason()
    except (OSError, ValueError):
        reason = None
    u = urllib.parse.urlsplit(url)
    address = f"{u.hostname}:{u.port}" if u.port else str(u.hostname)
    return (TEXT_STATION_NOT_HTTPS_WHY.format(address=address, reason=reason) if reason
            else TEXT_STATION_NOT_HTTPS_AT.format(address=address))

