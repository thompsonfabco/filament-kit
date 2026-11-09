"""Calibration job: learn how a printer numbers its AMS slots, with a gcode-only job that never heats or moves.

`build(labels, project)` makes a Bambu project 3MF with one PLA filament per slot label and a plate gcode that is
only comments and `M400`. With a `Project` (`project_for`: the model's `<slicer-project>` in the hardware file, the
nozzles and AMS-to-extruder links the report gives) it carries the printer fields Bambu Studio writes
(printer_model_id, printer and nozzle settings, filament_maps, the X-BBL-Client-Version header). Only a model marked
job-file="project" gets that file: the X2D and P2S, which refuse the minimal 3MF ("invalid 3mf"); whether they accept
this one is not known until a mapping has run on each. Every other model keeps the minimal 3MF, the file the H2D is
known to accept; none of them has run the project file, so the attribute is set only after a model has.
`run(manager, serial, slotmap)` uploads it over FTPS to `/cache/fk-calib-<serial>.gcode.3mf`,
starts it with `ams_mapping` = filament i -> the slot's legacy number (unit*4+tray, an HT unit its id: the command
Bambu Studio sends and the scanner verified on the owner's H2D) plus
`ams_mapping2` (`[{ams_id, slot_id}]`) when the model lists it, waits (at most `JOB_TIMEOUT` s) for the job to
start and end, records the `mapping` and `ams.tray_now` the printer reports, and decodes the reported mapping
against every candidate scheme: the first (model order) that round-trips every loaded slot is `CalibResult.scheme`
(another job, in the next candidate's numbers, only after a clean end that fits none or a refusal; see `run`). The
evidence is those numbers, not how a comments-only print ends: the job counts when it started and this job reported one
distinct number per filament, whether it ended FINISH or FAILED (the H2D ends a gcode-only job FAILED with no error). The
report is merged, so `mapping` from an earlier print would stay in it: it is dropped when the job is sent, though the full
report asked for after a command may bring it back. Numbers that fit a scheme are right wherever they came from. A FAILED with
a real `print_error` whose numbers are those sent, or those of the print before, can't prove the printer read the file:
the map is kept but `scheme_unsettled`. Numbers that fit no scheme are still the printer's numbers for those slots, a table with
`scheme` None, unless they are the last print's: those say nothing about these slots, so the map stays in observe. Afterwards (always) the file is deleted and every
slot whose settings changed since the start is set back from the snapshot taken at the start and the restore is
verified from the next report (`CalibResult.restored` false when any slot was not confirmed back). It does not save
a SlotMap (the mapping job does).

Watchdog (the gcode never heats or loads, so either means the printer is doing something we did not ask for):
while the job is watched, a nozzle or bed TARGET temperature above the snapshot's (`nozzle_target_temper`,
`bed_target_temper`, and the decoded target of the H2D's packed `device.extruder.info[].temp` /
`device.bed.info.temp`; a drop never counts) or an `ams.tray_now` other than the snapshot's ends the watch and
sends `stop`. After the job, a `tray_now` other than the snapshot's is the problem "printer left a filament
loaded in the toolhead" and `restored` is false.

Never act on a print that is not ours: each run sends its own `subtask_name`, `run_name(serial)` =
`fk-calib-<serial>-<nonce>` (the file keeps the fixed `job_name(serial)`), and `stop` (watchdog, timeout, never
started, should_stop, Ctrl-C) is sent only while the latest report's `subtask_name` is this run's name. A report
still naming an earlier run (or anything else) is never ours. Another print that starts while we watch (someone at
the touchscreen or in Bambu Studio) ends the watch with "the printer started another job; calibration abandoned":
it is not stopped, our file is still deleted, and its filament load is not held against us.

Never overwrite a slot setting someone else changed: the calibration writes no slot, so its slot step after the
job (`_check_slots`) only compares every loaded slot with the snapshot and reports a slot that changed meanwhile
("left as is"); it never writes one, as `snapshot.restore` for a calibration snapshot. `restored` true means we
left nothing changed (false only for a filament left loaded in the toolhead).

The print command, modelled on what Bambu Studio sends in LAN mode (to be confirmed on the owner's H2D, Task 9):

    {"print": {
        "command": "project_file",
        "param": "Metadata/plate_1.gcode",
        "url": "ftp:///cache/fk-calib-<serial>.gcode.3mf",
        "file": "",
        "md5": "",
        "subtask_name": "fk-calib-<serial>-<nonce>",
        "project_id": "0", "profile_id": "0", "task_id": "0", "subtask_id": "0",
        "bed_type": "auto",
        "use_ams": true,
        "ams_mapping": [<global id of slot 1>, <global id of slot 2>, ...],
        "bed_levelling": false, "flow_cali": false, "vibration_cali": false,
        "layer_inspect": false, "timelapse": false
    }}

`sequence_id` is left to `Manager.publish`. `ams_mapping2` is added for models that list it (see above). Not sent:
`md5` of the file.

Only loaded AMS slots take part (an empty slot is listed in `skipped`). External holders never do (`external`): they
are always numbered as their own id, and they have no sensor (an empty holder still reports a filament type and the
printer maps no slot for it). When the loaded slots number alike under several schemes (one AMS unit: shift8 and
legacy agree), the model's first is taken and `notes` says so. Refusals before anything is sent are reported
as codes in `problems`: `printer_offline`, `printer_busy`, `not_configured`, `cert_changed` (FTPS leaf not the pinned
one: nothing uploaded, no Access Code sent). Everything else is a sentence."""
from __future__ import annotations

import colorsys
import copy
import hashlib
import io
import json
import logging
import secrets
import time
import zipfile
from dataclasses import dataclass, field
from xml.sax.saxutils import quoteattr

