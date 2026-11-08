"""Sync storage (the PC sync's uploads), builds with last-good fallback, and the sync/profile state views.

State, all under `state/profiles/`:
  live/user/, live/system/   the PC sync's last good uploads (user filament folder, `system/BBL/filament`)
  live/orca/user/            Orca Slicer's user `filament/` folder (upload kind `orca_live`, Task 3)
  live/orca/system/          Orca's system presets (kind `orca_system`, Ruling L): `BBL/filament/**.json` from
                             `%APPDATA%\\OrcaSlicer\\system\\BBL\\filament\\` + `OrcaFilamentLibrary/index.json`
  live/meta.json             {owner, user_id, live_hash, live_at, system_hash, system_at, system_presets,
                             partial, orca_user_id, orca_live_hash, orca_live_at, orca_partial, orca_system_hash,
                             orca_system_at, orca_system_presets}; `partial` = a build whose install stopped
                             part-way on the PC (ruling S28, `PUT /api/sync/live?partial=<stamp>`), cleared by the
                             next install report; `orca_partial` the same for the Orca tree (Ruling O)
  builds/<stamp>/            one build: BUILD.json (the manifest) + base/<name>.json|.info, and with the Orca
                             target (Task 6) a flat orca/<name>.json|.info tree; SLICER.json + held/ (each
                             preset new / same / update against the slicer, and the slicer's own copies:
                             profiles.updates; never sent to the PC)
  updates.json               {accepted: {base, orca}}: the updates the owner accepted (`profiles apply-updates`)
  builds/*.tmp               a build or upload in progress; removed by the next build
  current.json               the last good build {stamp, created, live_hash, presets, problems} (+ orca_live_hash
                             with the Orca target)
  installed.json             the build the sync PC installed {stamp, at, device_id} (+ orca_stamp, orca_at: the
                             last build whose orca/ tree went in, and when; Ruling AB) (+ written, orca_written:
                             the presets the PC wrote of those builds; the rest it kept, profiles.updates)
  deleted.json               {deleted_before: [preset names deleted in the app]} (+ orca_deleted_before)
  owner-edits.json           {stamp, inapp, notes} (+ orca_inapp, orca_notes): the owner's in-app record and note
                             lines of the old PC's installed build, kept when the sync PC changes (ruling S34) until
                             the new PC installs
  build-state.json           {last_attempt: {at, ok, error}, handled: {at, started}} (the builder's own record)
  rebuild-request            written by `request_rebuild`; watched by filament-kit-build.path (PathModified).
                             The builder only ever READS it; what was handled is kept in build-state.json.
  restore-deleted            flag: the next build brings back presets deleted in the app (consumed by it)
  build.lock, live.lock,     cross-process locks (fcntl; thread locks only where fcntl is missing);
  state.lock                 state.lock guards the read-modify-write of build-state.json

Uploads (Decision "sync uploads", Review Focus 1): the body is streamed into a temp file and refused with 413 as
soon as it passes the cap (MAX_LIVE / MAX_SYSTEM), before reading further. The zip is then checked entry by
entry before anything is extracted (at most MAX_ENTRIES entries, relative POSIX names only: no absolute path,
drive letter, backslash, `..`, empty or `.` part; no symlink; a directory entry must be empty; only `.json` and
`.info` files; no two names equal when casefolded; declared sizes within MAX_FILE / MAX_TOTAL), extracted inside
a temp dir while counting the real bytes, and every live `.json` must parse. A system `.json` that does not parse
(or is not an object) is kept and reported as a store problem by the builds (ruling S29a). Only then is the live folder swapped
(under live.lock); a refused upload leaves the previous live folder as it was.

One sync PC (Decision): the first paired device that uploads becomes the owner; other devices get 409
`other_pc` until the owner is unpaired (it is then no longer in `pairing.devices()`). When the owner changes, the
old PC's installed.json, deleted.json and meta `partial` are dropped (the new PC starts like a first install), and
an installed.json written for another device than the owner is never read.

Builds (Decision "build trigger and retention"): `run_build` holds build.lock, builds into builds/<stamp>.tmp,
renames it, saves the lines, writes deleted.json and then current.json. The installed build (and the partial one,
if any) is the in-app edit snapshot; its BUILD.json `inapp` is the record of edits that last (ruling S27). Any exception leaves current.json (the
last good build) untouched. With no system presets uploaded yet it ends cleanly with `waiting: True`. So it does
(ruling S32, WAIT_LIVE) when the install the PC reported is newer than its last live upload: the live folder then
predates the install and would read the old values as in-app edits. That wait leaves the rebuild request pending
(build-state `wait_live`); the next live upload renews the request, so the build runs on fresh live data. It runs
again (at most MAX_RUNS times in all) while the rebuild request is newer than the run's start. The newest KEEP
builds plus the installed one (and a partial one still named in meta.json) are kept.

The Orca target (Task 6, Ruling O) is on when config `slicer_printers` lists a printer or `presets_orca` is true
(Ruling X: an uploaded Orca store alone changes nothing); off, a build is byte for byte what it was before the
Orca target. On, the build also writes `orca/` (generate.OrcaTarget: the Orca live folder, the snapshot's
`orca/` tree, `orca_partial`, `orca_deleted_before`, the owner's Orca record), BUILD.json gains
`orca_live_hash`, `orca_system_hash`, `orca_user_id`, `orca_inapp`, `orca_deleted`, `orca_restored`,
`orca_stale` and a `target` on every preset row,
but only the Bambu Studio live folder is waited for (S32). The Orca snapshot is the build whose orca/ tree the
PC installed (installed.json `orca_stamp`, from the install report's `trees`, Ruling AB), not the last install:
a base/-only install leaves the Orca folder as it was. With no such build, or an Orca live folder not uploaded
since that Orca install (an Orca upload that keeps failing, Ruling Z), the Orca live folder is stale: it is not
diffed, the Orca snapshot's record, restores and deletions are carried as they are
(generate.OrcaTarget.live_fresh). An Orca live upload
renews a waiting request like a Bambu Studio one. A new sync PC forgets the old one's Orca live upload (S34).
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import tempfile
import threading
import time
import zipfile
import zlib
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

try:
    import fcntl
except ImportError:  # Windows dev PC
    fcntl = None

from .. import config, pairing
from .. import library as library_mod
from ..bridge import registry
from ..pairing import _write_atomic, make_state_dir, open_lock
from . import generate, inapp as inapp_mod, lines as lines_mod, updates as updates_mod
from .bbl import Store
from .errors import ProfileError
from .orca import OrcaStore

MAX_LIVE = 32 << 20
MAX_SYSTEM = 64 << 20
MAX_ENTRIES = 20_000
MAX_FILE = 4 << 20
MAX_TOTAL = 512 << 20
MAX_RUNS = 3
KEEP = 5
CHUNK = 64 * 1024
MAX_PART = 255                  # bytes in one path part of an upload entry
UPLOAD_TMP_AGE = 3600           # an upload temp dir older than this is left over from a crash
SUFFIXES = (".json", ".info")
STAMP_RE = re.compile(r"\d{8}-\d{6}(?:-[1-9]\d{0,5})?")
USER_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
NO_SYSTEM = "no Bambu Studio system presets yet: install and pair the PC sync"
WAIT_LIVE = "waiting for the PC's next sync"
OWNER_EDITS = "owner-edits.json"
# upload kind -> (folder under live/, size cap, every .json must parse, meta.json key prefix)
KINDS = {"live": ("user", MAX_LIVE, True, ""), "system": ("system", MAX_SYSTEM, False, ""),
         "orca_live": ("orca/user", MAX_LIVE, True, "orca_"), "orca_system": ("orca/system", MAX_SYSTEM, False, "orca_")}
_BAD_PART = re.compile(r'[<>:"|?*\x00-\x1f\x7f]')
_DRIVE = re.compile(r"[A-Za-z]:")


class OtherPc(ProfileError):
    def __init__(self, owner: str | None = None):
        super().__init__(409, "other_pc", "another PC is this server's sync PC; unpair it first "
                                          "(filament-kit unpair <id>)", owner=owner)


class BadZip(ProfileError):
    def __init__(self, message: str):
        super().__init__(400, "bad_zip", message)


class TooLarge(ProfileError):
    def __init__(self, message: str):
        super().__init__(413, "too_large", message)


def _not_found(what: str) -> ProfileError:
    return ProfileError(404, "not_found", what)


# ---------- paths and small state files ----------

def _dir() -> Path:
    return config.paths().state / "profiles"


def _live() -> Path:
    return _dir() / "live"


def _builds() -> Path:
    return _dir() / "builds"


def _request_path() -> Path:
    return _dir() / "rebuild-request"


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def _read_obj(path: Path) -> dict:
    data = _read_json(path)
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, obj) -> None:
    make_state_dir(path.parent)
    _write_atomic(path, (json.dumps(obj, indent=2, ensure_ascii=False) + "\n").encode("utf-8"), 0o644,
                  state_owned=True)


_thread_locks: dict[str, threading.RLock] = {}
_thread_locks_guard = threading.Lock()
_held = threading.local()


@contextmanager
def _locked(name: str):
    """Cross-process lock on `profiles/<name>` (re-entrant within a thread)."""
    with _thread_locks_guard:
        lock = _thread_locks.setdefault(name, threading.RLock())
    with lock:
        depth = getattr(_held, name.replace(".", "_"), 0)
        if fcntl is None or depth:
            setattr(_held, name.replace(".", "_"), depth + 1)
            try:
                yield
            finally:
                setattr(_held, name.replace(".", "_"), depth)
            return
        make_state_dir(_dir())
        with open_lock(_dir() / name) as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            setattr(_held, name.replace(".", "_"), 1)
            try:
                yield
            finally:
                setattr(_held, name.replace(".", "_"), 0)
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _meta() -> dict:
    return _read_obj(_live() / "meta.json")


def meta() -> dict:
    """A copy of the live upload's meta.json (owner, user_id, live/system hashes, times, system_presets), read under
    live.lock so it never sees a half-done upload."""
    with _locked("live.lock"):
        return dict(_meta())


# ---------- the uploaded system store (one definition for every caller) ----------

def _system_hash(meta: dict, kind: str = "system") -> str | None:
    """meta.json's `system_hash` (`orca_system_hash` for kind "orca_system"), but None when its folder is missing
    or holds no preset .json (a backup restored without it, final review I5): the PC then sees a mismatch and
    uploads its system presets again."""
    sub, _cap, _strict, prefix = KINDS[kind]
    h = meta.get(prefix + "system_hash")
    if not isinstance(h, str) or not h:
        return None
    try:
        has = any(p.suffix.casefold() == ".json" and p.is_file() for p in _live().joinpath(*sub.split("/")).rglob("*"))
    except OSError:
        has = False
    return h if has else None


_store_cache: dict = {}
_store_cache_lock = threading.Lock()


def system_store() -> Store | None:
    """The uploaded Bambu Studio system presets (`live/system/`, the PC sync's upload of its
    `system/BBL/filament` folder), or None when none are uploaded.

    A store is uploaded exactly when meta.json has a `system_hash` and the folder holds at least one preset
    (`_system_hash`). The
    store is cached by (folder, system_hash). A cache hit takes no lock (meta.json is replaced atomically), so an
    intake add never waits behind a build holding live.lock (final review I6). On a cache miss the raw files are
    read under live.lock (so an upload swap can't interleave) and parsed after it is released."""
    folder = _live() / "system"
    fast = (str(folder), _system_hash(_meta()))
    with _store_cache_lock:
        if fast[1] is not None and _store_cache.get("key") == fast:
            return _store_cache["store"]
    with _locked("live.lock"):
        h = _system_hash(_meta())
        key = (str(folder), h)
        with _store_cache_lock:
            if _store_cache.get("key") == key:
                return _store_cache["store"]
        files = Store.read(folder) if h else []
    store = Store.parse(files) if files else None
    if store is not None and not store.names():
        store = None
    with _store_cache_lock:
        _store_cache.update(key=key, store=store)
    return store


_orca_cache: dict = {}


def orca_store() -> OrcaStore | None:
    """The uploaded Orca system presets (`live/orca/system/`, Ruling L), or None when none are uploaded; cached
    and locked exactly as `system_store`."""
    folder = _live() / "orca" / "system"
    fast = (str(folder), _system_hash(_meta(), "orca_system"))
    with _store_cache_lock:
        if fast[1] is not None and _orca_cache.get("key") == fast:
            return _orca_cache["store"]
    with _locked("live.lock"):
        h = _system_hash(_meta(), "orca_system")
        key = (str(folder), h)
        with _store_cache_lock:
            if _orca_cache.get("key") == key:
                return _orca_cache["store"]
        raw = OrcaStore.read(folder) if h else None
    store = OrcaStore.parse(raw) if raw else None
    if store is not None and not store.names():
        store = None
    with _store_cache_lock:
        _orca_cache.update(key=key, store=store)
    return store


def _state() -> dict:
    return _read_obj(_dir() / "build-state.json")


def _set_state(**changes) -> None:
    """Read-modify-write of build-state.json under state.lock (builds and uploads both write it)."""
    with _locked("state.lock"):
        st = _state()
        st.update(changes)
        _write_json(_dir() / "build-state.json", st)


def _installed() -> dict | None:
    """installed.json, or None; also None when it was written for another device than the sync PC (meta.json
    `owner`): another PC's snapshot would turn its presets into false deletions and edits (final review I4)."""
    d = _read_obj(_dir() / "installed.json")
    if not (isinstance(d.get("stamp"), str) and STAMP_RE.fullmatch(d["stamp"])):
        return None
    return d if d.get("device_id") == _meta().get("owner") else None


def _written(installed: dict | None, key: str) -> list[str] | None:
    """installed.json `written` / `orca_written`: the presets the PC wrote of that build (None: an older PC sync's
    report, which wrote every preset)."""
    v = (installed or {}).get(key)
    return [n for n in v if isinstance(n, str)] if isinstance(v, list) else None


def _owner_record(stamp, orca_stamp=None) -> dict | None:
    """The owner's part of an installed build (ruling S34): its BUILD.json `inapp` record and, per preset, the note
    lines below MARK; the Orca part (`orca_inapp`, `orca_notes`) from the build whose orca/ tree was installed
    (`orca_stamp`). None when that build is gone."""
    if not (isinstance(stamp, str) and STAMP_RE.fullmatch(stamp)):
        return None
    folder = _builds() / stamp
    m = _read_json(folder / "BUILD.json")
    if not isinstance(m, dict):
        return None
    out = {"stamp": stamp}
    trees = [("", "base", folder, m)]
    if isinstance(orca_stamp, str) and STAMP_RE.fullmatch(orca_stamp):
        om = _read_json(_builds() / orca_stamp / "BUILD.json")
        if isinstance(om, dict):
            trees.append(("orca_", generate.ORCA, _builds() / orca_stamp, om))
    for prefix, tree, folder, m in trees:
        rec = m.get(prefix + "inapp")
        if not isinstance(rec, dict):
            rec = {}
        rec = {n: v for n, v in rec.items() if isinstance(n, str) and isinstance(v, dict)}
        notes = {}
        base = folder / tree
        if base.is_dir():
            for f in sorted(base.iterdir()):
                if f.suffix.casefold() != ".json" or not f.is_file():
                    continue
                cfg = _read_json(f)
                if isinstance(cfg, dict):
                    mine = inapp_mod.user_notes(cfg, cfg)
                    if mine:
                        notes[f.stem] = mine
        out.update({prefix + "inapp": rec, prefix + "notes": notes})
    return out


def _owner_edits() -> dict | None:
    d = _read_obj(_dir() / OWNER_EDITS)
    return d or None


def _forget_old_pc(meta: dict) -> None:
    """A new sync PC (the owner changes; also the same PC re-paired, which gets a new device id): the old PC's
    install snapshot (the basis for deletions and diffs), partial build and deletion record are dropped, so the new
    PC starts like a first install. The owner's in-app record and note lines of the installed build are theirs,
    not the PC's: they are kept in owner-edits.json (ruling S34) and carried by the next builds until the new PC
    installs one. Called under live.lock before meta.json is written."""
    raw = _read_obj(_dir() / "installed.json")
    rec = _owner_record(raw.get("stamp"), raw.get("orca_stamp"))
    if rec is not None:
        if "orca_inapp" not in rec:             # no Orca install yet: the owner's Orca record kept so far (e.g.
            kept = _owner_edits() or {}         # seeded by migrate-ops) still counts (B-I3)
            rec.update({k: kept[k] for k in ("orca_inapp", "orca_notes") if k in kept})
        _write_json(_dir() / OWNER_EDITS, rec)
    for name in ("installed.json", "deleted.json"):
        try:
            (_dir() / name).unlink()
        except FileNotFoundError:
            pass
    meta.pop("partial", None)
    meta.pop("orca_partial", None)
    for key in ("orca_live_at", "orca_live_hash", "orca_user_id"):   # the old PC's Orca: never waited for (I1)
        meta.pop(key, None)


def _rmtree(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)
    elif path.exists() or path.is_symlink():
        try:
            path.unlink()
        except OSError:
            pass


# ---------- tree hash ----------

def tree_hash(root: Path) -> str:
    """The contract hash (must equal pc-sync `treehash.tree_hash`): every file under root whose suffix casefolds
    to .json/.info, as a relative POSIX path, sorted as strings; h.update(path utf-8 + b"\\0" + sha256(content))."""
    root = Path(root)
    h = hashlib.sha256()
    if not root.is_dir():
        return h.hexdigest()
    files = sorted((p.relative_to(root).as_posix(), p) for p in root.rglob("*")
                   if p.suffix.casefold() in SUFFIXES and p.is_file())
    for rel, path in files:
        h.update(rel.encode("utf-8") + b"\0" + hashlib.sha256(path.read_bytes()).digest())
    return h.hexdigest()


# ---------- the sync PC ----------

def owner() -> str | None:
    """The sync PC's device id: the first paired device that uploaded, while it is still paired."""
    o = _meta().get("owner")
    if not isinstance(o, str) or not o:
        return None
    return o if o in {d["id"] for d in pairing.devices()} else None


def check_owner(device_id: str) -> None:
    """Raise OtherPc when another paired device is the sync PC."""
    o = owner()
    if o is not None and o != device_id:
        raise OtherPc(o)


# ---------- uploads ----------

def _check_part(name: str, part: str) -> None:
    if part in ("", ".", ".."):
        raise BadZip(f"entry {name!r}: empty, '.' and '..' path parts are not allowed")
    if _BAD_PART.search(part):
        raise BadZip(f"entry {name!r}: characters a file name cannot hold")
    if len(part.encode("utf-8")) > MAX_PART:
        raise BadZip(f"entry {name!r}: a path part is over {MAX_PART} bytes")
    if part[-1] in " .":
        raise BadZip(f"entry {name!r}: a path part ends with a space or a dot")


def _safe_rel(name: str) -> str:
    if not name or len(name) > 512:
        raise BadZip("an entry has an empty or overlong name")
    if "\\" in name:
        raise BadZip(f"entry {name!r}: backslashes are not allowed")
    if name.startswith("/"):
        raise BadZip(f"entry {name!r}: absolute paths are not allowed")
    if _DRIVE.match(name):
        raise BadZip(f"entry {name!r}: drive letters are not allowed")
    parts = name.split("/")
    for part in parts:
        _check_part(name, part)
    leaf = parts[-1]
    stem, dot, suffix = leaf.rpartition(".")
    if not dot or not stem or "." + suffix.casefold() not in SUFFIXES:
        raise BadZip(f"entry {name!r}: only .json and .info files are accepted")
    return name


def _receive(src: BinaryIO, dest: Path, cap: int) -> int:
    """Copy `src` into `dest`, refusing (TooLarge) as soon as more than `cap` bytes arrived."""
    total = 0
    with open(dest, "wb") as fh:
        while True:
            chunk = src.read(min(CHUNK, cap + 1 - total))
            if not chunk:
                break
            total += len(chunk)
            if total > cap:
                raise TooLarge(f"the upload is over {cap >> 20} MiB")
            fh.write(chunk)
    return total


def _extract(zpath: Path, tree: Path, *, strict_json: bool = True) -> int:
    """Check every entry, then extract into `tree` counting the real bytes; returns the number of .json files
    holding a JSON object. With strict_json a .json that does not parse refuses the zip; without it (the system
    presets) the file is kept and left for the store to report."""
    try:
        zf = zipfile.ZipFile(zpath)
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, ValueError, EOFError) as e:
        raise BadZip(f"not a readable zip ({e.__class__.__name__})") from None
    with zf:
        try:
            infos = zf.infolist()
            if len(infos) > MAX_ENTRIES:
                raise BadZip(f"{len(infos)} entries (at most {MAX_ENTRIES})")
            plan, seen, declared = [], set(), 0
            for info in infos:
                raw = info.orig_filename        # as stored: zipfile turns "\\" into "/" on Windows
                mode = (info.external_attr >> 16) & 0o170000
                if mode == 0o120000:
                    raise BadZip(f"entry {raw!r}: symlinks are not allowed")
                if raw.endswith("/"):
                    if info.file_size or info.compress_size:
                        raise BadZip(f"entry {raw!r}: a directory entry with a payload")
                    _safe_dir(raw)
                    continue
                rel = _safe_rel(raw)
                key = rel.casefold()
                if key in seen:
                    raise BadZip(f"entry {rel!r} appears twice (names are compared case-insensitively)")
                seen.add(key)
                if info.file_size > MAX_FILE:
                    raise BadZip(f"entry {rel!r} is over {MAX_FILE >> 20} MiB")
                declared += info.file_size
                if declared > MAX_TOTAL:
                    raise BadZip(f"over {MAX_TOTAL >> 20} MiB uncompressed")
                plan.append((info, rel))
            tree.mkdir(parents=True)
            written, jsons = 0, 0
            for info, rel in plan:
                dest = tree.joinpath(*rel.split("/"))
                dest.parent.mkdir(parents=True, exist_ok=True)
                n = 0
                with zf.open(info) as r, open(dest, "xb") as w:
                    while True:
                        chunk = r.read(CHUNK)
                        if not chunk:
                            break
                        n += len(chunk)
                        written += len(chunk)
                        if n > MAX_FILE or written > MAX_TOTAL:
                            raise BadZip(f"entry {rel!r}: more data than declared or over the limits")
                        w.write(chunk)
                if rel.casefold().endswith(".json"):
                    try:
                        data = json.loads(dest.read_bytes().decode("utf-8"))
                    except (UnicodeDecodeError, ValueError):
                        if strict_json:
                            raise BadZip(f"entry {rel!r} is not valid JSON") from None
                        continue
                    if isinstance(data, dict) or strict_json:
                        jsons += 1
            return jsons
        except BadZip:
            raise
        except (zipfile.BadZipFile, zipfile.LargeZipFile, NotImplementedError, RuntimeError, EOFError,
                zlib.error, ValueError, FileExistsError, IsADirectoryError, NotADirectoryError,
                PermissionError, FileNotFoundError) as e:
            # names that collide on disk (a file where a directory is needed, ...); ENOSPC and other I/O
            # failures stay errors of the server (500)
            raise BadZip(f"the zip cannot be extracted ({e.__class__.__name__})") from None


