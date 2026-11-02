"""Bambu Studio system filament presets (`system/BBL/filament`, uploaded by the PC sync): load, resolve, query.

A system preset is only ever the template a generated preset is flattened from, never a slot's preset.
`merge` and `Store.resolve` are ports of the owner's `gen.merge` / `gen.resolve_bs_system`: the `inherits`
chain, then the `include` templates, then the preset's own keys; a child list value "nil" keeps the parent's
value at that position when both lists have the same length.

Presets are keyed by file name without `.json`, as Bambu Studio and `gen.py` refer to them.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

STD = "Direct Drive Standard"
HF = "Direct Drive High Flow"


class BblError(Exception):
    """A system preset that cannot be resolved: unknown name, missing parent or include, or a cycle."""


def merge(child: dict, parent: dict) -> dict:
    out = dict(parent)
    for k, v in child.items():
        if isinstance(v, list) and isinstance(parent.get(k), list) and len(parent[k]) == len(v):
            out[k] = [pv if cv == "nil" else cv for cv, pv in zip(v, parent[k])]
        else:
            out[k] = v
    return out


def _first(v) -> str | None:
    if isinstance(v, list):
        return str(v[0]) if v else None
    return None if v is None else str(v)


class Store:
    def __init__(self, presets: dict[str, dict] | None = None, problems: list[str] | None = None):
        self._raw: dict[str, dict] = dict(presets or {})
        self.problems: list[str] = list(problems or [])
        self._cache: dict[str, dict] = {}

    @classmethod
    def load(cls, folder: Path) -> "Store":
        folder = Path(folder)
        presets: dict[str, dict] = {}
        problems: list[str] = []
        if not folder.is_dir():
            return cls(presets, problems)
        files = sorted((p for p in folder.rglob("*") if p.is_file() and p.suffix.casefold() == ".json"),
                       key=lambda p: p.relative_to(folder).as_posix())
        for p in files:
            rel = p.relative_to(folder).as_posix()
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, ValueError) as e:
                problems.append(f"{rel}: unreadable ({e.__class__.__name__}: {e})")
                continue
            if not isinstance(data, dict):
                problems.append(f"{rel}: not a JSON object")
                continue
            name = p.stem
            if name in presets:
                problems.append(f"{rel}: duplicate preset name {name!r}, ignored")
                continue
            presets[name] = data
        return cls(presets, problems)

    # ---------- lookup ----------
    def names(self) -> set[str]:
        return set(self._raw)

    def resolve(self, name: str) -> dict:
        return copy.deepcopy(self._resolve(name, ()))

    def _resolve(self, name: str, stack: tuple[str, ...]) -> dict:
        if name in self._cache:
            return self._cache[name]
        if name in stack:
            raise BblError(f"inheritance cycle: {' -> '.join(stack + (name,))}")
        if name not in self._raw:
            if stack:
                raise BblError(f"{stack[-1]!r} refers to missing system preset {name!r}")
            raise BblError(f"unknown system preset {name!r}")
        j = self._raw[name]
        here = stack + (name,)
        cfg = self._resolve(j["inherits"], here) if j.get("inherits") else {}
        for inc in j.get("include") or []:
            cfg = merge(self._resolve(inc, here), cfg)
        cfg = merge(j, cfg)
        cfg.pop("include", None)
        self._cache[name] = cfg
        return cfg

    def _try(self, name: str) -> dict | None:
        try:
            return self._resolve(name, ())
        except BblError:
            return None

    @staticmethod
    def base_name(name: str) -> str:
        return name.split(" @", 1)[0]

    def _instantiable(self) -> list[str]:
        return sorted(n for n, j in self._raw.items() if j.get("instantiation") == "true")

    def bases(self, material: str | None = None) -> list[str]:
        out = set()
        for n in self._instantiable():
            cfg = self._try(n)
            if cfg is None:
                continue
            if material is not None and _first(cfg.get("filament_type")) != material:
                continue
            out.add(self.base_name(n))
        return sorted(out)

    def vendor_bases(self, vendor: str, bs_type: str) -> list[str]:
        want = (vendor or "").casefold()
        out = set()
        for n in self._instantiable():
            cfg = self._try(n)
            if cfg is None:
                continue
            if (_first(cfg.get("filament_vendor")) or "").casefold() == want \
                    and _first(cfg.get("filament_type")) == bs_type:
                out.add(self.base_name(n))
        return sorted(out)

    def _with_base(self, base: str) -> list[tuple[str, dict]]:
        out = []
        for n in self._instantiable():
            if self.base_name(n) == base:
                cfg = self._try(n)
                if cfg is not None:
                    out.append((n, cfg))
        return out

    @staticmethod
    def _compatible(cfg: dict) -> list[str]:
        v = cfg.get("compatible_printers")
        return [str(x) for x in v] if isinstance(v, list) else []

    def parent_for(self, base: str, printer: str, nozzle: str) -> str | None:
        target = f"{printer} {nozzle} nozzle"
        hits = [n for n, cfg in self._with_base(base) if target in self._compatible(cfg)]
        if not hits:
            return None
        return min(hits, key=lambda n: (not n.endswith(f" {nozzle} nozzle"), len(n), n))

    def nozzles_for(self, base: str, printer: str) -> list[str]:
        pat = re.compile(re.escape(printer) + r" (\d+(?:\.\d+)?) nozzle")
        sizes: dict[float, str] = {}
        for _n, cfg in self._with_base(base):
            for cp in self._compatible(cfg):
                m = pat.fullmatch(cp)
                if m:
                    sizes.setdefault(float(m.group(1)), m.group(1))
        return [sizes[k] for k in sorted(sizes)]

    def variants(self, name: str) -> list[str]:
        v = self.resolve(name).get("filament_extruder_variant")
        if isinstance(v, list) and v:
            return [str(x) for x in v]
        return [STD]

    def gcode_values(self) -> set[str]:
        out = set()
        for j in self._raw.values():
            for k, v in j.items():
                if "gcode" in k:
                    out.add(json.dumps(v, sort_keys=True))
        return out
