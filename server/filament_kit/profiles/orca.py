"""Orca Slicer system filament presets (the PC sync's `orca_system` upload, Ruling L): load and query.

Orca 2.5.0 packs its vendor profiles into `.opc` bundles, so the upload has two parts:
  BBL/filament/**.json            Orca's unpacked `%APPDATA%\\OrcaSlicer\\system\\BBL\\filament\\` (same JSON shape as
                                  Bambu Studio's system presets; resolved with `bbl.Store`, inherits within BBL)
  OrcaFilamentLibrary/index.json  {"version": 1, "source": str, "presets": [{name, setting_id, filament_id,
                                  filament_type, inherits}]}, extracted by the PC sync from OrcaFilamentLibrary.opc
Library presets are names only (`"<base> @System"`): an Orca preset inherits them, nothing is flattened.

A broken file or index row is a problem in `problems`, never an exception: one bad upload never breaks the store.
"""
from __future__ import annotations

import collections
import copy
import json
import re
from pathlib import Path

from .bbl import STD, Store

BBL_DIR = ("BBL", "filament")
INDEX = ("OrcaFilamentLibrary", "index.json")
INDEX_VERSION = 1
SYSTEM = " @System"
_TEXT_KEYS = ("setting_id", "filament_id", "filament_type", "inherits")


def _index_rel() -> str:
    return "/".join(INDEX)


class OrcaStore:
    def __init__(self, bbl: Store | None = None, library: dict[str, dict] | None = None,
                 problems: list[str] | None = None):
        self.bbl = bbl if bbl is not None else Store()
        self.library: dict[str, dict] = dict(library or {})
        self._problems: list[str] = list(problems or [])
        self._variants: dict[str, list[str]] = {}

    # ---------- loading ----------
    @classmethod
    def load(cls, folder: Path) -> "OrcaStore":
        return cls.parse(cls.read(folder))

    @staticmethod
    def read(folder: Path) -> dict:
        """The raw files (cheap I/O only, so a caller can do it under a lock): `bbl` = `Store.read` of
        BBL/filament, `index` = the index bytes, an OSError, or None when there is no index."""
        folder = Path(folder)
        path = folder.joinpath(*INDEX)
        try:
            index: bytes | OSError | None = path.read_bytes()
        except FileNotFoundError:
            index = None
        except OSError as e:
            index = e
        return {"bbl": Store.read(folder.joinpath(*BBL_DIR)), "index": index}

    @classmethod
    def parse(cls, raw: dict) -> "OrcaStore":
        bbl = Store.parse(raw.get("bbl") or [])
        bbl.problems = [f"{'/'.join(BBL_DIR)}/{p}" for p in bbl.problems]
        library, problems = cls._parse_index(raw.get("index"))
        return cls(bbl, library, problems)

    @staticmethod
    def _parse_index(raw) -> tuple[dict[str, dict], list[str]]:
        rel = _index_rel()
        if raw is None:
            return {}, []
        try:
            if isinstance(raw, OSError):
                raise raw
            data = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, ValueError, RecursionError) as e:
            return {}, [f"{rel}: unreadable ({e.__class__.__name__})"]
        if not isinstance(data, dict) or data.get("version") != INDEX_VERSION \
                or not isinstance(data.get("presets"), list):
            return {}, [f"{rel}: not a version {INDEX_VERSION} index with a presets list"]
        out: dict[str, dict] = {}
        problems: list[str] = []
        for i, row in enumerate(data["presets"]):
            name = row.get("name") if isinstance(row, dict) else None
            if not (isinstance(name, str) and name.strip()):
                problems.append(f"{rel}: preset {i} has no name, ignored")
                continue
            bad = [k for k in _TEXT_KEYS if not (row.get(k) is None or isinstance(row.get(k), str))]
            if bad:
                problems.append(f"{rel}: {name!r}: {', '.join(bad)} must be text or null, ignored")
                continue
            if name in out:
                problems.append(f"{rel}: duplicate preset name {name!r}, ignored")
                continue
            out[name] = {"name": name, **{k: row.get(k) for k in _TEXT_KEYS}}
        return out, problems

    @property
    def problems(self) -> list[str]:
        """The BBL store's problems (files, and presets that failed to resolve so far) and the index's."""
        return list(self.bbl.problems) + self._problems

    def __bool__(self) -> bool:
        return bool(self.names())

    # ---------- lookup ----------
    def names(self) -> set[str]:
        return self.bbl.names() | set(self.library)

    def library_names(self) -> set[str]:
        return set(self.library)

    def parent(self, name: str) -> dict | None:
        """A library preset's index row, or a BBL preset resolved through its inherits chain (a copy); None when
        unknown or unresolvable."""
        if name in self.library:
            return dict(self.library[name])
        if name not in self.bbl.names():
            return None
        cfg = self.bbl._try(name)
        return copy.deepcopy(cfg) if cfg is not None else None

    def system_parent_for(self, printer: str, nozzle: str, base: str) -> str | None:
        """The BBL system preset of `base` for `printer` ("Bambu Lab H2D") and `nozzle` ("0.4"), as Orca names it
        (`Bambu PLA Basic @BBL H2D` lists "Bambu Lab H2D 0.4 nozzle", the 0.6 one is `... @BBL H2D 0.6 nozzle`);
        None when no instantiable preset of that base lists that printer and nozzle."""
        return self.bbl.parent_for(base, printer, nozzle)

    def printer_variants(self, printer: str) -> list[str]:
        """The extruder variants Orca's BBL presets give `printer` (e.g. H2D: Standard + High Flow): the most
        common `filament_extruder_variant` among presets compatible with one of its nozzles; [STD] for a printer
        no BBL preset lists (a non-Bambu printer such as the SV08 MAX)."""
        if printer in self._variants:
            return list(self._variants[printer])
        pat = re.compile(re.escape(printer) + r" \d+(?:\.\d+)? nozzle")
        seen: collections.Counter = collections.Counter()
        for n in self.bbl._instantiable():
            cfg = self.bbl._try(n)
            if cfg is None or not any(pat.fullmatch(cp) for cp in self.bbl._compatible(cfg)):
                continue
            v = cfg.get("filament_extruder_variant")
            seen[tuple(str(x) for x in v) if isinstance(v, list) and v else (STD,)] += 1
        if not seen:
            out = [STD]
        else:
            out = list(min(seen, key=lambda t: (-seen[t], -len(t), t)))
        self._variants[printer] = out
        return list(out)