def _safe_dir(name: str) -> None:
    body = name.rstrip("/")
    if not body or "\\" in body or body.startswith("/") or _DRIVE.match(body):
        raise BadZip(f"entry {name!r}: not a safe relative directory")
    for part in body.split("/"):
        _check_part(name, part)


def sweep_uploads(now: float | None = None) -> None:
    """Remove `profiles/upload-*.tmp` dirs older than UPLOAD_TMP_AGE (left by a crash mid-upload); a younger one
    may belong to an upload in progress."""
    now = time.time() if now is None else now
    try:
        found = list(_dir().glob("upload-*.tmp"))
    except OSError:
        return
    for p in found:
        try:
            old = now - p.stat().st_mtime > UPLOAD_TMP_AGE
        except OSError:
            continue
        if old:
            _rmtree(p)


def _orca_presets(tree: Path) -> int:
    """The presets in an extracted `orca_system` upload: the store's BBL names plus its library index rows."""
    store = OrcaStore.load(tree)
    return len(store.bbl.names()) + len(store.library)


def store_upload(kind: str, src: BinaryIO, *, device_id: str, user_id: str | None = None,
                 partial: str | None = None) -> str:
    """Store a PC sync upload and return its tree hash. Claims the sync owner. Kinds (KINDS):
      live         Bambu Studio's user filament folder        -> live/user/
      system       Bambu Studio's `system/BBL/filament`       -> live/system/
      orca_live    Orca Slicer's user `filament/` folder      -> live/orca/user/
      orca_system  `BBL/filament/**.json` + `OrcaFilamentLibrary/index.json` (Ruling L) -> live/orca/system/
    `user_id` (the slicer's user folder id) is kept for the two live kinds. `partial` (live kinds only) names the
    build whose install stopped part-way in this live folder (ruling S28; meta `orca_partial` for orca_live, Ruling
    O). Raises OtherPc, BadZip or TooLarge; then nothing changed."""
    if kind not in KINDS:
        raise ValueError(f"unknown upload kind {kind!r}")
    sub, cap, strict, prefix = KINDS[kind]
    is_live = kind in ("live", "orca_live")
    if user_id is not None and not USER_ID.fullmatch(user_id):
        raise ProfileError(400, "bad_request", "user_id may only have letters, digits, - and _ (at most 64)")
    if partial is not None and (kind not in ("live", "orca_live") or not isinstance(partial, str)
                                or not STAMP_RE.fullmatch(partial)):
        raise ProfileError(400, "bad_request", "partial must be a build stamp (live uploads only)")
    check_owner(device_id)                      # refuse before reading the body
    make_state_dir(_dir())
    sweep_uploads()
    tmp = Path(tempfile.mkdtemp(prefix=f"upload-{kind}-", suffix=".tmp", dir=_dir()))
    try:
        zpath = tmp / "upload.zip"
        _receive(src, zpath, cap)
        tree = tmp / "tree"
        jsons = _extract(zpath, tree, strict_json=strict)
        if kind == "orca_system":               # presets = BBL preset files + library index rows (fix M2)
            jsons = _orca_presets(tree)
        h = tree_hash(tree)
        with _locked("live.lock"):
            check_owner(device_id)
            make_state_dir(_live())
            dest = _live().joinpath(*sub.split("/"))
            if dest.parent != _live():
                make_state_dir(dest.parent)
            old = tmp / "old"
            if dest.exists():
                os.replace(dest, old)
            try:
                os.replace(tree, dest)
            except BaseException:
                if old.exists() and not dest.exists():
                    os.replace(old, dest)
                raise
            meta = _meta()
            now = time.time()
            if meta.get("owner") != device_id and (meta.get("owner") or _dir().joinpath("installed.json").exists()):
                _forget_old_pc(meta)
            meta["owner"] = device_id
            renew = False
            if is_live:
                if user_id is not None:
                    meta[prefix + "user_id"] = user_id
                if partial is not None:
                    meta[prefix + "partial"] = partial
                meta.update({prefix + "live_hash": h, prefix + "live_at": now})
                # S32: a build waits for a live folder newer than the install (Bambu Studio's or Orca's)
                renew = bool(_state().get("wait_live"))
            else:
                meta.update({prefix + "system_hash": h, prefix + "system_at": now, prefix + "system_presets": jsons})
            _write_json(_live() / "meta.json", meta)
        if renew:                               # a build waited for this upload (S32)
            _set_state(wait_live=False)
            if kind == "orca_live":             # each hash under its own name (Ruling O)
                request_rebuild("Orca live upload after an install", meta.get("live_hash"), orca_live_hash=h)
            else:
                request_rebuild("live upload after an install", h, orca_live_hash=meta.get("orca_live_hash"))
        return h
    finally:
        _rmtree(tmp)


