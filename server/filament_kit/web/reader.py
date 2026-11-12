"""The Printer Station reader API (firmware: reader/README.md, whose contract this file follows exactly).

Routes of the web process, under `<public path>/reader` (nginx strips the public path), LAN only (`auth.lan_only`
and a check here), every one with the reader token in `X-Auth-Token`:

    GET  /reader/healthz                  200 "ok" (the reader keeps a fresh firmware update only if this answers,
                                          so an image built with a revoked token rolls itself back)
    GET  /reader/fw/manifest.json         the OTA files tools/ota_publish.py copies into FK_STATE/reader-fw
    GET  /reader/fw/firmware.bin          (/var/lib/filament-kit/reader-fw), as the old nginx /h2d/fw/ served them
    GET  /reader/printers                 [{id, name, say}]: the kit's configured printers, ids as strings
    GET  /reader/printers/{id}/slots      [{label, say, kind, present, type, spool}] in knob order (kind "ext" of
                                          the kit is "external" here); at most MAX_SLOTS and MAX_SLOTS_JSON bytes,
                                          cut at the end with a {"note"} entry (no label: the firmware skips it)
    POST /reader/scan {uid, printer, slot, dry_run}
                                          {status, message, filament}; status one of set | queued | unknown_tag |
                                          unknown_spool | archived_spool | no_preset | offline | error (the
                                          scanner's /set-slot statuses; set and queued always with 200)

A scan loads the tag's spool into the slot through the kit server's own load route (KitApi, as the MCP printer
tools do): the user's exact preset or `no_preset`, never Generic (bridge/loading.py); mid-print only the slot that
feeds the job is refused (Ruling BK: `slot_in_use`). The reply comes within SCAN_WAIT seconds of the request
(a deadline from the start of the scan) even when the printer's confirmation takes longer (the firmware waits
6 s): the load goes on in the background and the reply says "sent". Queue-on-empty (ported from the scanner): a
slot the printer reports empty (`present` false) or still reading its tag is not set at once (the AMS resets a
slot when filament goes in);
the preset is checked with a dry run, then the tap waits in LoadQueue (memory only, QUEUE_TTL 900 s) until the slot
is present and read, SETTLE 3 s more, is sent, and VERIFY_AFTER 4 s later must show the preset (`preset_id`, type),
else it is sent again, MAX_TRIES 3 in all. A direct set of a slot replaces its queued tap. An unknown presence
(`present` null) is sent directly, as the scanner did when its state was unknown. A refusal that will not change
by waiting (write_refused, needs_developer_mode, no_preset, not_found) drops the job; a passing one (printer_busy,
already_running, slot_in_use, unreachable, ...) keeps it waiting, logged only when the reason changes.

Deviation from the scanner (1): the scanner wrote Spoolman only once the setting was verified; here each queued
send is a kit load, which updates Spoolman when the printer takes the write. If all MAX_TRIES fail to stick,
Spoolman already shows the spool in that slot (logged); a later tap or load corrects it.

Reader tokens: `filament-kit reader token [--name X]` (root) prints a new one once, for the reader's secrets.h;
only its sha256 is kept, in FK_STATE/web/reader_tokens (XML, 0600, the service user's; the root's `next-id` keeps
ids monotonic, so a revoked id is never reused), `reader tokens` lists them and `reader revoke <id|name>` removes
one. A token file that does not validate accepts no token (and is never
overwritten by the CLI), so a damaged file fails closed.
"""
from __future__ import annotations

import concurrent.futures
import functools
import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse
from starlette.routing import Route

from .. import config, inventory, tags
from ..spoolman import SpoolmanError
from . import auth, slots
from ..reader_tokens import (MAX_FILE, MAX_TOKENS, SHA256, TOKEN_ID, TokenFileError,  # noqa: F401
                             TokenStore, _clean_name, _hash, parse_tokens, render_tokens, token_file)
from .errors import Problem

log = logging.getLogger(__name__)

