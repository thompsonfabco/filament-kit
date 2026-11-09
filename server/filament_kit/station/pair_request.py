"""The station asks the kit server to pair it (reverse pairing, protocol version 2; the kit side is
filament_kit/station_requests.py, the protocol in the handoff 2026-11-09-1350-...-protocol-v2.md).

An unpaired station whose drop-in names the server (STATION_SERVER, from `station.allow`) asks once at start, and
again on a long press of yellow while it shows "Not paired":

1. It meets the server's certificate and pins its fingerprint for this request only.
2. It sends a commitment to a secret, gets the kit's nonce, then reveals the secret.
3. It shows the six digits (comparison_code) on the panel and says them; the owner compares them on the setup page
   (Devices) and taps Pair.
4. It polls; with the token it writes `pair/request.json` (fingerprint, token, port) into its own state folder. The
   station service cannot write its pairing files (they are root's, and the unit's file system is read-only), so a
   path unit starts filament-kit-station-pair.service, which saves them as root (pair_apply.py).

Nothing here is trusted beyond that request: the root side takes the server's address from `station.allow`, never from
this file, and checks the token against the pinned certificate before it saves anything.
"""
from __future__ import annotations

import http.client
import json
import logging
import os
import secrets
import threading
import time
from pathlib import Path

from .. import station_requests
from . import server_api

log = logging.getLogger("intake-station")

POLL = 3.0
LIMIT = station_requests.TTL
REQUEST_FILE = "request.json"
_running = threading.Lock()
status = {"state": "idle", "code": None, "message": ""}     # what the screen shows (flow.screen reads it)


def drop_dir() -> Path:
    """`pair/` in the station's own state folder (systemd's StateDirectory, owned by its service user)."""
    return Path(os.environ.get("STATE_DIRECTORY", "/var/lib/filament-kit-station").split(":")[0]) / "pair"


def server_address() -> tuple[str, int] | None:
    host = os.environ.get("STATION_SERVER", "").strip()
    if not host:
        return None
    try:
        return host, int(os.environ.get("STATION_SERVER_PORT", "8710"))
    except ValueError:
        return None


def _call(host: str, port: int, fp: str, method: str, path: str, body: dict | None = None,
          timeout: float = 15) -> tuple[int, dict]:
    """One request over a connection pinned to `fp` (server_api._Pinned): (status, JSON body or {})."""
    c = server_api._Pinned(host, port, fp, timeout)
    try:
        data = None if body is None else json.dumps(body).encode("utf-8")
        c.request(method, path, body=data, headers={"Content-Type": "application/json"} if data else {})
        r = c.getresponse()
        raw = r.read(64 * 1024)
        try:
            out = json.loads(raw or b"{}")
        except ValueError:
            out = {}
        return r.status, out if isinstance(out, dict) else {}
    finally:
        c.close()


def write_drop(fp: str, token: str, port: int, folder: Path | None = None) -> Path:
    """The approved pairing for the root side: written whole (a temporary file, then a rename), 0600."""
    d = folder or drop_dir()
    d.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = d / (REQUEST_FILE + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"fp": fp, "token": token, "port": port}, fh)
    os.replace(tmp, d / REQUEST_FILE)
    return d / REQUEST_FILE


def run_once(host: str, port: int, name: str, *, on_code=None, folder: Path | None = None,
             sleep=time.sleep, clock=time.monotonic) -> str:
    """Ask, show the code (`on_code(code)`), wait for the owner. Returns approved | refused | expired | failed."""
    try:
        fp = server_api.peer_fingerprint(host, port, timeout=server_api.CONNECT_TIMEOUT)
    except OSError as e:
        log.info("pairing request: the server at %s:%s does not answer (%s)", host, port, type(e).__name__)
        return "failed"
    request_id, secret = secrets.token_hex(32), secrets.token_hex(32)
    try:
        st, body = _call(host, port, fp, "POST", "/api/station/pair-request",
                         {"request_id": request_id, "commit": station_requests.commitment(secret), "name": name})
        if st != 202 or not station_requests.HEX64.fullmatch(str(body.get("nonce", ""))):
            log.info("pairing request refused: %s %s", st, body.get("error"))
            return "failed"
        nonce = body["nonce"]
        st, body = _call(host, port, fp, "POST", f"/api/station/pair-request/{request_id}/reveal", {"secret": secret})
        if st != 200:
            log.info("pairing reveal refused: %s %s", st, body.get("error"))
            return "failed"
        code = station_requests.comparison_code(fp, secret, nonce)
        if on_code is not None:
            on_code(code)
        end = clock() + LIMIT
        while clock() < end:
            st, body = _call(host, port, fp, "GET", f"/api/station/pair-request/{request_id}")
            if st == 200 and isinstance(body.get("token"), str):
                write_drop(fp, body["token"], port, folder)
                return "approved"
            if st in (404, 410):
                return "refused"
            sleep(POLL)
        return "expired"
    except (OSError, http.client.HTTPException) as e:
        log.info("pairing request: %s", type(e).__name__)
        return "failed"


def ask(name: str = "station", say=None, show=None) -> bool:
    """Run one request in the background, if the server is known and none runs yet. False when it did not start."""
    where = server_address()
    if where is None or not _running.acquire(blocking=False):
        return False

    def work():
        try:
            status.update(state="asking", code=None, message="")
            if show:
                show()

            def on_code(code):
                status.update(state="code", code=code)
                if show:
                    show()
                if say:
                    say(f"Pairing code {' '.join(code[:3])}, {' '.join(code[3:])}. Compare it on the setup page.")
            result = run_once(*where, name, on_code=on_code)
            status.update(state=result, code=None, message={
                "approved": "Paired: saving", "refused": "Not paired", "expired": "Ran out: hold yellow",
                "failed": "Server not reached"}.get(result, ""))
            if say:
                say({"approved": "Paired.", "refused": "Not paired.", "expired": "The pairing ran out.",
                     "failed": "The server did not answer."}.get(result, ""))
            if show:
                show()
        finally:
            _running.release()
    threading.Thread(target=work, daemon=True, name="station-pair").start()
    return True