# ---------- rebuild requests ----------

def request_rebuild(reason: str, live_hash: str | None = None, *, orca_live_hash: str | None = None) -> None:
    """Ask for a build: (re)write `profiles/rebuild-request`, which filament-kit-build.path watches. The hashes
    are the PC's live folders the request was made from (Bambu Studio, Orca: Ruling O)."""
    make_state_dir(_dir())
    data = {"at": time.time(), "reason": str(reason), "live_hash": live_hash, "orca_live_hash": orca_live_hash}
    _write_atomic(_request_path(), (json.dumps(data) + "\n").encode("utf-8"), 0o644, state_owned=True)


def _request() -> dict | None:
    """The rebuild request as read (never changed here): {at, live_hash, orca_live_hash}; `at` is the later of its own time and
    the file's mtime, so a bare `touch` counts too."""
    path = _request_path()
    try:
        st = path.stat()
    except OSError:
        return None
    data = _read_obj(path)
    at = data.get("at")
    at = float(at) if isinstance(at, (int, float)) and not isinstance(at, bool) else 0.0
    lh, olh = data.get("live_hash"), data.get("orca_live_hash")
    return {"at": max(at, st.st_mtime), "live_hash": lh if isinstance(lh, str) else None,
            "orca_live_hash": olh if isinstance(olh, str) else None}


