"""Installs a downloaded build into the live Bambu Studio user folder, and its Orca Slicer tree into the live
Orca Slicer user folder (port of install.py).

A build holds `base/` (Bambu Studio, installed into <user filament>/base) and may hold `orca/` (Orca Slicer,
installed flat into Orca's user filament folder). The Orca tree is installed only when this PC has Orca
Slicer (`orca` given); otherwise it is left out, also from the snapshot. Each target gets the same checks.

Order (each check runs before anything is written):
  1. the staged names come from build_dir/base and build_dir/orca;
  2. untrusted G-code: for Bambu Studio every value of a key containing "gcode" must equal a value from this
     PC's system filament presets, a value of the installed snapshot (dirs.installed: this PC accepted it
     once, e.g. the owner's G-code edit carried after an app reset), or the live preset's current value; for
     Orca Slicer (whose presets inherit their G-code from `@System`) a "gcode" key is only allowed with the
     live preset's current value (the builder never writes G-code of its own);
  3. a preset edited or deleted in the app after the build was made refuses the install
     (unless more than a quarter of the installed presets vanished at once: an app reset); a live
     value equal to the copy in dirs.partial (a build whose install stopped part-way, ruling S28) was
     written by that install, not typed in the app, so it is not an edit (the server agrees); nor is
     a live value equal to the build's own record of the in-app values it carried (BUILD.json
     `inapp`, `orca_inapp` for Orca: the build saw it, e.g. a "nil" it filled in); a preset the build
     brought back on `profiles restore-deleted` (BUILD.json `restored`, `orca_restored`) is not a deletion;
     into a secondary folder (`secondary`, another Bambu Studio folder of this PC, which cannot ask for a
     rebuild) nothing is refused here: a preset edited there since its last install is held (never written over,
     accepted or not) and one deleted there is skipped (not written again);
  4. Bambu Studio (and Orca Slicer, when its tree is installed) must not be running; this is checked again
     right before the first write, and if one runs then nothing is written, not even the backup;
  5. the user filament folders (which must exist) are backed up to dirs.backups/<stamp> and
     dirs.orca_backups/<same name> (the 5 newest of each are kept); a backup that fails part-way is removed
     and the install refused;
  6. only presets the slicer does not have yet are copied in (the owner's rule, 2026-11-06: never replace one
     that exists, only add new ones). A preset exists when its file is there (names compared NFC + casefolded) or
     another .json there holds the same preset `name` (for Bambu Studio also in filament/ itself, where the owner's
     inheriting presets live: those are never written over); it is left exactly as it is (`kept`, `kept_orca`) unless
     the owner accepted its update on the server (`accept`, {"base"|"orca": [names]}): then it is written over
     that existing file (after the backup); this is the only path that overwrites a preset. Each written .json
     gets its .info, keeping a live cloud setting_id; every file goes to a sibling `.<name>.fktmp` first and is
     renamed over the target, so a crash never leaves a half-written preset (leftover temp files are removed at
     the start of this phase);
     The kept presets whose live copy differs from the build's (inapp.diff, either way; an inheriting preset in
     filament/ always) are returned as `differing`, to be listed;
  7. nothing is ever deleted: presets no longer built but still live are returned as `stale` /
     `stale_orca` (they are deleted in the app, never on disk);
  8. dirs.installed is replaced with what the slicers now hold (temp dir + rename): the build, with a kept
     preset's own live .json in place of the build's copy (the owner's file: its G-code counts as theirs) and no
     copy at all of a preset that lives under another file name (it is not ours to diff); an orca/ tree not
     installed this time keeps the previous snapshot's orca/ (B-I1: Orca edits are still diffed against what
     Orca holds).
"""
import json
import os
import shutil
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import inapp, studio
from .store import AppDirs
from .studio import OrcaFolders, StudioFolders

KEEP_BACKUPS = 5
STUDIO_RUNNING = "Bambu Studio is running"
ORCA_RUNNING = "Orca Slicer is running"
TMP_SUFFIX = ".fktmp"
KEPT = "KEPT.json"              # dirs.installed/KEPT.json {"base": [names]}: snapshot copies that are the folder's own
BAMBU, ORCA = "Bambu Studio", "Orca Slicer"


