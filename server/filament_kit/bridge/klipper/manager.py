"""KlipperFamily: every configured Klipper printer's Moonraker connection, its live state and status (spec §4.2, §8).

One `_Conn` per printer in the registry (`family="klipper"`, configured). Its worker thread sets the printer up
(`/printer/info`, object list, database namespaces → `detect`, the active spool, webcams) and then keeps a websocket
`Subscriber` on the common objects plus the filament system's own; Klipper restarting (`notify_klippy_*`) or the
printer going away sends it back to set-up with doubling backoff. Status is kept merged in memory, so a printer that
drops keeps showing its last values (`updated` says when).

States: `connected`, `unknown_model` (connected, no model entry matched: the generic one is in use), `offline`,
`klippy_not_ready` (Klipper's message is `status.notes[0]`), `unauthorized` (Moonraker wants an API key),
`connecting` (first set-up not done yet), `not_configured` (not in the registry).

`status(pid)` has the Bambu `status.summarize` keys; the units/slots come from the filament-system adapter, and a slot
shows the Spoolman spool whose id the printer shows (spool list cached 30 s). Listeners (`add_listener(fn)`) are called
as `fn(pid, event, data)` with event `status` (a delta arrived), `spool` (a slot's spool may have changed) or `klippy`.
Loads, unloads, follow mode and the usage log are in `loads.py` and `usage.py` (KlipperFamily mixes them in).
"""
from __future__ import annotations

import logging
import math
import threading
import time
import urllib.parse
from pathlib import Path

from ... import config
from .. import registry
from ..connection import PrinterOffline, UnknownPrinter
from . import adapters, detect, discovery, lanes
from . import usage as kusage
from . import hardware as kh
from .adapters.base import UnitState
from .loads import LoadsMixin
from .moonraker import Moonraker, MoonrakerError, Offline, Subscriber, Unauthorized

log = logging.getLogger(__name__)
COMMON = ("print_stats", "toolhead", "virtual_sdcard", "heater_bed", "webhooks", "display_status")
GCODE_STATE = {"printing": "RUNNING", "paused": "PAUSE", "complete": "FINISH", "cancelled": "FAILED",
               "error": "FAILED", "standby": "IDLE"}
SPOOL_CACHE = 30.0
OFFLINE_AFTER = 10.0    # seconds a websocket may be down before the printer reads as offline
SYNC_EVERY = 15.0       # seconds between registry re-reads (the CLI edits it in another process)
HISTORY_WAIT = 10.0     # seconds to wait for Moonraker to close a finished job's history entry
SCAN_GAP = 30.0         # seconds from the end of one scan to the start of the next
ONLINE = ("connected", "unknown_model")
SYSTEM_WORDS = {"single": "a single-extruder printer", "tool-macros": "a toolchanger", "afc": "an AFC printer",
                "happy-hare": "a Happy Hare printer", "lane-data": "a printer with lane_data"}


def generic_note(system_key: str) -> str:
    """The status note for a printer no model entry matched: generic is `verified`, so only this says so."""
    return (f"No model entry matched this printer, so the kit uses its generic rules for "
            f"{SYSTEM_WORDS.get(system_key, f'a {system_key} printer')}. It works; the Klipper guide says how to add an "
            f"entry.")


def printer_dir(pid: str) -> Path:
    return config.paths().state / "printers" / pid