def _pending_request() -> dict | None:
    req = _request()
    if req is None:
        return None
    handled = _state().get("handled")
    started = handled.get("started") if isinstance(handled, dict) else None
    if isinstance(started, (int, float)) and req["at"] <= started:
        return None
    return req


def restore_deleted_next() -> None:
    """The next build brings back the presets deleted in the app (the flag is consumed by a good build)."""
    make_state_dir(_dir())
    _write_atomic(_dir() / "restore-deleted", b"1\n", 0o644, state_owned=True)


# ---------- builds ----------

def _stamp_key(name: str):
    base, _, n = name[:15], name[15:16], name[16:]
    return base, int(n) if n else 1


def _new_stamp(now: float) -> str:
    base = time.strftime("%Y%m%d-%H%M%S", time.gmtime(now))
    cur = (_read_obj(_dir() / "current.json")).get("stamp")
    n = 1
    while True:
        s = base if n == 1 else f"{base}-{n}"
        if not (_builds() / s).exists() and not (_builds() / f"{s}.tmp").exists() and s != cur:
            return s
        n += 1


def _prune() -> None:
    root = _builds()
    dirs = sorted((p.name for p in root.iterdir() if p.is_dir() and STAMP_RE.fullmatch(p.name)), key=_stamp_key)
    keep = set(dirs[-KEEP:])
    inst = _installed()
    if inst:
        keep.add(inst["stamp"])
        if isinstance(inst.get("orca_stamp"), str):
            keep.add(inst["orca_stamp"])          # the Orca snapshot (Ruling AB)
    cur = current()
    if cur:
        keep.add(cur["stamp"])
    for key in ("partial", "orca_partial"):
        part = _meta().get(key)
        if isinstance(part, str):
            keep.add(part)
    for name in dirs:
        if name not in keep:
            _rmtree(root / name)


