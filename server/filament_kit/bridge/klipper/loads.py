"""Loads, unloads and follow mode for Klipper printers (spec §6), mixed into KlipperFamily.

Load: the adapter's set gcode goes to Moonraker; the kit then waits up to CONFIRM_TIMEOUT for the printer to show the
spool in that slot. Only a confirmed load changes Spoolman (location "<name> – <label>", prev_location = where it
came from; the slot's earlier spools go back to theirs). Refused while printing (allowed paused or idle). A gcode
Klipper refuses is returned word for word in `problems`.

Follow mode: whenever a slot's spool changes on the printer without a kit load (an nfc2klipper tap, the touchscreen,
a macro, an AFC/Happy Hare lane change) the same Spoolman moves are made, so inventory matches the printer however
the spool got there. The first status after connecting is only recorded (no moves). Moves run on one worker
thread, never on the websocket's; a slot's kit load and its follow moves share one lock, and after every load the
slot is checked again so a tap that landed meanwhile wins.

Unload: the clear gcode when the printer is online and not printing, then the slot's spools go back (Spoolman only
when the printer is offline, like the Bambu unload).
"""
from __future__ import annotations

import logging
import queue
import threading
import time

from ... import inventory, profiles
from ...spoolman import SpoolmanError
from .. import loading, registry, status as bstatus
from ..connection import PrinterOffline
from . import lanes
from .adapters.base import NotSupported, UnknownSlot
from .moonraker import GcodeError, MoonrakerError, Offline

log = logging.getLogger(__name__)
CONFIRM_TIMEOUT = 10.0


def _slot_location(s: dict, cur: str) -> bool:
    """`cur` is a printer slot: loading's rule, or a kit-placed spool (prev_location set) whose printer was renamed."""
    return loading._is_slot_location(cur) or bool(loading.prev_location(s))


def _patch(s: dict, loc: str) -> dict:
    import json
    cur = s.get("location") or ""
    if cur == loc:
        return {}
    prev = loading.prev_location(s) if _slot_location(s, cur) else cur
    return {"location": loc, "extra": {**(s.get("extra") or {}), "prev_location": json.dumps(prev)}}