class Refused(Exception):
    """The install was not done; nothing was written. `.reason` says why, `.code` is a short tag."""

    def __init__(self, reason: str, code: str = "refused"):
        super().__init__(reason)
        self.reason = reason
        self.code = code


@dataclass
class InstallResult:
    installed: list[str]        # written this time (new, or an accepted update)
    stale: list[str]
    backup: Path
    installed_orca: list[str] = field(default_factory=list)
    stale_orca: list[str] = field(default_factory=list)
    backup_orca: Path | None = None
    kept: list[str] = field(default_factory=list)          # already in the slicer: left as they are
    kept_orca: list[str] = field(default_factory=list)
    differing: list[str] = field(default_factory=list)     # kept Bambu Studio presets that differ from the build's
    skipped: list[str] = field(default_factory=list)       # secondary: deleted there since its install, not re-added


def read_info(path: Path) -> dict:
    d = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                d[k.strip()] = v.strip()
    return d


def _key(v) -> str:
    return json.dumps(v, sort_keys=True)


def _names(folder: Path) -> list[str]:
    if not folder.is_dir():
        return []
    return sorted(p.stem for p in folder.iterdir() if p.suffix.casefold() == ".json" and p.is_file())


def _load_or_none(path: Path) -> dict | None:
    """The preset at path, None when missing; Refused when present but unreadable."""
    if not path.exists():
        return None
    try:
        return inapp.load(path)
    except (OSError, UnicodeDecodeError, ValueError) as e:
        raise Refused(f"could not read {path}: {e}") from None


def trusted_gcode(system_filament: Path, *more: Path) -> set[str]:
    """Every G-code value in this PC's Bambu Studio system filament presets (and in the `more` folders, e.g. the
    installed snapshot's base/: the builds this PC accepted, and the owner's own presets it kept). A kept preset's
    G-code counts because it is the owner's own file, already in their slicer: a build can only repeat G-code the
    owner has, never bring new G-code in."""
    ok = set()
    for folder in (system_filament, *more):
        if not folder.is_dir():
            continue
        for f in folder.iterdir():
            if f.suffix.casefold() == ".json" and f.is_file():
                try:
                    d = inapp.load(f)
                except (OSError, UnicodeDecodeError, ValueError):
                    continue
                ok.update(_key(v) for k, v in d.items() if "gcode" in k.lower())
    return ok