def _filament_map(manifest: dict) -> dict[str, str]:
    out = {}
    for lid, row in sorted(manifest.get("lines", {}).items()):
        for i in row.get("spoolman_ids", []):
            out.setdefault(str(i), lid)
    return dict(sorted(out.items(), key=lambda kv: int(kv[0])))


def _orca_config() -> dict | None:
    """The Orca printers asked for in config: {"bambu": presets_orca, "slicer": slicer_printers, "nozzles":
    presets_orca_nozzles}, or None when neither printer key is set (then the build is Bambu Studio only, Ruling
    X). An unreadable config is taken as no Orca printers: it never stops the Bambu Studio build."""
    try:
        cfg = config.load()
    except (OSError, ValueError):
        return None
    slicer = cfg.get("slicer_printers")
    slicer = slicer if isinstance(slicer, list) else ([slicer] if slicer else [])
    bambu = cfg.get("presets_orca") is True
    return {"bambu": bambu, "slicer": slicer, "nozzles": cfg.get("presets_orca_nozzles")} \
        if bambu or slicer else None


def _prune_accepted(build_dir: Path) -> None:
    """An accepted update stays accepted only while the new build lists an update for that preset with exactly the
    values the owner accepted (the same hash); otherwise (no longer an update, or other values) it is dropped and
    the preset is pending again, so an acceptance never covers values the owner did not see."""
    with _locked("state.lock"):
        acc = updates_mod.accepted(_dir())
        if not any(acc.values()):
            return
        rows = updates_mod.slicer(build_dir)
        keep = {t: {n: h for n, h in acc.get(t, {}).items()
                    if (rows.get(t, {}).get(n) or {}).get("status") == "update"
                    and updates_mod.preset_hash(build_dir / t / f"{n}.json") == h}
                for t in updates_mod.TREES}
        if keep != acc:
            updates_mod.save_accepted(_dir(), keep, _write_json)


def _predates_install(installed: dict | None, live_at) -> bool:
    """The PC reported an install after its last upload of this live folder (S32)."""
    return bool(installed) and isinstance(live_at, (int, float)) and isinstance(installed.get("at"), (int, float)) \
        and installed["at"] > live_at


