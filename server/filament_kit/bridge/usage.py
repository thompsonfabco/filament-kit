"""Usage tracking: when a print ends, deduct the filament it used from the spools in its AMS slots.

Ported from the owner's H2D usage tracker (`h2d-filament-scanner/usage/usage_tracker.py`, proven on hardware).

Lifecycle (`Tracker`, fed by `Manager.add_listener`): while a printer is RUNNING / PAUSE / PREPARE / SLICING the
job is remembered (`subtask_name`, plate, `mapping`); when it turns FINISH or FAILED it is settled
once. A job start drops the previous job's `mapping` / `plate_idx` from the merged report (`status.merge_report`),
so a job settles with its own mapping or none (`no_mapping`, nothing written). A FINISH/FAILED already shown by the first report after a (re)connect is never settled (it ended while
nobody watched, and may have been settled before a restart); a server restarted mid-print picks the job up from
that first RUNNING report and settles it when it ends. Exactly-once rests on that transition alone (the
watched state goes ACTIVE -> FINISH/FAILED once per job), not on `task_id`: LAN, SD-card and touchscreen
prints, and our calibration job, all report "0", and a reprint may reuse an id. Our own calibration job
(`fk-calib-*`) is never settled and logs nothing.

Settling (on a worker thread): the job's 3MF is fetched from the printer's SD card over FTPS by name,
`<subtask_name>_plate_<n>.gcode.3mf` then `<subtask_name>.gcode.3mf`, each in `/` then `/cache`, then a listed
file whose name is exactly one of those two, ignoring case, in an NLST of both (the printer has no MLSD and no
mtimes: never "the newest file", never a similar name).
`Metadata/slice_info.config` lists, per plate, `<filament id=N used_g=...>` with N the project filament number;
the printer's slot for it is `mapping[N - 1]` (a global slot id), which the slot map (`ams.load_map`) turns into a
label (A1, HT-A ...) (`decode`: the calibrated map's own numbers and the numbers prints taught it, then the
numbering scheme calibration proved, a label the printer had at the print's start; an uncalibrated map: the scheme
it has, else the model's first candidate scheme, for the log only), and the spool in that slot is the Spoolman
spool whose `location` is exactly "<printer name> – AMS <label>" (two non-archived spools there:
`ambiguous_spool`, nothing written). Grams = `used_g` × final `mc_percent` / 100 (a FINISH counts as 100 %, so
a late percent delta cannot under-count), rounded to 0.01 g; filaments with 0 g are skipped. The deduction is
`Spoolman.use(spool_id, grams)` (`PUT /spool/{id}/use`). A printer whose map is not `calibrated`, or is
`observe`, is in observe mode: entries are logged with `observe: true`, nothing is written.

Learning and checking (calibrated maps; ported from the scanner): the slots the printer showed when the print
started (`layout.build` of its first active report) are kept with the job. A number nothing decodes is learned
when exactly one loaded slot at the start holds the sliced filament (same `tray_info_idx`, or with no preset in the
slice the same type and colour): saved in the map (`SlotMap.learned`) and used from then on. A decoded slot that
held another filament than the slice says (another preset, or with none another type) is not deducted
(`slot_mismatch`); two prints in a row with such a slot make the map `suspect`: observe mode (from that print on)
until `mapping.LayoutWatch` re-maps the printer when it is idle (`mapping.request_remap`). A print whose decoded
slots all agreed resets the streak. Without a start layout (no AMS in the report) nothing is learned or checked.

Log: `state/printers/<serial>/usage.jsonl`, append-only, one JSON object per line, written by this process
only (one uvicorn worker; a module lock serialises appends and undo). Two kinds of lines:
  entry: {"id", "at", "job", "grams", "spool_id", "slot", "observe"[, "error"]}
  undo:  {"undo": <entry id>, "at"}
Undo never rewrites the file: it appends an undo line, and `entries` folds them into `undone`.

Entry shape returned by `entries` / `undo` (what `GET /api/printers/{id}/usage` and `POST /api/usage/{id}/undo`
serve):
  id        32 hex chars (unique across printers)
  at        ISO-8601 UTC, "2026-11-01T22:59:08Z"
  job       the print's subtask_name
  grams     float grams deducted (or that would be, in observe mode); null when the job could not be read
  spool_id  Spoolman spool id, or null (no spool in that slot / unknown)
  slot      slot label ("A2", "HT-A", "Ext"), or null (no mapping for that filament / job unreadable)
  observe   true: logged only, nothing written to Spoolman
  undone    true once undone
  error     only when set: "file_not_found" | "no_slice_info" | "plate_not_found" | "printer_unreachable" |
            "cert_changed" | "no_mapping" (the job's reports never carried `mapping`) (job-level, one entry,
            nothing written) | "spoolman_unreachable" | "spoolman_failed" | "ambiguous_spool" |
            "unmapped_slot" (calibrated map, but nothing decodes its slot id) | "slot_mismatch" (the decoded
            slot held another filament at the print's start) (that filament's write did not happen)
An entry was written to Spoolman iff observe is false, spool_id is set, grams > 0 and there is no error; only
those can be undone.

Exceptions (each has `.code` and `.status` for the API to map):
  UsageNotFound  404 not_found        unknown entry id / malformed serial or id
  TooOld         409 too_old          the entry is older than 7 days
  AlreadyUndone  409 already_undone   undone before
  NothingToUndo  409 nothing_to_undo  the entry wrote nothing (observe, no spool, error)
  SpoolChanged   409 spool_changed    that spool id is another spool now, or the spool is gone
A Spoolman failure during undo raises `SpoolmanError` and records nothing."""
from __future__ import annotations