SCAN_WAIT = 4.0              # seconds from the start of a scan to its reply at the latest (firmware timeout: 6 s)
MIN_WAIT = 0.5               # the load gets at least this long, even when the lookups used up SCAN_WAIT
QUEUE_TTL = 900              # seconds a tap on an empty slot waits for the filament
SETTLE, VERIFY_AFTER, MAX_TRIES = 3, 4, 3
POLL = 2.0                   # seconds between queue checks
WAIT_POLL = 10.0             # seconds between sends of a job whose last send was refused (busy, unreachable ...)
# kit refusals that waiting does not change: the queued tap is dropped (others keep it waiting)
FINAL_REFUSALS = ("no_preset", "not_found", "write_refused", "needs_developer_mode", "unpaired")
MAX_SLOTS = 128              # the firmware keeps at most 128 slots ...
MAX_SLOTS_JSON = 16 * 1024   # ... and holds the whole reply in its small RAM: keep the JSON under 16 KB
FW_FILES = {"manifest.json": "application/json", "firmware.bin": "application/octet-stream"}
OFFLINE_STATES = {"offline", "not_configured", "wrong_code", "cert_changed", "connecting"}
STATUSES = ("set", "queued", "unknown_tag", "unknown_spool", "archived_spool", "no_preset", "offline", "error")


def fw_dir() -> Path:
    return config.paths().state / "reader-fw"


# ---------- queue-on-empty ----------

@dataclass
class Job:
    spool_id: int
    at: float
    seen: float | None = None
    sent: float = 0.0
    tries: int = 0
    preset: dict | None = None
    waiting: str | None = None        # why the last send was refused (logged when it changes)
    tried: float = 0.0                # when a send was last attempted (refused or not)


class LoadQueue:
    """Taps on empty slots, keyed (printer id, label), kept in memory. `kit_fn()` -> the kit server's API."""

    def __init__(self, kit_fn=None, *, clock=time.time, start_thread: bool = True):
        self.kit_fn = kit_fn
        self.clock = clock
        self._start_thread = start_thread
        self._jobs: dict[tuple[str, str], Job] = {}
        self._lock = threading.Lock()
        self._sends: dict[tuple[str, str], threading.Lock] = {}   # held around a queued send, per slot
        self._thread: threading.Thread | None = None

    def add(self, printer: str, label: str, spool_id: int, preset: dict | None = None) -> None:
        with self._lock:
            self._jobs[(printer, label)] = Job(int(spool_id), self.clock(), preset=preset)
        self._ensure_thread()

    def _send_lock(self, key: tuple[str, str]) -> threading.Lock:
        with self._lock:
            return self._sends.setdefault(key, threading.Lock())

    def drop(self, printer: str, label: str) -> None:
        """Forget the queued tap for that slot. A send of it already in progress finishes first (at most the kit
        API's timeout), so a direct set made after drop() always lands after the older tap, never before it; a
        tap not yet sent is never sent (final review M5)."""
        key = (printer, label)
        with self._send_lock(key):
            with self._lock:
                self._jobs.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._jobs.clear()

    def jobs(self) -> dict[tuple[str, str], Job]:
        with self._lock:
            return dict(self._jobs)

    def _ensure_thread(self) -> None:
        if not self._start_thread:
            return
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="reader-queue", daemon=True)
                self._thread.start()

    def _run(self) -> None:
        while True:
            time.sleep(POLL)
            self.tick()

    def tick(self) -> None:
        for key, job in self.jobs().items():
            try:
                self._process(key, job)
            except Exception as e:  # noqa: BLE001 - one bad job must not stop the others; it expires
                self._wait(key, job, type(e).__name__, f"{type(e).__name__}: {e}")

    @staticmethod
    def _wait(key, job: Job, reason: str, text: str) -> None:
        """Keep the job; log only when the reason it waits for changes (no line every POLL seconds)."""
        if job.waiting != reason:
            job.waiting = reason
            log.warning("queued %s %s spool %s waits: %s", key[0], key[1], job.spool_id, text)

    def _done(self, key, job: Job, why: str) -> None:
        with self._lock:
            if self._jobs.get(key) is job:
                self._jobs.pop(key)
        log.info("queued %s %s spool %s: %s", key[0], key[1], job.spool_id, why)

    def _slot(self, kit, printer: str, label: str) -> dict | None:
        """The slot as the printer reports it now, or None when that is unknown (offline, no presence)."""
        try:
            view = kit.get(slots.printer_path(printer))
        except slots.SlotError:
            return None
        if (view.get("printer") or {}).get("state") in OFFLINE_STATES:
            return None
        s = next((s for s in slots.status_slots(view.get("status") or {}) if s.get("label") == label), None)
        return s if s is not None and s.get("present") is not None else None

    def _process(self, key, job: Job) -> None:
        printer, label = key
        now = self.clock()
        if now - job.at > QUEUE_TTL:
            return self._done(key, job, "expired, the filament was never loaded")
        if job.waiting and now - job.tried < WAIT_POLL:
            return                             # a refused send: back off (no kit call every POLL seconds)
        kit = self.kit_fn()
        st = self._slot(kit, printer, label)
        if st is None:
            return
        if not st.get("present") or st.get("reading"):
            job.seen = None
            return
        if job.seen is None:
            job.seen = now                     # just detected: let the AMS finish its own reset first
            return
        if now - job.seen < SETTLE or (job.sent and now - job.sent < VERIFY_AFTER):
            return
        p = job.preset or {}
        if job.sent and p and st.get("type") == p.get("filament_type") and st.get("preset_id") == p.get("filament_id"):
            return self._done(key, job, f"set to {p.get('name')} after loading")
        if job.tries >= MAX_TRIES:
            return self._done(key, job, f"the printer did not keep the setting after {MAX_TRIES} tries (slot shows "
                                        f"{st.get('type')!r} {st.get('preset_id')!r})")
        with self._send_lock(key):
            with self._lock:
                if self._jobs.get(key) is not job:
                    return                     # dropped (a direct set replaced it) or re-queued: stale, not sent
            job.tried = now
            try:
                r = kit.post(slots.load_path(printer, label),
                             {"spool_id": job.spool_id, "dry_run": False})
            except slots.SlotError as e:
                if e.code in FINAL_REFUSALS:
                    return self._done(key, job, f"refused ({e.code}): {e}")
                return self._wait(key, job, e.code or "error", f"{e.code or 'error'}: {e}")   # not a try
        job.waiting = None
        job.preset = (r or {}).get("preset") or job.preset
        job.sent, job.tries = self.clock(), job.tries + 1


