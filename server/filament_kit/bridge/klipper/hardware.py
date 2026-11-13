"""Klipper/Moonraker printer facts from `klipper_hardware.xml`: filament systems, models, speech words.

The bundled file (package data next to this module) is the default; an optional override at
`/etc/filament-kit/klipper_hardware.xml` (`$FK_ETC`) wins per element (a `<system>` or `<model>` by `key`, a speech
`<word>` by `text`) when its root version is above the bundled file's. Loading, validation and the override rules are
`bridge.xmlfile`'s (the same as `bambu_hardware.xml`): a bad override keeps the last good data and `Hardware.errors`
says why. Nothing about a printer model lives in code.

Interfaces
----------
`load() -> Hardware` (cached; rebuilt when either file changes).
`Hardware.model(key) -> Model` (unknown key: the `generic` model), `Hardware.system(key) -> System` (KeyError),
`Hardware.say(label) -> list[str]`, `.errors`, `.warnings`, `.models` (dict in file order), `.systems`.
`fill(template, **values) -> str`: a gcode template with its placeholders filled; ValueError for an unknown
placeholder or an unsafe value (Global Constraints of the plan: lane/gate names `[A-Za-z0-9_]{1,32}`, tool/spool
non-negative ints).
`validate(data, where) -> list[str]`, `file_version(data)`, `override_path()`, `BUNDLED`, `MAX_BYTES`, `_reset_cache()`.
"""
from __future__ import annotations

import re
import string
from dataclasses import dataclass
from pathlib import Path

from ... import config
from .. import xmlfile

BUNDLED = Path(__file__).with_name("klipper_hardware.xml")
OVERRIDE_NAME = "klipper_hardware.xml"
MAJOR = "1"
MAX_BYTES = 256_000
ADAPTERS = ("single", "toolchanger", "afc", "happyhare", "lanedata")
PLACEHOLDERS = {"spool", "tool", "lane", "gate"}
NAME = re.compile(r"[A-Za-z0-9_]{1,32}")
_GCODE_LINE = re.compile(r"[ -~]{1,200}")       # one printable ASCII line


class KlipperHardwareError(xmlfile.XmlError):
    pass


def override_path() -> Path:
    return config.paths().etc / OVERRIDE_NAME


# --- records ------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class System:
    key: str
    adapter: str
    set_gcode: str | None = None
    clear_gcode: str | None = None
    detect_object: str | None = None
    detect_namespace: str | None = None
    spool_var_macro: str | None = None
    spool_var: str | None = None


@dataclass(frozen=True)
class Slot:
    n: int
    label: str
    say: str | None = None


@dataclass(frozen=True)
class Orca:
    nozzle: str
    printer: str


@dataclass(frozen=True)
class Model:
    key: str
    name: str
    say: str | None = None
    system: str = "auto"
    verified: bool = True
    detect_objects: tuple = ()
    detect_namespaces: tuple = ()
    detect_hostnames: tuple = ()
    slots: tuple = ()
    orca: tuple = ()
    light_on: str | None = None
    light_off: str | None = None


GENERIC = Model("generic", "Klipper printer", "printer", "auto", True)


def _placeholders(t: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(t) if f is not None}


def _template(v: str) -> str:
    """A gcode template: one printable line, known placeholders only."""
    v = v.strip()
    if not _GCODE_LINE.fullmatch(v):
        raise ValueError("must be one line of printable text (at most 200 characters)")
    try:
        names = _placeholders(v)
    except ValueError as e:
        raise ValueError(f"has a broken placeholder ({e})") from None
    unknown = names - PLACEHOLDERS
    if unknown:
        raise ValueError(f"has unknown placeholder(s) {', '.join(sorted(unknown))} "
                         f"(allowed: {', '.join(sorted(PLACEHOLDERS))})")
    return v


def _plain(v: str) -> str:
    """A gcode line with nothing to fill in (light on / off)."""
    v = _template(v)
    if _placeholders(v):
        raise ValueError("may not have placeholders")
    return v


