"""Sync storage (the PC sync's uploads), builds with last-good fallback, and the sync/profile state views.

State, all under `state/profiles/`:
  live/user/, live/system/   the PC sync's last good uploads (user filament folder, `system/BBL/filament`)
  live/meta.json             {owner, user_id, live_hash, live_at, system_hash, system_at, system_presets}
  builds/<stamp>/            one build: BUILD.json (the manifest) + base/<name>.json|.info
  builds/*.tmp               a build or upload in progress; removed by the next build
  current.json               the last good build {stamp, created, live_hash, presets, problems}
  installed.json             the build the sync PC installed {stamp, at, device_id}
  deleted.json               {deleted_before: [preset names deleted in the app]}
  build-state.json           {last_attempt: {at, ok, error}, handled: {at, started}} (the builder's own record)
  rebuild-request            written by `request_rebuild`; watched by filament-kit-build.path (PathModified).
                             The builder only ever READS it; what was handled is kept in build-state.json.
  restore-deleted            flag: the next build brings back presets deleted in the app (consumed by it)
  build.lock, live.lock      cross-process locks (fcntl; thread locks only where fcntl is missing)

Uploads (Decision "sync uploads", Review Focus 1): the body is streamed into a temp file and refused with 413 as
soon as it passes the cap (MAX_LIVE / MAX_SYSTEM), before reading further. The zip is then checked entry by
entry before anything is extracted (at most MAX_ENTRIES entries, relative POSIX names only: no absolute path,
drive letter, backslash, `..`, empty or `.` part; no symlink; a directory entry must be empty; only `.json` and
`.info` files; no two names equal when casefolded; declared sizes within MAX_FILE / MAX_TOTAL), extracted inside
a temp dir while counting the real bytes, and every `.json` must parse. Only then is the live folder swapped
(under live.lock); a refused upload leaves the previous live folder as it was.

One sync PC (Decision): the first paired device that uploads becomes the owner; other devices get 409
`other_pc` until the owner is unpaired (it is then no longer in `pairing.devices()`).

Builds (Decision "build trigger and retention"): `run_build` holds build.lock, builds into builds/<stamp>.tmp,
renames it, saves the lines, writes deleted.json and then current.json. Any exception leaves current.json (the
last good build) untouched. With no system presets uploaded yet it ends cleanly with `waiting: True`. It runs
again (at most MAX_RUNS times in all) while the rebuild request is newer than the run's start. The newest KEEP
builds plus the installed one are kept.
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
from . import generate, lines as lines_mod
from .bbl import Store
from .errors import ProfileError

MAX_LIVE = 32 << 20
MAX_SYSTEM = 64 << 20
MAX_ENTRIES = 20_000
MAX_FILE = 4 << 20
MAX_TOTAL = 512 << 20
MAX_RUNS = 3
KEEP = 5
CHUNK = 64 * 1024
SUFFIXES = (".json", ".info")
STAMP_RE = re.compile(r"\d{8}-\d{6}(?:-[1-9]\d{0,5})?")
USER_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
NO_SYSTEM = "no Bambu Studio system presets yet: install and pair the PC sync"
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


def _state() -> dict:
    return _read_obj(_dir() / "build-state.json")


def _set_state(**changes) -> None:
    st = _state()
    st.update(changes)
    _write_json(_dir() / "build-state.json", st)


def _installed() -> dict | None:
    d = _read_obj(_dir() / "installed.json")
    return d if isinstance(d.get("stamp"), str) and STAMP_RE.fullmatch(d["stamp"]) else None


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
        if part in ("", ".", ".."):
            raise BadZip(f"entry {name!r}: empty, '.' and '..' path parts are not allowed")
        if _BAD_PART.search(part):
            raise BadZip(f"entry {name!r}: characters a file name cannot hold")
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


def _extract(zpath: Path, tree: Path) -> int:
    """Check every entry, then extract into `tree` counting the real bytes; returns the number of .json files."""
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
                    jsons += 1
                    try:
                        json.loads(dest.read_bytes().decode("utf-8"))
                    except (UnicodeDecodeError, ValueError):
                        raise BadZip(f"entry {rel!r} is not valid JSON") from None
            return jsons
        except BadZip:
            raise
        except (zipfile.BadZipFile, zipfile.LargeZipFile, NotImplementedError, RuntimeError, EOFError,
                zlib.error, ValueError, FileExistsError) as e:
            raise BadZip(f"the zip cannot be read ({e.__class__.__name__}: {e})") from None


def _safe_dir(name: str) -> None:
    body = name.rstrip("/")
    if not body or "\\" in body or body.startswith("/") or _DRIVE.match(body) \
            or any(p in ("", ".", "..") or _BAD_PART.search(p) for p in body.split("/")):
        raise BadZip(f"entry {name!r}: not a safe relative directory")


def store_upload(kind: str, src: BinaryIO, *, device_id: str, user_id: str | None = None) -> str:
    """Store the PC sync's zip of its user filament folder (`live`) or `system/BBL/filament` (`system`) and
    return its tree hash. Claims the sync owner. Raises OtherPc, BadZip or TooLarge; then nothing changed."""
    if kind not in ("live", "system"):
        raise ValueError(f"unknown upload kind {kind!r}")
    if user_id is not None and not USER_ID.fullmatch(user_id):
        raise ProfileError(400, "bad_request", "user_id may only have letters, digits, - and _ (at most 64)")
    check_owner(device_id)                      # refuse before reading the body
    cap = MAX_LIVE if kind == "live" else MAX_SYSTEM
    make_state_dir(_dir())
    tmp = Path(tempfile.mkdtemp(prefix=f"upload-{kind}-", suffix=".tmp", dir=_dir()))
    try:
        zpath = tmp / "upload.zip"
        _receive(src, zpath, cap)
        tree = tmp / "tree"
        jsons = _extract(zpath, tree)
        h = tree_hash(tree)
        with _locked("live.lock"):
            check_owner(device_id)
            make_state_dir(_live())
            dest = _live() / ("user" if kind == "live" else "system")
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
            meta["owner"] = device_id
            if kind == "live":
                if user_id is not None:
                    meta["user_id"] = user_id
                meta.update(live_hash=h, live_at=now)
            else:
                meta.update(system_hash=h, system_at=now, system_presets=jsons)
            _write_json(_live() / "meta.json", meta)
        return h
    finally:
        _rmtree(tmp)


# ---------- rebuild requests ----------

def request_rebuild(reason: str, live_hash: str | None = None) -> None:
    """Ask for a build: (re)write `profiles/rebuild-request`, which filament-kit-build.path watches."""
    make_state_dir(_dir())
    data = {"at": time.time(), "reason": str(reason), "live_hash": live_hash}
    _write_atomic(_request_path(), (json.dumps(data) + "\n").encode("utf-8"), 0o644, state_owned=True)


def _request() -> dict | None:
    """The rebuild request as read (never changed here): {at, live_hash}; `at` is the later of its own time and
    the file's mtime, so a bare `touch` counts too."""
    path = _request_path()
    try:
        st = path.stat()
    except OSError:
        return None
    data = _read_obj(path)
    at = data.get("at")
    at = float(at) if isinstance(at, (int, float)) and not isinstance(at, bool) else 0.0
    lh = data.get("live_hash")
    return {"at": max(at, st.st_mtime), "live_hash": lh if isinstance(lh, str) else None}


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
    cur = current()
    if cur:
        keep.add(cur["stamp"])
    for name in dirs:
        if name not in keep:
            _rmtree(root / name)