import datetime as dt
import io
import json
import logging
import os
import re
import threading
import time
import uuid
import zipfile
from concurrent.futures import Future, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from .. import config
from ..pairing import give_to_state_owner, make_state_dir
from ..spoolman import SpoolmanError
from . import ams, ftps, hardware, layout, mapping, registry, status, tlspin

log = logging.getLogger(__name__)

FILE = "usage.jsonl"
UNDO_DAYS = 7
ACTIVE = {'RUNNING', 'PAUSE', 'PREPARE', 'SLICING'}
TERMINAL = {'FINISH', 'FAILED'}
DIRS = ('/', '/cache')
CALIB_PREFIX = 'fk-calib-'      # our calibration job (calib3mf): not a print, its file is deleted afterwards
MAX_SLICE_INFO = 4 * 1024 * 1024
ENTRY_ID = re.compile(r"[0-9a-f]{32}")
FIELDS = ('id', 'at', 'job', 'grams', 'spool_id', 'slot', 'observe')

_lock = threading.Lock()


class UsageError(Exception):
    code = 'usage_error'
    status = 400


class UsageNotFound(UsageError):
    code, status = 'not_found', 404


class TooOld(UsageError):
    code, status = 'too_old', 409


class AlreadyUndone(UsageError):
    code, status = 'already_undone', 409


class NothingToUndo(UsageError):
    code, status = 'nothing_to_undo', 409


class SpoolChanged(UsageError):
    code, status = 'spool_changed', 409


def _registered(spool) -> float | None:
    """A spool's `registered` time from Spoolman, in epoch seconds, or None when it can't be read."""
    text = spool.get('registered') if isinstance(spool, dict) else None
    if not isinstance(text, str):
        return None
    try:
        when = dt.datetime.fromisoformat(text.replace('Z', '+00:00'))
    except ValueError:
        return None
    if when.tzinfo is None:         # Spoolman's times are UTC
        when = when.replace(tzinfo=dt.timezone.utc)
    return when.timestamp()


def _same_spool(spoolman, rec: dict, at: float) -> None:
    """Spoolman's spool ids are reused: delete the newest spool, add one, and it has the old id. An Undo then would take
    grams off a spool that never fed that print. So the spool must have been there when the print ended. When that can't be
    shown, nothing is written: the guard exists to stop a wrong write."""
    entry = rec['id']
    try:
        spool = spoolman.get(f"spool/{int(rec['spool_id'])}")
    except SpoolmanError as e:
        if e.status == 404:
            raise SpoolChanged(f"usage entry {entry}: its spool is gone from Spoolman; nothing was changed") from None
        raise
    registered = _registered(spool)
    if registered is None:
        raise SpoolChanged(f"usage entry {entry}: can't tell when its spool was added; nothing was changed")
    if registered > at:
        raise SpoolChanged(f"usage entry {entry}: that spool was added after this print, so the original spool is gone; "
                           "nothing was changed")


