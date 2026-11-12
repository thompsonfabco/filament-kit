"""Slot test: prove which (ams_id, tray_id) address reaches which AMS slot, then put every slot back.

For each slot (AMS units, AMS HT, external holder) the slot's own setting is written back with
only the colour changed to a unique test colour (`FA<nn>00FF`, nn in hex; another prefix if a slot already holds it), and the slot counts as confirmed once a report
shows that colour on that unit/tray (within CONFIRM_TIMEOUT). Afterwards every slot that may have changed is
written back to its snapshot and the restore is confirmed from the report. The test stops early, and still
restores, when the printer starts a job, goes offline, or refuses writes (Developer Mode). Nothing is saved here:
the caller (mapping) turns the result into a SlotMap.

An AMS slot the presence bits say is empty gets no write: it is not a target, and it goes into `empty` with the
address the report gives (the X2D refuses a write to an empty slot). So does a slot with no filament type whose write
was refused (no presence bits to tell): an empty slot's refusal is not a problem.

Idle = connected (or connected but flagged `needs_developer_mode`) and `gcode_state` not in status.ACTIVE."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

from . import ams, layout, registry, snapshot, status
from .connection import PrinterOffline, UnknownPrinter

log = logging.getLogger(__name__)

CONFIRM_TIMEOUT = 10.0          # seconds for a report to show a write
TEST_COLOUR = "{prefix}{n:02X}00FF"   # RRGGBBAA; n = the slot's number in test order (01, 02 ... in hex)
TEST_PREFIXES = ("FA", "FB", "FC", "FD", "FE", "F9", "F8", "F7")
ONLINE = ('connected', 'needs_developer_mode')   # the MQTT session is up in both


class PrinterBusy(Exception):
    """The printer is running, paused, preparing or slicing a job (the gcode_state is the message)."""


class NoStatus(PrinterOffline):
    """Connected, but the printer has not reported its `gcode_state` yet: not known to be idle."""

    def __init__(self, serial: str):
        super().__init__("no status from the printer yet; try again in a few seconds")
        self.serial = serial


@dataclass
class SlotTestResult:
    confirmed: dict[str, dict] = field(default_factory=dict)   # label -> {ams_id, tray_id}
    restored: bool = True              # every changed slot confirmed back at its snapshot, no test colour left
    problems: list[str] = field(default_factory=list)          # one line per issue, "<label>: ..." for a slot
    needs_developer_mode: bool = False
    reason: str = "none"               # mapping.REASONS: why the test stopped before its end (busy, offline, ...)
    empty: dict[str, dict] = field(default_factory=dict)       # label -> {ams_id, tray_id}: empty, not written


@dataclass
class _Target:
    label: str
    ams_id: int
    tray_id: int
    snap: dict
    kind: str | None = None        # the unit's kind ("ext": the model's external addressing)


def check_idle(manager, serial: str) -> None:
    """Raise PrinterOffline (NoStatus: no `gcode_state` reported yet) / PrinterBusy unless the printer may be
    changed now."""
    if manager.state(serial) not in ONLINE:
        raise PrinterOffline(serial)
    gs = manager.summary(serial).get('gcode_state')
    if not isinstance(gs, str) or gs in ('', 'UNKNOWN'):
        raise NoStatus(serial)
    if gs in status.ACTIVE:
        raise PrinterBusy(gs)


def pick_test_colour(n: int, taken: set[str]) -> str:
    """Slot n's test colour: `FA<nn>00FF` (nn = n as two hex digits), or the next prefix (`FB` ...) if a slot's
    snapshot (or an earlier slot's test) already holds it, so no report can confirm a write by coincidence."""
    used = {_norm(c) for c in taken}
    for prefix in TEST_PREFIXES:
        c = TEST_COLOUR.format(prefix=prefix, n=n & 0xFF)
        if c not in used:
            return c
    for g in range(256):                     # every prefix taken (absurd): vary the blue byte instead
        c = f"FA{n & 0xFF:02X}{g:02X}FF"
        if c not in used:
            return c
    raise ValueError("no free test colour")


def _busy(report: dict) -> bool:
    return status._s(status._d(report).get('gcode_state')) in status.ACTIVE


def _raw_tray(report: dict, unit: ams.Unit, slot: ams.Slot) -> dict:
    return layout.raw_trays(report).get((unit.ams_id, slot.tray_id), {})


def _snapshot(t: dict) -> dict:
    return {k: status._s(t.get(k)) for k in ('tray_info_idx', 'tray_color', 'tray_type', 'tray_sub_brands')} | \
        {k: t.get(k) for k in ('nozzle_temp_min', 'nozzle_temp_max')}


def _slots(report: dict, model=None) -> dict[str, ams.Slot]:
    return {s.label: s for u in ams.units(report, model) for s in u.slots}


def _norm(colour: str) -> str:
    c = (colour or '').upper()
    return '' if c in ('', '00000000') else c


def _showing(report: dict, colour: str, model=None) -> list[str]:
    """Labels whose slot shows `colour`."""
    c = _norm(colour)
    return [lab for lab, s in _slots(report, model).items() if _norm(s.color) == c]


def _matches(report: dict, t: _Target, model=None) -> bool:
    s = _slots(report, model).get(t.label)
    return s is not None and s.preset == t.snap['tray_info_idx'] and s.type == t.snap['tray_type'] and \
        _norm(s.color) == _norm(t.snap['tray_color'])


def _reason(reply: dict) -> str:
    return str(reply.get('reason') or reply.get('err_code') or reply.get('result') or 'refused')


def _failed(reply: dict | None) -> bool:
    return reply is not None and str(reply.get('result', '')).lower() != 'success'


INTERRUPTED = "The mapping was stopped; the slot test stopped."
OFFLINE = "The printer went offline; the slot test stopped."
# what a slot left untested says, by the reason the test stopped
NOT_TESTED = {"busy": "the printer started a job", "offline": "the printer went offline", "interrupted": "stopped",
              "kit_error": "an error in the kit", "developer_mode": "write refused", "none": "not tested"}


def run(manager, serial: str, on_step: Callable[[str], None],
        should_stop: Callable[[], bool] | None = None) -> SlotTestResult:
    """Run the slot test on an idle printer (raises PrinterOffline / PrinterBusy before touching anything).

    `on_step(text)` is told each step ("Testing slot A1 (1/6)", "Restoring slot A1" ...). `should_stop()` true
    (the CLI got a signal, the service is stopping) ends the test early as "interrupted"; the restore still runs.
    Returns the result; a problem never goes unreported: every slot not confirmed and every slot not confirmed
    restored has a line. The snapshot is saved to disk (`snapshot.save`) before the first write and deleted after
    a confirmed restore; the restore runs whatever stops the test (a KeyboardInterrupt too, re-raised afterwards).
    The test colours avoid every colour a slot holds (`pick_test_colour`), so a real near-red spool is mapped too."""
    def step(text: str) -> None:
        try:
            on_step(text)
        except Exception:
            log.exception("slot test: progress callback failed")

    stopping = should_stop or (lambda: False)
    check_idle(manager, serial)
    res = SlotTestResult()
    if snapshot.pending(serial):
        res.problems.append("a slot snapshot from an interrupted mapping is still pending; run the mapping again "
                            "to restore it first")
        return res
    step("Reading the AMS slots")
    report = manager.wait_report(serial, lambda r: True, 0)
    if report is None:
        raise PrinterOffline(serial)
    targets = []
    model = ams.printer_model(serial)
    empty = {s.label for u in layout.build(report, model).units if u.kind != layout.EXT_KIND
             for s in u.slots if s.present is False}
    for u in ams.units(report, model):
        for s in u.slots:
            if s.label in empty:
                res.empty[s.label] = {'ams_id': u.ams_id, 'tray_id': s.tray_id}
                continue
            targets.append(_Target(s.label, u.ams_id, s.tray_id, _snapshot(_raw_tray(report, u, s)), u.kind))
    by_label = {t.label: t for t in targets}
    # a slot's colour is its own even when it looks like a test colour (a real near-red spool): an interrupted
    # run is covered by the snapshot on disk, which `snapshot.pending` above already made the caller restore
    taken = {t.snap['tray_color'] for t in targets if t.snap['tray_color']}   # never pick a colour a slot holds
    plan: list[str] = []                 # the test colour of each target, in test order
    for n in range(1, len(targets) + 1):
        c = pick_test_colour(n, taken)
        taken.add(c)
        plan.append(c)
    try:
        snapshot.save(serial, "slottest", [{"label": t.label, "ams_id": t.ams_id, "tray_id": t.tray_id,
                                            "setting": dict(t.snap)} for t in targets], plan)
    except Exception as e:               # no snapshot on disk: never touch the printer
        log.exception("slot test on %s: cannot save the slot snapshot", registry.log_label(serial))
        res.problems.append(f"cannot save the slot snapshot ({type(e).__name__}: {e}); nothing was changed")
        return res
    changed: list[_Target] = []          # may differ from their snapshot now
    reported: set[str] = set()           # slots that already have a "not confirmed" line
    colours: set[str] = set()            # test colours written (or being written) in this run
    abort = None
    reason = "none"
    interrupted: BaseException | None = None
    current: list[_Target] = []          # the slot being written right now

    def mark(t: _Target) -> None:
        if t not in changed:
            changed.append(t)

    try:
        for n, t in enumerate(targets, 1):
            if stopping():
                abort, reason = INTERRUPTED, "interrupted"
                break
            try:
                check_idle(manager, serial)
            except PrinterBusy as e:
                abort, reason = f"The printer started a job ({e}); the slot test stopped.", "busy"
                break
            except PrinterOffline:
                abort, reason = OFFLINE, "offline"
                break
            step(f"Testing slot {t.label} ({n}/{len(targets)})")
            if stopping():
                abort, reason = INTERRUPTED, "interrupted"
                break
            colour = plan[n - 1]
            colours.add(colour)
            current[:] = [t]
            try:
                reply = manager.set_slot(serial, t.ams_id, t.tray_id, dict(t.snap, tray_color=colour), kind=t.kind)
            except (PrinterOffline, UnknownPrinter):
                mark(t)                  # it may have reached the printer before the drop
                abort, reason = OFFLINE, "offline"
                break
            if _failed(reply):
                current.clear()
                if t.kind != layout.EXT_KIND and not t.snap['tray_type']:
                    # no filament in it, and no presence bits said so: an empty slot takes no setting
                    log.info("slot test on %s: %s has no filament and refused the write (%s): empty", registry.log_label(serial),
                             t.label, _reason(reply))
                    res.empty[t.label] = {'ams_id': t.ams_id, 'tray_id': t.tray_id}
                    reported.add(t.label)
                    continue
                if manager.state(serial) == 'needs_developer_mode':
                    res.needs_developer_mode = True
                    res.problems.append(f"needs_developer_mode: the printer refused the write to {t.label} "
                                        f"({_reason(reply)}); turn on Developer Mode (LAN-only mode) and retry")
                    res.problems.append(f"{t.label}: not confirmed (write refused)")
                    reported.add(t.label)
                    abort, reason = "needs_developer_mode", "developer_mode"
                    break
                res.problems.append(f"{t.label}: not confirmed (write refused: {_reason(reply)})")
                reported.add(t.label)
                continue
            mark(t)
            current.clear()
            r = manager.wait_report(serial, lambda r, c=colour: _busy(r) or bool(_showing(r, c, model)), CONFIRM_TIMEOUT)
            if r is None:
                if manager.state(serial) not in ONLINE:
                    abort, reason = OFFLINE, "offline"
                    break
                res.problems.append(f"{t.label}: not confirmed (no report showed its test colour within "
                                    f"{CONFIRM_TIMEOUT:g} s)")
                reported.add(t.label)
                continue
            where = _showing(r, colour, model)
            for lab in where:                # before any abort: wherever the colour landed gets restored
                if lab in by_label:
                    mark(by_label[lab])
            if _busy(r):
                abort = f"The printer started a job ({status._s(r.get('gcode_state'))}); the slot test stopped."
                reason = "busy"
                break
            if t.label in where:
                res.confirmed[t.label] = {'ams_id': t.ams_id, 'tray_id': t.tray_id}
            else:
                res.problems.append(f"{t.label}: not confirmed (its test colour appeared on {', '.join(where)})")
                reported.add(t.label)
    except Exception as e:                  # never leave test colours behind because of a bug or callback
        log.exception("slot test on %s failed", registry.log_label(serial))
        abort, reason = "The slot test stopped on an error in the kit; the slots are put back.", "kit_error"
    except BaseException as e:              # Ctrl-C, SystemExit ...: restore first, re-raise afterwards
        log.warning("slot test on %s interrupted (%s); restoring the slots", registry.log_label(serial), type(e).__name__)
        abort, reason = INTERRUPTED, "interrupted"
        interrupted = e
    for t in current:                       # stopped in the middle of a write: it may have landed
        mark(t)

    if abort and abort != "needs_developer_mode":
        res.problems.insert(0, abort)
    res.reason = reason
    why = NOT_TESTED.get(reason, "not tested")
    for t in targets:
        if t.label not in res.confirmed and t.label not in reported:
            res.problems.append(f"{t.label}: not confirmed ({why})")

    _restore(manager, serial, res, changed, colours, step)
    if res.restored:
        try:
            snapshot.clear(serial)
        except OSError:
            log.exception("slot test on %s: cannot delete the slot snapshot", registry.log_label(serial))
    step("Slot test finished")
    if interrupted is not None:
        raise interrupted
    return res


def _restore(manager, serial: str, res: SlotTestResult, changed: list[_Target], colours: set[str], step) -> None:
    """Put every changed slot back to its snapshot and confirm it; then check no test colour is left anywhere."""
    model = ams.printer_model(serial)
    # unconfirmed addresses first, so a mis-addressed write is overwritten by the right slot's restore
    order = [t for t in changed if t.label not in res.confirmed] + [t for t in changed if t.label in res.confirmed]
    for t in order:
        step(f"Restoring slot {t.label}")
        try:
            reply = manager.set_slot(serial, t.ams_id, t.tray_id, t.snap, kind=t.kind)
            if _failed(reply):
                res.problems.append(f"{t.label}: restore refused ({_reason(reply)}); "
                                    f"its test colour may still be set")
                res.restored = False
                continue
            if manager.wait_report(serial, lambda r, t=t: _matches(r, t, model), CONFIRM_TIMEOUT) is None:
                res.problems.append(f"{t.label}: restore not confirmed (no report showed its original setting "
                                    f"within {CONFIRM_TIMEOUT:g} s)")
                res.restored = False
        except (PrinterOffline, UnknownPrinter):
            res.problems.append(f"{t.label}: not restored (the printer went offline); its test colour may still be set")
            res.restored = False
        except Exception as e:               # one slot's failure must not skip the others' restores
            log.exception("slot test on %s: restoring %s failed", registry.log_label(serial), t.label)
            res.problems.append(f"{t.label}: not restored (error: {type(e).__name__}: {e}); "
                                f"its test colour may still be set")
            res.restored = False

    try:
        final = manager.wait_report(serial, lambda r: True, 0)
        if final is not None:
            left = {_norm(c) for c in colours}
            for lab, s in _slots(final, model).items():
                if _norm(s.color) in left:
                    res.problems.append(f"{lab}: test colour {s.color} still in the slot")
                    res.restored = False
        elif changed:
            res.problems.append("final check failed (no report from the printer); test colours may remain")
            res.restored = False
    except Exception as e:
        log.exception("slot test on %s: final check failed", registry.log_label(serial))
        res.problems.append(f"final check failed (error: {type(e).__name__}: {e}); test colours may remain")
        res.restored = False