def fill(template: str, **values) -> str:
    """The template with its placeholders filled; refuses anything that could change the gcode's meaning."""
    names = _placeholders(template)
    unknown = names - PLACEHOLDERS
    if unknown:
        raise ValueError(f"unknown placeholder(s) {', '.join(sorted(unknown))}")
    safe = {}
    for k in names:
        if k not in values:
            raise ValueError(f"no value for {{{k}}}")
        v = values[k]
        if k in ("tool", "spool"):
            if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                raise ValueError(f"{k} must be a whole number of 0 or more")
        elif not (isinstance(v, str) and NAME.fullmatch(v)):
            raise ValueError(f"{k} {v!r} may only have letters, digits and _ (at most 32)")
        safe[k] = v
    return template.format(**safe)


# --- the validator ------------------------------------------------------------------------------------------------

_GCODE = xmlfile.E(text=True, text_check=_template)
_DETECT_TEXT = xmlfile.E(text=True)
_SLOT = xmlfile.E(attrs={"label": xmlfile.text, "say": xmlfile.text}, required=("label",))
_SCHEMA = xmlfile.E(
    attrs={"version": xmlfile.text}, required=("version",), once=("filament-systems", "models", "speech"),
    children={
        "filament-systems": xmlfile.E(children={"system": xmlfile.E(
            attrs={"key": xmlfile.text, "adapter": xmlfile.enum(*ADAPTERS), "detect-object": xmlfile.text,
                   "detect-namespace": xmlfile.text},
            required=("key", "adapter"), once=("set-gcode", "clear-gcode", "spool-var"),
            children={"set-gcode": _GCODE, "clear-gcode": _GCODE,
                      "spool-var": xmlfile.E(attrs={"macro": xmlfile.text, "var": _template},
                                             required=("macro", "var"))})}),
        "models": xmlfile.E(children={"model": xmlfile.E(
            attrs={"key": xmlfile.text, "name": xmlfile.text, "say": xmlfile.text, "system": xmlfile.text,
                   "verified": xmlfile.boolean},
            required=("key", "name"), once=("detect", "light"),
            children={
                "detect": xmlfile.E(children={"object": _DETECT_TEXT, "namespace": _DETECT_TEXT,
                                              "hostname": _DETECT_TEXT}),
                "slot": _SLOT,
                "tool": xmlfile.E(attrs={"n": xmlfile.nonneg, "label": xmlfile.text, "say": xmlfile.text},
                                  required=("n", "label")),
                "orca": xmlfile.E(attrs={"nozzle": xmlfile.text, "printer": xmlfile.text},
                                  required=("nozzle", "printer")),
                "light": xmlfile.E(attrs={"on": _plain, "off": _plain}, required=("on", "off")),
            })}),
        "speech": xmlfile.E(children={"word": xmlfile.E(attrs={"text": xmlfile.text, "say": xmlfile.text},
                                                        required=("text", "say"))}),
    })
_SECTIONS = {
    "filament-systems": ("system", "key", False),
    "models": ("model", "key", False),
    "speech": ("word", "text", True),
}
_LABEL = re.compile(r"[A-Za-z0-9-]{1,16}")    # api.LABEL: a slot label must fit the load/unload route


def _parse(data: bytes, where: str):
    return xmlfile.parse(data, where, root_tag="klipper-hardware", schema=_SCHEMA, major=MAJOR,
                         max_bytes=MAX_BYTES, err=KlipperHardwareError)


def _elements(root, where: str) -> dict[str, dict]:
    return xmlfile.elements(root, _SECTIONS, where, KlipperHardwareError)


def _opt(el, tag: str, attr: str | None = None) -> str | None:
    c = el.find(tag)
    if c is None:
        return None
    return (c.get(attr) if attr else (c.text or "")).strip() or None