# ---------- routes ----------

MAX_TEXT = 40               # the firmware cuts every string field at 40 bytes ...
MAX_ID = 64                 # ... and skips a printer whose id is longer than 64 bytes


def clip(v, n: int = MAX_TEXT) -> str:
    """`v` as text of at most `n` UTF-8 bytes (cut on a character boundary)."""
    b = str(v if v is not None else "").encode("utf-8")
    return b[:n].decode("utf-8", "ignore") if len(b) > n else b.decode("utf-8")


def say_tokens(say) -> list[str]:
    """`say` (a string or a list) as a list of tokens, none over 40 bytes (a longer one cannot be a firmware word
    anyway; cut, it beeps)."""
    words = say.split() if isinstance(say, str) else [w for x in say or () for w in str(x).split()]
    return [clip(w) for w in words if w]


def fits(v, n: int) -> bool:
    return len(str(v).encode("utf-8")) <= n


def reply(code: int, status: str, message: str = "", **extra) -> JSONResponse:
    body = {"status": status, "message": message, **extra}
    return JSONResponse({k: clip(v) if isinstance(v, str) else v for k, v in body.items()}, status_code=code)


def _kit_error(e: slots.SlotError) -> JSONResponse:
    """A kit server refusal as the reader's status (the message is the kit's own text)."""
    msg = str(e)
    if e.code == "no_preset":
        return reply(200, "no_preset", msg)
    if e.code in ("printer_offline", "cert_changed"):
        return reply(200, "offline", msg)
    if e.code == "not_found":
        return reply(404, "error", msg)
    if e.code in ("printer_busy", "already_running", "needs_developer_mode", "write_refused", "module_off",
                  "slot_in_use"):
        return reply(409, "error", msg)
    return reply(502, "error", msg)


def _spool_name(s: dict) -> str:
    f = s.get("filament") or {}
    return f"{(f.get('vendor') or {}).get('name') or ''} {f.get('name') or ''}".strip() or f"spool {s.get('id')}"


def _short_spool(v) -> dict | None:
    if not isinstance(v, dict) or v.get("id") is None:
        return None
    return {"id": v["id"], "name": clip(v.get("name") or f"spool {v['id']}")}


def reader_slots(rows: list[dict], printer: str = "") -> list[dict]:
    """The slots the firmware can tell apart: it keeps and sends back a label as is, cut at 40 bytes, and the kit
    matches labels whatever their case and surrounding spaces (`slots.label_key`). A label over 40 bytes is left
    out rather than cut (kit labels are short), and of slots with the same key only the first is listed (the one
    `slots.kit_label` picks for it)."""
    seen, out = set(), []
    for s in rows:
        key = slots.label_key(s["label"])
        if not fits(s["label"], MAX_TEXT) or key in seen:
            log.warning("reader: printer %s slot %s left out of the list (%s)", _safe(printer), _safe(s["label"]),
                        "listed twice" if key in seen else f"label over {MAX_TEXT} bytes")
            continue
        seen.add(key)
        out.append(s)
    return out


