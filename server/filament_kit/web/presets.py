"""Preset-line tools for the web process (ops regen.py's status / list_lines / find_parents / add_ids / add_line /
generate), on the kit's own `profiles/`.

Kit lines differ from ops in one way that matters here: every Spoolman filament joins a line by itself at the next
build (`lines.group`, by the product in its name or its `extra.line`). So "uncovered" filaments are only those the
lines file does not record yet, and `add_filaments_to_line` / `add_line` are for when the automatic line is wrong.
A filament put in a line here also gets `extra.line` = that line's product in Spoolman, so the next grouping keeps it
there. Builds run in filament-kit-build.service: `generate` requests one (the same request a phone or the PC sync
makes) and returns at once.
"""
from __future__ import annotations

import json

from .. import library as library_mod
from ..profiles import builds, lines as lines_mod
from .errors import Problem as PresetProblem

MAX_PARENTS = 60


def _name(line) -> str:
    return f"{line.vendor} {line.product}".strip()


def _resolve(ls: dict, line: str):
    """A line by its line_id or its '<vendor> <product>' name (case-insensitive)."""
    key = (line or "").strip()
    if key in ls:
        return ls[key]
    want = key.casefold()
    for ln in ls.values():
        if _name(ln).casefold() == want:
            return ln
    raise PresetProblem(f"no preset line {line!r}: list_lines shows the lines (name or line_id)")


def _members(ls: dict) -> dict[int, str]:
    out: dict[int, str] = {}
    for ln in sorted(ls.values(), key=lambda l: l.line_id):
        for i in ln.filaments:
            out.setdefault(i, ln.line_id)
    return out


def _vendor(f: dict) -> str:
    return ((f.get("vendor") or {}).get("name") or "").strip()


def status(sm) -> dict:
    """Filaments no line records yet (with the lines of their brand), the last build and the PC's install."""
    ls = lines_mod.load()
    known = _members(ls)
    by_vendor: dict[str, list[str]] = {}
    for ln in ls.values():
        by_vendor.setdefault(ln.vendor.casefold(), []).append(_name(ln))
    uncovered = []
    for f in sm.get("filament"):
        if f.get("archived") or f.get("id") in known or not _vendor(f):
            continue
        uncovered.append({"id": f["id"], "vendor": _vendor(f), "name": f.get("name"), "material": f.get("material"),
                          "lines_for_vendor": sorted(by_vendor.get(_vendor(f).casefold(), []))})
    st = builds.status()
    build = st.get("build") or {}
    installed = st.get("installed") or {}
    return {"uncovered_filaments": uncovered, "lines": len(ls),
            "last_build": build.get("stamp"), "installed_build": installed.get("stamp"),
            "waiting_for_desktop": bool(build.get("stamp")) and build.get("stamp") != installed.get("stamp"),
            "presets": st.get("presets"), "problems": st.get("problems", []),
            "pc_waiting": builds.pc_waiting_text(st.get("pc")),
            "note": "an uncovered filament joins a line by its name at the next build; add it to a line here "
                    "only when that would be the wrong line"}


def _view(ln) -> dict:
    return {"line": _name(ln), "line_id": ln.line_id, "vendor": ln.vendor, "product": ln.product,
            "material": ln.material, "filament_ids": list(ln.filaments), "bambu_parent": ln.bambu_parent,
            "parent_source": ln.parent_source, **_orca_view(ln)}


def list_lines(vendor: str | None = None) -> dict:
    want = (vendor or "").strip().casefold()
    return {"lines": [_view(ln) for _k, ln in sorted(lines_mod.load().items())
                      if not want or ln.vendor.casefold() == want]}


def find_parents(text: str) -> dict:
    """Bambu Studio system bases (and Orca library parents) whose name has every word of `text`."""
    words = (text or "").casefold().split()
    store = builds.system_store()
    bs = [] if store is None else [b for b in store.bases() if all(w in b.casefold() for w in words)
                                   and lines_mod.usable(store, b)]
    out = {"bs_templates": bs[:MAX_PARENTS], "orca_parents": _orca_parents(words)[:MAX_PARENTS],
           "synced": store is not None}
    if store is None:
        out["note"] = "no Bambu Studio system presets uploaded yet: the PC sync uploads them"
    return out


def _filaments(sm, ids) -> list[dict]:
    if not isinstance(ids, list) or not ids or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids):
        raise PresetProblem("filament_ids must be a non-empty list of Spoolman filament ids")
    if len(set(ids)) != len(ids):
        raise PresetProblem("filament_ids lists an id twice")
    by_id = {f["id"]: f for f in sm.get("filament")}
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise PresetProblem(f"no Spoolman filament {missing}")
    return [by_id[i] for i in ids]


