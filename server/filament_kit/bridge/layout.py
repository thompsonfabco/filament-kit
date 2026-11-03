"""The AMS layout of one printer, read from its merged report: the one unit builder behind `status` (the app's
`ams` list) and `ams.units` (slot test, loading, mapping), so every caller sees the same units and labels.

Units: every entry of `ams.ams[]` (any count, ordered by id) plus the external spool holders from `vir_slot[]` and
`vt_tray` (one unit per holder, kind "ext"; `vir_slot` wins for an id both name). A unit's type
(`hardware.Hardware.ams_type`) comes from its module code when the printer reported one (`get_version`, kept in
the report under MODULES by the connection), else from the printer model, else from its id range and tray count;
an unknown module gives the generic type (kind "generic") and a note.

Labels: spreadsheet style without limit (A ... Z, AA, AB ...), counted from the start of the type's id range, after
the type's prefix (AMS HT: "HT-A" ...). A unit with one slot has the unit label as its slot label, others add the
slot number ("A1" ... "A4"). An unknown module is labelled as its id range's type would be (its Spoolman locations
stay put). Externals take the model's labels ("Ext" for single-holder printers, "Ext-L" / "Ext-R"); a holder the
model does not list is "Ext" when it is the only one and the model has one, else Ext-L / Ext-R for 254 / 255, else
"Ext-<id>". Labels are unique per printer (a clash gets "#<id>" appended). `say` = the reader's speech tokens.

Presence (`SlotInfo.present` / `reading`): from the model's presence layout (`hardware.Presence`) and the report's
bit fields (hex). When the model has no layout, the report has no bits, or the layout does not describe this
hardware (a slot without a bit, or two slots on one bit) the whole printer falls back: `present` = True when the
slot reports a filament type, else None (unknown), `reading` None, and a note says "presence layout unknown".
Externals have no sensor: `present` follows the same tray_type rule.

Fingerprint: `[[ams_id, type key or None, slot count], ...]` over all units (externals as "ext"); the type is
only given when it came from a module code, so a code arriving after the first report is not a change.
`same_layout(a, b)` compares ids and slot counts, and types where both sides have one."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import hardware
from .fields import _d, _int, _l, _s
from .hardware import AmsType, ModelInfo

MODULES = 'fk_modules'          # report key: {"<ams_id>": "<module code>"} from the printer's get_version reply
EXT_DEFAULT = {254: 'Ext-L', 255: 'Ext-R'}   # Bambu: 254 = deputy (left) nozzle, 255 = main (right)
EXT_KIND = 'ext'
HT_BASE = 128
PRESENCE_UNKNOWN = "presence layout unknown: shown from the slot's filament type"


@dataclass(frozen=True)
class SlotInfo:
    tray_id: int
    label: str
    say: tuple[str, ...]
    present: bool | None
    reading: bool | None
    raw: dict = field(default_factory=dict, compare=False, repr=False)
    alias: str | None = None   # an older label of this slot (the file's external alias, "Ext" for the H2D's Ext-L)


@dataclass(frozen=True)
class UnitInfo:
    ams_id: int
    kind: str                  # ams-type key ("ams", "ams_2pro", "ams_ht", "ams_lite", "generic") or "ext"
    type_name: str
    label: str
    say: tuple[str, ...]
    known: bool
    module: str | None
    slots: tuple[SlotInfo, ...]
    typed: bool = False        # the type came from a module code


@dataclass
class Layout:
    units: list[UnitInfo]
    notes: list[str]
    presence: str              # "bits" | "tray_type"
    model: ModelInfo
    fingerprint: list = field(default_factory=list)


def letters(n: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA, 701 -> ZZ, 702 -> AAA."""
    n = int(n)
    out = ''
    n += 1
    while n > 0:
        n, r = divmod(n - 1, 26)
        out = chr(ord('A') + r) + out
    return out


def _hex(v: Any) -> int | None:
    if isinstance(v, int) and not isinstance(v, bool):
        return v if v >= 0 else None
    if isinstance(v, str) and v.strip():
        try:
            n = int(v.strip(), 16)
        except ValueError:
            return None
        return n if n >= 0 else None
    return None


def _label_type(hw: hardware.Hardware, t: AmsType, aid: int, model: ModelInfo, count: int | None) -> AmsType:
    """The type whose label style names this unit: its own, or for an unknown module its id range's type."""
    if t.key != 'generic':
        return t
    by_range = hw.ams_type(aid, None, model, count)
    return by_range if by_range.key != 'generic' else t


def unit_label(t: AmsType, aid: int) -> str:
    if t.key == 'generic':
        return f"HT-{letters(aid - HT_BASE)}" if aid >= HT_BASE else letters(aid)
    base = t.ids[0] if t.ids else (HT_BASE if t.label == 'ht' else 0)
    return f"{t.label_prefix}{letters(max(0, aid - base))}"


