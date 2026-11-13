"""Shared pieces of the kit's printer data files (`bambu_hardware.xml`, `klipper_hardware.xml`).

Each file has a bundled default (package data) and an optional override in `/etc/filament-kit` that wins per
element. Files are parsed with defusedxml (no DTD, no entities, no external references) and checked by a validator
in code (`E` specs: allowed attributes with checkers, required attributes, child elements, text). Unknown elements
and attributes are warnings; anything else is an error and refuses the whole file. An override is applied only when
its root `version` is above the bundled file's (Ruling BT); a bad override keeps the last good data (`Cached`).

Interfaces
----------
`E(attrs, required, children, text, once)`: the validator spec of one element.
Checkers: `integer`, `pos`, `nonneg`, `boolean`, `text`, `enum(*allowed)`: return the parsed value or raise ValueError.
`check(el, spec, path, errors, warnings)`: validate an element tree against a spec.
`parse(data, where, *, root_tag, schema, major, max_bytes, err) -> (root, warnings)`: raises `err(errors)`.
`elements(root, sections, where, err) -> {section: {identity: element}}`: `sections` = {section: (tag, identity
attribute, case-insensitive)}; an identity given twice is an error.
`merge(base, over)`, `root_version(root)`, `file_version(data)`, `vtext(v)`, `stamp(path)`, `read_capped(...)`.
`Cached(...)`: the reread-on-change loader with the override rules; `.load()`, `.reset()`.
"""
from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import defusedxml.ElementTree as DET


_INVALID_XML = re.compile("[^\u0009\u000a\u000d -퟿-�\U00010000-\U0010ffff]")


def clean(value) -> str:
    """`value` as text XML 1.0 can hold: characters it forbids (most control characters, U+FFFE/FFFF, lone
    surrogates) are dropped. Every kit XML writer passes outside strings (printer names from SSDP / mDNS, file
    names from Moonraker) through this, or one stray byte would make the whole file unreadable."""
    return _INVALID_XML.sub("", "" if value is None else str(value))


class XmlError(Exception):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


# --- value checkers -------------------------------------------------------------------------------------------------

_INT_RE = re.compile(r"-?\d{1,9}")


def integer(v: str) -> int:
    if not _INT_RE.fullmatch(v):
        raise ValueError("is not an integer")
    return int(v)


def pos(v: str) -> int:
    n = integer(v)
    if n < 1:
        raise ValueError("is not a positive integer")
    return n


def nonneg(v: str) -> int:
    n = integer(v)
    if n < 0:
        raise ValueError("is negative")
    return n


def boolean(v: str) -> bool:
    if v not in ("true", "false"):
        raise ValueError("is not true or false")
    return v == "true"


def text(v: str) -> str:
    if not v.strip():
        raise ValueError("is empty")
    return v.strip()


def enum(*allowed):
    def f(v: str) -> str:
        if v not in allowed:
            raise ValueError(f"is not one of {', '.join(allowed)}")
        return v
    return f


# --- the validator --------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class E:
    attrs: dict = field(default_factory=dict)        # name -> checker
    required: tuple = ()
    children: dict = field(default_factory=dict)     # tag -> E
    text: bool = False                               # element carries text (checked non-empty)
    once: tuple = ()                                 # child tags allowed at most once
    ignored: tuple = ()                              # child tags of an older file format: skipped without a warning
    text_check: Callable[[str], object] | None = None   # extra check of the text (raise ValueError)


TEXT = E(text=True)
VERSION = re.compile(r"(\d{1,4})(?:\.(\d{1,4}))?")


def where(el, path: str) -> str:
    ident = el.get("code") or el.get("key") or el.get("text")
    return f"{path} {ident!r}" if ident else path


