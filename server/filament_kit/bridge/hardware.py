"""Bambu printer hardware facts from `bambu_hardware.xml`: models, AMS unit types, slot numbering schemes, presence
bit layouts and speech words.

The bundled file (package data next to this module) is the default. An optional override at
`/etc/filament-kit/bambu_hardware.xml` (`$FK_ETC`) wins per element: a `<model>` by `code`, an `<ams-type>`,
`<scheme>` or `<layout>` by `key`, a speech `<word>` by `text`. `load()` rereads both files when their mtime or size
changes. Files are parsed with defusedxml (no DTD, no entities, no external references) and checked by the
validator below (an XSD equivalent in code: allowed elements and attributes, required attributes, value types, cross
references). A bad override is refused whole: the last good data stays in use and `Hardware.errors` says why. The
program never guesses silently: an unknown model or AMS module gets a generic record with `known=False`.

Interfaces
----------
`load() -> Hardware` (cached).

`Hardware.model(code_or_name) -> ModelInfo`: a reported code (`O1D`, `BL-P001`, `3DPrinter-X1-Carbon`) or a typed
name (`H2D`, `Bambu Lab X1 Carbon`, `x1c`, `h2d pro`); case, spaces, dashes and a leading "Bambu Lab" do not matter.
Unknown → the generic record.

`ModelInfo` fields:
    code          str          primary code from the file (generic: the code asked for, upper case, maybe "")
    name          str          display name ("H2D", "X1 Carbon"); generic: "Unknown Bambu printer (...)"
    preset_name   str | None   Bambu Studio printer name ("Bambu Lab H2D"); None for the generic record
    say           str | None   speech text for the printer ("x one c"); generic: "printer"
    aliases       tuple[str]   other codes and typed names that find this model
    nozzles       int | None   number of nozzles; generic: None (not known: treated as more than one, Ruling BM)
    camera        str | None   "hls" (RTSPS, relayed as HLS), "mjpeg" (port-6000 JPEG) or None (no camera offered)
    chamber_max   int | None   highest chamber temperature in °C, None without a heated chamber
    presence      str | None   presence layout key (`Hardware.presence`), None = unknown (fall back to tray_type)
    gcode_only_failed_is_finish  bool  a gcode-only calibration job ending FAILED with no print_error has finished
    ams_mapping2  bool         calibration also sends `ams_mapping2`
    light_nodes   tuple[str]   MQTT light nodes ("chamber_light", ...); generic: () (none assumed)
    externals     tuple[External]  external spool holders, each `External(id, label, say, alias)`: id 254/255,
                               label "Ext" (single holder) or "Ext-L"/"Ext-R", say = speech text ("external
                               left"), alias = an older label of the same holder (None): Spoolman locations and
                               slot-map keys under the alias count as this holder ("Ext" -> "Ext-L" on the H2D)
    external_addressing  str   how `ams_filament_setting` names an external holder: "tray-is-ams" (tray_id =
                               ams_id, slot_id 0; verified on the H2D) or "legacy" (ams_id = holder id, tray_id 0,
                               no slot_id: the kit's earlier command); generic: "legacy"
    numbering     tuple[str]   candidate numbering scheme keys, first guess first (generic: ("legacy",))
    ftp_dirs      tuple[str]   FTPS directories where print jobs land
    known         bool         False for the generic record (calibration required, nothing assumed)

`Hardware.ams_type(ams_id, module_code, model, tray_count) -> AmsType`: by module code (longest matching prefix; a
code that matches no prefix gives the generic type), with no code by the printer model (types listing model codes,
e.g. AMS Lite on A1/A1 mini), else by id range and slot count
(first type in file order), else a generic type with the report's slot count. `model` is a code, a name, a
`ModelInfo` or None; `module_code` and `tray_count` may be None.

`AmsType` fields:
    key           str          "ams", "ams_2pro", "ams_ht", "ams_lite"; "generic" for an unknown unit
    name          str          display name ("AMS 2 Pro"); generic: "Unknown AMS"
    slots         int          slots per unit (generic: the report's tray count, else 4, or 1 for ids >= 128)
    label         str          label style: "letter" (A, B, ... Z, AA ...) or "ht" (HT-A ...), others from the file
    label_prefix  str          text before the letters ("" for letter, "HT-" for ht, or the file's `prefix`)
    say           str | None   speech text for the label prefix ("h t"), None when there is none
    ids           tuple[int, int] | None   inclusive id range the type can have, None = any
    modules       tuple[str]   module code prefixes (upper case)
    models        tuple[str]   printer model codes this type belongs to (empty = any)
    known         bool         False for the generic type and for types marked verified="false" in the file
                               (first-gen AMS until a capture confirms it)

`Hardware.scheme(key) -> Scheme` (KeyError when unknown): `encode(ams_id, tray_id) -> int` (ValueError when the
scheme cannot number that slot) and `decode(n) -> (ams_id, tray_id) | None` (None for negative or impossible
numbers, e.g. -1 = unused). Kinds: `linear` (`per_unit`, `ht_from`: unit*per_unit+tray, units from ht_from up are
their own id) and `shift` (`bits`: unit << bits | tray).

`Hardware.presence(key) -> Presence | None`: `exist` / `reading` = report field names; `bit(ams_id, tray_id) -> int
| None` (None = the layout does not describe that unit). Bit expressions use a tiny grammar parsed by hand (never
eval): `id`, `tray`, integers, `+ - * <<`, parentheses.

`Hardware.say(label, model=None) -> list[str]`: speech tokens for a slot or unit label ("HT-B" → ["h", "t", "b"]);
with a model (code, name or ModelInfo) its own external holders are matched first.

`Hardware.errors -> list[str]`: problems from the last load (empty when clean). Fatal: the file was refused.
`Hardware.warnings -> list[str]`: unknown elements and attributes (ignored, the rest loads: forward compatibility).

Versions: `version="major[.minor]"`; a file with another major version is refused, minor versions load.

`validate(data: bytes) -> list[str]`: check a complete file without installing it.
`file_version(data: bytes) -> (major, minor) | None`: a file's root version, for comparing files (the updater's
hardware data feed installs a release's file as the override only when it is newer than the bundled one).
"""
from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import defusedxml.ElementTree as DET