def _build_meta(build_dir: Path, prefix: str = "") -> tuple[dict[str, dict], set[str]]:
    """(BUILD.json `<prefix>inapp`: {preset: {key: value}}, casefolded `<prefix>restored` names); empty when absent."""
    try:
        m = json.loads((build_dir / "BUILD.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return {}, set()
    if not isinstance(m, dict):
        return {}, set()
    rec = m.get(f"{prefix}inapp")
    rec = {n: v for n, v in rec.items() if isinstance(n, str) and isinstance(v, dict)} if isinstance(rec, dict) else {}
    restored = m.get(f"{prefix}restored")
    restored = {n.casefold() for n in restored if isinstance(n, str)} if isinstance(restored, list) else set()
    return rec, restored


def untrusted_gcode(new: dict, live: dict | None, trusted: set[str]) -> list[str]:
    """G-code keys of a staged preset whose value is neither a trusted one nor the live copy's."""
    keys = [k for k, v in new.items() if "gcode" in k.lower() and _key(v) not in trusted]
    if keys and live is not None:
        keys = [k for k in keys if _key(live.get(k)) != _key(new[k])]
    return keys


def _backup(user_filament: Path, backups: Path, stamp: str, prune: bool = True) -> Path:
    """Copy user_filament to backups/<stamp>[-n]; `prune` then keeps the KEEP_BACKUPS newest."""
    backups.mkdir(parents=True, exist_ok=True)
    dest, n = backups / stamp, 1
    while dest.exists():
        n += 1
        dest = backups / f"{stamp}-{n}"
    try:
        shutil.copytree(user_filament, dest)
    except OSError as e:
        shutil.rmtree(dest, ignore_errors=True)  # a partial backup must not count as one of the 5
        raise Refused(f"could not back up {user_filament} to {dest} ({e}); nothing was installed") from None
    if prune:
        _prune(backups)
    return dest


def _prune(backups: Path) -> None:
    for old in sorted(p for p in backups.iterdir() if p.is_dir())[:-KEEP_BACKUPS]:
        shutil.rmtree(old)


def _write_live(target: Path, data: bytes) -> None:
    """Write target via a sibling temp file + os.replace, so a live preset is never half-written."""
    tmp = target.with_name(f".{target.name}{TMP_SUFFIX}")
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _info_bytes(d: dict) -> bytes:
    return "".join(f"{k} = {v}\n" for k, v in d.items()).encode("utf-8")


def _remove_leftover_tmp(live: Path) -> None:
    """Temp files a crashed earlier run left behind (only ours: dot-prefixed, .fktmp)."""
    for p in live.iterdir():
        if p.name.startswith(".") and p.name.endswith(TMP_SUFFIX) and p.is_file():
            p.unlink()


def _replace_installed(build_dir: Path, dirs: AppDirs, skip: tuple[str, ...] = (), targets=()) -> None:
    """dirs.installed becomes what the slicers hold now: a copy of the build, with each target's kept presets
    swapped for their live copy (or dropped when they live under another file name); a `skip`ped tree (not
    installed here) keeps the previous snapshot's copy, if any: it is still what the app holds (the server's
    Orca snapshot too, Ruling AB)."""
    dirs.ensure()
    work = Path(tempfile.mkdtemp(prefix=".installed.", suffix=".tmp", dir=dirs.base))
    try:
        new = work / "installed"
        top = Path(build_dir)
        shutil.copytree(build_dir, new, ignore=lambda d, names: [n for n in names if Path(d) == top and n in skip])
        for tree in skip:
            if (dirs.installed / tree).is_dir():
                shutil.copytree(dirs.installed / tree, new / tree)
        for t in targets:
            for name, fname in sorted(t.write.items()):    # an accepted update written over another file
                if not _own_copy(name, fname):
                    for suffix in (".json", ".info"):
                        (new / t.tree / f"{name}{suffix}").unlink(missing_ok=True)
            for name, fname in sorted(t.kept.items()):
                for suffix in (".json", ".info"):
                    (new / t.tree / f"{name}{suffix}").unlink(missing_ok=True)
                if _own_copy(name, fname):
                    shutil.copyfile(t.live / fname, new / t.tree / f"{name}.json")
        for t in targets:                                   # whose each snapshot copy is (an accepted update may
            if t.tree == "base":                            # only replace one the kit wrote, in a secondary)
                own = sorted(n for n in t.kept if n not in t.proven)
                (new / KEPT).write_text(json.dumps({"base": own}), encoding="utf-8")
        old = work / "old"
        if dirs.installed.exists():
            dirs.installed.rename(old)
        try:
            new.rename(dirs.installed)
        except OSError:
            if old.exists() and not dirs.installed.exists():
                old.rename(dirs.installed)
            raise
    finally:
        shutil.rmtree(work, ignore_errors=True)


@dataclass
class _Target:
    app: str                    # BAMBU or ORCA
    tree: str                   # "base" or "orca": the build's and the snapshot's folder
    stage: Path
    live: Path                  # where the presets go
    snap: Path
    half: Path
    staged: list[str] = field(default_factory=list)
    new: dict = field(default_factory=dict)
    stale: list[str] = field(default_factory=list)
    write: dict = field(default_factory=dict)       # name -> the live file stem it is written to
    kept: dict = field(default_factory=dict)        # name -> the live file stem that holds it (left as it is)
    hold: set = field(default_factory=set)          # secondary: edited there since its install (never written over)
    proven: set = field(default_factory=set)        # unchanged since the kit wrote it (the snapshot says so)
    gone: set = field(default_factory=set)          # secondary: deleted there since its install (not brought back)
    skipped: list = field(default_factory=list)


def fold(name: str) -> str:
    """How preset names are compared: Unicode NFC, then casefolded (the server's profiles.updates does the same)."""
    return unicodedata.normalize("NFC", name).casefold()


def _existing(folder: Path) -> tuple[dict[str, str], dict[str, str]]:
    """({folded file stem: real file name}, {folded preset `name`: real file name}) of the .json files in a folder."""
    by_file, by_name = {}, {}
    if not folder.is_dir():
        return by_file, by_name
    for p in sorted(folder.iterdir()):
        if p.suffix.casefold() != ".json" or not p.is_file():
            continue
        by_file.setdefault(fold(p.stem), p.name)
        try:
            n = inapp.load(p).get("name")
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        if isinstance(n, str) and n:
            by_name.setdefault(fold(n), p.name)
    return by_file, by_name


ROOT = "\0root"                 # t.kept value: the preset lives in Bambu Studio's filament/ root, never written


def _plan(t: _Target, accept: dict | None, root: Path | None = None, secondary: bool = False) -> None:
    """Step 6's plan for one target: what is written (new presets, accepted updates) and what is kept. `root`:
    Bambu Studio's filament/ folder, where the user presets that inherit a system preset live (base/ holds the
    flattened ones it writes): a preset of the same name there is the owner's and is never written over, accepted
    or not (a base/ copy would make two presets of one name)."""
    ok = {fold(n) for n in (accept or {}).get(t.tree, []) if isinstance(n, str)}
    by_file, by_name = _existing(t.live)
    top_file, top_name = _existing(root) if root is not None else ({}, {})
    for name in t.staged:
        key = fold(name)
        fname = by_file.get(key) or by_name.get(key)
        if name in t.gone:
            t.skipped.append(name)
        elif fname is None and (key in top_file or key in top_name):
            t.kept[name] = ROOT
        elif fname is None:
            t.write[name] = f"{name}.json"
        elif key in ok and name not in t.hold and (not secondary or name in t.proven):
            t.write[name] = fname           # in a secondary only over a preset the kit wrote there (never the owner's)
        else:
            t.kept[name] = fname


def _read_kept(installed: Path) -> set[str] | None:
    """The snapshot's KEPT.json names (copies that are the folder's own files, not the kit's); None for a snapshot
    from before that record (in a secondary that proves nothing; in the primary a copy equal to the live file
    counts as the kit's)."""
    try:
        d = json.loads((installed / KEPT).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    names = d.get("base") if isinstance(d, dict) else None
    return {n for n in names if isinstance(n, str)} if isinstance(names, list) else None


def _differing(t: _Target) -> list[str]:
    """The kept presets whose live copy differs from the build's (by inapp.diff, either way; the owner's own
    inheriting preset in filament/ counts as differing): listed, never written."""
    out = []
    for name, fname in t.kept.items():
        if fname == ROOT:
            out.append(name)
            continue
        try:
            live = inapp.load(t.live / fname)
        except (OSError, UnicodeDecodeError, ValueError):
            out.append(name)
            continue
        new = t.new.get(name) or {}
        if inapp.diff(new, live) or inapp.diff(live, new):
            out.append(name)
    return sorted(out)


def _own_copy(name: str, fname: str) -> bool:
    """The live file is the preset's own (exactly `<name>.json`, the path every later check reads): the snapshot
    keeps it under that name. Any other file (another name, a case-only difference in the name or the suffix, the
    filament/ root) is not ours to diff: no snapshot copy, so nothing reads it as edited or deleted (on Linux a
    case-only difference is another path)."""
    return fname == f"{name}.json"


def _check(t: _Target, trusted: set[str], record: dict, restored: set[str], unsafe: list, stop: list,
           secondary: bool = False) -> None:
    """Steps 1-3 for one target: load the staged presets, collect untrusted G-code and late app changes (`secondary`:
    those are not refusals but t.hold / t.gone: a secondary folder cannot ask for a rebuild)."""
    for name in t.staged:
        try:
            t.new[name] = inapp.load(t.stage / f"{name}.json")
        except (OSError, UnicodeDecodeError, ValueError) as e:
            raise Refused(f"build preset {name} is not valid JSON: {e}") from None
    before = _names(t.snap)
    live_names = _names(t.live)
    owners = _read_kept(t.snap.parent) if t.tree == "base" else set()
    reset = inapp.is_reset(set(before), set(live_names))
    label = "" if t.app == BAMBU else f"{ORCA} "
    for name in t.staged:
        now = _load_or_none(t.live / f"{name}.json")
        unsafe += [f"{label}{name}: {k}" for k in untrusted_gcode(t.new[name], now, trusted)]
        old = _load_or_none(t.snap / f"{name}.json")
        if old is None:
            continue
        if now is None:
            if not reset and name.casefold() not in restored:
                if secondary:
                    t.gone.add(name)
                else:
                    stop.append(f"{name}: deleted in {t.app} after the build was made")
            continue
        part = _load_or_none(t.half / f"{name}.json") if t.half.is_dir() else None
        seen = record.get(name, {})
        late = [k for k, v in inapp.diff(old, now).items() if inapp.norm(t.new[name].get(k)) != inapp.norm(v)
                and not (part is not None and k in part and inapp.norm(part[k]) == inapp.norm(v))
                and not (k in seen and inapp.norm(seen[k]) == inapp.norm(v))]
        # proven: unchanged since the kit wrote it. A snapshot without KEPT.json cannot tell the kit's copies from
        # the owner's own kept files, so in a secondary it proves nothing (the preset is listed as differing and
        # `apply-updates --folder` takes the build's copy on request); the primary keeps the equality rule.
        if not inapp.diff(old, now) and (name not in owners if owners is not None else not secondary):
            t.proven.add(name)
        if late and secondary:
            t.hold.add(name)
        elif late:
            stop.append(f"{name}: edited in {t.app} after the build was made ({', '.join(late)})")
    staged_cf = {n.casefold() for n in t.staged}
    live_cf = {n.casefold() for n in live_names}
    t.stale = [n for n in before if n.casefold() not in staged_cf and n.casefold() in live_cf]


def local_info(info: dict, user_id: str) -> dict:
    """The .info of a fresh local preset of this folder, as Bambu Studio saves one: its own user id, no cloud
    setting_id (Studio uploads such a preset under the signed-in account itself), no base_id (the preset is
    flattened), no sync_info. Only updated_time is kept from the build's."""
    out = {"sync_info": "", "user_id": user_id, "setting_id": "", "base_id": ""}
    out["updated_time"] = info.get("updated_time") or "0"
    return out


def write_preset(live: Path, fname: str, src_json: Path, src_info: Path, own_user: str | None = None) -> None:
    """Write one preset (`src_json` + `src_info`) as live/<fname>, merging .info so a live cloud setting_id is kept;
    each file goes to a temp file next to it, then is renamed over it. `own_user` (a secondary folder): the build's
    .info is the primary's, so the preset gets that folder's own local .info instead (its user id; never the
    primary's cloud setting_id, only the folder's own one when the preset already had it)."""
    stem = Path(fname).stem
    _write_live(live / fname, src_json.read_bytes())
    info, old_info = read_info(src_info), read_info(live / f"{stem}.info")
    if own_user is not None:
        info = local_info(info, own_user)
    if old_info.get("setting_id") and not info.get("setting_id"):  # synced to the cloud since the build
        info.update(setting_id=old_info["setting_id"], base_id=old_info.get("base_id", ""), sync_info="update")
    _write_live(live / f"{stem}.info", _info_bytes(info))


def _copy_in(t: _Target, own_user: str | None = None) -> None:
    """Step 6 for one target: copy the presets planned for writing (write_preset)."""
    t.live.mkdir(parents=True, exist_ok=True)
    _remove_leftover_tmp(t.live)
    for name, fname in t.write.items():
        write_preset(t.live, fname, t.stage / f"{name}.json", t.stage / f"{name}.info", own_user)


def install(build_dir: Path, folders: StudioFolders, dirs: AppDirs, *,
            running: Callable[[], bool], stamp_now: str,
            before_write: Callable[[Path], None] | None = None,
            orca: OrcaFolders | None = None, orca_running: Callable[[], bool] | None = None,
            accept: dict | None = None, secondary: bool = False,
            trusted_extra: tuple[Path, ...] = ()) -> InstallResult:
    """before_write(backup_dir) runs after the backups and before the first live write (the sync
    records it so an interrupted install can be told apart from later in-app edits). `orca`: this PC's
    Orca Slicer folders (None: the build's orca/ tree is not installed). `accept`: the updates the owner accepted,
    {"base"|"orca": [preset names]}: the only existing presets that are written over.
    `secondary`: `folders` is another Bambu Studio folder of this PC (not the one the server builds from):
    step 3 refuses nothing; a preset edited there since its last install is never written over (accepted or not)
    and one deleted there is not written again (`skipped`). `trusted_extra`: more system preset folders whose G-code
    is trusted (a secondary trusts the primary's: same PC, its Bambu Studio version may differ)."""
    build_dir = Path(build_dir)
    orca_running = orca_running or studio.orca_running
    if running():
        raise Refused(STUDIO_RUNNING, "studio_running")

    bambu = _Target(BAMBU, "base", build_dir / "base", folders.user_filament / "base", dirs.installed / "base",
                    dirs.partial / "base", staged=_names(build_dir / "base"))
    targets = [bambu]
    o = None
    if orca is not None and (build_dir / "orca").is_dir():
        o = _Target(ORCA, "orca", build_dir / "orca", orca.user_filament, dirs.installed / "orca",
                    dirs.partial / "orca", staged=_names(build_dir / "orca"))
        targets.append(o)
        if orca_running():
            raise Refused(ORCA_RUNNING, "studio_running")

    # 1. staged names
    if not any(t.staged for t in targets):
        raise Refused(f"build {build_dir} has no presets")

    # 2. untrusted G-code, 3. edited / deleted after the build
    unsafe, stop = [], []
    _check(bambu, trusted_gcode(folders.system_filament, bambu.snap, *trusted_extra), *_build_meta(build_dir),
           unsafe, stop, secondary=secondary)
    if o is not None:
        _check(o, set(), *_build_meta(build_dir, "orca_"), unsafe, stop)   # Orca: only the live copy's G-code
    if unsafe:
        raise Refused(f"{len(unsafe)} presets carry G-code that is neither from a Bambu Studio system preset nor "
                      "already in your live copy (Orca Slicer presets: only the live copy's) (the build may have "
                      "been tampered with): " + "; ".join(unsafe[:20]), "untrusted_gcode")
    if stop:
        apps = " / ".join(t.app for t in targets)
        raise Refused(f"the build is older than your latest {apps} changes; a rebuild is asked for: "
                      + "; ".join(stop[:20]), "stale_build")

    if not folders.user_filament.is_dir():
        raise Refused(f"the Bambu Studio user filament folder {folders.user_filament} does not exist; open Bambu "
                      "Studio once (and sign in, if you use an account), then run the sync again")
    if o is not None and not orca.user_filament.is_dir():
        raise Refused(f"the Orca Slicer user filament folder {orca.user_filament} does not exist; open Orca "
                      "Slicer once, then run the sync again")

    for t in targets:                   # what step 6 writes and keeps (read before anything is written)
        _plan(t, accept, root=folders.user_filament if t is bambu else None, secondary=secondary and t is bambu)

    # 4. right before the first write
    if running():
        raise Refused(STUDIO_RUNNING, "studio_running")
    if o is not None and orca_running():
        raise Refused(ORCA_RUNNING, "studio_running")

    # 5. backups (the Orca one under the same name, so a marker naming one finds both)
    #    old backups are pruned only once both exist, so a failed Orca backup costs no Bambu one
    backup = _backup(folders.user_filament, dirs.backups, stamp_now, prune=False)
    backup_orca = None
    if o is not None:
        shutil.rmtree(dirs.orca_backups / backup.name, ignore_errors=True)  # ours, from an attempt in the same second
        try:
            backup_orca = _backup(orca.user_filament, dirs.orca_backups, backup.name, prune=False)
        except Refused:
            shutil.rmtree(backup, ignore_errors=True)
            raise
        _prune(dirs.orca_backups)
    _prune(dirs.backups)
    if before_write is not None:
        before_write(backup)

    # 6. copy the new presets and the accepted updates
    for t in targets:
        _copy_in(t, folders.user_id if secondary and t is bambu else None)

    # 7. nothing deleted; 8. snapshot (without an orca/ tree that was not installed here)
    _replace_installed(build_dir, dirs, skip=() if o is not None else ("orca",), targets=targets)
    return InstallResult(installed=list(bambu.write), stale=bambu.stale, backup=backup,
                         installed_orca=list(o.write) if o else [], stale_orca=o.stale if o else [],
                         backup_orca=backup_orca, kept=list(bambu.kept), kept_orca=list(o.kept) if o else [],
                         differing=_differing(bambu), skipped=list(bambu.skipped))


__all__ = ["Refused", "InstallResult", "install", "write_preset", "local_info", "KEEP_BACKUPS", "KEPT",
           "STUDIO_RUNNING", "ORCA_RUNNING"]