from . import ftps, hardware, layout, registry, snapshot, tlspin
from .ams import SlotMap
from .status import _d, _int, _l, _s, packed

log = logging.getLogger(__name__)

JOB_TIMEOUT = 120.0        # seconds from the print command to the end of the job
SNAPSHOT_TIMEOUT = 10.0
STOP_TIMEOUT = 20.0
BUSY = ('RUNNING', 'PAUSE', 'PREPARE', 'SLICING')
ENDED = ('FINISH', 'FAILED')
REFUSED = "printer refused the calibration job"
NO_AMS_LOADED = ("no loaded AMS slot to calibrate (external holders need none): load a spool into an AMS slot and "
                 "map again")
GCODE = "Metadata/plate_1.gcode"
_ZIP_TIME = (2026, 1, 1, 0, 0, 0)


def job_name(serial: str) -> str:
    return f"fk-calib-{serial}"


def run_name(serial: str) -> str:
    """This run's `subtask_name`: unique per run, so a report naming an earlier run is never taken for ours. It
    keeps the `fk-calib-` prefix that usage skips (`usage.CALIB_PREFIX`)."""
    return f"{job_name(serial)}-{secrets.token_hex(3)}"


def remote_path(serial: str) -> str:
    return f"/cache/{job_name(serial)}.gcode.3mf"


@dataclass
class CalibResult:
    decoding: dict[str, int] = field(default_factory=dict)   # label -> the global id the printer reported
    consistent: bool = False                                  # job finished and its mapping proved a scheme
    problems: list[str] = field(default_factory=list)
    sent: dict[str, int] = field(default_factory=dict)        # label -> the candidate global id sent
    mapping: list | None = None                               # the raw `mapping` the printer reported
    tray_now: list[str] = field(default_factory=list)         # each `ams.tray_now` seen during the job
    skipped: list[str] = field(default_factory=list)          # empty slots, not part of the job
    external: list[str] = field(default_factory=list)         # external holders: never part of the job (own id)
    notes: list[str] = field(default_factory=list)            # not problems: what the result does not settle yet
    scheme_unsettled: bool = False                            # several schemes fit; the model's first was taken
    report_wanted: str | None = None                          # printer_report.WANTED: why a report would help
    trail: list[dict] = field(default_factory=list)           # what each job sent and got: numbers and codes only
    job_file: str | None = None                               # minimal | project
    final: str | None = None                                  # how the printer ended the job
    print_error: str | None = None                            # hex, when there was one
    fits: list[str] = field(default_factory=list)             # the schemes the reported numbers fit
    repeats_last_print: bool = False                          # the numbers equal those of the print before this mapping
    cert_changed: bool = False
    restored: bool = True     # we left nothing changed (false: a filament left loaded in the toolhead)
    job: str = ""             # this run's subtask_name (`run_name`)
    other_job: bool = False   # another print started while we watched: abandoned, never stopped
    scheme: str | None = None                                 # the numbering scheme the reported mapping proved
    sent_scheme: str | None = None                            # the scheme whose numbers this job sent
    tried: list[str] = field(default_factory=list)            # schemes sent, one job each, in order
    attempts: list[str] = field(default_factory=list)         # what each earlier job (that proved none) saw
    failed_as_finish: bool = False                            # ended FAILED, counted as finished (model rule)
    retry: bool = False       # the job ended but proved no scheme (or was refused): try the next candidate
    skip: bool = False        # nothing sent: this candidate numbers the loaded slots as an earlier one did


# ---------------------------------------------------------------- the 3MF

