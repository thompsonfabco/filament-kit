"""Calibration job: learn how a printer numbers its AMS slots, with a gcode-only job that never heats or moves.

`build(labels)` makes a minimal Bambu project 3MF with one PLA filament per slot label and a plate gcode that is
only comments and `M400`. `run(manager, serial, slotmap)` uploads it over FTPS to `/cache/fk-calib-<serial>.gcode.3mf`,
starts it with `ams_mapping` = filament i -> the slot's candidate global id (`ams.default_global`), waits (at most
`JOB_TIMEOUT` s) for the job to start and end, records the `mapping` and `ams.tray_now` the printer reports, and
compares the reported mapping with what was sent. Afterwards (always) the file is deleted and every slot whose
settings changed since the start is set back from the snapshot taken at the start and the restore is verified
from the next report (`CalibResult.restored` false when any slot was not confirmed back). It does not save a
SlotMap (the mapping job does).

Watchdog (the gcode never heats or loads, so either means the printer is doing something we did not ask for):
while the job is watched, a nozzle or bed TARGET temperature above the snapshot's (`nozzle_target_temper`,
`bed_target_temper`; for the H2D's packed `device.extruder.info[].temp` / `device.bed.info.temp` any change of
the decoded target) or an `ams.tray_now` other than the snapshot's sends `stop` at once. After the job, a
`tray_now` other than the snapshot's is the problem "printer left a filament loaded in the toolhead" and
`restored` is false. A job that never started still gets a best-effort `stop`.

The print command, modelled on what Bambu Studio sends in LAN mode (to be confirmed on the owner's H2D, Task 9):

    {"print": {
        "command": "project_file",
        "param": "Metadata/plate_1.gcode",
        "url": "ftp:///cache/fk-calib-<serial>.gcode.3mf",
        "file": "",
        "md5": "",
        "subtask_name": "fk-calib-<serial>",
        "project_id": "0", "profile_id": "0", "task_id": "0", "subtask_id": "0",
        "bed_type": "auto",
        "use_ams": true,
        "ams_mapping": [<global id of slot 1>, <global id of slot 2>, ...],
        "bed_levelling": false, "flow_cali": false, "vibration_cali": false,
        "layer_inspect": false, "timelapse": false
    }}

`sequence_id` is left to `Manager.publish`. Not sent (open for Task 9): `ams_mapping2`, `md5` of the file.

Only loaded slots take part (an empty slot is listed in `skipped`). Refusals before anything is sent are reported
as codes in `problems`: `printer_offline`, `printer_busy`, `not_configured`, `cert_changed` (FTPS leaf not the pinned
one: nothing uploaded, no Access Code sent). Everything else is a sentence."""
from __future__ import annotations

import colorsys
import copy
import hashlib
import io
import json
import logging
import time
import zipfile
from dataclasses import dataclass, field
from xml.sax.saxutils import quoteattr

from . import ftps, registry, snapshot, tlspin
from .ams import SlotMap, default_global
from .status import _d, _int, _l, _s, packed

log = logging.getLogger(__name__)

JOB_TIMEOUT = 120.0        # seconds from the print command to the end of the job
SNAPSHOT_TIMEOUT = 10.0
STOP_TIMEOUT = 20.0
RESTORE_TIMEOUT = 20.0
BUSY = ('RUNNING', 'PAUSE', 'PREPARE', 'SLICING')
ENDED = ('FINISH', 'FAILED')
REFUSED = "printer refused the calibration job"
GCODE = "Metadata/plate_1.gcode"
_ZIP_TIME = (2026, 1, 1, 0, 0, 0)


def job_name(serial: str) -> str:
    return f"fk-calib-{serial}"


def remote_path(serial: str) -> str:
    return f"/cache/{job_name(serial)}.gcode.3mf"