def check(el, spec: E, path: str, errors: list[str], warnings: list[str]) -> None:
    """Fatal problems go to errors; unknown attributes and elements (a newer file) go to warnings and are ignored."""
    for name, value in el.attrib.items():
        checker = spec.attrs.get(name)
        if checker is None:
            warnings.append(f"{where(el, path)}: unknown attribute {name!r} ignored")
            continue
        try:
            checker(value)
        except ValueError as e:
            errors.append(f"{where(el, path)}: {name}={value!r} {e}")
    for name in spec.required:
        if name not in el.attrib:
            errors.append(f"{where(el, path)}: missing required attribute {name!r}")
    if spec.text:
        if not (el.text or "").strip():
            errors.append(f"{path}: empty text")
        elif spec.text_check is not None:
            try:
                spec.text_check(el.text)
            except ValueError as e:
                errors.append(f"{path}: {e}")
    elif (el.text or "").strip():
        errors.append(f"{where(el, path)}: unexpected text {(el.text or '').strip()[:20]!r}")
    seen: dict[str, int] = {}
    for child in el:
        if not isinstance(child.tag, str):
            continue
        sub = spec.children.get(child.tag)
        if sub is None and child.tag in spec.ignored:
            continue
        if sub is None:
            warnings.append(f"{where(el, path)}: unknown element <{child.tag}> ignored")
            continue
        seen[child.tag] = seen.get(child.tag, 0) + 1
        if child.tag in spec.once and seen[child.tag] == 2:
            errors.append(f"{where(el, path)}: <{child.tag}> given twice")
        if (child.tail or "").strip():
            errors.append(f"{where(el, path)}: unexpected text after <{child.tag}>")
        check(child, sub, f"{path}/{child.tag}", errors, warnings)


def fromstring(data: bytes):
    return DET.fromstring(data, forbid_dtd=True, forbid_entities=True, forbid_external=True)


def parse(data: bytes, where_: str, *, root_tag: str, schema: E, major: str, max_bytes: int,
          err: type[XmlError] = XmlError):
    """(root element, warnings) of a well-formed, schema-valid file, or `err`."""
    if len(data) > max_bytes:
        raise err([f"{where_}: larger than {max_bytes} bytes"])
    try:
        root = fromstring(data)
    except Exception as e:  # ParseError, DTDForbidden, EntitiesForbidden, ...
        raise err([f"{where_}: parse error: {type(e).__name__}: {e}"]) from None
    if root.tag != root_tag:
        raise err([f"{where_}: root element is <{root.tag}>, not <{root_tag}>"])
    errors: list[str] = []
    warnings: list[str] = []
    check(root, schema, root_tag, errors, warnings)
    v = root.get("version")
    if v is not None:
        m = VERSION.fullmatch(v.strip())
        if not m or m.group(1).lstrip("0") != major:
            errors.append(f"{root_tag}: version {v!r} not supported (this server reads version {major}.x)")
    if errors:
        raise err([f"{where_}: {e}" for e in errors])
    return root, [f"{where_}: {w}" for w in warnings]


def elements(root, sections: dict[str, tuple[str, str, bool]], where_: str,
             err: type[XmlError] = XmlError) -> dict[str, dict]:
    """section -> {identity: element} in file order; an identity given twice in one file is an error."""
    out: dict[str, dict] = {}
    errors = []
    for section, (tag, ident, fold) in sections.items():
        found: dict = {}
        for sec in root.findall(section):
            for el in sec.findall(tag):
                k = el.get(ident, "")
                k = k.strip().upper() if fold else k.strip()
                if k in found:
                    errors.append(f"{where_}: <{tag} {ident}={el.get(ident)!r}> given twice")
                found[k] = el
        out[section] = found
    if errors:
        raise err(errors)
    return out


def merge(base: dict[str, dict], over: dict[str, dict]) -> dict[str, dict]:
    return {section: {**base[section], **over.get(section, {})} for section in base}


def root_version(root) -> tuple[int, int] | None:
    m = VERSION.fullmatch((root.get("version") or "").strip())
    return (int(m.group(1)), int(m.group(2) or 0)) if m else None


