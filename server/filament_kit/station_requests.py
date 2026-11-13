"""Reverse pairing of an intake station on another machine (web console design §5, Q3): the station asks, the owner
approves on the setup page after comparing a code. Protocol version 2 (commit, then reveal):

1. An unpaired station that knows the server's address (`station.allow`) makes two random 32-byte values, as hex: a
   `request_id` (its name for this request, which it polls with) and a `secret`. It sends
   `POST /api/station/pair-request` {request_id, commit, name} with `commit = commitment(secret)`, trusting the
   server's certificate for this request only and remembering its fingerprint. The kit answers 202 {nonce}: a random
   value of its own.
2. Only then the station reveals: `POST /api/station/pair-request/<request_id>/reveal` {secret}. The kit checks it
   against the commitment. From here the request shows on the setup page.
3. Both sides derive the same six digits from the certificate's fingerprint, the secret and the kit's nonce
   (`comparison_code`); they never travel. The station shows them on its screen and says them; the Devices tab shows
   them next to the station's name and address. The owner taps Pair only if they match (with the setup code).
4. The station polls `GET /api/station/pair-request/<request_id>`: 202 while it waits, 200 {token} once approved (the
   token goes out again only within GRACE seconds, for a lost reply; a station token reaches only /api/station/*), 410
   when refused or expired.

Why the commitment: a man in the middle sees the station's values before the kit does. If the station chose the only
free input, the attacker could try request after request towards the kit until one showed the station's digits (a
million tries is about a second). Here the attacker has to commit towards the kit, and give the station a nonce,
before it learns the station's secret, so the two codes match only by a one-in-a-million chance.

At most MAX_PENDING requests wait at once, each for TTL seconds; an address the owner refused may not ask again
until its request would have run out. A token waits here (the state folder, 600) only until the station fetched it and
GRACE passed; an approval nobody fetches is revoked when it runs out.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time

from . import config, pairing

TTL = 600
# A security limit, not a tidiness one: commit-then-reveal stops a man in the middle only because unrevealed requests
# are few (3) and short-lived (TTL). Raising either gives such an attacker more tries at the six-digit code
# (audit v0.5.0, finding 4; R61).
MAX_PENDING = 3
GRACE = 120     # seconds a fetched token can be fetched again (a lost reply); 0 gives it out once, as before
FILE = "station-requests.json"
HEX64 = re.compile(r"[0-9a-f]{64}")
REQUEST_ID = HEX64
ID = re.compile(r"[0-9a-f]{12}")


class RequestError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code = status, code


def commitment(secret: str) -> str:
    """What the station sends before it reveals its secret."""
    return hashlib.sha256(f"filament-kit station pairing commit\n{secret}".encode("ascii")).hexdigest()


def comparison_code(fingerprint: str, secret: str, nonce: str) -> str:
    """The six digits both sides show: from the server certificate's sha256 fingerprint (hex, any case, colons or
    spaces ignored), the station's revealed secret and the kit's nonce. The station side computes exactly this."""
    fp = re.sub(r"[^0-9a-f]", "", fingerprint.lower())
    digest = hashlib.sha256(f"filament-kit station pairing v2\n{fp}\n{secret}\n{nonce}".encode("ascii")).digest()
    return f"{int.from_bytes(digest[:4], 'big') % 1_000_000:06d}"


def _fingerprint() -> str:
    return pairing.fingerprint((config.paths().etc / "cert.pem").read_bytes())


def _clean_name(name) -> str:
    text = re.sub(r"[^\w .-]", "", str(name or ""))[:40].strip()
    return text or "station"


_UNFETCHED: list[str] = []      # tokens of approvals that ran out unfetched: revoked once the lock is released


def _live(rows: list, now: float) -> list:
    """The rows still within their window. An approval nobody fetched in time is noted for revoking (`_drop_unfetched`,
    called after the pairing lock is released: pairing.revoke takes that lock too)."""
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        if r.get("expires", 0) > now:
            if r.get("state") == "fetched" and now - r.get("fetched", 0) > GRACE:
                r.pop("token", None)        # the grace for a lost reply is over
            out.append(r)
        elif r.get("state") == "approved" and r.get("token"):
            _UNFETCHED.append(r["token"])
    return out


def _drop_unfetched() -> None:
    while _UNFETCHED:
        got = pairing.authorize(_UNFETCHED.pop())
        if got is not None:
            pairing.revoke(got[0])


def _ask(request_id, commit, name, address: str, now: float | None = None) -> dict:
    """A station's request with its commitment: kept for TTL. Asking again with the same id answers as before."""
    now = time.time() if now is None else now
    if not isinstance(request_id, str) or not HEX64.fullmatch(request_id):
        raise RequestError(400, "bad_request", "request_id must be 64 hex characters")
    if not isinstance(commit, str) or not HEX64.fullmatch(commit):
        raise RequestError(400, "bad_request", "commit must be 64 hex characters (protocol version 2)")
    address = str(address)[:64]
    with pairing._locked():
        rows = _live(pairing._read(FILE), now)
        mine = next((r for r in rows if r["request_id"] == request_id), None)
        if mine is None:
            if any(r.get("state") == "refused" and r.get("address") == address for r in rows):
                raise RequestError(429, "refused", "the owner refused a request from this address; try again later")
            if len([r for r in rows if r.get("state") in ("committed", "pending")]) >= MAX_PENDING:
                raise RequestError(429, "too_many", "too many stations are asking to pair; try again in a few minutes")
            mine = {"id": secrets.token_hex(6), "request_id": request_id, "commit": commit,
                    "nonce": secrets.token_hex(32), "name": _clean_name(name), "address": address, "asked": now,
                    "expires": now + TTL, "state": "committed"}
            rows.append(mine)
        elif mine.get("commit") != commit:
            raise RequestError(409, "conflict", "this request was made with another commitment")
        pairing._write(FILE, rows)
    return {"nonce": mine["nonce"], "expires_in": int(mine["expires"] - now)}


