"""The camera ticket and the camera session (R83 ruled 20:58 and 22:10).

An image request cannot carry the setup code, so the Hub page asks `POST printers/{id}/camera/ticket` with the code and
gets `{ticket, expires_in: 60}`. The FIRST camera request that carries `?ticket=` (the MJPEG stream, or the HLS
playlist) spends the ticket (`use_ticket`) and opens a camera SESSION, whose id the route sets as a cookie
(`session_cookie`). The session is for that printer's camera routes only, lasts 10 minutes and is moved forward by every
camera request that presents it (`verify_session`: a segment, the playlist again). It ends at `close_session`
(POST printers/{id}/camera/close, which needs only the cookie), after 10 idle minutes, at a restart or when the printer
is removed (`drop_printer`). At most MAX_SESSIONS are open at once.

Everything is in memory in the Hub process (a restart drops it, which costs a click), bounded, thread-safe, with every
secret compared in constant time. Nothing is written anywhere.
"""
from __future__ import annotations

import hmac
import secrets
import threading
import time
from urllib.parse import quote

TTL = 60                 # seconds a ticket waits for its first use
SESSION_TTL = 600        # seconds of idle a session lives (the Max-Age of its cookie)
MAX_LIVE = 256           # tickets
MAX_SESSIONS = 8
COOKIE_NAME = "fk_camera"
TOO_MANY = "Too many camera views are open. Close one first."

_lock = threading.Lock()
_tickets: dict[str, tuple[str, float]] = {}      # ticket -> (printer id, expires at), oldest first
_sessions: dict[str, tuple[str, float]] = {}     # session id -> (printer id, idle expiry)
_clock = time.monotonic


class TooManyViews(Exception):
    """MAX_SESSIONS camera sessions are open; str() is the sentence to show (TOO_MANY)."""

    def __init__(self):
        super().__init__(TOO_MANY)


def _now(clock) -> float:
    return (clock or _clock)()


def issue(printer_id: str, *, clock=None) -> dict:
    """A new ticket for `printer_id`: {ticket, expires_in}. 256 random bits, URL-safe. TooManyViews when MAX_SESSIONS
    camera sessions are open (a ticket could not open another)."""
    now = _now(clock)
    ticket = secrets.token_urlsafe(32)
    with _lock:
        _drop_expired(now)
        if len(_sessions) >= MAX_SESSIONS:
            raise TooManyViews()
        while len(_tickets) >= MAX_LIVE:
            del _tickets[next(iter(_tickets))]
        _tickets[ticket] = (str(printer_id), now + TTL)
    return {"ticket": ticket, "expires_in": TTL}


def _find(table: dict, secret) -> str | None:
    """The key of `table` equal to `secret`, comparing every key in constant time (no early exit)."""
    if not isinstance(secret, str) or not secret or len(secret) > 200:
        return None
    found = None
    for k in table:
        if hmac.compare_digest(k.encode(), secret.encode()) and found is None:
            found = k
    return found


def use_ticket(printer_id: str, ticket, *, clock=None) -> str | None:
    """Spend `ticket` and open a camera session for `printer_id`: the session id, or None when the ticket is unknown,
    expired, used, or another printer's (that one is not spent). TooManyViews when MAX_SESSIONS are open: the ticket is
    NOT spent then, so it can be used once a view is closed."""
    now = _now(clock)
    with _lock:
        _drop_expired(now)
        key = _find(_tickets, ticket)
        if key is None or not hmac.compare_digest(_tickets[key][0].encode(), str(printer_id).encode()):
            return None
        if len(_sessions) >= MAX_SESSIONS:
            raise TooManyViews()
        del _tickets[key]
        sid = secrets.token_urlsafe(32)
        _sessions[sid] = (str(printer_id), now + SESSION_TTL)
        return sid


def verify_session(printer_id: str, session_id, *, clock=None) -> bool:
    """True for a live session of `printer_id`, and its 10 idle minutes start again. Another printer's session, an
    unknown or an expired one: False."""
    now = _now(clock)
    with _lock:
        _drop_expired(now)
        key = _find(_sessions, session_id)
        if key is None or not hmac.compare_digest(_sessions[key][0].encode(), str(printer_id).encode()):
            return False
        _sessions[key] = (_sessions[key][0], now + SESSION_TTL)
        return True


def close_session(printer_id: str, session_id, *, clock=None) -> dict:
    """End the session (POST printers/{id}/camera/close). Always {"closed": True}: closing what is already gone, or a
    session that is not this printer's (which is left alone), is not an error."""
    now = _now(clock)
    with _lock:
        _drop_expired(now)
        key = _find(_sessions, session_id)
        if key is not None and hmac.compare_digest(_sessions[key][0].encode(), str(printer_id).encode()):
            del _sessions[key]
    return {"closed": True}


def drop_printer(printer_id: str) -> int:
    """The printer is removed: its tickets and sessions end. How many were dropped."""
    pid = str(printer_id)
    with _lock:
        gone = [(t, v) for table in (_tickets, _sessions) for t, v in table.items() if v[0] == pid]
        for t, _ in gone:
            _tickets.pop(t, None)
            _sessions.pop(t, None)
        return len(gone)


def session_cookie(printer_id: str, session_id: str) -> dict:
    """The cookie the route sets for a session, as data: name, value, path (only that printer's camera routes under the
    Hub page's base), max_age, http_only, secure, same_site."""
    return {"name": COOKIE_NAME, "value": session_id, "path": f"/setup/api/printers/{quote(str(printer_id), safe='')}/camera",
            "max_age": SESSION_TTL, "http_only": True, "secure": True, "same_site": "Strict"}


def set_cookie_header(printer_id: str, session_id: str, *, closing: bool = False) -> str:
    """`session_cookie` as a Set-Cookie header value; `closing`: the same cookie emptied and expired (the close route)."""
    c = session_cookie(printer_id, session_id)
    value, age = ("", 0) if closing else (c["value"], c["max_age"])
    return (f"{c['name']}={value}; Path={c['path']}; Max-Age={age}; HttpOnly; Secure; SameSite={c['same_site']}")


def purge(*, clock=None) -> int:
    """Drop what has expired; the number of tickets and sessions still live."""
    with _lock:
        _drop_expired(_now(clock))
        return len(_tickets) + len(_sessions)


def sessions_open(*, clock=None) -> int:
    with _lock:
        _drop_expired(_now(clock))
        return len(_sessions)


def clear() -> None:
    with _lock:
        _tickets.clear()
        _sessions.clear()


def _drop_expired(now: float) -> None:
    for table in (_tickets, _sessions):
        for t in [t for t, (_p, exp) in table.items() if exp <= now]:
            del table[t]