def _now() -> float:
    return time.time()


def _iso(t: float) -> str:
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _epoch(s: Any) -> float | None:
    try:
        return dt.datetime.strptime(str(s), '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=dt.timezone.utc).timestamp()
    except ValueError:
        return None


# ---------------------------------------------------------------- the log

def _dir(serial: str) -> Path:
    if not isinstance(serial, str) or not registry.SERIAL.fullmatch(serial):
        raise UsageNotFound(f"no printer {serial!r}")
    return config.paths().state / "printers" / serial


def append(serial: str, entry: dict) -> dict:
    """Add an entry (id and at are filled in) to the printer's log; returns the stored line."""
    rec = {'id': uuid.uuid4().hex, 'at': _iso(_now()), **entry}
    with _lock:
        _write_line(serial, rec)
    return rec


def _write_line(serial: str, rec: dict) -> None:
    d = _dir(serial)
    make_state_dir(d)
    f = d / FILE
    new = not f.exists()
    fd = os.open(f, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, 'O_BINARY', 0), 0o600)
    try:
        if new:
            give_to_state_owner(f)
        os.write(fd, (json.dumps(rec, separators=(',', ':')) + "\n").encode('utf-8'))
        os.fsync(fd)
    finally:
        os.close(fd)


def _read(serial: str) -> tuple[list[dict], dict[str, str]]:
    """(entry lines in file order, {undone entry id: undo time})."""
    try:
        text = (_dir(serial) / FILE).read_text(encoding='utf-8')
    except FileNotFoundError:
        return [], {}
    out, undone = [], {}
    for line in text.splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue                    # a torn last line after a crash
        if not isinstance(rec, dict):
            continue
        if 'undo' in rec:
            undone.setdefault(str(rec['undo']), rec.get('at'))
        elif isinstance(rec.get('id'), str):
            out.append(rec)
    return out, undone


def _view(rec: dict, undone: dict) -> dict:
    e = {k: rec.get(k) for k in FIELDS}
    e['observe'] = bool(e['observe'])
    e['undone'] = rec['id'] in undone
    if rec.get('error'):
        e['error'] = rec['error']
    return e


def entries(serial: str, days: float = UNDO_DAYS) -> list[dict]:
    """The printer's entries of the last `days` days, newest first. UsageNotFound for a malformed serial; a
    printer without a log has none."""
    recs, undone = _read(serial)
    since = _now() - max(0.0, float(days)) * 86400
    out = [_view(r, undone) for r in recs if (_epoch(r.get('at')) or 0) >= since]
    out.reverse()
    return out


def _written(rec: dict) -> bool:
    g = rec.get('grams')
    return (not rec.get('observe') and rec.get('spool_id') is not None and not rec.get('error')
            and isinstance(g, (int, float)) and g > 0)


def undo(entry_id: str, spoolman) -> dict:
    """Give an entry's grams back to its spool (`use_weight` negative) once, within 7 days; returns the entry."""
    if not isinstance(entry_id, str) or not ENTRY_ID.fullmatch(entry_id):
        raise UsageNotFound(f"no usage entry {entry_id!r}")
    root = config.paths().state / "printers"
    with _lock:
        for d in sorted(root.iterdir()) if root.is_dir() else []:
            if not d.is_dir() or not registry.SERIAL.fullmatch(d.name):
                continue
            recs, undone = _read(d.name)
            rec = next((r for r in recs if r['id'] == entry_id), None)
            if rec is None:
                continue
            if entry_id in undone:
                raise AlreadyUndone(f"usage entry {entry_id} was undone already")
            at = _epoch(rec.get('at'))
            if at is None or _now() - at > UNDO_DAYS * 86400:
                raise TooOld(f"usage entry {entry_id} is older than {UNDO_DAYS} days")
            if not _written(rec):
                raise NothingToUndo(f"usage entry {entry_id} wrote nothing to Spoolman")
            _same_spool(spoolman, rec, at)
            spoolman.use(int(rec['spool_id']), -float(rec['grams']))
            _write_line(d.name, {'undo': entry_id, 'at': _iso(_now())})
            log.info("usage: printer %s: undid %s g on spool %s (%s)", d.name, rec['grams'], rec['spool_id'],
                     rec.get('job'))
            undone[entry_id] = _iso(_now())
            return _view(rec, undone)
    raise UsageNotFound(f"no usage entry {entry_id}")