from .. import config

BUNDLED = Path(__file__).with_name("bambu_hardware.xml")
OVERRIDE_NAME = "bambu_hardware.xml"
MAJOR = "1"           # file version major[.minor]: another major is refused, any minor loads
MAX_BYTES = 1_000_000


def override_path() -> Path:
    return config.paths().etc / OVERRIDE_NAME


class HardwareError(Exception):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


# --- records ------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class External:
    id: int
    label: str
    say: str
    alias: str | None = None


@dataclass(frozen=True)
class ModelInfo:
    code: str
    name: str
    preset_name: str | None
    say: str | None = None
    aliases: tuple[str, ...] = ()
    nozzles: int | None = 1
    camera: str | None = None
    chamber_max: int | None = None
    presence: str | None = None
    gcode_only_failed_is_finish: bool = False
    ams_mapping2: bool = False
    external_addressing: str = "legacy"
    light_nodes: tuple[str, ...] = ("chamber_light",)
    externals: tuple[External, ...] = (External(254, "Ext", "external"),)
    numbering: tuple[str, ...] = ("legacy",)
    ftp_dirs: tuple[str, ...] = ("/", "/cache")
    known: bool = True


def generic_model(code: str | None) -> ModelInfo:
    c = (code or "").strip().upper()
    return ModelInfo(code=c, name=f"Unknown Bambu printer ({c})" if c else "Unknown Bambu printer",
                     preset_name=None, say="printer", nozzles=None, light_nodes=(), known=False)


@dataclass(frozen=True)
class AmsType:
    key: str
    name: str
    slots: int
    label: str
    label_prefix: str = ""
    say: str | None = None
    ids: tuple[int, int] | None = None
    modules: tuple[str, ...] = ()
    models: tuple[str, ...] = ()
    known: bool = True


MAX_AMS_ID = 255


