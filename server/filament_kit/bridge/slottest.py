"""Slot test: prove which (ams_id, tray_id) address reaches which AMS slot, then put every slot back.

For each slot (AMS units, AMS HT, external holder; empty slots too) the slot's own setting is written back with
only the colour changed to a unique test colour (`FA<nn>00FF`, nn in hex; another prefix if a slot already holds it), and the slot counts as confirmed once a report
shows that colour on that unit/tray (within CONFIRM_TIMEOUT). Afterwards every slot that may have changed is
written back to its snapshot and the restore is confirmed from the report. The test stops early, and still
restores, when the printer starts a job, goes offline, or refuses writes (Developer Mode). Nothing is saved here:
the caller (mapping) turns the result into a SlotMap.

Idle = connected (or connected but flagged `needs_developer_mode`) and `gcode_state` not in status.ACTIVE."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

from . import ams, status
from .connection import PrinterOffline, UnknownPrinter

log = logging.getLogger(__name__)

CONFIRM_TIMEOUT = 10.0          # seconds for a report to show a write
TEST_COLOUR = "{prefix}{n:02X}00FF"   # RRGGBBAA; n = the slot's number in test order (01, 02 ... in hex)
TEST_PREFIXES = ("FA", "FB", "FC", "FD", "FE", "F9", "F8", "F7")
ONLINE = ('connected', 'needs_developer_mode')   # the MQTT session is up in both


class PrinterBusy(Exception):
    """The printer is running, paused, preparing or slicing a job (the gcode_state is the message)."""


@dataclass
class SlotTestResult:
    confirmed: dict[str, dict] = field(default_factory=dict)   # label -> {ams_id, tray_id}
    restored: bool = True              # every changed slot confirmed back at its snapshot, no test colour left
    problems: list[str] = field(default_factory=list)          # one line per issue, "<label>: ..." for a slot
    needs_developer_mode: bool = False


@dataclass
class _Target:
    label: str
    ams_id: int
    tray_id: int
    snap: dict


def check_idle(manager, serial: str) -> None:
    """Raise PrinterOffline / PrinterBusy unless the printer may be changed now."""
    if manager.state(serial) not in ONLINE:
        raise PrinterOffline(serial)
    gs = manager.summary(serial)['gcode_state']
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
    p = status._d(report)
    if unit.label == ams.EXT:
        return status._d(p.get('vt_tray'))
    for u in status._l(status._d(p.get('ams')).get('ams')):
        if status._int(u.get('id')) == unit.ams_id:
            for t in status._l(u.get('tray')):
                if status._int(t.get('id')) == slot.tray_id:
                    return t
    return {}


def _snapshot(t: dict) -> dict:
    return {k: status._s(t.get(k)) for k in ('tray_info_idx', 'tray_color', 'tray_type', 'tray_sub_brands')} | \
        {k: t.get(k) for k in ('nozzle_temp_min', 'nozzle_temp_max')}


def _slots(report: dict) -> dict[str, ams.Slot]:
    return {s.label: s for u in ams.units(report) for s in u.slots}


def _norm(colour: str) -> str:
    c = (colour or '').upper()
    return '' if c in ('', '00000000') else c


def _showing(report: dict, colour: str) -> list[str]:
    """Labels whose slot shows `colour`."""
    c = _norm(colour)
    return [lab for lab, s in _slots(report).items() if _norm(s.color) == c]


def _matches(report: dict, t: _Target) -> bool:
    s = _slots(report).get(t.label)
    return s is not None and s.preset == t.snap['tray_info_idx'] and s.type == t.snap['tray_type'] and \
        _norm(s.color) == _norm(t.snap['tray_color'])


def _reason(reply: dict) -> str:
    return str(reply.get('reason') or reply.get('err_code') or reply.get('result') or 'refused')


def _failed(reply: dict | None) -> bool:
    return reply is not None and str(reply.get('result', '')).lower() != 'success'


def run(manager, serial: str, on_step: Callable[[str], None]) -> SlotTestResult:
    """Run the slot test on an idle printer (raises PrinterOffline / PrinterBusy before touching anything).

    `on_step(text)` is told each step ("Testing slot A1 (1/6)", "Restoring slot A1" ...). Returns the result; a
    problem never goes unreported: every slot not confirmed and every slot not confirmed restored has a line."""
    def step(text: str) -> None:
        try:
            on_step(text)
        except Exception:
            log.exception("slot test: progress callback failed")

    check_idle(manager, serial)
    step("Reading the AMS slots")
    report = manager.wait_report(serial, lambda r: True, 0)
    if report is None:
        raise PrinterOffline(serial)
    targets = []
    for u in ams.units(report):
        for s in u.slots:
            targets.append(_Target(s.label, u.ams_id, s.tray_id, _snapshot(_raw_tray(report, u, s))))
    by_label = {t.label: t for t in targets}
    res = SlotTestResult()
    changed: list[_Target] = []          # may differ from their snapshot now
    reported: set[str] = set()           # slots that already have a "not confirmed" line
    colours: set[str] = set()            # test colours written in this run
    taken = {t.snap['tray_color'] for t in targets if t.snap['tray_color']}   # never pick a colour a slot holds
    abort = None

    def mark(t: _Target) -> None:
        if t not in changed:
            changed.append(t)

    try:
        for n, t in enumerate(targets, 1):
            try:
                check_idle(manager, serial)
            except PrinterBusy as e:
                abort = f"printer_busy: the printer started a job ({e}); slot test stopped"
                break
            except PrinterOffline:
                abort = "printer_offline: the printer went offline; slot test stopped"
                break
            step(f"Testing slot {t.label} ({n}/{len(targets)})")
            colour = pick_test_colour(n, taken)
            taken.add(colour)
            colours.add(colour)
            try:
                reply = manager.set_slot(serial, t.ams_id, t.tray_id, dict(t.snap, tray_color=colour))
            except (PrinterOffline, UnknownPrinter):
                mark(t)                  # it may have reached the printer before the drop
                abort = "printer_offline: the printer went offline; slot test stopped"
                break
            if _failed(reply):
                if manager.state(serial) == 'needs_developer_mode':
                    res.needs_developer_mode = True
                    res.problems.append(f"needs_developer_mode: the printer refused the write to {t.label} "
                                        f"({_reason(reply)}); turn on Developer Mode (LAN-only mode) and retry")
                    res.problems.append(f"{t.label}: not confirmed (write refused)")
                    reported.add(t.label)
                    abort = "needs_developer_mode"
                    break
                res.problems.append(f"{t.label}: not confirmed (write refused: {_reason(reply)})")
                reported.add(t.label)
                continue
            mark(t)
            r = manager.wait_report(serial, lambda r, c=colour: _busy(r) or bool(_showing(r, c)), CONFIRM_TIMEOUT)
            if r is None:
                if manager.state(serial) not in ONLINE:
                    abort = "printer_offline: the printer went offline; slot test stopped"
                    break
                res.problems.append(f"{t.label}: not confirmed (no report showed its test colour within "
                                    f"{CONFIRM_TIMEOUT:g} s)")
                reported.add(t.label)
                continue
            where = _showing(r, colour)
            for lab in where:                # before any abort: wherever the colour landed gets restored
                if lab in by_label:
                    mark(by_label[lab])
            if _busy(r):
                abort = (f"printer_busy: the printer started a job ({status._s(r.get('gcode_state'))}); "
                         f"slot test stopped")
                break
            if t.label in where:
                res.confirmed[t.label] = {'ams_id': t.ams_id, 'tray_id': t.tray_id}
            else:
                res.problems.append(f"{t.label}: not confirmed (its test colour appeared on {', '.join(where)})")
                reported.add(t.label)
    except Exception as e:                  # never leave test colours behind because of a bug or callback
        log.exception("slot test on %s failed", serial)
        abort = f"error: slot test failed ({type(e).__name__}: {e})"

    if abort and abort != "needs_developer_mode":
        res.problems.insert(0, abort)
    why = (abort or '').split(':')[0] or 'not tested'
    for t in targets:
        if t.label not in res.confirmed and t.label not in reported:
            res.problems.append(f"{t.label}: not confirmed ({why})")

    # restore: unconfirmed addresses first, so a mis-addressed write is overwritten by the right slot's restore
    order = [t for t in changed if t.label not in res.confirmed] + [t for t in changed if t.label in res.confirmed]
    for t in order:
        step(f"Restoring slot {t.label}")
        try:
            reply = manager.set_slot(serial, t.ams_id, t.tray_id, t.snap)
            if _failed(reply):
                res.problems.append(f"{t.label}: restore refused ({_reason(reply)}); "
                                    f"its test colour may still be set")
                res.restored = False
                continue
            if manager.wait_report(serial, lambda r, t=t: _matches(r, t), CONFIRM_TIMEOUT) is None:
                res.problems.append(f"{t.label}: restore not confirmed (no report showed its original setting "
                                    f"within {CONFIRM_TIMEOUT:g} s)")
                res.restored = False
        except (PrinterOffline, UnknownPrinter):
            res.problems.append(f"{t.label}: not restored (printer_offline); its test colour may still be set")
            res.restored = False
        except Exception as e:               # one slot's failure must not skip the others' restores
            log.exception("slot test on %s: restoring %s failed", serial, t.label)
            res.problems.append(f"{t.label}: not restored (error: {type(e).__name__}: {e}); "
                                f"its test colour may still be set")
            res.restored = False

    try:
        final = manager.wait_report(serial, lambda r: True, 0)
        if final is not None:
            left = {_norm(c) for c in colours}
            for lab, s in _slots(final).items():
                if _norm(s.color) in left:
                    res.problems.append(f"{lab}: test colour {s.color} still in the slot")
                    res.restored = False
    except Exception as e:
        log.exception("slot test on %s: final check failed", serial)
        res.problems.append(f"final check failed (error: {type(e).__name__}: {e}); test colours may remain")
        res.restored = False
    step("Slot test finished")
    return res