def _filament_map(manifest: dict) -> dict[str, str]:
    out = {}
    for lid, row in sorted(manifest.get("lines", {}).items()):
        for i in row.get("spoolman_ids", []):
            out.setdefault(str(i), lid)
    return dict(sorted(out.items(), key=lambda kv: int(kv[0])))


def _build_once(sm, now: float) -> dict:
    root = _builds()
    make_state_dir(root)
    for p in root.glob("*.tmp"):
        _rmtree(p)
    _set_state(last_attempt={"at": now, "ok": None, "error": None})
    stamp = _new_stamp(now)
    tmp = root / f"{stamp}.tmp"
    live_copy = root / f"{stamp}.live.tmp"
    final = root / stamp
    try:
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
        lib = library_mod.load()
        filaments = sm.get("filament")
        if not isinstance(filaments, list):
            raise ValueError("Spoolman returned no filament list")
        models = [p.model for p in registry.load().values() if p.model]
        snapshot = root / installed["stamp"] if installed and (root / installed["stamp"]).is_dir() else None
        before = _read_obj(_dir() / "deleted.json").get("deleted_before")
        deleted_before = {n for n in before if isinstance(n, str)} if isinstance(before, list) else set()
        restore_flag = _dir() / "restore-deleted"
        restore = restore_flag.exists()
        with lines_mod.locked():
            ls = lines_mod.load()
            manifest, new_lines = generate.build_all(
                filaments=filaments, models=models, store=store, library=lib, lines=ls, live=live,
                snapshot=snapshot, deleted_before=deleted_before, restore_deleted=restore, out_dir=tmp, now=now)
            problems = list(store.problems) + [p for p in manifest.get("problems", []) if p not in store.problems]
            manifest.update(stamp=stamp, created=now, live_hash=meta.get("live_hash"),
                            system_hash=meta.get("system_hash"), user_id=meta.get("user_id"), problems=problems,
                            filaments=_filament_map(manifest))
            with open(tmp / "BUILD.json", "w", encoding="utf-8", newline="\n") as fh:
                json.dump(manifest, fh, indent=2, ensure_ascii=False)
            os.replace(tmp, final)
            lines_mod.save(new_lines)
        _write_json(_dir() / "deleted.json", {"deleted_before": manifest.get("deleted", [])})
        _write_json(_dir() / "current.json", {"stamp": stamp, "created": now, "live_hash": meta.get("live_hash"),
                                              "presets": len(manifest.get("presets", [])),
                                              "problems": len(problems)})
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