class _Conn:
    def __init__(self, fam: "KlipperFamily", p: registry.Printer):
        self.fam, self.p = fam, p
        self.client = fam.mr_factory(p.host, p.port, api_key=p.api_key)
        self.target = (p.host, p.port, p.api_key)
        self.state, self.message = "connecting", ""
        self.status: dict = {}
        self.spool_id: int | None = None
        self.lane_db: dict | None = None
        self.objects: list[str] = []
        self.detected: detect.Detected | None = None
        self.webcams: list[dict] = []
        self.spoolman_warning: str | None = None
        self.spoolman_connected: bool | None = None    # Moonraker's own word; kept current by its notification
        self.nozzle: float | None = None         # [extruder] nozzle_diameter from Klipper's config
        self.lane_last: dict = {}                # lane_data values the kit last wrote (only changes are sent)
        self.job_state: str | None = None        # print_stats.state as last seen (job-end detection)
        self.updated: float | None = None
        self.sub: Subscriber | None = None
        self.lock = threading.RLock()
        self._stop = threading.Event()
        self._again = threading.Event()        # set up again (Klipper restarted, a key was added ...)
        self.ready = threading.Event()         # the first set-up attempt finished (any outcome)
        self.thread = threading.Thread(target=self._run, daemon=True, name=f"klipper-{p.serial}")

    # --- the worker ----------------------------------------------------------------------------------------------
    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._again.set()
        if self.sub is not None:
            self.sub.stop()
        self.thread.join(5)

    def _set(self, state: str, message: str = "") -> None:
        with self.lock:
            changed = (state, message) != (self.state, self.message)
            self.state, self.message = state, message
        if changed:
            self.fam._emit(self.p.serial, "klippy", {"state": state})

    def _setup(self) -> bool:
        """One set-up attempt; True when the subscription runs."""
        c = self.client
        info = c.info()
        if info.get("state") != "ready":
            self._set("klippy_not_ready", str(info.get("state_message") or info.get("state") or "Klipper is not ready"))
            return False
        hw = self.fam.hw()
        objs = c.objects()
        namespaces = c.db_namespaces()
        if lanes.NAMESPACE in namespaces and lanes.kit_written(c.db_get(lanes.NAMESPACE)):
            namespaces = [n for n in namespaces if n != lanes.NAMESPACE]   # the kit's own publishing
        d = detect.detect(objs, namespaces, str(info.get("hostname") or ""), hw)
        try:
            detect.save(d, printer_dir(self.p.serial) / "detected.xml")
        except OSError as e:
            log.warning("klipper %s: cannot save detected.xml: %s", self.p.serial, e)
        try:
            cams = c.webcams()
        except MoonrakerError:
            cams = []
        spool = c.spool_id() if "spoolman" in (c.server_info().get("components") or []) else None
        model, system = hw.model(d.model_key), hw.systems.get(d.system_key)
        adapter = adapters.get(system.adapter) if system else adapters.get("single")
        lane_db = c.db_get("lane_data") if system and system.adapter == "lanedata" else None
        try:
            warn = kusage.spoolman_warning(c.server_config(), getattr(self.fam.sm, "base_url", None), self.p.host)
        except MoonrakerError:
            warn = None
        connected = kusage.spoolman_connected(c, self.spoolman_connected)
        try:
            ext = ((c.query({"configfile": ["settings"]}).get("configfile") or {}).get("settings") or {}).get("extruder")
            nozzle = float((ext or {}).get("nozzle_diameter")) if (ext or {}).get("nozzle_diameter") else None
        except (MoonrakerError, TypeError, ValueError):
            nozzle = None
        wanted = {o: None for o in COMMON if o in objs}
        wanted.update({o: None for o in objs if o.startswith("extruder") or o.startswith("temperature_sensor")})
        wanted.update({o: None for o in adapter.objects(model, system) if o in objs or o.startswith("gcode_macro")})
        wanted.update(adapter.objects_from(objs))
        with self.lock:
            self.objects, self.detected, self.webcams, self.spool_id, self.lane_db = objs, d, cams, spool, lane_db
            self.spoolman_warning, self.spoolman_connected = warn, connected
            self.nozzle = nozzle
        # set before the websocket starts: a Klipper event arriving on it afterwards must win over this
        self._set("connected" if d.model_key != "generic" else "unknown_model")
        if self.sub is None:
            self.sub = Subscriber(c, wanted, self._on_status, self._on_event, backoff=self.fam.backoff,
                                  on_connect=self._on_connect).start()
        else:
            self.sub.set_objects(wanted)
        # wait briefly for the first snapshot so callers see filled-in status
        end = time.monotonic() + max(self.client.timeout, 2.0)
        while time.monotonic() < end and not self.sub.connected and not self._stop.is_set():
            time.sleep(0.02)
        return True

    def _run(self) -> None:
        delay = self.fam.backoff[0]
        while not self._stop.is_set():
            self._again.clear()
            ok = False
            try:
                ok = self._setup()
            except Unauthorized:
                self._set("unauthorized", "Moonraker wants an API key: add it with `filament-kit klipper api-key`")
            except Offline as e:
                self._set("offline", str(e))
            except MoonrakerError as e:
                self._set("offline", str(e))
            except Exception:  # noqa: BLE001 - never let one printer's oddity kill its worker
                log.exception("klipper %s: set-up failed", self.p.serial)
                self._set("offline", "set-up failed (see the server log)")
            self.ready.set()
            if ok:
                delay = self.fam.backoff[0]
                self._again.wait()              # until Klipper restarts or we are stopped
                continue
            self._again.wait(delay)
            delay = min(delay * 2, self.fam.backoff[1])

    def effective_state(self) -> str:
        """The state, with a websocket that has been down for `offline_after` seconds counting as offline (the
        subscriber keeps reconnecting by itself; a powered-off printer must not keep showing its last job)."""
        with self.lock:
            state = self.state
        sub = self.sub
        if state in ONLINE and sub is not None and not sub.connected and \
                time.monotonic() - sub.down_since > self.fam.offline_after:
            return "offline"
        return state

    # --- subscriber callbacks ------------------------------------------------------------------------------------
    def _on_connect(self) -> None:
        """Every (re)subscribe: what may have changed while the socket was down, read again over HTTP."""
        connected = kusage.spoolman_connected(self.client, self.spoolman_connected)
        with self.lock:
            self.spoolman_connected = connected
        try:
            spool = self.client.spool_id()
        except MoonrakerError:
            return
        with self.lock:
            changed, self.spool_id = spool != self.spool_id, spool
        if changed:
            self.fam._emit(self.p.serial, "spool", {"spool_id": spool})

    def _on_status(self, delta: dict) -> None:
        ended = False
        klippy = (delta.get("webhooks") or {}) if isinstance(delta.get("webhooks"), dict) else {}
        with self.lock:
            for obj, fields in delta.items():
                if isinstance(fields, dict):
                    self.status.setdefault(obj, {}).update(fields)
            now = (self.status.get("print_stats") or {}).get("state")
            # a change INTO an end state ends a job; a short print can go standby -> complete between two updates
            # (the first snapshot after connecting is never one: job_state is None then)
            ended = self.job_state is not None and self.job_state != now and now in ("complete", "cancelled", "error")
            if now != self.job_state:
                log.info("klipper %s: print %s -> %s", self.p.serial, self.job_state, now)
            self.job_state = now
            self.updated = time.time()
            if self.state not in ONLINE and self.detected is not None and self.state != "klippy_not_ready":
                self.state = "connected" if self.detected.model_key != "generic" else "unknown_model"
        if klippy.get("state") in ("shutdown", "error", "startup"):
            self._set("klippy_not_ready", str(klippy.get("state_message") or f"Klipper {klippy['state']}"))
        elif klippy.get("state") == "ready" and self.state == "klippy_not_ready":
            self._again.set()                    # set up again: objects and model may have changed
        self.fam._emit(self.p.serial, "status", delta)
        if ended:
            self.fam._emit(self.p.serial, "job_ended", {})

    def _on_event(self, name: str, params: list) -> None:
        if name in ("notify_klippy_shutdown", "notify_klippy_disconnected"):
            with self.lock:
                was_job, self.job_state = self.job_state in ("printing", "paused"), None
            self._set("klippy_not_ready", "Klipper " + name.rsplit("_", 1)[-1])
            self._again.set()                    # set-up reads Klipper's own message (and waits for ready)
            if was_job:
                self.fam._emit(self.p.serial, "job_ended", {})
        elif name == "notify_klippy_ready":
            self._again.set()
        elif name == "notify_active_spool_set":
            v = (params[0] or {}).get("spool_id") if params and isinstance(params[0], dict) else None
            with self.lock:
                self.spool_id = v if isinstance(v, int) and not isinstance(v, bool) else None
            self.fam._emit(self.p.serial, "spool", {"spool_id": self.spool_id})
        elif name == "notify_spoolman_status_changed":
            v = (params[0] or {}).get("spoolman_connected") if params and isinstance(params[0], dict) else None
            with self.lock:
                self.spoolman_connected = v if isinstance(v, bool) else None


