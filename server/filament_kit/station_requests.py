"""Reverse pairing of an intake station on another machine (web console design §5, Q3): the station asks, the owner
approves on the setup page after comparing a code.

1. An unpaired station that knows the server's address (`station.allow`) sends `POST /api/station/pair-request`
   {request_id, name}: `request_id` is 32 random bytes as hex, made on the station and kept secret. The station trusts
   the server's certificate for this request only, and remembers its fingerprint.
2. Both sides derive the same six-digit comparison code from that fingerprint and the request id (`comparison_code`);
   the code never travels. The station shows it on its screen and says it; the setup page's Devices tab shows it next
   to the station's name and address.
3. The owner taps Pair only if the numbers match (with the setup code, as every change). A stranger on the network can
   ask too, but cannot make the owner's station show the code of the stranger's request.
4. The station polls `GET /api/station/pair-request/<request_id>`: 202 while it waits, 200 {token} once approved (the
   token goes out once; a station token reaches only /api/station/*), 410 when refused or expired.

At most MAX_PENDING requests wait at once, each for TTL seconds. The token waits here, root-free in the state folder
(600), for at most TTL after the approval.
"""
from __future__ import annotations

import hashlib
import re
import secrets
import time

from . import config, pairing

TTL = 600
MAX_PENDING = 3
FILE = "station-requests.json"
REQUEST_ID = re.compile(r"[0-9a-f]{64}")
ID = re.compile(r"[0-9a-f]{12}")


class RequestError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code = status, code


def comparison_code(fingerprint: str, request_id: str) -> str:
    """The six digits both sides show: from the server certificate's sha256 fingerprint (hex, any case, colons or
    spaces ignored) and the station's request id. The station side computes exactly this."""
    fp = re.sub(r"[^0-9a-f]", "", fingerprint.lower())
    digest = hashlib.sha256(f"filament-kit station pairing\n{fp}\n{request_id}".encode("ascii")).digest()
    return f"{int.from_bytes(digest[:4], 'big') % 1_000_000:06d}"


def _fingerprint() -> str:
    return pairing.fingerprint((config.paths().etc / "cert.pem").read_bytes())


def _clean_name(name) -> str:
    text = re.sub(r"[^\w .-]", "", str(name or ""))[:40].strip()
    return text or "station"


def _live(rows: list, now: float) -> list:
    return [r for r in rows if isinstance(r, dict) and r.get("expires", 0) > now]


def ask(request_id, name, address: str, now: float | None = None) -> dict:
    """A station's request: kept for TTL. Asking again with the same id just answers as before."""
    now = time.time() if now is None else now
    if not isinstance(request_id, str) or not REQUEST_ID.fullmatch(request_id):
        raise RequestError(400, "bad_request", "request_id must be 64 hex characters")
    with pairing._locked():
        rows = _live(pairing._read(FILE), now)
        mine = next((r for r in rows if r["request_id"] == request_id), None)
        if mine is None:
            if len([r for r in rows if r.get("state") == "pending"]) >= MAX_PENDING:
                raise RequestError(429, "too_many", "too many stations are asking to pair; try again in a few minutes")
            mine = {"id": secrets.token_hex(6), "request_id": request_id, "name": _clean_name(name),
                    "address": str(address)[:64], "asked": now, "expires": now + TTL, "state": "pending"}
            rows.append(mine)
        pairing._write(FILE, rows)
    return {"expires_in": int(mine["expires"] - now)}


def poll(request_id, now: float | None = None) -> tuple[int, dict]:
    """(HTTP status, body) for the station's poll."""
    now = time.time() if now is None else now
    if not isinstance(request_id, str) or not REQUEST_ID.fullmatch(request_id):
        return 404, {"error": "not_found", "message": "no such request"}
    with pairing._locked():
        rows = pairing._read(FILE)
        live = _live(rows, now)
        mine = next((r for r in live if r["request_id"] == request_id), None)
        if mine is None or mine.get("state") == "refused":
            if mine is not None:
                live.remove(mine)
            pairing._write(FILE, live)
            return 410, {"error": "gone", "message": "the request was refused or ran out; ask again"}
        if mine.get("state") == "approved":
            token = mine.pop("token")
            live.remove(mine)               # the token goes out once
            pairing._write(FILE, live)
            return 200, {"token": token}
        if len(live) != len(rows):
            pairing._write(FILE, live)
        return 202, {"state": "pending", "expires_in": int(mine["expires"] - now)}


def pending(now: float | None = None) -> list[dict]:
    """What the setup page shows: each waiting request with its comparison code."""
    now = time.time() if now is None else now
    fp = _fingerprint()
    with pairing._locked():
        rows = _live(pairing._read(FILE), now)
    return [{"id": r["id"], "name": r["name"], "address": r["address"], "code": comparison_code(fp, r["request_id"]),
             "expires_in": int(r["expires"] - now)} for r in rows if r.get("state") == "pending"]


def decide(rid: str, approve: bool, now: float | None = None) -> dict:
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
        p = pairing.issue(device_hint="station")
        token = pairing.redeem_code(p.code)          # claimed now: the device shows as paired at once
    with pairing._locked():
        rows = _live(pairing._read(FILE), now)
        mine = next((r for r in rows if r["id"] == rid), None)
        if mine is None:
            if token:
                pairing.revoke(pairing.authorize(token)[0])
            raise RequestError(404, "not_found", "no such request (it may have run out)")
        mine["state"] = "approved" if approve else "refused"
        if token:
            mine["token"] = token
        pairing._write(FILE, rows)
    return {"name": name, "approved": approve}