def run_build(sm, *, now: float | None = None) -> dict:
    """Build every preset (see the module docstring); returns {stamp, ok, error, problems} of the last run, plus
    `waiting: True` when no system presets were uploaded yet (a clean end, not a crash)."""
    with _locked("build.lock"):
        result: dict = {}
        for _ in range(MAX_RUNS):
            started = time.time()
            result = _build_once(sm, now if now is not None else started)
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


def build_zip(stamp: str) -> bytes:
    """`BUILD.json` + `base/<name>.json|.info` of a kept build; ProfileError 404 for an unknown stamp."""
    if not (isinstance(stamp, str) and STAMP_RE.fullmatch(stamp)):
        raise _not_found(f"no build {stamp!r}")
    folder = _builds() / stamp
    if not (folder / "BUILD.json").is_file():
        raise _not_found(f"no build {stamp!r}")
    base = folder / "base"
    files = [("BUILD.json", folder / "BUILD.json")]
    if base.is_dir():
        files += sorted((f"base/{p.name}", p) for p in base.iterdir()
                        if p.is_file() and p.suffix.casefold() in SUFFIXES)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, path in files:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, path.read_bytes())
    return buf.getvalue()


def record_installed(stamp: str, device_id: str) -> dict:
    """The sync PC installed build `stamp`: {stamp, at}. OtherPc for another device, 404 for an unknown stamp."""
    with _locked("live.lock"):
        check_owner(device_id)
        if not (isinstance(stamp, str) and STAMP_RE.fullmatch(stamp)
                and (_builds() / stamp / "BUILD.json").is_file()):
            raise _not_found(f"no build {stamp!r}")
        at = time.time()
        _write_json(_dir() / "installed.json", {"stamp": stamp, "at": at, "device_id": device_id})
        return {"stamp": stamp, "at": at}


def _build_view() -> dict | None:
    c = current()
    if c is None:
        return None
    return {"stamp": c["stamp"], "live_hash": c.get("live_hash"), "created": c.get("created"),
            "presets": int(c.get("presets") or 0), "problems": int(c.get("problems") or 0)}


def _attempt_view() -> dict | None:
    la = _state().get("last_attempt")
    if not isinstance(la, dict):
        return None
    return {"at": la.get("at"), "ok": la.get("ok"), "error": la.get("error")}


def _installed_view() -> dict | None:
    i = _installed()
    return {"stamp": i["stamp"], "at": i.get("at")} if i else None


def state_view(device_id: str) -> dict:
    """`GET /api/sync/state`."""
    meta = _meta()
    req = _pending_request()
    return {"owner": owner(), "you": device_id, "user_id": meta.get("user_id"),
            "live_hash": meta.get("live_hash"), "system_hash": meta.get("system_hash"), "build": _build_view(),
            "last_attempt": _attempt_view(), "installed": _installed_view(),
            "rebuild_requested": {"at": req["at"], "live_hash": req["live_hash"]} if req else None}


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
    return {"lines": n_lines, "presets": len(m.get("presets", [])), "build": _build_view(),
            "last_attempt": _attempt_view(), "installed": _installed_view(),
            "pc": {"device_id": o, "last_upload": max(ups) if ups else None} if o else None,
            "stale": list(m.get("stale", [])), "problems": list(m.get("problems", []))[:20]}