# ---------------------------------------------------------------- the job's 3MF

def _plate_of(report: dict) -> str | None:
    p = status._int(report.get('plate_idx'))
    if p is not None and p > 0:
        return str(p)
    m = re.search(r'plate[_-]?(\d+)', str(report.get('gcode_file') or ''), re.I)
    return m.group(1) if m else None


def candidate_paths(subtask: str, plate: str | None) -> list[str]:
    stems = ([f"{subtask}_plate_{plate}"] if plate else []) + [subtask]
    return [f"{d.rstrip('/')}/{stem}.gcode.3mf" for stem in stems for d in DIRS]


def nlst_match(names: list[str], subtask: str, plate: str | None) -> str | None:
    """The listed 3MF named exactly `<subtask>_plate_<n>.gcode.3mf` or `<subtask>.gcode.3mf` ignoring case (that
    order), `/` before `/cache`. Only case differences are forgiven: a similar name is another job."""
    wanted = ([f"{subtask}_plate_{plate}.gcode.3mf".casefold()] if plate else []) +         [f"{subtask}.gcode.3mf".casefold()]
    for w in wanted:
        hits = sorted((n for n in names if n.rsplit('/', 1)[-1].casefold() == w),
                      key=lambda n: n.startswith('/cache'))
        if hits:
            return hits[0]
    return None


def fetch_3mf(printer: registry.Printer, subtask: str, plate: str | None) -> tuple[bytes | None, str | None]:
    """(bytes, path) of the job's 3MF on the printer, or (None, None). Raises tlspin.CertChanged, and
    ftps.FtpsError when the printer cannot be reached."""
    with ftps.Client(printer) as c:
        for p in candidate_paths(subtask, plate):
            try:
                data = c.download(p)
            except ftps.FtpsError:
                continue
            if data:
                return data, p
        names = []
        for d in DIRS:
            try:
                listed = c.nlst(d)
            except ftps.FtpsError as e:
                log.info("usage: printer %s: cannot list %s: %s", printer.serial, d, e)
                continue
            for n in listed:
                names.append(n if n.startswith('/') else f"{d.rstrip('/')}/{n}")
        p = nlst_match(names, subtask, plate)
        if p:
            try:
                data = c.download(p)
            except ftps.FtpsError as e:
                log.info("usage: printer %s: cannot download %s: %s", printer.serial, p, e)
                return None, None
            if data:
                return data, p
    return None, None