@dataclass(frozen=True)
class Scheme:
    key: str
    kind: str                     # "linear" | "shift"
    per_unit: int | None = None
    ht_from: int | None = None
    bits: int | None = None

    def encode(self, ams_id: int, tray_id: int) -> int:
        a, t = int(ams_id), int(tray_id)
        if not 0 <= a <= MAX_AMS_ID or t < 0:
            raise ValueError(f"scheme {self.key}: no number for unit {a} tray {t}")
        if self.kind == "shift":
            if t >= 1 << self.bits:
                raise ValueError(f"scheme {self.key}: tray {t} does not fit in {self.bits} bits")
            return (a << self.bits) | t
        if self.ht_from is not None and a >= self.ht_from:
            if t:
                raise ValueError(f"scheme {self.key}: unit {a} has a single slot")
            return a
        if t >= self.per_unit:
            raise ValueError(f"scheme {self.key}: tray {t} beyond {self.per_unit} per unit")
        n = a * self.per_unit + t
        if self.ht_from is not None and n >= self.ht_from:
            raise ValueError(f"scheme {self.key}: unit {a} tray {t} collides with HT numbers")
        return n

    def decode(self, n: int) -> tuple[int, int] | None:
        try:
            n = int(n)
        except (TypeError, ValueError):
            return None
        if n < 0:
            return None
        if self.kind == "shift":
            a = n >> self.bits
            return (a, n & ((1 << self.bits) - 1)) if a <= MAX_AMS_ID else None
        if self.ht_from is not None and n >= self.ht_from:
            return (n, 0) if n <= MAX_AMS_ID else None
        return divmod(n, self.per_unit)


# Always present, also in an empty or fallback Hardware; the file's schemes of the same key win.
BUILTIN_SCHEMES = {"legacy": Scheme("legacy", "linear", per_unit=4, ht_from=128),
                   "shift8": Scheme("shift8", "shift", bits=8)}


@dataclass(frozen=True)
class Presence:
    key: str
    exist: str
    reading: str | None
    ranges: tuple[tuple[int, int, str], ...]
    _fns: tuple[Callable[[int, int], int], ...] = field(default=(), repr=False, compare=False)

    def bit(self, ams_id: int, tray_id: int) -> int | None:
        try:
            ams_id, tray_id = int(ams_id), int(tray_id)
        except (TypeError, ValueError):
            return None
        for (lo, hi, _src), fn in zip(self.ranges, self._fns):
            if lo <= ams_id <= hi:
                try:
                    v = fn(ams_id, tray_id)
                except ValueError:
                    return None
                return v if 0 <= v < 64 else None
        return None


# --- the bit expression grammar -----------------------------------------------------------------------------------
#   expr := sum ("<<" sum)*      sum := term (("+" | "-") term)*      term := atom ("*" atom)*
#   atom := INT | "id" | "tray" | "(" expr ")"

_TOKEN = re.compile(r"\s*(?:(\d+)|(id|tray)(?![A-Za-z0-9_])|(<<|[+\-*()]))")
_MAX_EXPR = 64
_LIMIT = 1 << 62


def _tokens(src: str) -> list[tuple[str, str]]:
    out, i = [], 0
    src = src.rstrip()
    while i < len(src):
        m = _TOKEN.match(src, i)
        if not m or m.end() == i:
            raise ValueError(f"unexpected {src[i:].strip()[:10]!r} in {src!r}")
        num, name, op = m.groups()
        if num is not None:
            if len(num) > 6:
                raise ValueError(f"number {num[:8]}... too long in {src!r}")
            out.append(("int", num))
        elif name is not None:
            out.append(("var", name))
        else:
            out.append(("op", op))
        i = m.end()
    return out


def _checked(v: int) -> int:
    if abs(v) >= _LIMIT:
        raise ValueError("value out of range")
    return v


def parse_expr(src: str) -> Callable[[int, int], int]:
    """Compile a bit expression into fn(id, tray) -> int. Raises ValueError for anything outside the grammar."""
    if not isinstance(src, str) or not src.strip() or len(src) > _MAX_EXPR:
        raise ValueError(f"bad expression {src!r}")
    toks = _tokens(src)
    pos = 0

    def peek():
        return toks[pos] if pos < len(toks) else ("end", "")

    def take():
        nonlocal pos
        t = peek()
        pos += 1
        return t

    def atom():
        kind, val = take()
        if kind == "int":
            n = int(val)
            return lambda i, t: n
        if kind == "var":
            return (lambda i, t: i) if val == "id" else (lambda i, t: t)
        if (kind, val) == ("op", "("):
            inner = expr()
            if take() != ("op", ")"):
                raise ValueError(f"missing ')' in {src!r}")
            return inner
        raise ValueError(f"expected a number, id, tray or '(' in {src!r}")

    def term():
        left = atom()
        while peek() == ("op", "*"):
            take()
            right = atom()
            left = (lambda a, b: lambda i, t: _checked(a(i, t) * b(i, t)))(left, right)
        return left

    def sum_():
        left = term()
        while peek() in (("op", "+"), ("op", "-")):
            op = take()[1]
            right = term()
            if op == "+":
                left = (lambda a, b: lambda i, t: _checked(a(i, t) + b(i, t)))(left, right)
            else:
                left = (lambda a, b: lambda i, t: _checked(a(i, t) - b(i, t)))(left, right)
        return left

    def shift(a, b):
        def f(i, t):
            n = b(i, t)
            if not 0 <= n <= 62:
                raise ValueError(f"shift by {n}")
            return _checked(a(i, t) << n)
        return f

    def expr():
        left = sum_()
        while peek() == ("op", "<<"):
            take()
            left = shift(left, sum_())
        return left

    fn = expr()
    if pos != len(toks):
        raise ValueError(f"unexpected {peek()[1]!r} in {src!r}")
    return fn