def _build_once(sm, now: float) -> dict:
    root = _builds()
    make_state_dir(root)
    for p in root.glob("*.tmp"):
        _rmtree(p)
    sweep_uploads()
    _set_state(last_attempt={"at": now, "ok": None, "error": None})
    stamp = _new_stamp(now)
    tmp = root / f"{stamp}.tmp"
    live_copy = root / f"{stamp}.live.tmp"
    orca_copy = root / f"{stamp}.orca-live.tmp"
    snap_view, osnap_view = root / f"{stamp}.snap.tmp", root / f"{stamp}.orca-snap.tmp"
    final = root / stamp
    try:
        orca_printers = _orca_config()
        with _locked("live.lock"):
            meta = _meta()
            store = Store.load(_live() / "system")
            store.bases()                       # resolve every system preset once: problems list the bad ones
            if not store.names():
                _set_state(last_attempt={"at": now, "ok": False, "error": NO_SYSTEM})
                return {"stamp": None, "ok": False, "error": NO_SYSTEM, "problems": [], "waiting": True}
            user = _live() / "user"
            live = None
            if user.is_dir():
                shutil.copytree(user, live_copy)
                live = generate.Live(live_copy, str(meta.get("user_id") or ""))
            installed = _installed()
            part = meta.get("partial")
            orca_on = orca_printers is not None         # Ruling X: config only
            ostore = orca_store() if orca_on else None
            orca_live = None
            ouser = _live() / "orca" / "user"
            if orca_on and ouser.is_dir() and meta.get("orca_live_hash"):
                shutil.copytree(ouser, orca_copy)
                orca_live = generate.Live(orca_copy, str(meta.get("orca_user_id") or ""), sub="")
            # Ruling Z/AB: never wait for Orca; the Orca snapshot is the build whose orca/ went in; an Orca live
            # folder from before that install (or with no such install) is not diffed
            ostamp = (installed or {}).get("orca_stamp")
            ostamp = ostamp if isinstance(ostamp, str) and STAMP_RE.fullmatch(ostamp) \
                and (root / ostamp / "BUILD.json").is_file() else None
            olive_at, oat = meta.get("orca_live_at"), (installed or {}).get("orca_at")
            orca_fresh = ostamp is not None and isinstance(olive_at, (int, float)) \
                and isinstance(oat, (int, float)) and olive_at > oat
            if _predates_install(installed, meta.get("live_at")):
                # the PC reported an install but has not uploaded the live folder since (S32)
                _set_state(last_attempt={"at": now, "ok": False, "error": WAIT_LIVE}, wait_live=True)
                return {"stamp": None, "ok": False, "error": WAIT_LIVE, "problems": [], "waiting": True,
                        "keep_request": True}
        lib = library_mod.load()
        filaments = sm.get("filament")
        if not isinstance(filaments, list):
            raise ValueError("Spoolman returned no filament list")
        models = [p.model for p in registry.load().values() if p.model]
        snapshot = root / installed["stamp"] if installed and (root / installed["stamp"]).is_dir() else None
        if snapshot is not None:                # what the slicer holds: the presets the PC kept are its own
            snapshot = updates_mod.view(snapshot, "base", _written(installed, "written"), snap_view)
        # a build whose install stopped part-way (S28): only while it is kept and is not the installed one
        partial = (root / part if isinstance(part, str) and STAMP_RE.fullmatch(part)
                   and (root / part / "BUILD.json").is_file() and part != (installed or {}).get("stamp") else None)
        owner_edits = _owner_edits() if snapshot is None else None     # S34: a re-paired / new sync PC
        before = _read_obj(_dir() / "deleted.json").get("deleted_before")
        deleted_before = {n for n in before if isinstance(n, str)} if isinstance(before, list) else set()
        restore_flag = _dir() / "restore-deleted"
        restore = restore_flag.exists()
        orca = None
        if orca_on:
            want = orca_printers or {}
            oprinters, oproblems = generate.orca_printers(models if want.get("bambu") else [], want.get("slicer", []),
                                                          bambu_nozzles=want.get("nozzles"))
            opart = meta.get("orca_partial")
            obefore = _read_obj(_dir() / "deleted.json").get("orca_deleted_before")
            osnap = root / ostamp if ostamp is not None else None
            if osnap is not None:
                osnap = updates_mod.view(osnap, generate.ORCA, _written(installed, "orca_written"), osnap_view)
            oe = _owner_edits() if osnap is None else None      # S34 for the Orca tree
            orca = generate.OrcaTarget(
                store=ostore, printers=oprinters, problems=oproblems, live=orca_live, snapshot=osnap,
                partial=(root / opart if isinstance(opart, str) and STAMP_RE.fullmatch(opart)
                         and (root / opart / "BUILD.json").is_file() and opart != ostamp else None),
                deleted_before={n for n in obefore if isinstance(n, str)} if isinstance(obefore, list) else set(),
                owner_edits={"inapp": oe.get("orca_inapp"), "notes": oe.get("orca_notes")} if oe else None,
                user_id=str(meta.get("orca_user_id") or ""), live_fresh=orca_fresh)
        with lines_mod.locked():
            ls = lines_mod.load()
            manifest, new_lines = generate.build_all(
                filaments=filaments, models=models, store=store, library=lib, lines=ls, live=live,
                snapshot=snapshot, deleted_before=deleted_before, restore_deleted=restore, out_dir=tmp, now=now,
                partial=partial, owner_edits=owner_edits, orca=orca)
            sproblems = list(store.problems)
            if orca is not None and ostore is not None and orca.printers:
                sproblems += [f"Orca Slicer system presets: {p}" for p in ostore.problems]
            problems = sproblems + [p for p in manifest.get("problems", []) if p not in sproblems]
            manifest.update(stamp=stamp, created=now, live_hash=meta.get("live_hash"),
                            system_hash=meta.get("system_hash"), user_id=meta.get("user_id"), problems=problems,
                            filaments=_filament_map(manifest))
            if orca is not None:
                manifest.update(orca_live_hash=meta.get("orca_live_hash"),
                                orca_system_hash=_system_hash(meta, "orca_system"),
                                orca_user_id=meta.get("orca_user_id"))
            with open(tmp / "BUILD.json", "w", encoding="utf-8", newline="\n") as fh:
                json.dump(manifest, fh, indent=2, ensure_ascii=False)
            # new / same / update against the live folders this build was made from (never sent to the PC)
            updates_mod.record(tmp, live_copy if live is not None else None,
                               orca_copy if orca_live is not None else None, orca is not None)
            os.replace(tmp, final)
            lines_mod.save(new_lines)
        deleted = {"deleted_before": manifest.get("deleted", [])}
        cur = {"stamp": stamp, "created": now, "live_hash": meta.get("live_hash"),
               "presets": len(bambu_rows(manifest)), "problems": len(problems)}
        if orca is not None:
            deleted["orca_deleted_before"] = manifest.get("orca_deleted", [])
            cur["orca_live_hash"] = meta.get("orca_live_hash")
            cur["orca_presets"] = len(manifest.get("presets", [])) - cur["presets"]
        _write_json(_dir() / "deleted.json", deleted)
        _write_json(_dir() / "current.json", cur)
        _prune_accepted(final)
        if restore:
            try:
                restore_flag.unlink()
            except FileNotFoundError:
                pass
        _set_state(last_attempt={"at": now, "ok": True, "error": None, "stamp": stamp})
        try:
            _prune()
        except OSError:
            pass                                # retention is retried by the next build
        return {"stamp": stamp, "ok": True, "error": None, "problems": problems}
    except Exception as e:
        error = f"{e.__class__.__name__}: {e}"
        _rmtree(tmp)
        if final.exists() and (current() or {}).get("stamp") != stamp:
            _rmtree(final)
        _set_state(last_attempt={"at": now, "ok": False, "error": error})
        return {"stamp": None, "ok": False, "error": error, "problems": []}
    finally:
        _rmtree(live_copy)
        _rmtree(orca_copy)
        _rmtree(snap_view)
        _rmtree(osnap_view)