def _reveal(request_id, secret, now: float | None = None) -> dict:
    """The station's secret, after it got the kit's nonce: from now on the owner sees the request."""
    now = time.time() if now is None else now
    if not isinstance(request_id, str) or not HEX64.fullmatch(request_id):
        raise RequestError(404, "not_found", "no such request")
    if not isinstance(secret, str) or not HEX64.fullmatch(secret):
        raise RequestError(400, "bad_request", "secret must be 64 hex characters")
    with pairing._locked():
        rows = _live(pairing._read(FILE), now)
        mine = next((r for r in rows if r["request_id"] == request_id), None)
        if mine is None:
            raise RequestError(404, "not_found", "no such request (it may have run out)")
        if not hmac.compare_digest(commitment(secret), mine["commit"]):
            raise RequestError(400, "bad_request", "the secret does not match the commitment")
        if mine.get("state") == "committed":
            mine["secret"], mine["state"] = secret, "pending"
        # any other state: the secret was revealed already, and the commitment check above makes this the same secret
        pairing._write(FILE, rows)
    return {"state": "pending", "expires_in": int(mine["expires"] - now)}


def _poll(request_id, now: float | None = None) -> tuple[int, dict]:
    """(HTTP status, body) for the station's poll."""
    now = time.time() if now is None else now
    if not isinstance(request_id, str) or not HEX64.fullmatch(request_id):
        return 404, {"error": "not_found", "message": "no such request"}
    with pairing._locked():
        rows = pairing._read(FILE)
        live = _live(rows, now)
        mine = next((r for r in live if r["request_id"] == request_id), None)
        if mine is None or mine.get("state") == "refused":
            pairing._write(FILE, live)
            return 410, {"error": "gone", "message": "the request was refused or ran out; ask again"}
        if mine.get("state") == "approved":
            mine["state"], mine["fetched"] = "fetched", now     # kept until it runs out: the refused-address rule needs no gap
            pairing._write(FILE, live)
            return 200, {"token": mine["token"]}
        if mine.get("state") == "fetched":
            # a reply lost on the way (Wi-Fi drop): the station's next poll gets the same token, for GRACE seconds
            if mine.get("token") and now - mine.get("fetched", 0) <= GRACE:
                return 200, {"token": mine["token"]}
            pairing._write(FILE, live)          # _live dropped the token
            return 410, {"error": "gone", "message": "the pairing was given out already"}
        if len(live) != len(rows):
            pairing._write(FILE, live)
        return 202, {"state": mine["state"], "expires_in": int(mine["expires"] - now)}


def _pending(now: float | None = None) -> list[dict]:
    """What the setup page shows: each revealed request with its comparison code."""
    now = time.time() if now is None else now
    fp = _fingerprint()
    with pairing._locked():
        rows = pairing._read(FILE)
        live = _live(rows, now)
        if len(live) != len(rows):
            pairing._write(FILE, live)
    return [{"id": r["id"], "name": r["name"], "address": r["address"],
             "code": comparison_code(fp, r["secret"], r["nonce"]), "expires_in": int(r["expires"] - now)}
            for r in live if r.get("state") == "pending"]


def _decide(rid: str, approve: bool, now: float | None = None) -> dict:
    """The owner's answer. Approving pairs a station device (scope station) whose token the station's next poll gets."""
    now = time.time() if now is None else now
    if not isinstance(rid, str) or not ID.fullmatch(rid):
        raise RequestError(404, "not_found", "no such request")
    with pairing._locked():
        rows = _live(pairing._read(FILE), now)
        mine = next((r for r in rows if r["id"] == rid and r.get("state") == "pending"), None)
        if mine is None:
            raise RequestError(404, "not_found", "no such request (it may have run out)")
        name = mine["name"]
    token = None
    if approve:
        p = pairing.issue(device_hint="station" if name == "station" else f"station: {name}", scope="station")
        token = pairing.redeem_code(p.code)          # claimed now: the device shows as paired at once
    with pairing._locked():
        rows = _live(pairing._read(FILE), now)
        mine = next((r for r in rows if r["id"] == rid and r.get("state") == "pending"), None)
        if mine is not None:
            mine["state"] = "approved" if approve else "refused"
            if token:
                mine["token"] = token
            pairing._write(FILE, rows)
    if mine is None:
        # gone between the two sections (answered twice, expired): the device just paired is revoked here, with the lock
        # released: authorize and revoke take it too, and it is not reentrant
        if token:
            pairing.revoke(pairing.authorize(token)[0])
        raise RequestError(404, "not_found", "no such request (it may have run out)")
    return {"name": name, "approved": approve}


def _then_drop(fn):
    def run(*a, **k):
        try:
            return fn(*a, **k)
        finally:
            _drop_unfetched()
    run.__doc__ = fn.__doc__
    return run


ask, reveal, poll, pending, decide = (_then_drop(f) for f in (_ask, _reveal, _poll, _pending, _decide))