# --- the validator ------------------------------------------------------------------------------------------------

_INT_RE = re.compile(r"-?\d{1,9}")


def _int(v: str) -> int:
    if not _INT_RE.fullmatch(v):
        raise ValueError("is not an integer")
    return int(v)


def _pos(v: str) -> int:
    n = _int(v)
    if n < 1:
        raise ValueError("is not a positive integer")
    return n


def _nonneg(v: str) -> int:
    n = _int(v)
    if n < 0:
        raise ValueError("is negative")
    return n


def _bool(v: str) -> bool:
    if v not in ("true", "false"):
        raise ValueError("is not true or false")
    return v == "true"


def _text(v: str) -> str:
    if not v.strip():
        raise ValueError("is empty")
    return v.strip()


def _enum(*allowed):
    def f(v: str) -> str:
        if v not in allowed:
            raise ValueError(f"is not one of {', '.join(allowed)}")
        return v
    return f


def _expr(v: str) -> str:
    parse_expr(v)
    return v


@dataclass(frozen=True)
class _E:
    attrs: dict = field(default_factory=dict)        # name -> checker
    required: tuple = ()
    children: dict = field(default_factory=dict)     # tag -> _E
    text: bool = False                               # element carries text (checked non-empty)
    once: tuple = ()                                 # child tags allowed at most once


_TEXT = _E(text=True)
_VERSION = re.compile(r"(\d{1,4})(?:\.(\d{1,4}))?")
_SCHEMA = _E(
    attrs={"version": _text}, required=("version",), once=("models", "ams-types", "numbering-schemes",
                                                             "presence-layouts", "speech"),
    children={
        "models": _E(children={"model": _E(
            attrs={"code": _text, "name": _text, "preset-name": _text, "say": _text, "nozzles": _pos,
                   "camera": _enum("hls", "mjpeg", "none"), "chamber-max": _pos, "presence": _text,
                   "gcode-only-failed-is-finish": _bool, "ams-mapping2": _bool,
                   "external-addressing": _enum("tray-is-ams", "legacy")},
            required=("code", "name"),
            children={"alias": _TEXT, "light-node": _TEXT, "ftp-dir": _TEXT,
                      "external": _E(attrs={"id": _nonneg, "label": _text, "say": _text, "alias": _text},
                                     required=("id", "label")),
                      "numbering": _E(attrs={"ref": _text}, required=("ref",))})}),
        "ams-types": _E(children={"ams-type": _E(
            attrs={"key": _text, "name": _text, "slots": _pos, "label": _text, "prefix": str, "say": _text,
                   "verified": _bool},
            required=("key", "name", "slots", "label"), once=("ids",),
            children={"ids": _E(attrs={"from": _nonneg, "to": _nonneg}, required=("from", "to")),
                      "module": _E(attrs={"prefix": _text}, required=("prefix",)),
                      "model": _E(attrs={"code": _text}, required=("code",))})}),
        "numbering-schemes": _E(children={"scheme": _E(
            attrs={"key": _text, "kind": _enum("linear", "shift"), "per-unit": _pos, "ht-from": _pos,
                   "bits": _pos},
            required=("key", "kind"))}),
        "presence-layouts": _E(children={"layout": _E(
            attrs={"key": _text, "exist": _text, "reading": _text}, required=("key", "exist"),
            children={"range": _E(attrs={"from": _nonneg, "to": _nonneg, "bit": _expr},
                                  required=("from", "to", "bit"))})}),
        "speech": _E(children={"word": _E(attrs={"text": _text, "say": _text}, required=("text", "say"))}),
    })


def _where(el, path: str) -> str:
    ident = el.get("code") or el.get("key") or el.get("text")
    return f"{path} {ident!r}" if ident else path