def cap_slots(rows: list[dict], printer: str = "") -> list[dict]:
    """At most MAX_SLOTS rows and MAX_SLOTS_JSON bytes of JSON: rows are cut at the end, and a last entry without a
    label (the firmware skips it) says how many are left out."""
    def body(part: list[dict]) -> list[dict]:
        left = len(rows) - len(part)
        return part + [{"note": f"{left} more slots not listed"}] if left else part

    out = rows[:MAX_SLOTS]
    while out and len(json.dumps(body(out), ensure_ascii=False).encode("utf-8")) > MAX_SLOTS_JSON:
        out = out[:-1]
    if len(out) < len(rows):
        log.warning("reader: printer %s has %d slots; the list is cut to %d", _safe(printer), len(rows), len(out))
    return body(out)


class Reader:
    def __init__(self, tools, sm, *, lan_cidrs=(), tokens: TokenStore | None = None, queue: LoadQueue | None = None):
        self.tools, self.sm = tools, sm
        self.nets = auth.parse_lan(lan_cidrs)
        self.tokens = tokens if tokens is not None else TokenStore()
        self.queue = queue if queue is not None else LoadQueue(tools.kit_bridge)
        if self.queue.kit_fn is None:
            self.queue.kit_fn = tools.kit_bridge
        self._pool = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="reader-load")

    # --- plumbing ---

    def _lan(self, request: Request) -> bool:
        return auth.is_lan(request.client.host if request.client else "", self.nets)

    def _gated(self, fn):
        @functools.wraps(fn)
        async def wrapper(request: Request):
            if not self._lan(request):
                return reply(403, "error", "home network only")
            if not await run_in_threadpool(self.tokens.check, request.headers.get("x-auth-token")):
                return reply(401, "error", "unauthorized: run filament-kit reader token")
            try:
                return await fn(request)
            except slots.SlotError as e:
                return _kit_error(e)
            except Problem as e:
                return reply(409, "error", str(e))
            except SpoolmanError as e:
                return reply(502, "error", "Spoolman is not reachable" if e.status is None else str(e))
        return wrapper

    def routes(self) -> list[Route]:
        return [Route("/reader/healthz", self._gated(self.healthz), methods=["GET"]),
                Route("/reader/fw/{name}", self._gated(self.fw), methods=["GET"]),
                Route("/reader/printers", self._gated(self.printers), methods=["GET"]),
                Route("/reader/printers/{id}/slots", self._gated(self.slot_list), methods=["GET"]),
                Route("/reader/scan", self._gated(self.scan), methods=["POST"])]

    # --- handlers ---

    async def healthz(self, request: Request):
        return PlainTextResponse("ok")

    async def fw(self, request: Request):
        name = request.path_params["name"]
        path = fw_dir() / name
        if name not in FW_FILES or not path.is_file():
            return reply(404, "error", "no firmware published (tools/ota_publish.py)")
        return FileResponse(path, media_type=FW_FILES[name], headers={"Cache-Control": "no-store"})

    async def printers(self, request: Request):
        def build() -> list[dict]:
            from ..bridge import hardware
            try:
                hw = hardware.load()
            except Exception:  # noqa: BLE001 - the list must still answer
                log.exception("hardware data cannot be loaded")
                hw = None
            out = []
            for p in slots.kit_printers(self.tools.kit_bridge()):
                pid = str(p["id"])
                if not fits(pid, MAX_ID):            # the firmware would skip it; it cannot be cut (sent back)
                    log.warning("reader: printer id longer than %d bytes left out of the list", MAX_ID)
                    continue
                say = hw.model(p.get("model")).say if hw is not None else None
                out.append({"id": pid, "name": clip(p.get("name") or pid), "say": say_tokens(say or "printer")})
            return out
        return JSONResponse(await run_in_threadpool(build))

    async def slot_list(self, request: Request):
        pid = request.path_params["id"]

        def build() -> list[dict]:
            view = self.tools.kit_bridge().get(slots.printer_path(pid))
            return cap_slots([{"label": s["label"], "say": say_tokens(s.get("say")),
                     "kind": clip("external" if s.get("kind") == "ext" else s.get("kind") or ""),
                     "present": s.get("present") if isinstance(s.get("present"), bool) else None,
                     "type": clip(s.get("type") or ""), "spool": _short_spool(s.get("spool"))}
                    for s in reader_slots(slots.status_slots(view.get("status") or {}), pid)], pid)
        return JSONResponse(await run_in_threadpool(build))

    async def scan(self, request: Request):
        try:
            body = json.loads(await request.body() or b"{}")
        except ValueError:
            return reply(400, "error", "the body must be JSON")
        if not isinstance(body, dict):
            return reply(400, "error", "the body must be a JSON object")
        printer, label, dry = body.get("printer"), body.get("slot"), body.get("dry_run", False)
        if isinstance(printer, int) and not isinstance(printer, bool):
            printer = str(printer)
        if not isinstance(printer, str) or not printer or not isinstance(label, str) or not label.strip():
            return reply(400, "error", "printer and slot are required")
        if not isinstance(dry, bool):
            return reply(400, "error", "dry_run must be true or false")
        try:
            uid = tags.normalize_uid(str(body.get("uid") or ""))
        except ValueError as e:
            return reply(400, "error", str(e))
        res = await run_in_threadpool(self._scan, uid, printer, label.strip(), dry)
        log.info("reader scan printer=%s slot=%s dry_run=%s status=%s", _safe(printer), _safe(label), dry,
                 json.loads(res.body).get("status"))
        return res

    def _scan(self, uid: str, printer: str, slot: str, dry: bool) -> JSONResponse:
        deadline = time.monotonic() + SCAN_WAIT
        sp = inventory.by_tag(self.sm, uid)
        if sp is None:
            return reply(200, "unknown_tag", f"Tag {uid} is not linked to a spool")
        name = _spool_name(sp)
        if sp.get("archived"):
            return reply(200, "archived_spool", f"Spool {sp['id']} is archived", filament=name)
        kit = self.tools.kit_bridge()
        try:
            view = kit.get(slots.printer_path(printer))
        except slots.SlotError as e:
            return _kit_error(e) if e.code != "not_found" else reply(404, "error", f"no printer {printer}")
        pv = view.get("printer") or {}
        pname = pv.get("name") or printer
        if pv.get("state") in OFFLINE_STATES:
            return reply(200, "offline", f"{pname} is {pv.get('state').replace('_', ' ')}", filament=name)
        found = slots.status_slots(view.get("status") or {})
        try:
            label = slots.kit_label(slot, [s["label"] for s in found])
        except slots.SlotError:
            return reply(404, "error", f"{pname} has no slot {slot}", filament=name)
        cur = next((s for s in found if s["label"] == label), {})
        path = slots.load_path(printer, label)
        load = {"spool_id": int(sp["id"]), "dry_run": True}
        if cur.get("present") is False or cur.get("reading") is True:
            r = kit.post(path, load)                       # the preset check; nothing is sent
            preset = (r or {}).get("preset") or {}
            extra = {"filament": name, "preset": preset.get("name"), "slot": label}
            msg = f"{label} empty: load it now (waits {QUEUE_TTL // 60} min)"
            if dry:
                return reply(200, "queued", msg, dry_run=True, **extra)
            self.queue.add(printer, label, int(sp["id"]), preset or None)
            log.info("queued %s %s spool %s until the filament is loaded", _safe(printer), label, sp["id"])
            return reply(200, "queued", msg, **extra)
        if dry:
            r = kit.post(path, load)
            preset = (r or {}).get("preset") or {}
            return reply(200, "set", f"{label}: {preset.get('name')}", filament=name, preset=preset.get("name"),
                         slot=label, dry_run=True)
        self.queue.drop(printer, label)                   # a direct set replaces an older queued tap
        fut = self._pool.submit(kit.post, path, {**load, "dry_run": False})
        try:
            r = fut.result(timeout=max(MIN_WAIT, deadline - time.monotonic()))
        except concurrent.futures.TimeoutError:
            fut.add_done_callback(functools.partial(_late, printer, label))
            return reply(200, "set", f"{label}: sent", filament=name, slot=label)
        preset = (r or {}).get("preset") or {}
        msg = f"{label}: {preset.get('name') or 'set'}"
        if r and r.get("confirmed") is False:
            msg = "(not confirmed) " + msg          # first: the 40-byte cut must keep it
        return reply(200, "set", msg, filament=name, preset=preset.get("name"), slot=label)


def _late(printer: str, label: str, fut: concurrent.futures.Future) -> None:
    """A load that outlived SCAN_WAIT: its outcome goes to the log (the reader was told "sent")."""
    e = fut.exception()
    if e is not None:
        log.error("reader load %s %s failed after the reply: %s: %s", _safe(printer), label, type(e).__name__, e)
    elif (fut.result() or {}).get("confirmed") is False:
        log.warning("reader load %s %s: the printer did not confirm the setting", _safe(printer), label)


def _safe(v) -> str:
    s = str(v)
    return s if re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", s) else "<invalid>"


__all__ = ["LoadQueue", "Reader", "cap_slots", "TokenFileError", "TokenStore", "parse_tokens", "render_tokens"]