def file_version(data: bytes) -> tuple[int, int] | None:
    """(major, minor) of a data file's root `version` ("1" is (1, 0)); None when it has none or cannot be parsed."""
    try:
        root = fromstring(data)
    except Exception:  # noqa: BLE001 - ParseError, DTDForbidden, ...
        return None
    return root_version(root)


def vtext(v: tuple[int, int]) -> str:
    return f"{v[0]}.{v[1]}"


def stamp(p: Path):
    try:
        st = os.stat(p)
    except FileNotFoundError:
        return None
    except OSError as e:
        return ("error", type(e).__name__)
    return (st.st_mtime_ns, st.st_size)


def read_capped(p: Path, where_: str, max_bytes: int, err: type[XmlError] = XmlError) -> bytes:
    try:
        with open(p, "rb") as f:
            data = f.read(max_bytes + 1)
    except OSError as e:
        raise err([f"{where_}: cannot read: {e.strerror or e}"]) from None
    return data


class Cached:
    """Rebuilds the data when the bundled file or the override changes (mtime or size).

    `parse(data, where) -> (root, warnings)` and `elements(root, where) -> sections` validate; `build(sections, where)`
    makes the result object, which has `with_errors(errors, warnings=None)`; `empty()` is the generic-only result used
    when even the bundled file is broken. All of them raise `err` (an XmlError subclass)."""

    def __init__(self, bundled: Path, override: Callable[[], Path], *, parse: Callable, elements: Callable,
                 build: Callable, empty: Callable, max_bytes: int, err: type[XmlError] = XmlError):
        self.bundled, self.override = bundled, override
        self._parse, self._elements, self._build, self._empty = parse, elements, build, empty
        self.max_bytes, self.err = max_bytes, err
        self._lock = threading.Lock()
        self._cache: tuple | None = None
        self._last_good = None

    def reset(self) -> None:
        with self._lock:
            self._cache, self._last_good = None, None

    def _fresh(self, ov: Path, ov_present: bool):
        where_b = str(self.bundled)
        try:
            base_root, warnings = self._parse(read_capped(self.bundled, where_b, self.max_bytes, self.err), where_b)
            base = self._elements(base_root, where_b)
        except self.err as e:          # a packaging bug: keep what we had, else generic records only
            return (self._last_good or self._empty()).with_errors(e.errors)
        errors: list[str] = []
        result = None
        if ov_present:
            where_o = str(ov)
            try:
                over_root, over_warnings = self._parse(read_capped(ov, where_o, self.max_bytes, self.err), where_o)
                merged = self._build(merge(base, self._elements(over_root, where_o)), where_o)
                base_v, over_v = root_version(base_root), root_version(over_root)
                if base_v is not None and (over_v is None or over_v <= base_v):
                    # a feed file left behind after an upgrade, or a hand-made one that never bumped its version:
                    # applying it would shadow newer bundled data per element (final review I2, Ruling BT)
                    warnings = warnings + [
                        f"{where_o}: override version {over_root.get('version', '').strip()} is not newer than "
                        f"the kit's own {base_root.get('version', '').strip()}: ignored (give it a version above "
                        f"{vtext(base_v)} to use it)"]
                else:
                    result = merged
                    warnings = warnings + over_warnings
            except self.err as e:
                errors = e.errors
                if self._last_good is not None:
                    return self._last_good.with_errors(errors)
        if result is None:
            try:
                result = self._build(base, where_b)
            except self.err as e:
                return (self._last_good or self._empty()).with_errors(errors + e.errors)
        self._last_good = result.with_errors([], warnings)
        return result.with_errors(errors, warnings)

    def load(self):
        ov = self.override()
        key = (str(ov), stamp(self.bundled), stamp(ov))
        with self._lock:
            if self._cache is not None and self._cache[0] == key:
                return self._cache[1]
            result = self._fresh(ov, key[2] is not None)
            self._cache = (key, result)
            return result