def _slot_label(ulabel: str, single: bool, tray_id: int) -> str:
    return ulabel if single else f"{ulabel}{tray_id + 1}"


def _externals(p: dict) -> dict[int, dict]:
    """id -> raw holder dict, from vir_slot[] (wins) and vt_tray (id 254 when it gives none)."""
    out: dict[int, dict] = {}
    vt = p.get('vt_tray')
    if isinstance(vt, dict):
        gid = _int(vt.get('id'))
        out[gid if gid is not None and gid >= 0 else 254] = vt
    for t in _l(p.get('vir_slot')):
        gid = _int(t.get('id'))
        if gid is not None and gid >= 0:
            out[gid] = t
    return out


def _ext_labels(ids: list[int], model: ModelInfo) -> dict[int, tuple[str, str | None, str | None]]:
    """id -> (label, say text or None, alias or None)."""
    known = {x.id: x for x in model.externals}
    out = {}
    for i in ids:
        if i in known:
            out[i] = (known[i].label, known[i].say, known[i].alias)
        elif len(ids) == 1 and len(model.externals) == 1:
            x = model.externals[0]
            out[i] = (x.label, x.say, x.alias)
        elif i in EXT_DEFAULT and len(ids) > 1:
            out[i] = (EXT_DEFAULT[i], None, None)
        else:
            out[i] = ('Ext' if len(ids) == 1 else f"Ext-{i}", None, None)
    return out


def aliases(model=None, hw: hardware.Hardware | None = None) -> dict[str, str]:
    """Older label -> current label for the model's external holders (the file's `alias`): {"Ext": "Ext-L"} on
    the H2D. Spoolman locations and slot-map keys under an older label belong to the current one."""
    mi = (hw or hardware.load()).model(model)
    return {x.alias: x.label for x in mi.externals if x.alias and x.alias != x.label}


def raw_trays(report: dict) -> dict[tuple[int, int], dict]:
    """(ams_id, tray_id) -> raw tray dict for every AMS slot; each external holder as (its id, 0)."""
    p = _d(report)
    out: dict[tuple[int, int], dict] = {}
    for u in _l(_d(p.get('ams')).get('ams')):
        uid = _int(u.get('id'))
        if uid is None or uid < 0:
            continue
        for t in _l(u.get('tray')):
            tid = _int(t.get('id'))
            if tid is not None and tid >= 0:
                out[(uid, tid)] = t
    for gid, t in _externals(p).items():
        out[(gid, 0)] = t
    return out


def _modules(p: dict) -> dict[int, str]:
    out = {}
    for k, v in _d(p.get(MODULES)).items():
        i = _int(k)
        if i is not None and isinstance(v, str) and v.strip():
            out[i] = v.strip()
    return out


def build(report: dict, model=None, hw: hardware.Hardware | None = None) -> Layout:
    """The printer's units from a merged report. `model`: a code, name, ModelInfo or None (generic)."""
    hw = hw or hardware.load()
    mi = hw.model(model)
    p = _d(report)
    ams = _d(p.get('ams'))
    mods = _modules(p)
    notes: list[str] = []
    if not mi.known:
        what = f" {mi.code!r}" if mi.code else ""
        notes.append(f"printer model{what} unknown: generic handling (calibration required)")

    raw_units = []
    for u in _l(ams.get('ams')):
        uid = _int(u.get('id'))
        if uid is None or uid < 0:
            continue
        trays = []
        for t in _l(u.get('tray')):
            tid = _int(t.get('id'))
            if tid is not None and tid >= 0:
                trays.append((tid, t))
        trays.sort(key=lambda x: x[0])
        raw_units.append((uid, trays))
    raw_units.sort(key=lambda x: x[0])

    # presence: a bit per AMS slot, or the tray_type fallback for the whole printer
    pres = hw.presence(mi.presence)
    exist = _hex(ams.get(pres.exist)) if pres else None
    reading_bits = _hex(ams.get(pres.reading)) if pres and pres.reading else None
    bits: dict[tuple[int, int], int] | None = {} if pres is not None and exist is not None else None
    if bits is not None:
        seen: set[int] = set()
        for uid, trays in raw_units:
            for tid, _t in trays:
                b = pres.bit(uid, tid)
                if b is None or b in seen:
                    bits = None
                    break
                seen.add(b)
                bits[(uid, tid)] = b
            if bits is None:
                break
    if bits is None:
        notes.append(PRESENCE_UNKNOWN)

    def presence_of(key: tuple[int, int], t: dict) -> tuple[bool | None, bool | None]:
        if bits is not None and key in bits:
            b = 1 << bits[key]
            return bool(exist & b), (bool(reading_bits & b) if reading_bits is not None else None)
        return (True if _s(t.get('tray_type')) else None), None

    units: list[UnitInfo] = []
    for uid, trays in raw_units:
        code = mods.get(uid)
        count = len(trays) or None
        t = hw.ams_type(uid, code, mi, count)
        if t.key == 'generic':
            notes.append(f"AMS unit {uid}: module {code} unknown: generic unit" if code
                         else f"AMS unit {uid}: type unknown ({len(trays)} slots): generic unit")
        lt = _label_type(hw, t, uid, mi, count)
        ulabel = unit_label(lt, uid)
        single = t.slots == 1 and len(trays) <= 1
        slots = []
        for tid, tr in trays:
            pr, rd = presence_of((uid, tid), tr)
            slots.append(SlotInfo(tid, _slot_label(ulabel, single, tid), (), pr, rd, tr))
        units.append(UnitInfo(uid, t.key, t.name, ulabel, (), t.known, code, tuple(slots), typed=bool(code)))

    exts = _externals(p)
    names = _ext_labels(sorted(exts), mi)
    for gid in sorted(exts):
        tr = exts[gid]
        lab, said, alias = names[gid]
        pr = True if _s(tr.get('tray_type')) else None
        units.append(UnitInfo(gid, EXT_KIND, 'External spool holder', lab, tuple(said.split()) if said else (),
                              True, None, (SlotInfo(0, lab, tuple(said.split()) if said else (), pr, None, tr,
                                                    alias),), typed=True))

    units = _unique(units)
    units = [_with_say(hw, mi, u) for u in units]
    fp = [[u.ams_id, (EXT_KIND if u.kind == EXT_KIND else u.kind) if u.typed else None, len(u.slots)]
          for u in units]
    return Layout(units, notes, 'bits' if bits is not None else 'tray_type', mi, fp)