def _colors(n: int) -> list[str]:
    out = []
    for i in range(n):
        r, g, b = colorsys.hsv_to_rgb((i * 0.618033988749895) % 1.0, 0.85, 0.95 - 0.25 * ((i // 7) % 2))
        out.append("#%02X%02X%02X" % (round(r * 255), round(g * 255), round(b * 255)))
    return out


def gcode(labels: list[str], project: "Project | None" = None) -> str:
    """Comments and M400 only: no heating, homing, moves or tool changes. With a `project`, the header and config
    blocks also name the printer model and nozzles, as Bambu Studio's do (still comments only)."""
    lines = ["; HEADER_BLOCK_START"]
    if project is not None:
        lines.append(f"; BambuStudio {project.slicer.client_version}")
    lines += ["; filament-kit slot calibration: no heating, no homing, no motion",
              "; total layer number: 0",
              "; total filament length [mm] : 0.00",
              "; total filament weight [g] : 0.00",
              f"; total filament count: {len(labels)}",
              "; HEADER_BLOCK_END"]
    if project is not None:
        sp = project.slicer
        lines += ["", "; CONFIG_BLOCK_START",
                  f"; printer_model = {sp.printer_model}",
                  f"; printer_settings_id = {project.printer_settings_id}",
                  f"; nozzle_diameter = {','.join(project.nozzles)}",
                  f"; filament_map = {','.join(str(x) for x in project.maps)}",
                  "; CONFIG_BLOCK_END", ""]
    lines += [f"; filament {i}: slot {label}" for i, label in enumerate(labels, 1)]
    lines += ["M400", "; end of calibration job", ""]
    return "\n".join(lines)


EXTRUDER_TYPE = {"Direct Drive": 0, "Bowden": 1}               # slice_info's extruder_type codes
VOLUME_TYPE = {"Standard": 0, "High Flow": 1, "Hybrid": 2}     # slice_info's nozzle_volume_type codes


@dataclass
class Project:
    """The printer fields a calibration 3MF carries (`build`): the model's `hardware.SlicerProject`, the nozzle
    diameter of each of its extruders (Bambu Studio's order, as text: "0.4") and each filament's extruder (1-based,
    Bambu Studio's `filament_maps`)."""
    slicer: hardware.SlicerProject
    nozzles: list[str]
    maps: list[int]

    @property
    def printer_settings_id(self) -> str:
        return f"{self.slicer.printer_model} {self.nozzles[self.slicer.master_extruder - 1]} nozzle"

    @property
    def filament_preset(self) -> str:
        return self.slicer.filament_preset.replace("{nozzle}", self.nozzles[self.slicer.master_extruder - 1])


def _report_extruder(report: dict, ams_id: int) -> int | None:
    """The printer's own extruder id an AMS unit feeds: bits 8-11 of the unit's hex `info` (H2D/X2D; as
    loading._extruder). None when the report does not say."""
    for u in _l(_d(_d(report).get('ams')).get('ams')):
        if _int(u.get('id')) == ams_id:
            info = u.get('info')
            if isinstance(info, str) and info.strip():
                try:
                    return (int(info, 16) >> 8) & 0xF
                except ValueError:
                    return None
            return None
    return None


def _mm(v) -> float | None:
    try:
        n = float(v)
    except (TypeError, ValueError, OverflowError):
        return None
    return n if 0.1 <= n <= 2.0 else None


def project_for(mi: hardware.ModelInfo, report: dict, addrs: list[tuple[int, int]]) -> Project | None:
    """The 3MF's printer fields for the loaded slots `addrs`, from the model's slicer project and the report: each
    extruder's nozzle from `device.nozzle.info[]` (by the printer's own extruder id), else the top-level
    `nozzle_diameter`, else the model's default; each filament on the extruder its AMS unit feeds (`info` bits),
    else on the model's master extruder. None (the minimal 3MF) unless the model is marked job-file="project"."""
    sp = mi.slicer
    if sp is None or mi.job_file != "project":
        return None
    p = _d(report)
    top = _mm(p.get('nozzle_diameter'))
    by_id = {}
    for e in _l(_d(_d(p.get('device')).get('nozzle')).get('info')):
        i, n = _int(e.get('id')), _mm(e.get('diameter'))
        if i is not None and n is not None:
            by_id[i] = n
    nozzles = [sp.nozzle_text(by_id.get(x.physical) or top) for x in sp.extruders]
    logical = {x.physical: i for i, x in enumerate(sp.extruders, 1)}
    maps = []
    for a, _t in addrs:
        e = None if _external(a, mi) else _report_extruder(report, a)
        maps.append(logical.get(e, sp.master_extruder) if e is not None else sp.master_extruder)
    return Project(sp, nozzles, maps)


def _zip(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            info = zipfile.ZipInfo(name, _ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0      # the same bytes on Windows and Linux
            z.writestr(info, data)
    return buf.getvalue()


def build(slots: list[str], project: Project | None = None) -> bytes:
    """A Bambu project 3MF with one PLA filament per slot label (filament ids 1..N in label order): with a
    `project` (`project_for`), the printer fields Bambu Studio writes (`_build_project`); without, the minimal
    3MF (every model not marked job-file="project")."""
    labels = list(slots)
    if not labels:
        raise ValueError("no slots to calibrate")
    if project is not None:
        return _build_project(labels, project)
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
    return _zip(files)


def _build_project(labels: list[str], pr: Project) -> bytes:
    """The calibration 3MF with the printer fields of an unsliced Bambu Studio project of the model (the X2D and
    P2S refuse a job file without them, "invalid 3mf"): `slice_info.config`'s client header (X-BBL-Client-Version)
    and the plate's printer_model_id, extruder and nozzle fields; `project_settings.config`'s printer_model,
    printer_settings_id, nozzle_diameter, extruder_type, physical_extruder_map, master_extruder_id, printable_area
    and filament_map; the plate's gcode relationship. The gcode is still comments and M400 only."""
    sp, n = pr.slicer, len(labels)
    colors = _colors(n)
    code = gcode(labels, pr).encode()
    master = pr.nozzles[sp.master_extruder - 1]
    preset = pr.filament_preset
    fils = "\n".join(
        f'    <filament id="{i}" tray_info_idx="GFA00" type="PLA" color="{c}" used_m="0" used_g="0" '
        f'group_id="{m - 1}" nozzle_diameter="{float(pr.nozzles[m - 1]):.2f}" '
        f'volume_type="{sp.extruders[m - 1].volume}" used_for_object="true" used_for_support="false"/>'
        for i, (c, m) in enumerate(zip(colors, pr.maps), 1))
    nozz = "\n".join(f'    <nozzle id="{m - 1}" extruder_id="{m}" nozzle_diameter="{pr.nozzles[m - 1]}" '
                     f'volume_type="{sp.extruders[m - 1].volume}"/>' for m in sorted(set(pr.maps)))
    maps = " ".join(str(m) for m in pr.maps)
    ext_types = " ".join(str(EXTRUDER_TYPE.get(x.type, 0)) for x in sp.extruders)
    vol_types = " ".join(str(VOLUME_TYPE.get(x.volume, 0)) for x in sp.extruders)
    area = ["0x0", f"{sp.printable_width}x0", f"{sp.printable_width}x{sp.printable_depth}",
            f"0x{sp.printable_depth}"]
    settings = {
        "name": "project_settings", "from": "project", "version": sp.client_version,
        "printer_model": sp.printer_model, "printer_settings_id": pr.printer_settings_id,
        "printer_variant": master, "nozzle_diameter": list(pr.nozzles),
        "extruder_type": [x.type for x in sp.extruders],
        "physical_extruder_map": [str(x.physical) for x in sp.extruders],
        "master_extruder_id": str(sp.master_extruder),
        "nozzle_volume_type": [x.volume for x in sp.extruders],
        "printable_area": area, "printable_height": str(sp.printable_height),
        "filament_type": ["PLA"] * n, "filament_colour": colors, "filament_settings_id": [preset] * n,
        "filament_map": [str(m) for m in pr.maps], "filament_map_mode": "Manual",
        "curr_bed_type": "Textured PEI Plate"}
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
        "Metadata/_rels/model_settings.config.rels":
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
            f' <Relationship Target="/{GCODE}" Id="rel-1" Type="http://schemas.bambulab.com/package/2021/gcode"/>\n'
            '</Relationships>\n',
        "Metadata/slice_info.config":
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<config>\n'
            '  <header>\n'
            '    <header_item key="X-BBL-Client-Type" value="slicer"/>\n'
            f'    <header_item key="X-BBL-Client-Version" value="{sp.client_version}"/>\n'
            '  </header>\n'
            '  <plate>\n'
            '    <metadata key="index" value="1"/>\n'
            f'    <metadata key="extruder_type" value="{ext_types}"/>\n'
            f'    <metadata key="nozzle_volume_type" value="{vol_types}"/>\n'
            f'    <metadata key="printer_model_id" value={quoteattr(sp.model_id)}/>\n'
            f'    <metadata key="nozzle_diameters" value="{",".join(pr.nozzles)}"/>\n'
            '    <metadata key="timelapse_type" value="0"/>\n'
            '    <metadata key="prediction" value="1"/>\n'
            '    <metadata key="weight" value="0.00"/>\n'
            '    <metadata key="pause_count" value="0"/>\n'
            '    <metadata key="outside" value="false"/>\n'
            '    <metadata key="support_used" value="false"/>\n'
            '    <metadata key="label_object_enabled" value="false"/>\n'
            f'    <metadata key="filament_maps" value="{maps}"/>\n'
            '    <metadata key="limit_filament_maps" value="0"/>\n'
            f'{fils}\n'
            f'{nozz}\n'
            '  </plate>\n'
            '</config>\n',
        "Metadata/model_settings.config":
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<config>\n'
            '  <plate>\n'
            '    <metadata key="plater_id" value="1"/>\n'
            f'    <metadata key="plater_name" value={quoteattr("slot calibration")}/>\n'
            '    <metadata key="locked" value="false"/>\n'
            '    <metadata key="filament_map_mode" value="Manual"/>\n'
            f'    <metadata key="filament_maps" value="{maps}"/>\n'
            f'    <metadata key="gcode_file" value="{GCODE}"/>\n'
            '    <metadata key="pattern_bbox_file" value="Metadata/plate_1.json"/>\n'
            '  </plate>\n'
            '</config>\n',
        "Metadata/plate_1.json":
            json.dumps({"bbox_all": [], "bbox_objects": [], "bed_type": "textured_plate",
                        "filament_colors": colors, "filament_ids": list(range(n)),
                        "first_extruder": pr.maps[0] - 1, "is_seq_print": False,
                        "nozzle_diameter": float(master), "version": 2}),
        "Metadata/project_settings.config": json.dumps(settings, indent=4) + "\n",
    }
    return _zip(files)


def payload(serial: str, ams_mapping: list[int], name: str | None = None,
            ams_mapping2: list[dict] | None = None) -> dict:
    """The `project_file` print command (see the module docstring); `name` = this run's `run_name`;
    `ams_mapping2` (`[{ams_id, slot_id}]` per filament) only when given (models with `ams_mapping2`)."""
    body = {
        "command": "project_file",
        "param": GCODE,
        "url": f"ftp://{remote_path(serial)}",
        "file": "",
        "md5": "",
        "subtask_name": name or job_name(serial),
        "project_id": "0", "profile_id": "0", "task_id": "0", "subtask_id": "0",
        "bed_type": "auto",
        "use_ams": True,
        "ams_mapping": list(ams_mapping),
        "bed_levelling": False, "flow_cali": False, "vibration_cali": False,
        "layer_inspect": False, "timelapse": False,
    }
    if ams_mapping2 is not None:
        body["ams_mapping2"] = [dict(x) for x in ams_mapping2]
    return {"print": body}


# ---------------------------------------------------------------- report helpers

def _trays(report: dict) -> dict[tuple[int, int], dict]:
    """(ams_id, tray_id) -> raw tray dict; each external holder as (its id, 0) (`layout.raw_trays`)."""
    return layout.raw_trays(report)


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

def _external(ams_id: int, mi: hardware.ModelInfo) -> bool:
    return ams_id in layout.EXT_DEFAULT or any(x.id == ams_id for x in mi.externals)


def number(hw: hardware.Hardware, mi: hardware.ModelInfo, scheme: str, ams_id: int, tray_id: int) -> int:
    """The number to send for a slot under `scheme`; an external holder is sent as its own id (Bambu's virtual
    tray id). ValueError / KeyError when the scheme cannot number the slot."""
    if _external(ams_id, mi):
        return int(ams_id)
    return hw.scheme(scheme).encode(ams_id, tray_id)


def fits(hw: hardware.Hardware, mi: hardware.ModelInfo, scheme: str, value, ams_id: int, tray_id: int) -> bool:
    """`value` (a reported number) round-trips to this slot under `scheme`. An external holder also fits as its
    own id."""
    v = _int(value)
    if v is None or v < 0:
        return False
    if _external(ams_id, mi) and v == ams_id:
        return True
    try:
        return hw.scheme(scheme).decode(v) == (ams_id, tray_id)
    except KeyError:
        return False


def run(manager, serial: str, slotmap: SlotMap, printer: registry.Printer | None = None,
        should_stop=None) -> CalibResult:
    """Run the calibration job on an idle, connected printer (see the module docstring). Never raises for
    printer-side trouble: everything lands in `CalibResult.problems`. Once the upload was attempted, the file is
    always deleted (best effort, over a new session; skipped only for a changed leaf) and, once the job was sent,
    the slots are always restored, whatever went wrong in between. The snapshot of the loaded slots is saved to
    disk (`snapshot.save`) before the print command and deleted after a confirmed restore. `should_stop()` true
    (CLI signal, service stopping) stops the job at once (`stop` command), then the slots are restored.

    Numbering (P3, ruling BL): the first job sends `ams_mapping` in legacy numbers, Bambu Studio's command (plus
    `ams_mapping2` when the model lists it); the mapping the printer reports (in its own numbering: the owner's H2D
    answers [0, 2, 128, 129] with [0, 2, 32768, 33024]) is decoded against EVERY candidate scheme of the model
    (`ModelInfo.numbering`) and the first in the model's order that round-trips all loaded slots is the result
    (`scheme`). Only when the job finished (FINISH, or FAILED-as-finish) and no candidate fits, or the printer
    refused the job, is another job sent, in the next candidate's numbers (a scheme that numbers the loaded slots
    as an earlier job did is skipped; so is one that cannot number them, e.g. legacy for AMS ids >= 32). A real
    failure, a trip, a timeout or a stop never gets a second job. The result is the last job's; `attempts` says
    what the earlier ones saw."""
    if printer is None:
        printer = registry.load().get(serial)
    hw = hardware.load()
    mi = hw.model(printer.model if printer is not None and printer.model else None)
    listed = [k for k in mi.numbering if k in hw.schemes]
    others = [k for k in hw.schemes if k not in listed]
    # every scheme is a candidate, the model's own first; a model the file does not know has none of its own, and every
    # model the file lists two for has shift8 first
    candidates = (listed + others) if mi.known else sorted(hw.schemes, key=lambda k: k != 'shift8')
    candidates = candidates or ['legacy']
    sends = ['legacy'] + [k for k in candidates if k != 'legacy']     # what each job's ams_mapping is numbered in
    tried: list[list[int]] = []
    sent_keys: list[str] = []
    attempts: list[str] = []
    res: CalibResult | None = None
    table: CalibResult | None = None    # a job whose numbers fit no scheme: still the printer's numbers
    last_print: dict = {}               # the `mapping` of the print before this mapping began (the first job's snapshot)
    trail: list[dict] = []
    for key in sends:
        r = _attempt(manager, serial, slotmap, printer, should_stop, hw, mi, candidates, key, tried, last_print)
        if r.skip:
            continue
        if res is not None:             # the previous job proved no scheme: keep what it saw
            attempts.append(f"numbering {res.sent_scheme}: " + ("; ".join(res.problems) or "no scheme fits"))
        res = r
        sent_keys.append(key)
        trail.append(_trail_entry(r))
        if r.consistent and r.scheme is None:
            if table is not None and table.decoding != r.decoding:
                # the numbers follow what was sent, so they say nothing about the slots
                r.consistent, r.scheme_unsettled, r.notes, table = False, False, [], None
                r.report_wanted = "no_scheme"
                r.problems += [f"{label}: sent slot {r.sent.get(label)}, the printer reported {n}"
                               for label, n in r.decoding.items() if n != r.sent.get(label)]
                r.problems.append(f"the reported slot numbers {list(r.mapping or [])} fit no numbering scheme of this "
                                  f"printer model ({', '.join(candidates)}) and changed with the numbers sent")
            else:
                table = r
        stop = should_stop is not None and should_stop()
        if not res.retry or not res.restored or res.other_job or res.cert_changed or stop:
            break
    if res is not None and table is not None and not res.consistent and res.restored:
        res = table                     # a later job, in other numbers, proved less than this one
    if res is None:                     # no candidate can number the loaded slots
        res = CalibResult(problems=["no numbering scheme of this printer model can number the loaded slots"])
    res.tried, res.attempts, res.trail = sent_keys, attempts, trail
    if attempts:
        log.info("printer %s: calibration sent %d jobs (%s)", serial, len(sent_keys), "; ".join(attempts))
    return res


def _trail_entry(r: CalibResult) -> dict:
    return {"scheme": r.sent_scheme, "job_file": r.job_file, "final": r.final, "print_error": r.print_error,
            "sent": list(r.sent.values()), "reported": list(r.mapping or []), "fits": list(r.fits),
            "repeats_last_print": r.repeats_last_print}


def _attempt(manager, serial: str, slotmap: SlotMap, printer, should_stop, hw: hardware.Hardware,
             mi: hardware.ModelInfo, candidates: list[str], key: str, tried: list[list[int]],
             last_print: dict) -> CalibResult:
    """One calibration job sending `key`'s numbers (see `run`)."""
    res = CalibResult(sent_scheme=key)
    if manager.state(serial) != 'connected':
        res.problems.append('printer_offline')
        return res
    snap = manager.wait_report(serial, lambda r: True, SNAPSHOT_TIMEOUT)
    if snap is None:
        res.problems.append('printer_offline')
        return res
    snap = copy.deepcopy(snap)
    if "mapping" not in last_print:     # a job of ours before this one says nothing against its own numbers
        ours = _s(snap.get('subtask_name')).startswith(job_name(serial))
        last_print["mapping"] = None if ours else snap.get('mapping')
    if _s(snap.get('gcode_state')).upper() in BUSY:
        res.problems.append('printer_busy')
        return res

    # a slot the sensor says is empty stays out even if it still names a filament, as in the slot test
    lay = layout.build(snap, printer.model if printer is not None else None, hw)
    ams_units = [u for u in lay.units if u.kind != layout.EXT_KIND]
    absent = {(u.ams_id, s.tray_id) for u in ams_units for s in u.slots if s.present is False}
    trays0 = {k: t for k, t in _trays(snap).items() if k not in absent}
    labels: list[str] = []
    addrs: list[tuple[int, int]] = []
    for label, slot in slotmap.slots.items():
        k = _key(slot)
        if k is not None and _external(k[0], mi):
            # an external holder is always numbered as its own id (no scheme to prove), and it has no sensor:
            # an empty one still reports a filament type, and the printer maps no slot for it
            res.external.append(label)
            continue
        if k is None or not _loaded(trays0.get(k)):
            res.skipped.append(label)
            continue
        labels.append(label)
        addrs.append(k)
    if not labels:
        if not ams_units and not res.skipped:
            # no AMS at all: only holders, which keep their own ids, so there is nothing to prove and no job to
            # send. Adding a unit changes the layout, and that makes the map again.
            res.consistent = True
        else:
            res.problems.append(NO_AMS_LOADED)
        return res
    try:
        sent = [number(hw, mi, key, a, t) for a, t in addrs]
    except (KeyError, ValueError):
        res.skip = True                 # this scheme cannot number a loaded slot: nothing to send
        return res
    if sent in tried:
        res.skip = True                 # the printer saw these numbers already
        return res
    tried.append(sent)
    res.sent = dict(zip(labels, sent))
    mapping2 = None
    if mi.ams_mapping2:
        mapping2 = [{"ams_id": a, "slot_id": 0 if _external(a, mi) else t} for a, t in addrs]

    if printer is None or not printer.configured or not printer.access_code:
        res.problems.append('not_configured')
        return res

    if should_stop is not None and should_stop():
        res.problems.append("interrupted: mapping was stopped before the calibration job")
        return res
    path = remote_path(serial)
    try:
        with ftps.Client(printer) as c:
            project = project_for(mi, snap, addrs)
            res.job_file = "minimal" if project is None else "project"
            c.upload(path, build(labels, project))
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
    res.job = run_name(serial)
    try:
        _job(manager, serial, res, labels, sent, snap, should_stop,
             numbering=(hw, mi, candidates, addrs, mapping2, last_print.get("mapping")))
    except Exception as e:      # e.g. the MQTT connection was lost while watching the job
        log.warning("printer %s: calibration job interrupted (%s)", serial, type(e).__name__)
        res.consistent = res.retry = False
        res.problems.append(f"the calibration job was interrupted: connection lost ({type(e).__name__})")
    except BaseException:       # Ctrl-C with no handler installed: stop our job (only ours), then restore
        log.warning("printer %s: calibration job interrupted; stopping it if it is ours", serial)
        res.consistent = False
        _stop_ours(manager, serial, res.job)
        raise
    finally:
        _delete(printer, path, res)
        _check_slots(manager, serial, slotmap, trays0, res)
        if res.restored:            # we changed nothing: the snapshot on disk is done with
            try:
                snapshot.clear(serial)
            except OSError:
                log.exception("printer %s: cannot delete the slot snapshot", serial)
        if not res.other_job:   # another print's filament load is not ours to report
            _left_loaded(manager, serial, snap, res)
    log.info("printer %s: calibration %s; decoding %s; problems %s", serial,
             "consistent" if res.consistent else "not consistent", res.decoding, res.problems)
    return res


POLL = 0.5                 # seconds between stop checks while a stoppable wait runs
ONLINE = ('connected', 'needs_developer_mode')
LEFT_LOADED = "printer left a filament loaded in the toolhead"
HEATING = "the printer began heating during the calibration job"
LOADING = "the printer began loading a filament during the calibration job"
OTHER_JOB = "the printer started another job; calibration abandoned"
LATEST_TIMEOUT = 1.0       # seconds to get the latest report before deciding on a `stop`


def heater_targets(report: dict) -> dict[str, tuple[str, int]]:
    """Every nozzle / bed TARGET temperature in a report: name -> (kind, value). kind "plain" (a target field) or
    "packed" (an H2D `device.*.info[].temp` packed (target << 16) | current: the decoded target, the current part
    is ignored)."""
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
    """The name of a heater whose target rose since `before`; None if none did. Only a rise counts, for packed
    targets too: a drop (the owner preheated, the firmware zeroes it when a job starts) is no heating."""
    for name, (kind, v) in heater_targets(report).items():
        if v > before.get(name, (kind, 0))[1]:
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


def _ours(report: dict | None, name: str) -> bool:
    return bool(name) and isinstance(report, dict) and _s(report.get('subtask_name')) == name


def _stop_ours(manager, serial: str, name: str) -> bool | None:
    """`stop` our own job: sent only while the latest report names this run (`name`, `_ours`). True once a report shows
    the printer no longer busy, False if that was not confirmed, None when nothing was sent (not our job, or no
    report)."""
    try:
        latest = manager.wait_report(serial, lambda r: True, LATEST_TIMEOUT)
    except Exception:
        return None
    if not _ours(latest, name):
        log.info("printer %s: no stop sent: the printer shows %r, not our job", serial,
                 _s((latest or {}).get('subtask_name')))
        return None
    return _stop(manager, serial)


def _stopped_text(stopped: bool | None) -> str:
    if stopped is None:
        return "; our job was not running on the printer, so nothing was stopped; calibration abandoned"
    return "; the calibration job was stopped" if stopped else "; the stop was not confirmed"


def _stop(manager, serial: str) -> bool:
    """Best-effort `stop` (callers go through `_stop_ours`); true once a report shows the printer no longer
    busy."""
    try:
        manager.publish(serial, {"print": {"command": "stop", "param": ""}})
        return manager.wait_report(serial, lambda r: _s(r.get('gcode_state')).upper() not in BUSY,
                                   STOP_TIMEOUT) is not None
    except Exception:
        return False


def _no_error(v) -> bool:
    """`print_error` says no error: absent, 0, "0" or "" only."""
    if v is None:
        return True
    if isinstance(v, bool):
        return False
    if isinstance(v, int):
        return v == 0
    return isinstance(v, str) and v.strip() in ("", "0")


def _error_text(v) -> str:
    """A `print_error` for a problem line: an int in hex as the printer's HMS codes are written (0x0500C011)."""
    if isinstance(v, int) and not isinstance(v, bool):
        return f"0x{v & 0xFFFFFFFF:08X}"
    return str(v)[:32]


def _job(manager, serial: str, res: CalibResult, labels: list[str], sent: list[int], snap: dict,
         should_stop=None, *, numbering) -> None:
    """Send and watch one job. `numbering` = (hardware, model, candidate scheme keys, (ams_id, tray_id) per label,
    ams_mapping2 or None, the last print's mapping or None)."""
    hw, mi, candidates, addrs, mapping2, last_print = numbering
    name = res.job or run_name(serial)
    stopping = should_stop or (lambda: False)
    if stopping():
        res.problems.append("interrupted: mapping was stopped before the calibration job")
        return
    before_mapping = snap.get('mapping')
    try:
        manager.forget_report_key(serial, 'mapping')    # what `mapping` says from now on is this job's
        reply = manager.publish(serial, payload(serial, sent, name, mapping2))
    except Exception as e:      # offline / no reply raised by the Manager
        res.problems.append(f"cannot send the calibration job ({type(e).__name__})")
        return
    if reply is not None and not _ok(reply):
        log.warning("printer %s: calibration job refused (%s)", serial, _s(reply.get('reason')) or reply.get('result'))
        res.problems.append(REFUSED)
        res.report_wanted = "job_refused"
        res.retry = True        # the numbers may be what it refused: the next candidate's may do
        return

    before = (_s(snap.get('gcode_state')).upper(), _s(snap.get('subtask_name')), _s(snap.get('task_id')))
    heaters0, tray0 = heater_targets(snap), _tray_now(snap)
    st = {'started': False, 'final': None, 'trip': None, 'other': None, 'error': None}

    def watch(r: dict) -> bool:
        gs, sub = _s(r.get('gcode_state')).upper(), _s(r.get('subtask_name'))
        # another print started (not ours, not the one the printer showed before): never touch it
        if sub != name and gs in BUSY and (sub, _s(r.get('task_id'))) != before[1:]:
            st['other'] = sub or '?'
            return True
        # the watchdog, whether or not the job is seen as started: no heating, no filament load, ever
        if stopping():
            st['trip'] = "interrupted: mapping was stopped"
            return True
        h = heating(heaters0, r)
        if h is not None:
            st['trip'] = f"{HEATING} ({h})"
            return True
        tn = _tray_now(r)
        if tn is not None and tn != tray0:
            st['trip'] = f"{LOADING} (tray_now {tray0} -> {tn})"
            return True
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
            st['error'] = r.get('print_error')
            return True
        return False

    _wait(manager, serial, watch, JOB_TIMEOUT, should_stop)
    if st['other'] is not None:
        log.warning("printer %s: another job (%s) started; calibration abandoned, that job left alone", serial,
                    st['other'])
        res.other_job, res.consistent = True, False
        res.problems.append(f"{OTHER_JOB} (the printer is running {st['other']!r}; it was not stopped)")
        return
    if st['trip'] is not None:
        log.warning("printer %s: calibration job tripped: %s", serial, st['trip'])
        res.problems.append(st['trip'] + _stopped_text(_stop_ours(manager, serial, name)))
        res.consistent = False
        return
    if not st['started']:
        stopped = _stop_ours(manager, serial, name)   # best effort: ours may still start after we gave up on it
        res.report_wanted = "job_refused"
        res.problems.append(f"the printer did not start the calibration job within {JOB_TIMEOUT:.0f} s"
                            + ("" if stopped is None else _stopped_text(stopped)))
        return
    if st['final'] is None:
        res.report_wanted = "job_failed"
        res.problems.append(f"the calibration job did not finish within {JOB_TIMEOUT:.0f} s"
                            + _stopped_text(_stop_ours(manager, serial, name)))
        return
    err = st['error']
    code = "" if _no_error(err) else f" (print_error {_error_text(err)})"
    ended = f"the calibration job ended as {st['final']} on the printer{code}"
    res.final, res.print_error = st['final'], _error_text(err) if code else None
    clean = st['final'] == 'FINISH' or not code     # the H2D ends a gcode-only job FAILED with no error: finished
    res.failed_as_finish = st['final'] != 'FINISH' and clean
    if st['final'] != 'FINISH':
        log.info("printer %s: %s", serial, ended)

    if res.mapping is None:
        # a printer that reports no mapping will not for other numbers either: no second job, observe mode
        if st['final'] != 'FINISH':
            res.problems.append(ended)
        res.problems.append("the printer reported no slot mapping")
        res.report_wanted = "no_mapping" if st['final'] == 'FINISH' else "job_failed"
        return
    vals = []
    for i, label in enumerate(labels):
        v = _int(res.mapping[i]) if i < len(res.mapping) else None
        vals.append(v)
        if v is None:
            res.problems.append(f"{label}: the printer reported no slot")
        elif v >= 0:
            res.decoding[label] = v
    # one number per filament, all different, none of them "no slot": the only thing that makes this an answer
    numbers_ok = all(v is not None and v >= 0 for v in vals) and len(set(vals)) == len(vals)
    proved = [k for k in candidates
              if all(addr is not None and fits(hw, mi, k, v, *addr) for v, addr in zip(vals, addrs))] if numbers_ok else []
    own = [k for k in proved if k in mi.numbering]
    if mi.known and own:        # a scheme the model does not list is a last resort, not a rival to its own
        proved = own
    res.scheme, res.fits = proved[0] if proved else None, list(proved)
    # for the report: whether a real printer repeats the old mapping in its full report is not known yet
    res.repeats_last_print = (numbers_ok and isinstance(last_print, list)
                              and list(res.mapping)[:len(vals)] == last_print[:len(vals)])
    stale = res.scheme is None and res.repeats_last_print
    if res.scheme is None:
        # a job that ended FAILED may never have read our file: what to find out is why it failed, not how it numbers
        res.report_wanted = "no_scheme" if st['final'] == 'FINISH' else "job_failed"
    if stale and st['final'] != 'FINISH':
        res.problems.append(ended)
        res.problems.append("the printer's slot numbers are the same as its last print's, so they say nothing about these "
                            "slots; filament use stays logged only")
    elif stale:
        res.problems.append("the printer's slot numbers are the same as its last print's and fit no numbering this kit "
                            "knows, so they say nothing about these slots; filament use stays logged only")
    elif res.scheme is None and not (numbers_ok and clean):
        # a failed job whose numbers fit nothing, or no usable numbers: nothing is proven
        if st['final'] != 'FINISH':
            res.problems.append(ended)
        for label, s_, v in zip(labels, sent, vals):
            if v is not None and v != s_:
                res.problems.append(f"{label}: sent slot {s_}, the printer reported {v}")
        # not the scheme's fault: a job that failed may never have read our file, and a short list numbers nothing
        res.problems.append(f"the job failed on the printer, so the numbers it reported {list(res.mapping)} say nothing about "
                            "how it numbers its slots" if not clean else
                            f"the printer's numbers {list(res.mapping)} aren't one for each of the {len(labels)} filaments, so "
                            "they prove no numbering")
    elif res.scheme is None:
        log.info("printer %s: the reported numbers %s fit no scheme (%s); keeping them as they are", serial, vals,
                 ", ".join(candidates))
        res.scheme_unsettled = True
        res.notes.append("the printer's slot numbers fit no numbering this kit knows: each loaded slot keeps the "
                         "number the printer gave, and a slot that is empty now gets one when it is loaded and mapped")
    elif len(proved) > 1:
        res.scheme_unsettled = True
        log.info("printer %s: the loaded slots number alike under %s; taking %s (the model's first)", serial,
                 ", ".join(proved), res.scheme)
        res.notes.append(f"the loaded slots are numbered alike under {', '.join(proved)}: the numbering of further "
                         f"AMS units is not settled yet, so map again after loading a second unit")
    if res.scheme is not None and code:
        res.notes.append(f"{ended}; the numbers it reported are what count")
        if vals == sent or list(res.mapping) == before_mapping:
            # an echo, or the last print's numbers: nothing shows the printer read this job
            res.scheme_unsettled = True
            res.report_wanted = "job_failed"
            log.warning("printer %s: the job failed and its numbers prove little (sent %s, reported %s)", serial, sent,
                        vals)
    res.consistent = res.scheme is not None or (numbers_ok and clean and not stale)
    # another job only after a clean end with no scheme (never after a real failure or a stop)
    res.retry = clean and res.scheme is None and not stale


def delete_leftover(serial: str, printer: registry.Printer | None = None) -> list[str]:
    """Best effort: delete the job file a killed calibration left on the printer (`remote_path`). Returns the
    problems (none when it is gone, or was never there); never raises."""
    path = remote_path(serial)
    try:
        if printer is None:
            printer = registry.load().get(serial)
        if printer is None or not printer.configured or not printer.access_code:
            return ["not_configured"]
        with ftps.Client(printer) as c:
            try:
                c.delete(path)
            except ftps.FtpsError as e:
                if "550" not in str(e):          # 550: no such file, nothing left to delete
                    return [f"could not delete {path}: {e}"]
        return []
    except tlspin.CertChanged:
        return [f"could not delete {path}: cert_changed"]
    except Exception as e:
        return [f"could not delete {path}: {type(e).__name__}"]


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


def _check_slots(manager, serial: str, slotmap: SlotMap, trays0: dict, res: CalibResult) -> None:
    """After the job: compare every loaded slot with the snapshot and report one that changed meanwhile. The
    calibration writes no slot, so a change was made by someone else (another print, Studio, the touchscreen, an
    RFID read): it is left as is and never written, and `restored` stays true (we changed nothing)."""
    try:
        r = manager.wait_report(serial, lambda r: True, SNAPSHOT_TIMEOUT)
    except Exception:
        r = None
    if r is None:
        res.problems.append("could not check the slots after the calibration (no report); nothing was written "
                            "to them")
        return
    now = _trays(r)
    for label, slot in slotmap.slots.items():
        key = _key(slot)
        t0 = trays0.get(key) if key else None
        if _loaded(t0) and not _same(t0, now.get(key)):
            log.info("printer %s: slot %s changed during the calibration (not by us); left as is", serial, label)
            res.problems.append(f"{label}: its setting changed on the printer during the calibration (not by "
                                f"filament-kit); left as is")