def run_build(sm, *, now: float | None = None) -> dict:
    """Build every preset (see the module docstring); returns {stamp, ok, error, problems} of the last run, plus
    `waiting: True` when no system presets were uploaded yet, or the PC's live folder predates its reported
    install (WAIT_LIVE; a clean end, not a crash)."""
    with _locked("build.lock"):
        result: dict = {}
        for _ in range(MAX_RUNS):
            started = time.time()
            result = _build_once(sm, now if now is not None else started)
            if result.pop("keep_request", False):
                break                           # the request stays pending until fresh live data (S32)
            _set_state(handled={"started": started})
            if result.get("waiting"):
                break
            req = _request()
            if req is None or req["at"] <= started:
                break
        return result


# ---------- reading builds ----------

def current() -> dict | None:
    """The last good build {stamp, created, live_hash, presets, problems}, or None."""
    c = _read_obj(_dir() / "current.json")
    s = c.get("stamp")
    if not (isinstance(s, str) and STAMP_RE.fullmatch(s) and (_builds() / s / "BUILD.json").is_file()):
        return None
    return c


def manifest(stamp: str) -> dict | None:
    if not (isinstance(stamp, str) and STAMP_RE.fullmatch(stamp)):
        return None
    m = _read_json(_builds() / stamp / "BUILD.json")
    return m if isinstance(m, dict) else None


def bambu_rows(manifest: dict | None) -> list[dict]:
    """A build's Bambu Studio preset rows (a row without `target` predates the Orca target): what preset counts
    count (fix M2); Orca rows are counted apart."""
    rows = (manifest or {}).get("presets")
    return [p for p in rows if isinstance(p, dict) and p.get("target", generate.BAMBU_STUDIO)
            == generate.BAMBU_STUDIO] if isinstance(rows, list) else []


def build_zip(stamp: str) -> bytes:
    """`BUILD.json` + `base/<name>.json|.info` (+ the flat `orca/<name>.json|.info` tree) of a kept build;
    ProfileError 404 for an unknown stamp."""
    if not (isinstance(stamp, str) and STAMP_RE.fullmatch(stamp)):
        raise _not_found(f"no build {stamp!r}")
    folder = _builds() / stamp
    if not (folder / "BUILD.json").is_file():
        raise _not_found(f"no build {stamp!r}")
    files = [("BUILD.json", folder / "BUILD.json")]
    for tree in ("base", generate.ORCA):
        base = folder / tree
        if base.is_dir():
            files += sorted((f"{tree}/{p.name}", p) for p in base.iterdir()
                            if p.is_file() and p.suffix.casefold() in SUFFIXES)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, path in files:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0      # the same bytes on Windows and Linux (Python stamps its own OS otherwise)
            zf.writestr(info, path.read_bytes())
    return buf.getvalue()


TREES = ("base", "orca")


MAX_WRITTEN = 5000             # names per tree in one install report


def _check_written(written) -> dict | None:
    if written is None:
        return None
    if not (isinstance(written, dict) and all(t in TREES for t in written)
            and all(isinstance(v, list) and len(v) <= MAX_WRITTEN and all(isinstance(n, str) and 0 < len(n) <= 255
                                                                        for n in v) for v in written.values())):
        raise ProfileError(400, "bad_request", "written must be {\"base\": [names], \"orca\": [names]}")
    return written


def _union(prev, new: list[str]) -> list[str]:
    seen = {n.casefold() for n in new}
    return sorted(set(new) | {n for n in (prev if isinstance(prev, list) else []) if isinstance(n, str)
                              and n.casefold() not in seen})


def record_installed(stamp: str, device_id: str, trees: list[str] | None = None, written: dict | None = None) -> dict:
    """The sync PC installed build `stamp`: {stamp, at}. `trees` = what went in (Ruling AB): ["base"] (also an
    older PC sync's report without it) or ["base", "orca"]; with "orca" this build becomes the Orca snapshot
    (`orca_stamp`, `orca_at`), else the previous Orca snapshot stays. `written` = the presets the PC wrote per tree
    (it keeps the rest, profiles.updates); summed over installs of the same build, and cleared from the owner's
    accepted updates. OtherPc for another device, 404 for an unknown stamp, 400 for bad trees or written."""
    trees = ["base"] if trees is None else trees
    if not (isinstance(trees, list) and "base" in trees and all(t in TREES for t in trees)):
        raise ProfileError(400, "bad_request", "trees must be [\"base\"] or [\"base\", \"orca\"]")
    written = _check_written(written)
    with _locked("live.lock"):
        check_owner(device_id)
        if not (isinstance(stamp, str) and STAMP_RE.fullmatch(stamp)
                and (_builds() / stamp / "BUILD.json").is_file()):
            raise _not_found(f"no build {stamp!r}")
        # B-M4: "orca" counts only for a build with an orca/ tree (else it would become an empty Orca snapshot)
        trees = [t for t in TREES if t in trees and (t == "base" or (_builds() / stamp / t).is_dir())]
        at = time.time()
        rec = {"stamp": stamp, "at": at, "device_id": device_id}
        prev = _installed() or {}
        if "orca" in trees:
            rec.update(orca_stamp=stamp, orca_at=at)
        elif isinstance(prev.get("orca_stamp"), str):
            rec.update(orca_stamp=prev["orca_stamp"], orca_at=prev.get("orca_at"))
            if "orca_written" in prev:
                rec["orca_written"] = prev["orca_written"]
        # an older PC sync's report of this same build (no `written`): it wrote every preset, which stays so
        if written is not None and not (prev.get("stamp") == stamp and "written" not in prev):
            rec["written"] = _union(prev.get("written") if prev.get("stamp") == stamp else None,
                                    written.get("base", []))
        if written is not None and "orca" in trees and not (prev.get("orca_stamp") == stamp
                                                             and "orca_written" not in prev):
            rec["orca_written"] = _union(prev.get("orca_written") if prev.get("orca_stamp") == stamp else None,
                                         written.get("orca", []))
        _write_json(_dir() / "installed.json", rec)
        if written and any(written.values()):   # written now: no longer waiting for the PC
            with _locked("state.lock"):
                acc = updates_mod.accepted(_dir())
                for tree, names in written.items():
                    if tree in trees:
                        done = {updates_mod.fold(n) for n in names}
                        acc[tree] = {n: h for n, h in acc.get(tree, {}).items() if updates_mod.fold(n) not in done}
                updates_mod.save_accepted(_dir(), acc, _write_json)
        meta = _meta()
        if "partial" in meta or "orca_partial" in meta:     # a finished install ends the partial one (S28)
            meta.pop("partial", None)
            meta.pop("orca_partial", None)
            _write_json(_live() / "meta.json", meta)
        kept = _owner_edits() or {}
        orca_part = {k: kept[k] for k in ("orca_inapp", "orca_notes") if k in kept}
        if orca_part and "orca" not in trees:   # the Orca tree did not go in: the owner's Orca record still counts
            _write_json(_dir() / OWNER_EDITS, {"stamp": kept.get("stamp"), **orca_part})
        else:
            try:                                # the installed build's own record carries them from now on (S34)
                (_dir() / OWNER_EDITS).unlink()
            except FileNotFoundError:
                pass
        return {"stamp": stamp, "at": at}