class LoadsMixin:
    def _loads_init(self) -> None:
        self._slot_locks: dict[tuple[str, str], threading.Lock] = {}
        self._slot_locks_lock = threading.Lock()
        self._seen: dict[str, dict[str, int | None]] = {}
        self._follow_q: queue.Queue = queue.Queue()
        self._follow_thread: threading.Thread | None = None
        self.add_listener(self._on_change)

    def _follow_start(self) -> None:
        if self._follow_thread is None or not self._follow_thread.is_alive():
            self._follow_thread = threading.Thread(target=self._follow_run, daemon=True, name="klipper-follow")
            self._follow_thread.start()

    def _follow_stop(self) -> None:
        self._follow_q.put(None)
        if self._follow_thread is not None:
            self._follow_thread.join(5)
        self._follow_thread = None
        self._seen.clear()

    def _slot_lock(self, pid: str, label: str) -> threading.Lock:
        with self._slot_locks_lock:
            return self._slot_locks.setdefault((pid, label), threading.Lock())

    # --- follow mode ---------------------------------------------------------------------------------------------
    def _on_change(self, pid: str, event: str, data) -> None:
        if event in ("status", "spool"):
            self._follow_q.put(pid)
        elif event == "job_ended":
            # its own thread: waiting for Moonraker's history must never hold up any printer's follow moves
            threading.Thread(target=self._record_job_safe, args=(pid,), daemon=True,
                             name=f"klipper-usage-{pid}").start()
        elif event == "klippy" and (data or {}).get("state") not in ("connected", "unknown_model"):
            self._seen.pop(pid, None)            # re-baseline after a reconnect: no moves for the first snapshot

    def _record_job_safe(self, pid: str) -> None:
        try:
            self._record_job(pid)
        except Exception:  # noqa: BLE001 - a usage entry is a record only: log and go on
            log.exception("klipper %s: cannot record the finished job", pid)

    def _follow_run(self) -> None:
        while True:
            pid = self._follow_q.get()
            if pid is None:
                return
            pending = [pid]
            while not self._follow_q.empty():       # coalesce bursts of updates
                more = self._follow_q.get()
                if more is None:
                    return
                if more not in pending:
                    pending.append(more)
            for p in pending:
                try:
                    self._follow_check(p)
                except PrinterOffline:
                    log.info("klipper follow %s: the printer went offline; the reconcile at connect catches up", p)
                except Exception:  # noqa: BLE001 - Spoolman down etc.: the next update tries again
                    log.exception("klipper follow %s failed", p)

    def _current(self, pid: str) -> dict[str, int | None]:
        return {s.label: s.spool_id for u in self.slots(pid) for s in u.slots}

    def _follow_check(self, pid: str) -> None:
        c = self._conn(pid)
        if c is None or c.state not in ("connected", "unknown_model") or not (c.sub and c.sub.connected):
            return
        cur = self._current(pid)
        seen = self._seen.get(pid)
        if seen is None:
            # first status after connecting: reconcile what changed while the kit was not watching (a tap during a
            # kit restart). Only a spool the printer shows counts: Moonraker forgets its active spool on a restart,
            # and that is no reason to unload Spoolman.
            # A slot left out of the baseline stays unseen until its move succeeds, so a failure is retried.
            todo = []
            for label, sid in cur.items():
                if sid is None:
                    continue
                here = [s.get("id") for s in loading.occupants(self.sm, self._location(pid, label))]
                if here != [sid]:
                    todo.append((label, sid))
            self._seen[pid] = {l: s for l, s in cur.items() if (l, s) not in todo}
            for label, sid in todo:
                with self._slot_lock(pid, label):
                    self._follow_move(pid, label, sid)
            return
        for label, sid in cur.items():
            if seen.get(label, "unset") == sid:
                continue
            with self._slot_lock(pid, label):
                now = self._current(pid).get(label)
                if self._seen.get(pid, {}).get(label, "unset") == now:
                    continue
                self._follow_move(pid, label, now)

    def _follow_move(self, pid: str, label: str, spool_id) -> None:
        """Spoolman follows the printer for one slot. A spool id this Spoolman does not have (Moonraker reports to
        another one, or the spool was deleted) moves nothing and is logged once; it still counts as seen. Any other
        failure leaves the slot unseen, so the next update tries again."""
        if spool_id is not None:
            try:
                self.sm.get(f"spool/{spool_id}")
            except SpoolmanError as e:
                if e.status == 404:
                    log.warning("klipper %s %s: the printer shows spool %s, which this Spoolman does not have; "
                                "Spoolman left unchanged", pid, label, spool_id)
                    self._seen.setdefault(pid, {})[label] = spool_id
                    return
                raise
        self._move(pid, label, spool_id, dry=False)
        self._seen.setdefault(pid, {})[label] = spool_id
        self._publish(pid)
        log.info("klipper %s %s: printer shows spool %s; Spoolman follows", pid, label, spool_id)

    # --- Spoolman moves ------------------------------------------------------------------------------------------
    def _location(self, pid: str, label: str) -> str:
        p = registry.load().get(pid)
        return bstatus.location(registry.display_name(p) if p else pid, label, family="klipper")

    def _move(self, pid: str, label: str, spool_id, dry: bool, sealed: str = loading.SEALED):
        """Spoolman: spool `spool_id` (or nothing) is now in that slot. Returns (moved_back, final spool | None)."""
        sm, loc = self.sm, self._location(pid, label)
        with inventory._LOCK:
            moved = loading.send_back(sm, loading.occupants(sm, loc, spool_id), sealed, dry)
            final = None
            if spool_id is not None:
                fresh = sm.get(f"spool/{spool_id}")
                patch = _patch(fresh, loc)
                if patch and not dry:
                    sm.patch(f"spool/{spool_id}", patch)
                final = {**fresh, **patch} if dry else sm.get(f"spool/{spool_id}")
        self.forget_spools()
        return moved, final

    # --- load / unload -------------------------------------------------------------------------------------------
    def _target(self, pid: str, label: str):
        c = self._need(pid)
        model, system, adapter = self.model(pid)
        with c.lock:
            st, sid, db = dict(c.status), c.spool_id, c.lane_db
        plabel = self.printer_label(pid, label, st, sid, db, model, system, adapter)    # the owner's map, if any
        try:
            adapter.spool_on(st, sid, db, plabel, model, system)
        except UnknownSlot as e:
            raise loading.NotFound(f"{registry.display_name(registry.load()[pid])} has no slot {label}") from e
        return c, model, system, adapter, st, plabel

    def load(self, sm, pid: str, label: str, spool_id, dry: bool, *, sealed_location: str = loading.SEALED) -> dict:
        p = registry.load().get(pid)
        if p is None:
            raise loading.NotFound(f"no printer {pid}")
        spool = loading._spool(sm, spool_id)
        c, model, system, adapter, st, plabel = self._target(pid, label)
        if c.state not in ("connected", "unknown_model"):
            raise PrinterOffline(pid)
        if (st.get("print_stats") or {}).get("state") == "printing":
            raise loading.SlotInUse(f"{registry.display_name(p)} is printing; load {label} when it is paused or done")
        try:
            gcode = adapter.set_gcode(plabel, spool["id"], model, system, self.hw(), st)
        except (UnknownSlot, NotSupported) as e:
            raise loading.NotFound(f"{label}: {e}") from e
        loc = self._location(pid, label)
        preset = self._preset(spool.get("filament") or {}, pid)
        nozzle, assumed = self._nozzle(pid)
        result = {"slot": {"label": label, "location": loc}, "preset": preset, "dry_run": bool(dry), "problems": [],
                  "nozzle_mm": nozzle, "nozzle_assumed": assumed}
        if dry:
            moved, final = self._move(pid, label, spool["id"], dry=True, sealed=sealed_location)
            return {**result, "spool": final, "confirmed": None, "moved_back": moved, "command": {"gcode": gcode}}
        confirmed = False
        with self._slot_lock(pid, label):
            try:
                c.client.gcode(gcode)
                confirmed = self._wait_shows(pid, plabel, spool["id"])
                if not confirmed:
                    result["problems"].append(f"{label}: not confirmed (the printer did not show spool {spool['id']}"
                                              f" within {CONFIRM_TIMEOUT:g} s); Spoolman left unchanged")
            except GcodeError as e:
                result["problems"].append(f"{label}: Klipper refused {gcode!r}: {e}")
            except Offline as e:
                result["problems"].append(f"{label}: {e}")
            except MoonrakerError as e:
                result["problems"].append(f"{label}: {e}")
            moved = []
            final = sm.get(f"spool/{spool['id']}")
            if confirmed:
                moved, final = self._move(pid, label, spool["id"], dry=False, sealed=sealed_location)
                self._seen.setdefault(pid, {})[label] = spool["id"]
                self._publish(pid)
        self._follow_q.put(pid)                  # a tap that landed meanwhile wins
        return {**result, "spool": final, "confirmed": confirmed, "moved_back": moved}

    def _wait_shows(self, pid: str, label: str, spool_id: int) -> bool:
        """`label` is the printer's own (not the owner's map)."""
        end = time.monotonic() + CONFIRM_TIMEOUT
        c = self._conn(pid)
        drops = c.sub.drops if c is not None and c.sub else 0
        while time.monotonic() < end:
            c = self._conn(pid)
            if c is None or not (c.sub and c.sub.connected) or c.sub.drops != drops:
                return False                      # the websocket dropped: unconfirmed, follow mode settles it
            model, system, adapter = self.model(pid)
            with c.lock:
                st, sid, db = dict(c.status), c.spool_id, c.lane_db
            try:
                if adapter.spool_on(st, sid, db, label, model, system) == spool_id:
                    return True
            except UnknownSlot:
                return False
            time.sleep(0.05)
        return False

    def unload(self, sm, pid: str, label: str, dry: bool, *, sealed_location: str = loading.SEALED) -> dict:
        p = registry.load().get(pid)
        if p is None:
            raise loading.NotFound(f"no printer {pid}")
        loc = self._location(pid, label)
        c = self._conn(pid)
        online = c is not None and c.state in ("connected", "unknown_model")
        gcode = None
        if online:
            c, model, system, adapter, st, plabel = self._target(pid, label)
            if (st.get("print_stats") or {}).get("state") == "printing":
                raise loading.SlotInUse(f"{registry.display_name(p)} is printing; unload {label} once it is done")
            try:
                gcode = adapter.clear_gcode(plabel, model, system, self.hw(), st)
            except NotSupported:
                gcode = None
            except UnknownSlot as e:        # as load does: a message, not a server error
                raise loading.NotFound(f"{label}: {e}") from e
        with self._slot_lock(pid, label):
            here = loading.occupants(sm, loc)
            if not here:
                raise loading.NotFound(f"no spool is in {registry.display_name(p)} slot {label}")
            problems = []
            if gcode and not dry:
                try:
                    c.client.gcode(gcode)
                except MoonrakerError as e:
                    problems.append(f"{label}: {e}")
            moved = loading.send_back(sm, here, sealed_location, dry)
            if not dry:
                self._seen.setdefault(pid, {})[label] = None
                self.forget_spools()
                self._publish(pid)
            first = min(here, key=lambda s: s["id"])
            spool = ({**first, "location": moved[0]["location"]} if dry else sm.get(f"spool/{first['id']}"))
        return {"spool": spool, "slot": {"label": label, "location": loc}, "preset": None, "dry_run": bool(dry),
                "moved_back": moved, "problems": problems, **({"command": {"gcode": gcode}} if dry and gcode else {})}

    def _publish(self, pid: str) -> None:
        """Write the printer's slots to Moonraker lane_data when its setting says so (lanes.should_publish)."""
        p, c = registry.load().get(pid), self._conn(pid)
        if p is None or c is None:
            return
        _model, _system, adapter = self.model(pid)
        if not lanes.should_publish(p, adapter):
            if adapter.name not in lanes.NEVER and getattr(p, "lane_data", "auto") == "off":
                self._retract_lanes(pid, c)
            return
        try:
            units = self.slots(pid)
            by_id = {s.get("id"): s for s in (self.sm.get("spool") or [])}
            presets = {}
            for u in units:
                for s in u.slots:
                    sp = by_id.get(s.spool_id)
                    if sp is not None:
                        pr = self._preset(sp.get("filament") or {}, pid)
                        presets[s.label] = pr["name"] if pr else None
            pl = lanes.payload(units, by_id, presets)
            wrote = lanes.publish(c.client, pl, c.lane_last)
            if wrote:
                log.info("klipper %s: lane_data %s updated", pid, ", ".join(wrote))
            gone = lanes.retract(c.client, pl, c.lane_last)
            if gone:
                log.info("klipper %s: lane_data %s removed", pid, ", ".join(gone))
        except Exception as e:  # noqa: BLE001 - publishing is a convenience: never fail a load over it
            log.warning("klipper %s: cannot publish lane_data (%s)", pid, e)

    def _retract_lanes(self, pid: str, c) -> None:
        """The printer's setting is `off`: take the lanes the kit published out of lane_data (the slicer would read
        them as the loaded spools). Lanes without the kit's source stay."""
        try:
            gone = lanes.retract(c.client, {}, c.lane_last, c.client.db_get(lanes.NAMESPACE))
            if gone:
                log.info("klipper %s: lane_data %s removed (publishing is off)", pid, ", ".join(gone))
        except Exception as e:  # noqa: BLE001 - a convenience: never fail a load over it
            log.warning("klipper %s: cannot clear lane_data (%s)", pid, e)

    def _nozzle(self, pid: str) -> tuple[float, bool]:
        """(nozzle mm, assumed): Klipper's [extruder] nozzle_diameter, else the model's first Orca nozzle, else 0.4."""
        c = self._conn(pid)
        if c is not None and c.nozzle:
            return c.nozzle, False
        model, _s, _a = self.model(pid)
        try:
            return (float(model.orca[0].nozzle) if model.orca else 0.4), True
        except ValueError:
            return 0.4, True

    def _preset(self, filament: dict, pid: str):
        """The Orca preset view for this filament on this printer, or None (shown, never required)."""
        p = registry.load().get(pid)
        if p is None:
            return None
        model, _s, _a = self.model(pid)
        nozzle, _assumed = self._nozzle(pid)
        try:
            ref = profiles.preset_for(filament, model.key, nozzle, family="klipper",
                                      printer_name=registry.display_name(p))
        except Exception:  # noqa: BLE001 - a broken build must not block a load
            log.exception("klipper %s: preset lookup failed", pid)
            return None
        return loading._preset_view(ref) if ref else None