def _check(el, spec: _E, path: str, errors: list[str], warnings: list[str]) -> None:
    """Fatal problems go to errors; unknown attributes and elements (a newer file) go to warnings and are ignored."""
    for name, value in el.attrib.items():
        checker = spec.attrs.get(name)
        if checker is None:
            warnings.append(f"{_where(el, path)}: unknown attribute {name!r} ignored")
            continue
        try:
            checker(value)
        except ValueError as e:
            errors.append(f"{_where(el, path)}: {name}={value!r} {e}")
    for name in spec.required:
        if name not in el.attrib:
            errors.append(f"{_where(el, path)}: missing required attribute {name!r}")
    if spec.text:
        if not (el.text or "").strip():
            errors.append(f"{path}: empty text")
    elif (el.text or "").strip():
        errors.append(f"{_where(el, path)}: unexpected text {(el.text or '').strip()[:20]!r}")
    seen: dict[str, int] = {}
    for child in el:
        if not isinstance(child.tag, str):
            continue
        sub = spec.children.get(child.tag)
        if sub is None:
            warnings.append(f"{_where(el, path)}: unknown element <{child.tag}> ignored")
            continue
        seen[child.tag] = seen.get(child.tag, 0) + 1
        if child.tag in spec.once and seen[child.tag] == 2:
            errors.append(f"{_where(el, path)}: <{child.tag}> given twice")
        if (child.tail or "").strip():
            errors.append(f"{_where(el, path)}: unexpected text after <{child.tag}>")
        _check(child, sub, f"{path}/{child.tag}", errors, warnings)