def _build_view() -> dict | None:
    c = current()
    if c is None:
        return None
    view = {"stamp": c["stamp"], "live_hash": c.get("live_hash"), "created": c.get("created"),
            "presets": int(c.get("presets") or 0), "problems": int(c.get("problems") or 0)}
    if "orca_live_hash" in c:                   # a build with the Orca target (pc-sync compares it, Ruling O)
        view["orca_live_hash"] = c["orca_live_hash"]
    return view


def _attempt_view() -> dict | None:
    la = _state().get("last_attempt")
    if not isinstance(la, dict):
        return None
    return {"at": la.get("at"), "ok": la.get("ok"), "error": la.get("error")}


def _installed_view() -> dict | None:
    i = _installed()
    return {"stamp": i["stamp"], "at": i.get("at")} if i else None


def _update_items() -> tuple[str | None, list[dict], int]:
    """(the current build's stamp, its pending updates, how many of its presets are new to the slicers)."""
    c = current()
    if c is None:
        return None, [], 0
    stamp = c["stamp"]
    inst = _installed() or {}
    written = {"base": _written(inst, "written") if inst.get("stamp") == stamp else None,
               generate.ORCA: _written(inst, "orca_written") if inst.get("orca_stamp") == stamp else None}
    folder = _builds() / stamp
    items = updates_mod.pending(folder, manifest(stamp) or {}, written, updates_mod.accepted(_dir()))
    return stamp, items, updates_mod.new_count(folder, written)


def updates_view() -> dict:
    """`GET /api/profiles/updates`: the presets in the slicers whose generated values differ, not written yet
    {stamp, count, lines, accepted, new, updates: [{name, target, line_id, keys, accepted, file?}], yours: [names
    that differ from your own preset of that name in Bambu Studio's filament/ folder: never written over]}."""
    stamp, items, new = _update_items()
    mine = updates_mod.yours(_builds() / stamp) if stamp else []
    return {"stamp": stamp, **updates_mod.summary(items), "new": new, "updates": items, "yours": mine}


def apply_updates(*, line_id: str | None = None, all_: bool = False, dry_run: bool = False,
                  only: set[str] | None = None) -> dict:
    """Accept the pending updates of one line (`line_id`) or all of them (`only`: just these preset names): the next
    PC sync writes them over the existing presets. Each acceptance holds the hash of the values accepted (see
    _prune_accepted). {stamp, chosen: [update rows], dry_run}; with dry_run nothing is saved. ValueError when
    neither or both of line_id / all_ are given."""
    if bool(line_id) == bool(all_):
        raise ValueError("give --line <id> or --all")
    with _locked("state.lock"):
        stamp, items, _new = _update_items()
        chosen = [u for u in items if (all_ or u["line_id"] == line_id) and (only is None or u["name"] in only)]
        if chosen and not dry_run:
            acc = updates_mod.accepted(_dir())
            for u in chosen:
                tree = updates_mod.tree_of(u["target"])
                h = updates_mod.preset_hash(_builds() / stamp / tree / f"{u['name']}.json")
                if h is not None:
                    acc.setdefault(tree, {})[u["name"]] = h
            updates_mod.save_accepted(_dir(), acc, _write_json)
    return {"stamp": stamp, "chosen": chosen, "dry_run": dry_run}


def _accepted_view() -> dict | None:
    """The accepted updates the PC sync writes, for the current build: {stamp, base: [...], orca: [...]}."""
    stamp, items, _new = _update_items()
    if stamp is None:
        return None
    out = {"stamp": stamp, "base": [], generate.ORCA: []}
    for u in items:
        if u["accepted"]:
            out[updates_mod.tree_of(u["target"])].append(u["name"])
    return out


def state_view(device_id: str) -> dict:
    """`GET /api/sync/state`."""
    meta = _meta()
    req = _pending_request()
    return {"owner": owner(), "you": device_id, "user_id": meta.get("user_id"),
            "accepted_updates": _accepted_view(),
            "live_hash": meta.get("live_hash"), "system_hash": _system_hash(meta),
            "orca_live_hash": meta.get("orca_live_hash"), "orca_system_hash": _system_hash(meta, "orca_system"),
            "orca_target": _orca_config() is not None,     # B-I2: pc-sync syncs Orca only when true (Ruling X)
            "build": _build_view(),
            "last_attempt": _attempt_view(), "installed": _installed_view(),
            "rebuild_requested": {"at": req["at"], "live_hash": req["live_hash"],
                                  "orca_live_hash": req["orca_live_hash"]} if req else None}


def status() -> dict:
    """`GET /api/profiles/status` without the library part (the API adds it)."""
    try:
        n_lines = len(lines_mod.load())
    except lines_mod.LineStoreError:
        n_lines = 0
    c = current()
    m = manifest(c["stamp"]) if c else None
    m = m or {}
    meta = _meta()
    o = owner()
    ups = [t for t in (meta.get("live_at"), meta.get("system_at")) if isinstance(t, (int, float))]
    rows = m.get("presets") if isinstance(m.get("presets"), list) else []
    # C-I5: the Orca count (None: the build has no Orca target) and the Orca presets to delete in Orca Slicer
    orca_presets = len([p for p in rows if isinstance(p, dict) and p.get("target") == generate.ORCA])         if "orca_live_hash" in m else None
    _stamp, items, new = _update_items()
    return {"lines": n_lines, "presets": len(bambu_rows(m)), "orca_presets": orca_presets, "build": _build_view(),
            "updates": {**updates_mod.summary(items), "new": new,
                        "yours": len(updates_mod.yours(_builds() / _stamp)) if _stamp else 0},
            "last_attempt": _attempt_view(), "installed": _installed_view(),
            "pc": {"device_id": o, "last_upload": max(ups) if ups else None} if o else None,
            "stale": list(m.get("stale", [])), "orca_stale": list(m.get("orca_stale", [])),
            "problems": list(m.get("problems", []))[:20]}