@dataclass
class CalibResult:
    decoding: dict[str, int] = field(default_factory=dict)   # label -> the global id the printer reported
    consistent: bool = False                                  # job finished and reported exactly what was sent
    problems: list[str] = field(default_factory=list)
    sent: dict[str, int] = field(default_factory=dict)        # label -> the candidate global id sent
    mapping: list | None = None                               # the raw `mapping` the printer reported
    tray_now: list[str] = field(default_factory=list)         # each `ams.tray_now` seen during the job
    skipped: list[str] = field(default_factory=list)          # empty slots, not part of the job
    cert_changed: bool = False
    restored: bool = True     # every slot the restore step had to put back was confirmed back (true: none changed)


# ---------------------------------------------------------------- the 3MF

def _colors(n: int) -> list[str]:
    out = []
    for i in range(n):
        r, g, b = colorsys.hsv_to_rgb((i * 0.618033988749895) % 1.0, 0.85, 0.95 - 0.25 * ((i // 7) % 2))
        out.append("#%02X%02X%02X" % (round(r * 255), round(g * 255), round(b * 255)))
    return out


def gcode(labels: list[str]) -> str:
    """Comments and M400 only: no heating, homing, moves or tool changes."""
    lines = ["; HEADER_BLOCK_START",
             "; filament-kit slot calibration: no heating, no homing, no motion",
             "; total layer number: 0",
             "; total filament length [mm] : 0.00",
             "; total filament weight [g] : 0.00",
             f"; total filament count: {len(labels)}",
             "; HEADER_BLOCK_END"]
    lines += [f"; filament {i}: slot {label}" for i, label in enumerate(labels, 1)]
    lines += ["M400", "; end of calibration job", ""]
    return "\n".join(lines)


def build(slots: list[str]) -> bytes:
    """A minimal Bambu project 3MF with one PLA filament per slot label (filament ids 1..N in label order)."""
    labels = list(slots)
    if not labels:
        raise ValueError("no slots to calibrate")
    colors = _colors(len(labels))
    code = gcode(labels).encode()
    fils = "\n".join(f'    <filament id="{i}" tray_info_idx="" type="PLA" color="{c}" used_m="0" used_g="0"/>'
                     for i, c in enumerate(colors, 1))
    files = {
        "[Content_Types].xml":
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
            ' <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
            ' <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>\n'
            ' <Default Extension="gcode" ContentType="text/x.gcode"/>\n'
            '</Types>\n',
        "_rels/.rels":
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
            ' <Relationship Target="/3D/3dmodel.model" Id="rel-1" '
            'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n'
            '</Relationships>\n',
        "3D/3dmodel.model":
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<model unit="millimeter" xml:lang="en-US" '
            'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
            'xmlns:BambuStudio="http://schemas.bambulab.com/package/2021">\n'
            ' <metadata name="Application">filament-kit</metadata>\n'
            ' <metadata name="BambuStudio:3mfVersion">1</metadata>\n'
            ' <metadata name="Title">slot calibration</metadata>\n'
            ' <resources/>\n'
            ' <build/>\n'
            '</model>\n',
        GCODE: code,
        GCODE + ".md5": hashlib.md5(code).hexdigest().upper(),
        "Metadata/slice_info.config":
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<config>\n'
            '  <plate>\n'
            '    <metadata key="index" value="1"/>\n'
            '    <metadata key="prediction" value="1"/>\n'
            '    <metadata key="weight" value="0.00"/>\n'
            '    <metadata key="outside" value="false"/>\n'
            '    <metadata key="support_used" value="false"/>\n'
            '    <metadata key="label_object_enabled" value="false"/>\n'
            f'{fils}\n'
            '  </plate>\n'
            '</config>\n',
        "Metadata/model_settings.config":
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<config>\n'
            '  <plate>\n'
            '    <metadata key="plater_id" value="1"/>\n'
            f'    <metadata key="plater_name" value={quoteattr("slot calibration")}/>\n'
            '    <metadata key="locked" value="false"/>\n'
            f'    <metadata key="gcode_file" value="{GCODE}"/>\n'
            '  </plate>\n'
            '</config>\n',
        "Metadata/project_settings.config":
            json.dumps({"name": "project_settings", "from": "project",
                        "filament_type": ["PLA"] * len(labels), "filament_colour": colors,
                        "filament_settings_id": [""] * len(labels)}, indent=4) + "\n",
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            info = zipfile.ZipInfo(name, _ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    return buf.getvalue()


def payload(serial: str, ams_mapping: list[int]) -> dict:
    """The `project_file` print command (see the module docstring)."""
    return {"print": {
        "command": "project_file",
        "param": GCODE,
        "url": f"ftp://{remote_path(serial)}",
        "file": "",
        "md5": "",
        "subtask_name": job_name(serial),
        "project_id": "0", "profile_id": "0", "task_id": "0", "subtask_id": "0",
        "bed_type": "auto",
        "use_ams": True,
        "ams_mapping": list(ams_mapping),
        "bed_levelling": False, "flow_cali": False, "vibration_cali": False,
        "layer_inspect": False, "timelapse": False,
    }}


# ---------------------------------------------------------------- report helpers

def _trays(report: dict) -> dict[tuple[int, int], dict]:
    """(ams_id, tray_id) -> raw tray dict; the external holder as (its id, 0), as `ams.units` labels it."""
    out: dict[tuple[int, int], dict] = {}
    for u in _l(_d(_d(report).get('ams')).get('ams')):
        uid = _int(u.get('id'))
        if uid is None:
            continue
        for t in _l(u.get('tray')):
            tid = _int(t.get('id'))
            if tid is not None and isinstance(t, dict):
                out[(uid, tid)] = t
    vt = _d(report).get('vt_tray')
    if isinstance(vt, dict):
        out[(_int(vt.get('id'), 254), 0)] = vt
    return out


def _key(slot: dict) -> tuple[int, int] | None:
    a, t = _int(slot.get('ams_id')), _int(slot.get('tray_id'))
    return None if a is None or t is None else (a, t)


def _loaded(t: dict | None) -> bool:
    return isinstance(t, dict) and bool(_s(t.get('tray_type')))


def _same(a: dict | None, b: dict | None) -> bool:
    a, b = a or {}, b or {}
    return (_s(a.get('tray_type')) == _s(b.get('tray_type'))
            and _s(a.get('tray_color')).upper() == _s(b.get('tray_color')).upper()
            and _s(a.get('tray_info_idx')) == _s(b.get('tray_info_idx')))


def _setting(t: dict) -> dict:
    """The slot settings to put back (`Manager.set_slot`'s `setting`), from the tray as reported."""
    s = {'tray_info_idx': _s(t.get('tray_info_idx')), 'tray_color': _s(t.get('tray_color')),
         'tray_type': _s(t.get('tray_type'))}
    for k in ('nozzle_temp_min', 'nozzle_temp_max'):
        v = _int(t.get(k))
        if v is not None:
            s[k] = v
    return s


def _ok(reply: dict) -> bool:
    return isinstance(reply, dict) and str(reply.get('result', '')).lower() == 'success'


# ---------------------------------------------------------------- the job

def run(manager, serial: str, slotmap: SlotMap, printer: registry.Printer | None = None,
        should_stop=None) -> CalibResult:
    """Run the calibration job on an idle, connected printer (see the module docstring). Never raises for
    printer-side trouble: everything lands in `CalibResult.problems`. Once the upload was attempted, the file is
    always deleted (best effort, over a new session; skipped only for a changed leaf) and, once the job was sent,
    the slots are always restored, whatever went wrong in between. The snapshot of the loaded slots is saved to
    disk (`snapshot.save`) before the print command and deleted after a confirmed restore. `should_stop()` true
    (CLI signal, service stopping) stops the job at once (`stop` command), then the slots are restored."""
    res = CalibResult()
    if manager.state(serial) != 'connected':
        res.problems.append('printer_offline')
        return res
    snap = manager.wait_report(serial, lambda r: True, SNAPSHOT_TIMEOUT)
    if snap is None:
        res.problems.append('printer_offline')
        return res
    snap = copy.deepcopy(snap)
    if _s(snap.get('gcode_state')).upper() in BUSY:
        res.problems.append('printer_busy')
        return res

    trays0 = _trays(snap)
    labels: list[str] = []
    sent: list[int] = []
    for label, slot in slotmap.slots.items():
        key = _key(slot)
        if key is None or not _loaded(trays0.get(key)):
            res.skipped.append(label)
            continue
        labels.append(label)
        sent.append(default_global(*key))
    res.sent = dict(zip(labels, sent))
    if not labels:
        res.problems.append("no loaded slots to calibrate")
        return res

    if printer is None:
        printer = registry.load().get(serial)
    if printer is None or not printer.configured or not printer.access_code:
        res.problems.append('not_configured')
        return res

    if should_stop is not None and should_stop():
        res.problems.append("interrupted: mapping was stopped before the calibration job")
        return res
    path = remote_path(serial)
    try:
        with ftps.Client(printer) as c:
            c.upload(path, build(labels))
    except tlspin.CertChanged:
        res.cert_changed = True
        res.problems.append('cert_changed')
        return res
    except ftps.FtpsError as e:
        # a STOR that died midway (or whose final reply was lost) may have left a partial or complete file
        res.problems.append(f"cannot upload the calibration job: {e}")
        _delete(printer, path, res)
        return res

    try:
        snapshot.save(serial, "calibration", [{"label": label, "ams_id": _key(slot)[0], "tray_id": _key(slot)[1],
                                               "setting": _setting(trays0[_key(slot)])}
                                              for label, slot in slotmap.slots.items()
                                              if _key(slot) is not None and _loaded(trays0.get(_key(slot)))])
    except Exception as e:      # no snapshot on disk: do not start the job
        log.exception("printer %s: cannot save the slot snapshot", serial)
        res.problems.append(f"cannot save the slot snapshot ({type(e).__name__}: {e}); the job was not started")
        _delete(printer, path, res)
        return res
    try:
        _job(manager, serial, res, labels, sent, snap, should_stop)
    except Exception as e:      # e.g. the MQTT connection was lost while watching the job
        log.warning("printer %s: calibration job interrupted (%s)", serial, type(e).__name__)
        res.consistent = False
        res.problems.append(f"the calibration job was interrupted: connection lost ({type(e).__name__})")
    finally:
        _delete(printer, path, res)
        try:
            _restore(manager, serial, slotmap, trays0, res)
        except Exception as e:
            res.restored = False
            res.problems.append(f"could not restore the slots ({type(e).__name__})")
        if res.restored:            # every slot confirmed back: the snapshot on disk is done with
            try:
                snapshot.clear(serial)
            except OSError:
                log.exception("printer %s: cannot delete the slot snapshot", serial)
        _left_loaded(manager, serial, snap, res)
    log.info("printer %s: calibration %s; decoding %s; problems %s", serial,
             "consistent" if res.consistent else "not consistent", res.decoding, res.problems)
    return res


POLL = 0.5                 # seconds between stop checks while a stoppable wait runs
ONLINE = ('connected', 'needs_developer_mode')
LEFT_LOADED = "printer left a filament loaded in the toolhead"
HEATING = "the printer began heating during the calibration job; it was stopped"
LOADING = "the printer began loading a filament during the calibration job; it was stopped"


def heater_targets(report: dict) -> dict[str, tuple[str, int]]:
    """Every nozzle / bed TARGET temperature in a report: name -> (kind, value). kind "plain" (a target field:
    only a rise counts) or "packed" (an H2D `device.*.info[].temp` packed (target << 16) | current: any change of
    the decoded target counts, the current part is ignored)."""
    p = _d(report)
    out: dict[str, tuple[str, int]] = {}
    for k in ('nozzle_target_temper', 'bed_target_temper'):
        v = _int(p.get(k))
        if v is not None:
            out[k] = ('plain', v)
    dev = _d(p.get('device'))
    for ex in _l(_d(dev.get('extruder')).get('info')):
        cur, tgt = packed(ex.get('temp'))
        if tgt is not None:
            out[f"extruder{_int(ex.get('id'), 0)}"] = ('packed', tgt)
    _, bt = packed(_d(_d(dev.get('bed')).get('info')).get('temp'))
    if bt is not None:
        out['bed'] = ('packed', bt)
    return out


def heating(before: dict, report: dict) -> str | None:
    """The name of a heater whose target rose (plain) or changed (packed) since `before`; None if none did."""
    for name, (kind, v) in heater_targets(report).items():
        old = before.get(name, (kind, 0))[1]
        if (kind == 'plain' and v > old) or (kind == 'packed' and v != old):
            return name
    return None


def _tray_now(report: dict) -> str | None:
    tn = _d(_d(report).get('ams')).get('tray_now')
    return None if tn is None else str(tn)


def _wait(manager, serial: str, pred, timeout: float, should_stop) -> dict | None:
    """`manager.wait_report`, in short slices when the job can be stopped (`pred` checks `should_stop` itself)."""
    if should_stop is None:
        return manager.wait_report(serial, pred, timeout)
    deadline = time.monotonic() + timeout
    while True:
        left = deadline - time.monotonic()
        r = manager.wait_report(serial, pred, max(min(left, POLL), 0.01))
        if r is not None or left <= POLL or manager.state(serial) not in ONLINE:
            return r


def _stop(manager, serial: str) -> bool:
    """Best-effort `stop`; true once a report shows the printer no longer busy."""
    try:
        manager.publish(serial, {"print": {"command": "stop", "param": ""}})
        return manager.wait_report(serial, lambda r: _s(r.get('gcode_state')).upper() not in BUSY,
                                   STOP_TIMEOUT) is not None
    except Exception:
        return False


def _job(manager, serial: str, res: CalibResult, labels: list[str], sent: list[int], snap: dict,
         should_stop=None) -> None:
    name = job_name(serial)
    stopping = should_stop or (lambda: False)
    if stopping():
        res.problems.append("interrupted: mapping was stopped before the calibration job")
        return
    try:
        reply = manager.publish(serial, payload(serial, sent))
    except Exception as e:      # offline / no reply raised by the Manager
        res.problems.append(f"cannot send the calibration job ({type(e).__name__})")
        return
    if reply is not None and not _ok(reply):
        log.warning("printer %s: calibration job refused (%s)", serial, _s(reply.get('reason')) or reply.get('result'))
        res.problems.append(REFUSED)
        return

    before = (_s(snap.get('gcode_state')).upper(), _s(snap.get('subtask_name')), _s(snap.get('task_id')))
    heaters0, tray0 = heater_targets(snap), _tray_now(snap)
    st = {'started': False, 'final': None, 'trip': None}

    def watch(r: dict) -> bool:
        # the watchdog first, whether or not the job is seen as started: no heating, no filament load, ever
        if stopping():
            st['trip'] = "interrupted: mapping was stopped; the calibration job was stopped"
            return True
        h = heating(heaters0, r)
        if h is not None:
            st['trip'] = f"{HEATING} ({h})"
            return True
        tn = _tray_now(r)
        if tn is not None and tn != tray0:
            st['trip'] = f"{LOADING} (tray_now {tray0} -> {tn})"
            return True
        gs, sub = _s(r.get('gcode_state')).upper(), _s(r.get('subtask_name'))
        if not st['started']:
            if sub != name:
                return False
            if gs in BUSY or (gs in ENDED and (gs, sub, _s(r.get('task_id'))) != before):
                st['started'] = True
            else:
                return False
        m = r.get('mapping')
        if isinstance(m, list):
            res.mapping = list(m)
        if tn is not None and (not res.tray_now or res.tray_now[-1] != tn):
            res.tray_now.append(tn)
        if gs in ENDED or gs == 'IDLE':
            st['final'] = gs
            return True
        return False

    _wait(manager, serial, watch, JOB_TIMEOUT, should_stop)
    if st['trip'] is not None:
        log.warning("printer %s: calibration job tripped: %s", serial, st['trip'])
        stopped = _stop(manager, serial)
        res.problems.append(st['trip'] + ("" if stopped else " (the stop was not confirmed)"))
        res.consistent = False
        return
    if not st['started']:
        _stop(manager, serial)       # best effort: it may still start after we gave up on it
        res.problems.append(f"the printer did not start the calibration job within {JOB_TIMEOUT:.0f} s")
        return
    if st['final'] is None:
        stopped = _stop(manager, serial)
        res.problems.append(f"the calibration job did not finish within {JOB_TIMEOUT:.0f} s; "
                            + ("it was stopped" if stopped else "it could not be stopped"))
        return
    if st['final'] != 'FINISH':
        res.problems.append(f"the calibration job ended as {st['final']} on the printer")

    if res.mapping is None:
        res.problems.append("the printer did not report the job's slot mapping")
        return
    mismatch = False
    for i, label in enumerate(labels):
        v = _int(res.mapping[i]) if i < len(res.mapping) else None
        if v is None:
            res.problems.append(f"{label}: the printer reported no slot")
            mismatch = True
            continue
        res.decoding[label] = v
        if v != sent[i]:
            res.problems.append(f"{label}: sent slot {sent[i]}, the printer reported {v}")
            mismatch = True
    res.consistent = st['final'] == 'FINISH' and not mismatch


def _left_loaded(manager, serial: str, snap: dict, res: CalibResult) -> None:
    """After the job: a filament in the toolhead that was not there before -> not restored."""
    try:
        r = manager.wait_report(serial, lambda r: True, SNAPSHOT_TIMEOUT)
    except Exception:
        r = None
    if r is None:
        return
    if _tray_now(r) is not None and _tray_now(r) != _tray_now(snap):
        res.problems.append(LEFT_LOADED)
        res.restored = False
        res.consistent = False


def _delete(printer: registry.Printer, path: str, res: CalibResult) -> None:
    try:
        with ftps.Client(printer) as c:
            c.delete(path)
    except tlspin.CertChanged:
        res.cert_changed = True
        res.problems.append(f"could not delete {path}: cert_changed")
    except ftps.FtpsError as e:
        res.problems.append(f"could not delete {path}: {e}")
    except Exception as e:      # never let a delete failure skip the slot restore
        res.problems.append(f"could not delete {path}: {type(e).__name__}")


def _restore(manager, serial: str, slotmap: SlotMap, trays0: dict, res: CalibResult) -> None:
    """Put back every loaded slot whose settings differ from the snapshot; verify from the next report."""
    try:
        now = _trays(manager.wait_report(serial, lambda r: True, SNAPSHOT_TIMEOUT) or {})
    except Exception:
        now = {}
    pending: list[tuple[str, tuple[int, int], dict]] = []
    for label, slot in slotmap.slots.items():
        key = _key(slot)
        t0 = trays0.get(key) if key else None
        if not _loaded(t0) or (key in now and _same(t0, now[key])):
            continue
        try:
            reply = manager.set_slot(serial, key[0], key[1], _setting(t0))
        except Exception as e:
            res.restored = False
            res.problems.append(f"{label}: could not restore the slot ({type(e).__name__})")
            continue
        if reply is not None and not _ok(reply):
            res.restored = False
            res.problems.append(f"{label}: the printer refused to restore the slot")
            continue
        pending.append((label, key, t0))
    if not pending:
        return
    last: dict = {}

    def restored(r: dict) -> bool:
        last['trays'] = _trays(r)
        return all(_same(t0, last['trays'].get(key)) for _, key, t0 in pending)

    try:
        ok = manager.wait_report(serial, restored, RESTORE_TIMEOUT) is not None
    except Exception:
        ok = False
    if not ok:
        seen = last.get('trays', {})
        for label, key, t0 in pending:
            if not _same(t0, seen.get(key)):
                res.restored = False
                res.problems.append(f"{label}: restore not confirmed by the printer")