def _build(sections: dict[str, dict], where: str) -> "Hardware":
    errors: list[str] = []
    systems: dict[str, System] = {}
    for key, el in sections["filament-systems"].items():
        sv = el.find("spool-var")
        systems[key] = System(key, el.get("adapter"), _opt(el, "set-gcode"), _opt(el, "clear-gcode"),
                              el.get("detect-object"), el.get("detect-namespace"),
                              sv.get("macro") if sv is not None else None, sv.get("var") if sv is not None else None)
        if el.get("adapter") == "toolchanger" and sv is None:
            errors.append(f"system {key!r}: adapter toolchanger needs <spool-var>")
        if el.get("adapter") not in ("lanedata",) and systems[key].set_gcode is None:
            errors.append(f"system {key!r}: needs <set-gcode>")
    models: dict[str, Model] = {}
    for key, el in sections["models"].items():
        system = el.get("system", "auto")
        if system != "auto" and system not in systems:
            errors.append(f"model {key!r}: system {system!r} is not a <system> key")
        det = el.find("detect")
        objs = tuple((o.text or "").strip() for o in det.findall("object")) if det is not None else ()
        nss = tuple((o.text or "").strip() for o in det.findall("namespace")) if det is not None else ()
        hosts = tuple((o.text or "").strip() for o in det.findall("hostname")) if det is not None else ()
        slots = [Slot(i, s.get("label").strip(), s.get("say")) for i, s in enumerate(el.findall("slot"))]
        slots += [Slot(int(t.get("n")), t.get("label").strip(), t.get("say")) for t in el.findall("tool")]
        labels = [s.label for s in slots]
        for s in slots:
            if not _LABEL.fullmatch(s.label):
                errors.append(f"model {key!r}: slot label {s.label!r} may only have letters, digits and - "
                              f"(at most 16)")
        if len(set(labels)) != len(labels) or len({s.n for s in slots}) != len(slots):
            errors.append(f"model {key!r}: a slot label or tool number is given twice")
        light = el.find("light")
        models[key] = Model(
            key, el.get("name").strip(), el.get("say"), system, el.get("verified", "true") == "true",
            objs, nss, hosts, tuple(sorted(slots, key=lambda s: s.n)),
            tuple(Orca(o.get("nozzle").strip(), o.get("printer").strip()) for o in el.findall("orca")),
            light.get("on") if light is not None else None, light.get("off") if light is not None else None)
    if "generic" not in models:
        models["generic"] = GENERIC
    words = {k: el.get("say") for k, el in sections["speech"].items()}
    if errors:
        raise KlipperHardwareError([f"{where}: {e}" for e in errors])
    return Hardware(models, systems, words)


class Hardware:
    """The merged Klipper printer facts. Build with `load()`."""

    def __init__(self, models=None, systems=None, words=None, errors=None, warnings=None):
        self.models: dict[str, Model] = dict(models or {"generic": GENERIC})
        self.systems: dict[str, System] = dict(systems or {})
        self.words: dict[str, str] = dict(words or {})
        self.errors: list[str] = list(errors or [])
        self.warnings: list[str] = list(warnings or [])

    def with_errors(self, errors: list[str], warnings: list[str] | None = None) -> "Hardware":
        return Hardware(self.models, self.systems, self.words, errors,
                        self.warnings if warnings is None else warnings)

    def model(self, key: str | None) -> Model:
        return self.models.get((key or "").strip()) or self.models.get("generic") or GENERIC

    def system(self, key: str) -> System:
        return self.systems[key]

    def say(self, label: str) -> list[str]:
        w = self.words.get((label or "").strip().upper())
        if w:
            return [w]
        return [t.lower() for t in re.findall(r"[A-Za-z]+|\d+", label or "")]


def validate(data: bytes, where: str = "klipper_hardware.xml") -> list[str]:
    """Problems with a complete file (empty list = good)."""
    try:
        root, _warnings = _parse(data, where)
        _build(_elements(root, where), where)
    except KlipperHardwareError as e:
        return e.errors
    return []


file_version = xmlfile.file_version

_loader = xmlfile.Cached(BUNDLED, lambda: override_path(), parse=lambda d, w: _parse(d, w),
                         elements=lambda r, w: _elements(r, w), build=lambda s, w: _build(s, w),
                         empty=lambda: Hardware(), max_bytes=MAX_BYTES, err=KlipperHardwareError)


def _reset_cache() -> None:
    _loader.reset()


def load() -> Hardware:
    _loader.bundled = BUNDLED
    return _loader.load()
