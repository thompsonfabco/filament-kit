"""Presets already in the slicers are never replaced (the owner's rule, 2026-11-06); updates to them are listed and
written only once the owner accepts them (decision 2026-11-07: "list them, apply on request").

Each build compares every preset it generated with the PC's live upload it was made from (Bambu Studio's
`live/user/base`, Orca Slicer's `live/orca/user`) and records the result in `builds/<stamp>/SLICER.json`
({"base"|"orca": {name: {status, keys, file?}}}):
  new      not in the slicer (no file of that name, no other .json holding that preset `name`): the PC adds it
  same     in the slicer with the generated values
  update   in the slicer with other values (`keys`: the keys that differ, bookkeeping aside)
`file` names the live file when the preset lives under another file name (matched by its `name`). The live copy of
each `same` / `update` preset found under its own file name is kept as `builds/<stamp>/held/<tree>/<name>.json`:
the PC leaves that file as it is, so it, not the build's copy, is what the slicer holds afterwards.

The PC reports the presets it wrote (`installed.json` `written` for the base tree, `orca_written` for the Orca
tree's build; summed over installs of the same build). The in-app edit snapshot of the next build (`view`) is what
the slicer holds: the build's copy of a preset the PC wrote, the held copy of one it kept, none of one that lives
under another file name. An install report without `written` (an older PC sync, which wrote every preset) leaves
the snapshot the build as it is.

The owner's accepted updates (`profiles/updates.json` {"accepted": {"base"|"orca": [names]}}, written by
`accept`, `sudo filament-kit profiles apply-updates`) are sent to the PC in the sync state (`accepted_updates`);
the next sync writes them over the existing presets and the install report clears them. An update is pending
while the current build lists it and the PC has not written it for that build. The owner's in-app edits win as
always: they are recorded values the generated preset (and so an accepted update) already carries.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from . import generate, inapp as inapp_mod

SLICER = "SLICER.json"
HELD = "held"
TREES = ("base", generate.ORCA)
TARGET = {"base": generate.BAMBU_STUDIO, generate.ORCA: generate.ORCA}
# what the apps write on their own; never a difference
STATUS_IGNORE = {"updated_time", "setting_id", "user_id", "base_id", "is_custom_defined", "instantiation"}


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def _norm(v):
    return json.dumps(v, sort_keys=True)


def differs(generated: dict, live: dict) -> list[str]:
    """The keys whose values differ between a generated preset and the slicer's copy (sorted)."""
    keys = (set(generated) | set(live)) - STATUS_IGNORE
    return sorted(k for k in keys if k not in generated or k not in live or _norm(generated[k]) != _norm(live[k]))


def _live_index(live: Path | None) -> tuple[dict[str, str], dict[str, str]]:
    """({casefolded file stem: stem}, {casefolded preset `name`: stem}), as the PC sync's installer reads them."""
    by_file, by_name = {}, {}
    if live is None or not live.is_dir():
        return by_file, by_name
    for p in sorted(live.iterdir()):
        if not (p.is_file() and p.suffix.casefold() == ".json"):
            continue
        by_file.setdefault(p.stem.casefold(), p.stem)
        cfg = _read_json(p)
        n = cfg.get("name") if isinstance(cfg, dict) else None
        if isinstance(n, str) and n:
            by_name.setdefault(n.casefold(), p.stem)
    return by_file, by_name


def _hold(src: Path, dest: Path, gen, now) -> None:
    """Keep the slicer's copy as the next build's in-app snapshot. The owner's note lines the build carried (below
    MARK in the generated copy) are moved below MARK in it, as in a copy the PC installed: they stay theirs, and
    come back after an app reset."""
    mine = []
    if isinstance(gen, dict):
        lines = inapp_mod.notes_text(gen.get("filament_notes")).splitlines()
        if inapp_mod.MARK in lines:
            mine = [x for x in lines[lines.index(inapp_mod.MARK) + 1:] if not x.startswith(inapp_mod.IDS_PREFIX)]
    if not mine or not isinstance(now, dict):
        shutil.copyfile(src, dest)
        return
    have = [x for x in inapp_mod.notes_text(now.get("filament_notes")).splitlines()
            if x != inapp_mod.MARK and x not in mine]
    cfg = dict(now, filament_notes="\n".join(have + [inapp_mod.MARK] + mine))
    dest.write_text(json.dumps(cfg, indent=4, ensure_ascii=False), encoding="utf-8")


def classify(out_tree: Path, live: Path | None, held: Path) -> dict[str, dict]:
    """Every generated preset in `out_tree` against the live folder `live` (None: no upload, all new); the live
    copies of the ones found under their own file name go to `held`."""
    by_file, by_name = _live_index(live)
    out: dict[str, dict] = {}
    if not out_tree.is_dir():
        return out
    for p in sorted(out_tree.iterdir()):
        if not (p.is_file() and p.suffix.casefold() == ".json"):
            continue
        name, key = p.stem, p.stem.casefold()
        stem = by_file.get(key)
        own = stem is not None
        stem = stem or by_name.get(key)
        if stem is None:
            out[name] = {"status": "new"}
            continue
        gen, now = _read_json(p), _read_json(live / f"{stem}.json")
        keys = differs(gen, now) if isinstance(gen, dict) and isinstance(now, dict) else ["(unreadable)"]
        row = {"status": "update" if keys else "same", "keys": keys}
        if own:
            held.mkdir(parents=True, exist_ok=True)
            _hold(live / f"{stem}.json", held / f"{name}.json", gen, now)
        else:
            row["file"] = stem
        out[name] = row
    return out