def parse_filaments(data: bytes) -> dict[str | None, list[dict]]:
    """{plate index: [{id, used_g, type, color, idx}]} from the 3MF's Metadata/slice_info.config; {} when there is
    none or it cannot be read."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        name = next((n for n in z.namelist() if n.lower().endswith('slice_info.config')), None)
        if name is None or z.getinfo(name).file_size > MAX_SLICE_INFO:
            return {}
        root = ElementTree.fromstring(z.read(name))
    except (zipfile.BadZipFile, ElementTree.ParseError, OSError, KeyError, ValueError):
        return {}
    plates = root.findall('plate') or [root]
    out: dict[str | None, list[dict]] = {}
    for pl in plates:
        index = next((m.get('value') for m in pl.findall('metadata') if m.get('key') == 'index'), None)
        fils = []
        for f in pl.findall('filament'):
            fid = status._int(f.get('id'))
            try:
                g = float(f.get('used_g') or 0)
            except ValueError:
                g = 0.0
            if fid is None:
                continue
            fils.append({'id': fid, 'used_g': g, 'type': f.get('type'), 'color': f.get('color'),
                         'idx': f.get('tray_info_idx')})
        out[index] = fils
    return out


# ---------------------------------------------------------------- settling

def _guess_label(g: int, model=None) -> str | None:
    """Uncalibrated (observe mode, for the log only): the inverse of `ams.default_global`: the number decoded
    with the model's first numbering scheme, labelled as `layout` labels that slot. An external id the model
    does not have (e.g. 255 on a single-holder printer) is None."""
    hw = hardware.load()
    mi = hw.model(model)
    try:
        dec = hw.scheme(mi.numbering[0]).decode(g)
    except KeyError:
        dec = None
    if dec is None:
        return None
    a, t = dec
    if a in layout.EXT_DEFAULT and not any(x.id == a for x in mi.externals):
        return None
    return layout.label_for(a, t, mi, hw)


def start_slots(serial: str, report: dict) -> dict[str, dict]:
    """label -> {ams_id, tray_id, type, idx, color, present} of every slot in the report (the print's start); {}
    when the report shows no AMS (nothing to learn from or check against)."""
    try:
        if not isinstance(status._d(status._d(report).get('ams')).get('ams'), list):
            return {}
        out = {}
        for u in layout.build(report, ams.printer_model(serial)).units:
            for sl in u.slots:
                t = sl.raw if isinstance(sl.raw, dict) else {}
                typ = status._s(t.get('tray_type'))
                out[sl.label] = {'ams_id': u.ams_id, 'tray_id': sl.tray_id, 'type': typ,
                                 'idx': status._s(t.get('tray_info_idx')),
                                 'color': status._s(t.get('tray_color')).upper()[:6],
                                 'present': bool(typ) if sl.present is None else bool(sl.present and typ)}
        return out
    except Exception:  # noqa: BLE001 - an odd report: no start layout, never a lost job
        log.exception("usage: printer %s: cannot read the slots at the print's start", serial)
        return {}


def _same_type(a, b) -> bool:
    return bool(a) and str(a).strip().upper() == str(b or '').strip().upper()


def _holds(slot: dict | None, f: dict) -> bool:
    """The slot (at the print's start) held the sliced filament, the scanner's rule: same preset, or (no preset
    sliced, or another one) the same type. The presence bit is not asked: a slot reporting a type counts."""
    if not slot:
        return False
    return bool(f.get('idx')) and slot.get('idx') == f.get('idx') or _same_type(slot.get('type'), f.get('type'))


def _matches_unseen(slot: dict, f: dict) -> bool:
    """The learn rule's match: the same preset, or with no preset in the slice the same type and colour."""
    if not slot.get('present'):
        return False
    if f.get('idx'):
        return slot.get('idx') == f['idx']
    return _same_type(slot.get('type'), f.get('type')) and \
        slot.get('color') == str(f.get('color') or '').lstrip('#')[:6].upper()


def decode(g: int, smap: ams.SlotMap, model=None, start: dict | None = None,
           hw: hardware.Hardware | None = None) -> tuple[str | None, str]:
    """A printer slot number -> (label or None, how). Calibrated: the map's numbers ("map"), then numbers prints
    taught it ("learned"), then the scheme calibration proved ("scheme": only a label the printer had at the
    print's start, or with no start layout one the map lists, and never one the map gives another number).
    Uncalibrated: the map's scheme if it has one, else the model's first candidate ("model": for the log only)."""
    hw = hw or hardware.load()
    mi = hw.model(model)
    if g is None or g < 0:
        return None, 'unused'
    if smap.calibrated:
        for label, sl in smap.slots.items():
            if isinstance(sl, dict) and status._int(sl.get('global_id')) == g:
                return label, 'map'
        if str(g) in smap.learned:
            return smap.learned[str(g)], 'learned'
    if smap.scheme:
        if g in layout.EXT_DEFAULT or any(x.id == g for x in mi.externals):
            dec = (g, 0)
        else:
            try:
                dec = hw.scheme(smap.scheme).decode(g)
            except KeyError:
                dec = None
        label = None
        if dec is not None and start:       # the label the printer gave that slot at the print's start
            label = next((lab for lab, sl in start.items() if (sl.get('ams_id'), sl.get('tray_id')) == dec), None)
        elif dec is not None:               # no start layout: only a label the map lists for that slot
            lab = layout.label_for(*dec, mi, hw)
            sl = smap.slots.get(lab) if lab else None
            if isinstance(sl, dict) and (status._int(sl.get('ams_id')), status._int(sl.get('tray_id'))) == dec:
                label = lab
        if label is not None:
            mine = smap.slots.get(label)
            other = isinstance(mine, dict) and status._int(mine.get('global_id')) not in (None, g)
            if not (smap.calibrated and other):
                return label, 'scheme'
    if smap.calibrated:
        return None, 'unknown'
    if start:                               # the model's first candidate, labelled as the printer showed it
        try:
            dec = (g, 0) if g in layout.EXT_DEFAULT else hw.scheme(mi.numbering[0]).decode(g)
        except (KeyError, IndexError):
            dec = None
        hit = next((lab for lab, sl in start.items() if (sl.get('ams_id'), sl.get('tray_id')) == dec), None)
        if hit is not None:
            return hit, 'model'
    return _guess_label(g, mi), 'model'


def _save_map(serial: str, smap: ams.SlotMap, stamp) -> None:
    """Save what a print taught the map, unless the map changed since it was read (a mapping job saved a new
    one: that one wins)."""
    try:
        if not ams.save_map_if(serial, smap, stamp):
            log.info("usage: printer %s: the slot map changed meanwhile; this print's learning is dropped", serial)
    except OSError:
        log.exception("usage: printer %s: cannot save the slot map", serial)


class _Watch:
    def __init__(self):
        self.prev: str | None = None
        self.job: dict | None = None


class Tracker:
    """Watches every printer of `manager` and settles each print it saw end (see the module docstring)."""

    def __init__(self, manager, spoolman):
        self._spoolman = spoolman
        self._lock = threading.Lock()
        self._watch: dict[str, _Watch] = {}
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='usage')
        self._futures: list[Future] = []
        self._stopped = False
        manager.add_listener(self._on_report)

    def stop(self) -> None:
        self._stopped = True
        self._pool.shutdown(wait=False)

    def flush(self, timeout: float) -> None:
        """Wait up to `timeout` s for the settles queued so far (tests, shutdown)."""
        with self._lock:
            fs = list(self._futures)
        wait(fs, timeout)

    def _on_report(self, serial: str, report: dict, first: bool) -> None:
        if self._stopped:
            return
        gs = report.get('gcode_state')
        if not isinstance(gs, str):
            return
        with self._lock:
            w = self._watch.setdefault(serial, _Watch())
            prev, w.prev = w.prev, gs
            if gs in ACTIVE:
                sub = str(report.get('subtask_name') or '')
                slots = w.job.get('slots') if w.job is not None and w.job['subtask'] == sub else None
                if slots is None:
                    slots = start_slots(serial, report)
                w.job = {'subtask': sub, 'plate': _plate_of(report), 'mapping': report.get('mapping'),
                         'slots': slots}
                return
            job, w.job = w.job, None
            if first or gs not in TERMINAL or prev not in ACTIVE or job is None:
                return
            if job['subtask'].startswith(CALIB_PREFIX):
                return
            pct = 100.0 if gs == 'FINISH' else float(status._int(report.get('mc_percent'), 0) or 0)
            log.info("usage: printer %s: %s %s at %s %%", serial, job['subtask'], gs, pct)
            self._futures = [f for f in self._futures if not f.done()]
            try:
                self._futures.append(self._pool.submit(self._settle, serial, job, pct))
            except RuntimeError:          # stopped meanwhile
                pass

    def _settle(self, serial: str, job: dict, pct: float) -> None:
        try:
            settle(serial, job, pct, self._spoolman)
        except Exception:
            log.exception("usage: printer %s: settling %s failed", serial, job.get('subtask'))


def settle(serial: str, job: dict, pct: float, spoolman) -> list[dict]:
    """Settle one ended job (`{subtask, plate, mapping}`) at `pct` %: deduct and log; returns the new entries."""
    name = job.get('subtask') or ''
    p = registry.load().get(serial)

    def fail(error: str) -> list[dict]:
        log.warning("usage: printer %s: job %r not settled: %s", serial, name, error)
        return [append(serial, {'job': name, 'grams': None, 'spool_id': None, 'slot': None, 'observe': False,
                                'error': error})]
    if p is None or not name:
        return fail('file_not_found')
    if not isinstance(job.get('mapping'), list) or not job['mapping']:
        return fail('no_mapping')        # the printer never said which slots this job used: guess nothing
    try:
        data, path = fetch_3mf(p, name, job.get('plate'))
    except tlspin.CertChanged:
        return fail('cert_changed')
    except ftps.FtpsError:
        return fail('printer_unreachable')
    if data is None:
        return fail('file_not_found')
    plates = parse_filaments(data)
    if not plates:
        return fail('no_slice_info')
    plate = job.get('plate')
    fils = plates.get(plate) if plate in plates else (next(iter(plates.values())) if len(plates) == 1 else None)
    if fils is None:
        return fail('plate_not_found')

    smap = ams.load_map(serial)
    stamp = smap.updated
    hw = hardware.load()
    model = p.model or None
    start = job.get('slots') if isinstance(job.get('slots'), dict) else {}
    spools: dict[str, list[dict]] = {}
    spool_error = None
    try:
        for s in spoolman.get('spool') or []:          # archived spools are not listed
            spools.setdefault(str(s.get('location') or ''), []).append(s)
    except SpoolmanError as e:
        log.warning("usage: printer %s: cannot list spools: %s", serial, e)
        spool_error = 'spoolman_unreachable'
    mapping_ = job.get('mapping') if isinstance(job.get('mapping'), list) else []
    frac = max(0.0, min(100.0, pct)) / 100.0

    # decode every filament first: learning and the mismatch streak decide observe mode for this very print
    plan, mismatches, checked, changed = [], 0, 0, False
    for f in fils:
        grams = round(f['used_g'] * frac, 2)
        if grams <= 0:
            continue
        g = status._int(mapping_[f['id'] - 1]) if 1 <= f['id'] <= len(mapping_) else None
        label, how = decode(g, smap, model, start, hw) if g is not None else (None, 'no mapping entry')
        if label is None and smap.calibrated and g is not None and g >= 0 and start:
            cands = [lab for lab, sl in start.items() if _matches_unseen(sl, f)]
            if len(cands) == 1:
                label, how = cands[0], 'learned from this print'
                smap.learned[str(g)] = label
                changed = True
                log.info("usage: printer %s: learned slot number %s = %s from %r", serial, g, label, name)
        ok = True
        if smap.calibrated and label and start:
            ok = _holds(start.get(label), f)
            checked += 1
            if not ok:
                mismatches += 1
        plan.append((f, grams, g, label, how, ok))
    if smap.calibrated and checked:
        before = (smap.mismatch_streak, smap.suspect)
        if mismatches:
            smap.mismatch_streak += 1
            if smap.mismatch_streak >= 2 and not smap.suspect:
                smap.suspect, smap.observe = True, True
                log.warning("usage: printer %s: two prints in a row disagreed with the slot map: logging only "
                            "until it is re-mapped", serial)
        else:
            smap.mismatch_streak = 0
        changed = changed or (smap.mismatch_streak, smap.suspect) != before
    if changed:
        _save_map(serial, smap, stamp)
        if smap.suspect:
            mapping.request_remap(serial)
    observe = not smap.calibrated or smap.observe

    out = []
    for f, grams, g, label, how, ok in plan:
        here = []
        if label:
            pname = registry.display_name(p)
            here = spools.get(status.location(pname, label), [])
            old = next((a for a, cur in layout.aliases(p.model).items() if cur == label), None)
            if old:     # a spool still at the holder's older location ("<name> – AMS Ext" for Ext-L)
                here = here + spools.get(status.location(pname, old), [])
        spool = here[0] if len(here) == 1 else None
        entry = {'job': name, 'grams': grams, 'spool_id': spool.get('id') if spool else None, 'slot': label,
                 'observe': observe}
        if smap.calibrated and g is not None and g >= 0 and label is None:
            entry['error'] = 'unmapped_slot'     # a slot the map does not know: run Map slots
        elif not ok:
            entry['error'] = 'slot_mismatch'     # the slot held another filament than the slice says
        elif spool_error and label:
            entry['error'] = spool_error
        elif len(here) > 1:
            log.warning("usage: printer %s: spools %s all claim slot %s; nothing deducted", serial,
                        [x.get('id') for x in here], label)
            entry['error'] = 'ambiguous_spool'
        elif not observe and spool:
            try:
                spoolman.use(spool['id'], grams)
            except SpoolmanError as e:
                log.warning("usage: printer %s: cannot deduct %s g from spool %s: %s", serial, grams, spool['id'], e)
                entry['error'] = 'spoolman_failed'
        log.info("usage: printer %s: %s %s g filament %s (mapping %s, %s) -> %s spool %s%s", serial,
                 'would deduct' if observe else 'deducted', grams, f['id'], g, how, label, entry['spool_id'],
                 f" [{entry['error']}]" if entry.get('error') else '')
        out.append(append(serial, entry))
    log.info("usage: printer %s: job %r settled from %s (%d entries%s)", serial, name, path, len(out),
             ', observe mode' if observe else '')
    return out
