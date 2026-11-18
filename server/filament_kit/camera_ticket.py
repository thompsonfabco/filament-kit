"""The camera ticket (R83 ruled 20:58): an image request cannot carry the setup code, so the Hub page asks
`POST printers/{id}/camera/ticket` with the code, gets `{ticket, expires_in: 60}` and opens the stream with
`?ticket=<ticket>`.

A ticket starts ONE stream within 60 seconds, for THAT printer only, and is worthless afterwards (`verify` uses it up;
the stream then runs until it is closed). Tickets live in memory in the Hub process only (a restart drops them, which
costs a click), at most MAX_LIVE at a time (the oldest is dropped), nothing is written anywhere.
"""
from __future__ import annotations

import hmac
import secrets
import threading
import time

TTL = 60
MAX_LIVE = 256
_lock = threading.Lock()
_live: dict[str, tuple[str, float]] = {}        # ticket -> (printer id, expires at), oldest first
_clock = time.monotonic


def issue(printer_id: str, *, clock=None) -> dict:
    """A new ticket for `printer_id`: {ticket, expires_in}. 256 random bits, URL-safe."""
    now = (clock or _clock)()
    ticket = secrets.token_urlsafe(32)
    with _lock:
        _drop_expired(now)
        while len(_live) >= MAX_LIVE:
            del _live[next(iter(_live))]
        _live[ticket] = (str(printer_id), now + TTL)
    return {"ticket": ticket, "expires_in": TTL}


def verify(printer_id: str, ticket, *, clock=None) -> bool:
    """True once for an unexpired ticket issued for `printer_id`; the ticket is used up by a True answer (a stream
    that drops asks the page for a new one). A ticket of another printer is not used up. Compares every live ticket in
    constant time."""
    if not isinstance(ticket, str) or not ticket or len(ticket) > 200:
        return False
    now = (clock or _clock)()
    found = None
    with _lock:
        _drop_expired(now)
        for t, (pid, _exp) in _live.items():            # no early exit: the time does not tell which one matched
            if hmac.compare_digest(t.encode(), ticket.encode()) and found is None:
                found = (t, pid)
        if found is None or not hmac.compare_digest(found[1].encode(), str(printer_id).encode()):
            return False
        del _live[found[0]]
        return True


def purge(*, clock=None) -> int:
    """Drop the expired tickets; the number still live."""
    with _lock:
        _drop_expired((clock or _clock)())
        return len(_live)


def clear() -> None:
    with _lock:
        _live.clear()


def _drop_expired(now: float) -> None:
    for t in [t for t, (_p, exp) in _live.items() if exp <= now]:
        del _live[t]