def record(build_dir: Path, live: Path | None, orca_live: Path | None, orca: bool) -> dict:
    """Classify a build's trees (before it is renamed in place) and write its SLICER.json."""
    rec = {"base": classify(build_dir / "base", live, build_dir / HELD / "base")}
    if orca:
        rec[generate.ORCA] = classify(build_dir / generate.ORCA, orca_live, build_dir / HELD / generate.ORCA)
    (build_dir / SLICER).write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return rec


def slicer(build_dir: Path) -> dict[str, dict]:
    """A build's SLICER.json ({} for a build made before it)."""
    d = _read_json(build_dir / SLICER)
    if not isinstance(d, dict):
        return {}
    return {t: v for t, v in d.items() if t in TREES and isinstance(v, dict)}


def view(build_dir: Path, tree: str, written, dest: Path) -> Path:
    """The in-app edit snapshot of `tree`: the build as the slicer holds it after the PC's installs (`written`: the
    names it wrote; None = an older PC sync that wrote every preset, then the build itself is returned)."""
    rows = slicer(build_dir).get(tree)
    if written is None or rows is None:
        return build_dir
    done = {n.casefold() for n in written if isinstance(n, str)}
    shutil.copytree(build_dir, dest, ignore=lambda d, names: [n for n in names if Path(d) == build_dir
                                                              and n in (HELD, SLICER)])
    for name, row in rows.items():
        if not isinstance(row, dict) or row.get("status") not in ("same", "update"):
            continue
        target = dest / tree / f"{name}.json"
        held = build_dir / HELD / tree / f"{name}.json"
        if row.get("file") is not None:         # lives under another file name: not ours to diff
            target.unlink(missing_ok=True)
            (dest / tree / f"{name}.info").unlink(missing_ok=True)
        elif name.casefold() in done:
            continue                            # the PC wrote the build's copy (an accepted update)
        elif held.is_file():
            shutil.copyfile(held, target)
        else:
            target.unlink(missing_ok=True)
    return dest


# ---------- the list and the owner's acceptance ----------

def _accepted_path(profiles_dir: Path) -> Path:
    return profiles_dir / "updates.json"


def accepted(profiles_dir: Path) -> dict[str, set[str]]:
    d = _read_json(_accepted_path(profiles_dir))
    acc = d.get("accepted") if isinstance(d, dict) else None
    if not isinstance(acc, dict):
        return {t: set() for t in TREES}
    return {t: {n for n in acc.get(t) or [] if isinstance(n, str)} if isinstance(acc.get(t), list) else set()
            for t in TREES}


def save_accepted(profiles_dir: Path, acc: dict[str, set[str]], write) -> None:
    write(_accepted_path(profiles_dir), {"accepted": {t: sorted(acc.get(t, ())) for t in TREES}})


def pending(build_dir: Path, manifest: dict, written: dict[str, list[str] | None],
            acc: dict[str, set[str]]) -> list[dict]:
    """The current build's updates the PC has not written yet: [{name, target, line_id, keys, accepted, file?}]
    (sorted by target, line, name). `written`: per tree, what the PC wrote of this build (None: not installed)."""
    lines = {}
    for row in manifest.get("presets") or []:
        if isinstance(row, dict) and isinstance(row.get("name"), str):
            lines[(row.get("target", generate.BAMBU_STUDIO), row["name"])] = row.get("line_id")
    out = []
    for tree, rows in slicer(build_dir).items():
        done = {n.casefold() for n in (written.get(tree) or [])}
        for name, row in sorted(rows.items()):
            if not isinstance(row, dict) or row.get("status") != "update" or name.casefold() in done:
                continue
            item = {"name": name, "target": TARGET[tree], "line_id": lines.get((TARGET[tree], name)),
                    "keys": list(row.get("keys") or []), "accepted": name in acc.get(tree, set())}
            if row.get("file") is not None:
                item["file"] = row["file"]
            out.append(item)
    out.sort(key=lambda u: (u["target"], str(u["line_id"]), u["name"]))
    return out


def new_count(build_dir: Path, written: dict[str, list[str] | None]) -> int:
    """Presets of this build the slicers do not have yet (nor were written by the PC since)."""
    n = 0
    for tree, rows in slicer(build_dir).items():
        done = {x.casefold() for x in (written.get(tree) or [])}
        n += sum(1 for name, row in rows.items() if isinstance(row, dict) and row.get("status") == "new"
                 and name.casefold() not in done)
    return n


def summary(items: list[dict]) -> dict:
    return {"count": len(items), "lines": len({u["line_id"] for u in items}),
            "accepted": sum(1 for u in items if u["accepted"])}


def tree_of(target: str) -> str:
    return "base" if target == generate.BAMBU_STUDIO else generate.ORCA