def _join(sm, ls: dict, line, fils: list[dict], notes: list[str]) -> None:
    """Move the filaments into `line` (out of any other line) and pin them there with `extra.line`."""
    for f in fils:
        if _vendor(f).casefold() != line.vendor.casefold():
            raise PresetProblem(f"filament {f['id']} is {_vendor(f)}, not {line.vendor}: a line is one brand")
    for f in fils:
        fid = f["id"]
        for other in ls.values():
            if other is not line and fid in other.filaments:
                other.filaments = [i for i in other.filaments if i != fid]
                notes.append(f"filament {fid} moved from line {_name(other)}")
        line.filaments = sorted(set(line.filaments) | {fid})
        extra = f.get("extra") or {}
        if lines_mod._extra_line(f) != line.product:
            sm.patch(f"filament/{fid}", {"extra": {**extra, "line": json.dumps(line.product)}})


def add_ids(sm, line: str, filament_ids: list[int]) -> dict:
    fils = _filaments(sm, filament_ids)
    notes: list[str] = []
    with lines_mod.transaction() as ls:
        ln = _resolve(ls, line)
        dup = [f["id"] for f in fils if f["id"] in ln.filaments]
        if dup:
            raise PresetProblem(f"filament {dup} is already in line {_name(ln)}")
        _join(sm, ls, ln, fils, notes)
        view = _view(ln)
    builds.request_rebuild("mcp line add")
    return {**view, "notes": notes, "output": f"added {filament_ids} to {_name(ln)}; a build is requested"}


def add_line(sm, name: str, vendor: str, filament_ids: list[int], orca_parent: str, bs_template: str) -> dict:
    vendor = (vendor or "").strip()
    name = (name or "").strip()
    product = name[len(vendor):].strip() if name.casefold().startswith(vendor.casefold() + " ") else name
    for key, value, at_ok in (("vendor", vendor, False), ("name", product, False),
                              ("bs_template", bs_template, False), ("orca_parent", orca_parent, False)):
        problem = lines_mod.text_problem(value, at_ok=at_ok)
        if problem:
            raise PresetProblem(f"{key} {problem}")
    if not vendor or not product:
        raise PresetProblem("name ('<Brand> <Line>') and vendor are required")
    fils = _filaments(sm, filament_ids)
    store = builds.system_store()
    lines_mod.check_parent(bs_template, store)
    notes: list[str] = []
    with lines_mod.transaction() as ls:
        lid = lines_mod.line_id_for(vendor, product)
        if lid in ls:
            raise PresetProblem(f"line {_name(ls[lid])} exists already: use add_filaments_to_line")
        ln = lines_mod.ensure(ls, vendor, product, fils[0].get("material") or "", bambu_parent=bs_template or None,
                              library=library_mod.load(), store=store, used_fids=set(),
                              orca_store=builds.orca_store())
        _set_orca(ls, ln, orca_parent, notes)
        _join(sm, ls, ln, fils, notes)
        view = _view(ln)
    builds.request_rebuild("mcp line new")
    return {**view, "notes": notes, "output": f"line {_name(ln)} created; a build is requested"}


def generate() -> dict:
    builds.request_rebuild("mcp generate")
    st = builds.status()
    return {"requested": True, "last_build": (st.get("build") or {}).get("stamp"),
            "output": "a build is requested; the build service runs it within a minute or two (preset_status "
                      "shows the new build), and the desktop installs it the next time both slicers are closed"}


# ---------- Orca parents (Task 3: Line.orca_parent, lines.set_parent(target="orca"), builds.orca_store) ----------

def _orca_view(ln) -> dict:
    return {"orca_parent": ln.orca_parent, "orca_parent_source": ln.orca_parent_source}


def _orca_parents(words: list[str]) -> list[str]:
    """Base names of the uploaded OrcaFilamentLibrary `@System` presets with every word (no store: [])."""
    from ..profiles.orca import SYSTEM
    store = builds.orca_store()
    if store is None:
        return []
    names = sorted({n[: -len(SYSTEM)] for n in store.library_names() if n.endswith(SYSTEM)})
    return [n for n in names if all(w in n.casefold() for w in words)]


def _set_orca(ls: dict, ln, orca_parent: str, notes: list[str]) -> None:
    """The owner's Orca parent for the line (source "user"), checked against the uploaded Orca library; blank
    keeps the parent the line chose by itself."""
    parent = (orca_parent or "").strip()
    if not parent:
        return
    lines_mod.check_orca_parent(parent, builds.orca_store())
    lines_mod.set_parent(ls, ln.line_id, parent, target="orca")