def _unique(units: list[UnitInfo]) -> list[UnitInfo]:
    """Make every slot label unique: a unit whose labels clash with an earlier one gets "#<id>" appended."""
    taken: set[str] = set()
    out = []
    for u in units:
        mine = [s.label for s in u.slots] + [u.label]
        if any(lab in taken for lab in mine):
            suffix = f"#{u.ams_id}"
            u = UnitInfo(u.ams_id, u.kind, u.type_name, u.label + suffix, u.say, u.known, u.module,
                         tuple(SlotInfo(s.tray_id, s.label + suffix, s.say, s.present, s.reading, s.raw, s.alias)
                               for s in u.slots), u.typed)
        taken.update(s.label for s in u.slots)
        taken.add(u.label)
        out.append(u)
    return out


def _with_say(hw: hardware.Hardware, mi: ModelInfo, u: UnitInfo) -> UnitInfo:
    usay = u.say or tuple(hw.say(u.label, mi))
    slots = tuple(s if s.say else SlotInfo(s.tray_id, s.label, tuple(hw.say(s.label, mi)), s.present, s.reading,
                                           s.raw, s.alias) for s in u.slots)
    return UnitInfo(u.ams_id, u.kind, u.type_name, u.label, usay, u.known, u.module, slots, u.typed)


def kinds(report: dict, model=None) -> dict[int, str]:
    """ams_id -> unit kind ("ext" for an external holder) as `build` sees the report: what the slot command's
    addressing is chosen by."""
    return {u.ams_id: u.kind for u in build(report, model).units}


def same_layout(a, b) -> bool:
    """Two fingerprints describe the same hardware: ids and slot counts match, types where both know one."""
    if a is None or b is None:
        return a is None and b is None
    try:
        if len(a) != len(b):
            return False
        for (ia, ta, na), (ib, tb, nb) in zip(a, b):
            if ia != ib or na != nb or (ta is not None and tb is not None and ta != tb):
                return False
    except (TypeError, ValueError):
        return False
    return True


def label_for(ams_id: int, tray_id: int, model=None, hw: hardware.Hardware | None = None) -> str | None:
    """The label a slot has without a report to read (no module codes, the type by id range): for decoding a
    printer's slot number into a label (usage, observe mode). Externals (254 / 255) take the model's labels as
    `build` gives them to a LONE holder (the report lists only this one): on a printer whose report lists holders
    the model does not know, `build` may label them otherwise (Ext-L / Ext-R / Ext-<id>)."""
    hw = hw or hardware.load()
    a, t = _int(ams_id), _int(tray_id)
    if a is None or t is None or a < 0 or t < 0:
        return None
    mi = hw.model(model)
    if a in EXT_DEFAULT or any(x.id == a for x in mi.externals):
        # as `build` labels this holder when it is the one the report lists (a lone 255 on a single-holder
        # printer is "Ext" there too)
        return _ext_labels([a], mi)[a][0] if t == 0 else None
    typ = hw.ams_type(a, None, mi, None)
    ulabel = unit_label(typ, a)
    return _slot_label(ulabel, typ.slots == 1, t)