def _parse(data: bytes, where: str):
    """(root element, warnings) of a well-formed, schema-valid file, or HardwareError."""
    if len(data) > MAX_BYTES:
        raise HardwareError([f"{where}: larger than {MAX_BYTES} bytes"])
    try:
        root = DET.fromstring(data, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except Exception as e:  # ParseError, DTDForbidden, EntitiesForbidden, ...
        raise HardwareError([f"{where}: parse error: {type(e).__name__}: {e}"]) from None
    if root.tag != "bambu-hardware":
        raise HardwareError([f"{where}: root element is <{root.tag}>, not <bambu-hardware>"])
    errors: list[str] = []
    warnings: list[str] = []
    _check(root, _SCHEMA, "bambu-hardware", errors, warnings)
    v = root.get("version")
    if v is not None:
        m = _VERSION.fullmatch(v.strip())
        if not m or m.group(1).lstrip("0") != MAJOR:
            errors.append(f"bambu-hardware: version {v!r} not supported (this server reads version {MAJOR}.x)")
    if errors:
        raise HardwareError([f"{where}: {e}" for e in errors])
    return root, [f"{where}: {w}" for w in warnings]


# --- merging and building -----------------------------------------------------------------------------------------

_SECTIONS = {  # section -> (element tag, identity attribute, case-insensitive)
    "models": ("model", "code", True),
    "ams-types": ("ams-type", "key", False),
    "numbering-schemes": ("scheme", "key", False),
    "presence-layouts": ("layout", "key", False),
    "speech": ("word", "text", True),
}


def _elements(root, where: str) -> dict[str, dict]:
    """section -> {identity: element} in file order; an identity given twice in one file is an error."""
    out: dict[str, dict] = {}
    errors = []
    for section, (tag, ident, fold) in _SECTIONS.items():
        found: dict = {}
        for sec in root.findall(section):
            for el in sec.findall(tag):
                k = el.get(ident, "")
                k = k.strip().upper() if fold else k.strip()
                if k in found:
                    errors.append(f"{where}: <{tag} {ident}={el.get(ident)!r}> given twice")
                found[k] = el
        out[section] = found
    if errors:
        raise HardwareError(errors)
    return out


def _norm(s: str) -> str:
    s = s.strip().upper()
    s = s.removeprefix("BAMBU LAB")
    return re.sub(r"[\s\-_]", "", s)


def _build(sections: dict[str, dict], where: str) -> "Hardware":
    errors: list[str] = []

    schemes: dict[str, Scheme] = {}
    for key, el in sections["numbering-schemes"].items():
        kind = el.get("kind")
        if kind == "shift":
            if el.get("bits") is None:
                errors.append(f"scheme {key!r}: kind shift needs bits")
                continue
            bits = int(el.get("bits"))
            if bits > 16:
                errors.append(f"scheme {key!r}: bits={bits} is more than 16")
                continue
            schemes[key] = Scheme(key, "shift", bits=bits)
        else:
            if el.get("per-unit") is None:
                errors.append(f"scheme {key!r}: kind linear needs per-unit")
                continue
            ht = el.get("ht-from")
            schemes[key] = Scheme(key, "linear", per_unit=int(el.get("per-unit")),
                                  ht_from=int(ht) if ht is not None else None)

    ams_types: list[AmsType] = []
    for key, el in sections["ams-types"].items():
        ids_el = el.find("ids")
        ids = None
        if ids_el is not None:
            ids = (int(ids_el.get("from")), int(ids_el.get("to")))
            if ids[0] > ids[1] or ids[1] > MAX_AMS_ID:
                errors.append(f"ams-type {key!r}: ids {ids[0]}-{ids[1]} is not a valid id range")
        label = el.get("label").strip()
        prefix = el.get("prefix")
        if prefix is None:
            prefix = "HT-" if label == "ht" else ""
        ams_types.append(AmsType(
            key=key, name=el.get("name").strip(), slots=int(el.get("slots")), label=label, label_prefix=prefix,
            say=el.get("say"), ids=ids, modules=tuple(m.get("prefix").strip().upper() for m in el.findall("module")),
            models=tuple(m.get("code").strip().upper() for m in el.findall("model")),
            known=el.get("verified") != "false"))

    max_slots = max((t.slots for t in ams_types), default=4)

    def trays_for(i: int) -> int:
        """Slots a unit with this id can have: the largest of the types covering the id, else of all types."""
        return max((t.slots for t in ams_types if t.ids and t.ids[0] <= i <= t.ids[1]), default=max_slots)

    layouts: dict[str, Presence] = {}
    for key, el in sections["presence-layouts"].items():
        ranges, fns, used = [], [], {}
        for r in el.findall("range"):
            lo, hi, src = int(r.get("from")), int(r.get("to")), r.get("bit")
            if lo > hi or hi > MAX_AMS_ID:
                errors.append(f"layout {key!r}: range {lo}-{hi} is not a valid id range")
                continue
            fn = parse_expr(src)
            bad = False
            for i in range(lo, hi + 1):
                for t in range(trays_for(i)):
                    try:
                        b = fn(i, t)
                    except ValueError as e:
                        errors.append(f"layout {key!r}: bit {src!r} for id {i} tray {t}: {e}")
                        bad = True
                        break
                    if not 0 <= b < 64:
                        errors.append(f"layout {key!r}: bit {src!r} gives {b} for id {i} tray {t} (0-63 allowed)")
                        bad = True
                        break
                    if b in used and used[b] != (i, t):
                        errors.append(f"layout {key!r}: bit {b} used by id/tray {used[b]} and {(i, t)}")
                        bad = True
                        break
                    used[b] = (i, t)
                if bad:
                    break
            ranges.append((lo, hi, src))
            fns.append(fn)
        layouts[key] = Presence(key, el.get("exist"), el.get("reading"), tuple(ranges), tuple(fns))

    models: list[ModelInfo] = []
    for code_key, el in sections["models"].items():
        code, name = el.get("code").strip(), el.get("name").strip()
        tag = f"model {code!r}"
        numbering = tuple(n.get("ref") for n in el.findall("numbering")) or ("legacy",)
        for ref in numbering:
            if ref not in schemes:
                errors.append(f"{tag}: unknown numbering scheme {ref!r}")
        presence = el.get("presence")
        if presence is not None and presence not in layouts:
            errors.append(f"{tag}: unknown presence layout {presence!r}")
        externals, ext_ids = [], set()
        for x in el.findall("external"):
            xid = int(x.get("id"))
            if xid > MAX_AMS_ID or xid in ext_ids:
                errors.append(f"{tag}: external id {xid} is out of range or given twice")
                continue
            ext_ids.add(xid)
            alias = (x.get("alias") or "").strip() or None
            externals.append(External(xid, x.get("label").strip(), (x.get("say") or x.get("label")).strip(), alias))
        ext_labels = {x.label.upper() for x in externals}
        for x in externals:
            if x.alias and x.alias.upper() in ext_labels:
                errors.append(f"{tag}: external {x.id} alias {x.alias!r} is a current external label of the model "
                              f"(an alias names an older label only)")
        camera = el.get("camera", "none")
        cmax = el.get("chamber-max")
        models.append(ModelInfo(
            code=code, name=name, preset_name=(el.get("preset-name") or f"Bambu Lab {name}").strip(),
            say=(el.get("say") or name).strip(),
            aliases=tuple(a.text.strip() for a in el.findall("alias")),
            nozzles=int(el.get("nozzles", "1")), camera=None if camera == "none" else camera,
            chamber_max=int(cmax) if cmax is not None else None, presence=presence,
            gcode_only_failed_is_finish=el.get("gcode-only-failed-is-finish") == "true",
            ams_mapping2=el.get("ams-mapping2") == "true",
            external_addressing=el.get("external-addressing", "legacy"),
            light_nodes=tuple(n.text.strip() for n in el.findall("light-node")) or ("chamber_light",),
            externals=tuple(externals), numbering=numbering,
            ftp_dirs=tuple(d.text.strip() for d in el.findall("ftp-dir")) or ("/", "/cache")))

    words = tuple((el.get("text").strip(), el.get("say").strip()) for el in sections["speech"].values())

    hw = Hardware(models, ams_types, {**BUILTIN_SCHEMES, **schemes}, layouts, words)
    errors += hw._index_errors
    if errors:
        raise HardwareError([f"{where}: {e}" for e in errors])
    return hw


class Hardware:
    """The merged hardware facts. Build with `load()`."""

    def __init__(self, models=(), ams_types=(), schemes=None, layouts=None, words=(), errors=None, warnings=None):
        self.models: tuple[ModelInfo, ...] = tuple(models)
        self.ams_types: tuple[AmsType, ...] = tuple(ams_types)
        self.schemes: dict[str, Scheme] = dict(schemes) if schemes else dict(BUILTIN_SCHEMES)
        self.layouts: dict[str, Presence] = dict(layouts or {})
        self.words: tuple[tuple[str, str], ...] = tuple(sorted(words, key=lambda w: -len(w[0])))
        self.errors: list[str] = list(errors or [])
        self.warnings: list[str] = list(warnings or [])
        self._exact: dict[str, ModelInfo] = {}
        self._loose: dict[str, ModelInfo] = {}
        self._index_errors: list[str] = []
        for m in self.models:
            for k in (m.code, *m.aliases):
                self._add(self._exact, k.strip().upper(), m)
            for k in (m.code, m.name, *m.aliases):
                self._add(self._loose, _norm(k), m)
        self._external_say: dict[str, str] = {}
        for m in self.models:
            for x in m.externals:
                self._external_say.setdefault(x.label.upper(), x.say)

    def _add(self, index: dict, key: str, m: ModelInfo) -> None:
        other = index.get(key)
        if other is not None and other.code != m.code:
            self._index_errors.append(f"{key!r} names two models ({other.code}, {m.code})")
            return
        index[key] = m

    def with_errors(self, errors: list[str], warnings: list[str] | None = None) -> "Hardware":
        """A copy with these errors (and warnings; None keeps the current ones)."""
        c = object.__new__(Hardware)
        c.__dict__.update(self.__dict__)
        c.errors = list(errors)
        if warnings is not None:
            c.warnings = list(warnings)
        return c

    def model(self, code_or_name) -> ModelInfo:
        if isinstance(code_or_name, ModelInfo):
            return code_or_name
        s = (code_or_name or "").strip() if isinstance(code_or_name, str) else ""
        if s:
            m = self._exact.get(s.upper()) or self._loose.get(_norm(s))
            if m:
                return m
        return generic_model(s)

    def ams_type(self, ams_id, module_code=None, model=None, tray_count=None) -> AmsType:
        try:
            aid = int(ams_id)
        except (TypeError, ValueError):
            aid = None
        if module_code:
            mc = str(module_code).strip().upper()
            best, best_len = None, 0
            for t in self.ams_types:
                for p in t.modules:
                    if mc.startswith(p) and len(p) > best_len:
                        best, best_len = t, len(p)
            if best is not None:
                return best
            # a reported module nobody knows: never guess a type from the id or the model
            count = tray_count if isinstance(tray_count, int) and tray_count > 0 else None
            return AmsType(key="generic", name="Unknown AMS",
                           slots=count or (1 if aid is not None and aid >= 128 else 4), label="letter", known=False)
        in_range = lambda t: t.ids is None or (aid is not None and t.ids[0] <= aid <= t.ids[1])
        if model is not None:
            mi = self.model(model)
            if mi.known:
                for t in self.ams_types:
                    if t.models and mi.code.upper() in t.models and in_range(t):
                        return t
        count = tray_count if isinstance(tray_count, int) and tray_count > 0 else None
        if aid is not None:
            for t in self.ams_types:
                if t.ids is not None and not t.models and in_range(t) and (count is None or t.slots == count):
                    return t
        slots = count or (1 if aid is not None and aid >= 128 else 4)
        return AmsType(key="generic", name="Unknown AMS", slots=slots, label="letter", known=False)

    def scheme(self, key: str) -> Scheme:
        return self.schemes[key]

    def presence(self, key: str | None) -> Presence | None:
        return self.layouts.get(key) if key else None

    def say(self, label: str | None, model=None) -> list[str]:
        s = (label or "").strip()
        if not s:
            return []
        ext = None
        if model is not None:
            ext = next((x.say for x in self.model(model).externals if x.label.upper() == s.upper()), None)
        ext = ext or self._external_say.get(s.upper())
        if ext:
            return ext.split()
        out, i, up = [], 0, s.upper()
        while i < len(s):
            for text, said in self.words:
                if up.startswith(text.upper(), i):
                    out += said.split()
                    i += len(text)
                    break
            else:
                if s[i].isalnum():
                    out.append(s[i].lower())
                i += 1
        return out


# --- loading ------------------------------------------------------------------------------------------------------

def _read(p: Path, where: str) -> bytes:
    try:
        with open(p, "rb") as f:
            data = f.read(MAX_BYTES + 1)
    except OSError as e:
        raise HardwareError([f"{where}: cannot read: {e.strerror or e}"]) from None
    return data


def validate(data: bytes, where: str = "bambu_hardware.xml") -> list[str]:
    """Problems with a complete hardware file (empty list = good)."""
    try:
        root, _warnings = _parse(data, where)
        _build(_elements(root, where), where)
    except HardwareError as e:
        return e.errors
    return []


def file_version(data: bytes) -> tuple[int, int] | None:
    """(major, minor) of a hardware file's root `version` ("1" is (1, 0)); None when it has none or cannot be
    parsed. For comparing files only; `validate` says whether a file is good."""
    try:
        root = DET.fromstring(data, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except Exception:  # noqa: BLE001 - ParseError, DTDForbidden, ...
        return None
    m = _VERSION.fullmatch((root.get("version") or "").strip())
    return (int(m.group(1)), int(m.group(2) or 0)) if m else None


def _merge(base: dict[str, dict], over: dict[str, dict]) -> dict[str, dict]:
    return {section: {**base[section], **over.get(section, {})} for section in base}


def _stamp(p: Path):
    try:
        st = os.stat(p)
    except FileNotFoundError:
        return None
    except OSError as e:
        return ("error", type(e).__name__)
    return (st.st_mtime_ns, st.st_size)


_lock = threading.Lock()
_cache: tuple | None = None
_last_good: Hardware | None = None


def _reset_cache() -> None:
    global _cache, _last_good
    with _lock:
        _cache, _last_good = None, None


def _fresh(ov: Path, ov_present: bool) -> Hardware:
    global _last_good
    where_b = str(BUNDLED)
    try:
        base_root, warnings = _parse(_read(BUNDLED, where_b), where_b)
        base = _elements(base_root, where_b)
    except HardwareError as e:          # a packaging bug: keep what we had, else generic records only
        return (_last_good or Hardware()).with_errors(e.errors)
    errors: list[str] = []
    hw = None
    if ov_present:
        where_o = str(ov)
        try:
            over_root, over_warnings = _parse(_read(ov, where_o), where_o)
            hw = _build(_merge(base, _elements(over_root, where_o)), where_o)
            warnings = warnings + over_warnings
        except HardwareError as e:
            errors = e.errors
            if _last_good is not None:
                return _last_good.with_errors(errors)
    if hw is None:
        try:
            hw = _build(base, where_b)
        except HardwareError as e:
            return (_last_good or Hardware()).with_errors(errors + e.errors)
    _last_good = hw.with_errors([], warnings)
    return hw.with_errors(errors, warnings)


def load() -> Hardware:
    """The merged hardware facts; rebuilt when the bundled file or the override changes (mtime or size)."""
    global _cache
    ov = override_path()
    key = (str(ov), _stamp(BUNDLED), _stamp(ov))
    with _lock:
        if _cache is not None and _cache[0] == key:
            return _cache[1]
        hw = _fresh(ov, key[2] is not None)
        _cache = (key, hw)
        return hw