class KlipperFamily(LoadsMixin):
    def __init__(self, spoolman, hw_loader=kh.load, mr_factory=Moonraker, backoff: tuple[float, float] = (2.0, 60.0),
                 browser_factory=None, offline_after: float = OFFLINE_AFTER, sync_every: float = SYNC_EVERY):
        self.sm, self.hw, self.mr_factory, self.backoff = spoolman, hw_loader, mr_factory, backoff
        self.offline_after, self.sync_every = offline_after, sync_every
        self._stop_sync = threading.Event()
        self._sync_thread: threading.Thread | None = None
        self._conns: dict[str, _Conn] = {}
        self._lock = threading.Lock()
        self._listeners: list = []
        self._spools: tuple[float, list] = (0.0, [])
        self._started = False
        self._scan_lock = threading.Lock()
        self._scan_ended = float("-inf")
        self._twins_seen: tuple[set, set] = (set(), set())
        self._browser_factory = browser_factory      # discovery.Browser in the server; None in tests
        self._browser = None
        self._loads_init()

    # --- lifecycle -----------------------------------------------------------------------------------------------
    def start(self) -> None:
        self._started = True
        self._follow_start()
        if self._browser_factory is not None:
            self._browser = self._browser_factory(self._mdns_found).start()
        self.sync()
        self._stop_sync.clear()
        self._sync_thread = threading.Thread(target=self._sync_loop, daemon=True, name="klipper-sync")
        self._sync_thread.start()

    def _sync_loop(self) -> None:
        """Pick up registry changes made by another process (the CLI): add, remove, a new host or API key."""
        while not self._stop_sync.wait(self.sync_every):
            try:
                self.sync()
                self._forget_twins()
            except Exception:  # noqa: BLE001 - an unreadable registry: try again next round
                log.exception("klipper: registry sync failed")

    def _forget_twins(self) -> None:
        """Discovery reports addresses, so a printer added by name gets an unconfigured twin. No lookups unless the
        entries changed since the last look and there's an unconfigured one to compare: a name that won't resolve can
        take seconds, and this runs every round. A printer that moves shows up as a new entry, so it's looked at again."""
        klipper = [p for p in registry.load().values() if p.family == "klipper"]
        now = ({p.serial for p in klipper if not p.configured}, {(p.host, p.port) for p in klipper if p.configured})
        if now[0] and now != self._twins_seen:
            registry.forget_found_at(set(discovery.added_at()))
        self._twins_seen = now

    def stop(self) -> None:
        self._started = False
        self._stop_sync.set()
        if self._sync_thread is not None:
            self._sync_thread.join(5)
            self._sync_thread = None
        if self._browser is not None:
            self._browser.stop()
            self._browser = None
        with self._lock:
            conns, self._conns = list(self._conns.values()), {}
        for c in conns:
            c.stop()
        self._follow_stop()

    def sync(self) -> None:
        """Match the connections to the registry: new printers connect, removed ones stop, a changed host, port or
        API key reconnects."""
        if not self._started:
            return
        want = {p.serial: p for p in registry.load().values() if p.family == "klipper" and p.configured and p.host}
        start, stop = [], []
        with self._lock:
            for pid, c in list(self._conns.items()):
                p = want.get(pid)
                if p is None or (p.host, p.port, p.api_key) != c.target:
                    stop.append(self._conns.pop(pid))
            for pid, p in want.items():
                if pid not in self._conns:
                    self._conns[pid] = _Conn(self, p)
                    start.append(self._conns[pid])
        for c in stop:
            c.stop()
        for c in start:
            c.start()

    def _mdns_found(self, host: str, port: int, name: str) -> None:
        registry.detected_klipper(host, port, name)

    def scan(self, subnet: str | None = None) -> list[dict]:
        """The owner's Scan: probe a /24 (this machine's by default) for Moonraker; found printers are recorded
        unconfigured. Raises ValueError for a bad or too large subnet, one the server can't reach (discovery.check_range),
        and while a scan runs or within SCAN_GAP of the last: one at a time across the server."""
        import ipaddress
        net = ipaddress.ip_network(subnet, strict=False) if subnet else discovery.own_subnet()
        if net is None:
            raise ValueError("cannot tell this machine's network; give a subnet")
        discovery.check_range(net)
        if not self._scan_lock.acquire(blocking=False):
            raise ValueError("a scan is already running; try again when it ends")
        try:
            wait = self._scan_ended + SCAN_GAP - time.monotonic()
            if wait > 0:
                raise ValueError(f"a scan just ended; try again in {math.ceil(wait)} s")
            try:
                found = discovery.scan(net)
            finally:
                self._scan_ended = time.monotonic()
        finally:
            self._scan_lock.release()
        added = discovery.added_at() if found else {}
        out = []
        for host, port in found:
            p = added.get((host, port)) or registry.detected_klipper(host, port)
            out.append({"id": p.serial, "host": host, "port": port, "name": registry.display_name(p),
                        "configured": p.configured})
        return out

    def add_listener(self, fn) -> None:
        self._listeners.append(fn)

    def _emit(self, pid: str, event: str, data) -> None:
        for fn in list(self._listeners):
            try:
                fn(pid, event, data)
            except Exception:  # noqa: BLE001 - one bad listener must not stop the others
                log.exception("klipper listener failed on %s %s", pid, event)

    def _conn(self, pid: str) -> _Conn | None:
        with self._lock:
            return self._conns.get(pid)

    def _need(self, pid: str) -> _Conn:
        c = self._conn(pid)
        if c is None:
            if registry.load().get(pid) is None:
                raise UnknownPrinter(pid)
            raise PrinterOffline(pid)
        return c

    # --- reads ---------------------------------------------------------------------------------------------------
    def state(self, pid: str) -> str:
        c = self._conn(pid)
        return "not_configured" if c is None else c.effective_state()

    def wait_settled(self, pid: str, timeout: float) -> str:
        c = self._conn(pid)
        if c is not None:
            c.ready.wait(timeout)
        return self.state(pid)

    def verified(self, pid: str) -> bool | None:
        c = self._conn(pid)
        d = c.detected if c is not None else detect.read(printer_dir(pid) / "detected.xml")
        return d.verified if d is not None else None

    def model(self, pid: str):
        """(Model, System, adapter) for the printer, from its last detection (generic single when unknown)."""
        hw = self.hw()
        c = self._conn(pid)
        d = c.detected if c is not None and c.detected else detect.read(printer_dir(pid) / "detected.xml")
        model = hw.model(d.model_key if d else "generic")
        system = hw.systems.get(d.system_key if d else "single") or hw.systems.get("single")
        return model, system, adapters.get(system.adapter if system else "single")

    def slots(self, pid: str) -> list[UnitState]:
        c = self._need(pid)
        model, system, adapter = self.model(pid)
        with c.lock:
            st, sid, db = dict(c.status), c.spool_id, c.lane_db
        return adapter.read(st, sid, db, model, system, self.hw())

    def _spool_list(self) -> list[dict]:
        t, spools = self._spools
        if time.monotonic() - t < SPOOL_CACHE:
            return spools
        try:
            spools = self.sm.get("spool") or []
        except Exception as e:  # noqa: BLE001 - Spoolman down: slots show no spool, status still answers
            log.info("klipper status: Spoolman unavailable (%s)", type(e).__name__)
            return spools
        self._spools = (time.monotonic(), spools)
        return spools

    def forget_spools(self) -> None:
        self._spools = (0.0, self._spools[1])

    def summary(self, pid: str) -> dict | None:
        c = self._conn(pid)
        if c is None:
            return None
        with c.lock:
            st = dict(c.status)
        ps = st.get("print_stats") or {}
        return {"gcode_state": GCODE_STATE.get(ps.get("state"), "UNKNOWN") if c.effective_state() in ONLINE
                else "UNKNOWN",
                "percent": _percent(st), "remaining_min": _remaining(st), "job": ps.get("filename") or None}

    def status(self, pid: str) -> dict | None:
        c = self._conn(pid)
        if c is None:
            return None
        from ..status import _spool_view
        with c.lock:
            st, updated, message = dict(c.status), c.updated, c.message
        state = c.effective_state()
        p = registry.load().get(pid)
        try:
            units = self.slots(pid)
        except Exception:  # noqa: BLE001 - an odd status must not fail the whole answer
            log.exception("klipper %s: cannot read slots", pid)
            units = []
        by_id = {s.get("id"): s for s in self._spool_list()}
        ams = []
        for u in units:
            ams.append({"unit": u.unit, "label": u.label, "kind": u.kind, "type_name": u.kind.title(),
                        "say": [], "slots": [
                            {"slot": i, "label": s.label, "say": list(s.say), "type": s.material or "",
                             "color_hex": (s.color or "").lstrip("#"), "preset_id": "", "active": s.active,
                             "present": s.present, "reading": None,
                             "spool": _spool_view(by_id[s.spool_id]) if s.spool_id in by_id else None,
                             "spool_id": s.spool_id}
                            for i, s in enumerate(u.slots)]})
        ps = st.get("print_stats") or {}
        info = ps.get("info") or {}
        notes = [message] if state == "klippy_not_ready" and message else []
        if state == "unknown_model":
            with c.lock:
                detected = c.detected
            notes.append(generic_note(detected.system_key if detected else "Klipper"))
        out = {
            "gcode_state": GCODE_STATE.get(ps.get("state"), "UNKNOWN") if state in ONLINE else "UNKNOWN",
            "stage": "", "job": ps.get("filename") or "", "percent": _percent(st),
            "layer": info.get("current_layer"), "total_layers": info.get("total_layer"),
            "remaining_min": _remaining(st), "eta": None, "temps": _temps(st), "ams": ams, "presence": "printer",
            "notes": notes, "hms": [], "print_error": "", "light": None,
            "updated": int(updated) if updated else None, "family": "klipper", "state": state,
        }
        with c.lock:
            out["spoolman_warning"] = kusage.with_connection(c.spoolman_warning, c.spoolman_connected)
        return out

    # --- usage ---------------------------------------------------------------------------------------------------
    def usage(self, pid: str, days: float) -> list[dict]:
        return kusage.entries(pid, days)

    def _record_job(self, pid: str) -> None:
        c = self._conn(pid)
        if c is None:
            return
        job, end = None, time.monotonic() + HISTORY_WAIT
        while True:      # Moonraker closes the job's history entry just after print_stats changes
            try:
                job = c.client.history_last()
            except MoonrakerError as e:
                log.warning("klipper %s: job ended but its history is unavailable (%s); no usage entry", pid, e)
                return
            if not job or job.get("status") != "in_progress":
                break
            if time.monotonic() >= end:
                log.warning("klipper %s: Moonraker still shows job %s in progress; no usage entry", pid,
                            job.get("job_id"))
                return
            time.sleep(0.5)
        if not job:
            log.warning("klipper %s: a job ended but Moonraker's history has no job (is [history] on?)", pid)
            return
        kusage.record(pid, job, c.spool_id)

    # --- camera --------------------------------------------------------------------------------------------------
    def camera_url(self, pid: str) -> str | None:
        c = self._conn(pid)
        if c is None:
            return None
        for cam in c.webcams:
            url = cam.get("stream_url") if cam.get("enabled", True) else None
            if isinstance(url, str) and url:
                full = urllib.parse.urljoin(f"http://{c.p.host}/", url)
                u = urllib.parse.urlsplit(full)
                # the URL comes from the printer: only http(s) on the printer itself (never file:, another host)
                if u.scheme in ("http", "https") and (u.hostname or "").lower() == c.p.host.lower().strip("[]"):
                    return full
                log.warning("klipper %s: webcam %r ignored: not an http(s) stream on the printer", pid,
                            cam.get("name"))
        return None

    def camera_kind(self, pid: str) -> str | None:
        return "mjpeg" if self.camera_url(pid) else None

    # --- commands ------------------------------------------------------------------------------------------------
    def command(self, pid: str, action: str) -> dict:
        c = self._need(pid)
        if c.state not in ONLINE:
            raise PrinterOffline(pid)
        model, _system, _adapter = self.model(pid)
        try:
            if action in ("pause", "resume"):
                c.client.print_action(action)
            elif action == "stop":
                c.client.print_action("cancel")
            elif action in ("light_on", "light_off"):
                g = model.light_on if action == "light_on" else model.light_off
                if not g:
                    return {"ok": False, "reply": {"reason": "not_supported",
                                                   "message": "no light gcode in klipper_hardware.xml for this printer"}}
                c.client.gcode(kh.fill(g))
            else:
                raise ValueError(f"unknown action {action}")
        except Offline:
            raise PrinterOffline(pid) from None
        except MoonrakerError as e:
            return {"ok": False, "reply": {"reason": "refused", "message": str(e)}}
        return {"ok": True, "reply": {"result": "success"}}


def _percent(st: dict) -> int:
    try:
        return int(round(float((st.get("virtual_sdcard") or {}).get("progress") or 0) * 100))
    except (TypeError, ValueError):
        return 0


def _remaining(st: dict) -> int:
    ps = st.get("print_stats") or {}
    try:
        done = float((st.get("virtual_sdcard") or {}).get("progress") or 0)
        spent = float(ps.get("print_duration") or 0)
    except (TypeError, ValueError):
        return 0
    if ps.get("state") not in ("printing", "paused") or done <= 0 or spent <= 0:
        return 0
    return int(round(spent / done - spent) / 60)


def _temps(st: dict) -> dict:
    def t(obj):
        o = st.get(obj) or {}
        return {"current": o.get("temperature"), "target": o.get("target")}
    exts = sorted((k for k in st if k == "extruder" or (k.startswith("extruder") and k[8:].isdigit())),
                  key=lambda k: int(k[8:] or 0))
    chamber = next((k for k in st if k.startswith("temperature_sensor") and "chamber" in k.lower()), None)
    return {"nozzle": [t(k) for k in exts], "bed": t("heater_bed"),
            "chamber": {"current": (st.get(chamber) or {}).get("temperature"), "target": None} if chamber else None}
