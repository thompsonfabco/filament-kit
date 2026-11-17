"""The event store (ruling R80 section 1, docs/design 03): one place where the Hub writes what happens.

Layout under `<state>/events/`:
  <yyyy-mm>.xml    one file per month, one <event> per event, APPENDED without rewriting the file. The root element
                   is never closed on disk; a reader adds the closing tag and drops a torn last element (a crash in
                   the middle of an append), and the next append cuts the torn tail off before it writes.
  conditions.xml   the conditions raised now (the event that raised each one), rewritten atomically
  next-id          the counter: the id the next event gets. It is raised before the event is appended, so a crash
                   can lose an id but never reuse one
  .lock            the lock file two processes (the Hub service and the command line) take around a write

Owner and mode (R464): whoever writes first (the Hub, or root: the command line, the installer), every directory and
file the store creates or touches belongs to the owner of the state folder, files 0644 and the events directory with
the state folder's mode bits, so the Hub service can always write and the web unit can read. As root the store chowns
(guarded: only when the owner differs); nothing is ever followed through a symbolic link (O_NOFOLLOW, new files with
O_EXCL; a link at events/, a month file, conditions.xml or next-id is refused with an error). The same logic as
storage.py's `_write`, kept local here so the two can be unified at the merge. No JSON is stored.
Texts are not stored and not built here (EA3): an event is its kind, its subject and actor and named values (all
text, as stored). The catalogue of kinds and value names is event_kinds.py.
"""
from __future__ import annotations

import copy
import errno
import logging
import os
import re
import secrets
import stat
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config, event_kinds

log = logging.getLogger("filament_kit.events")

try:
    import fcntl
except ImportError:                    # Windows
    fcntl = None
    import msvcrt

VERSION = "1"
KEEP_DAYS, KEEP_MIN, KEEP_MAX = 400, 30, 3650
WAIT_MAX = 55
POLL = 0.25                            # seconds between looks at next-id while a request waits
LIMIT_DEFAULT, LIMIT_MAX = 100, 1000
_MONTH = re.compile(r"^(\d{4})-(\d{2})\.xml$")
_EVENT = re.compile(r"<event\b.*?</event>", re.S)
_BAD_CHARS = re.compile("[^\u0009\u000a\u000d -퟿-�\U00010000-\U0010ffff]")
_END = b"</event>\n"
FILE_MODE = 0o644
RETRY_REPLACE = os.name == "nt"        # Windows refuses a rename over a file another process has open (a reader)
REPLACE_TRIES, REPLACE_PAUSE = 40, 0.025


def _flag(name: str) -> int:
    return getattr(os, name, 0)


_READ = os.O_RDONLY | _flag("O_NOFOLLOW") | _flag("O_CLOEXEC") | _flag("O_BINARY")
_OPEN = os.O_RDWR | _flag("O_NOFOLLOW") | _flag("O_CLOEXEC") | _flag("O_BINARY")
_NEW = os.O_RDWR | os.O_CREAT | os.O_EXCL | _flag("O_NOFOLLOW") | _flag("O_CLOEXEC") | _flag("O_BINARY")


class EventError(ValueError):
    """The call is not valid: an unknown kind, a value the kind does not have, a bad subject or actor."""


def _text(v) -> str:
    return _BAD_CHARS.sub(" ", str(v))               # XML 1.0 cannot hold a control character; one would make the
                                                      # month unreadable for good


def _is_root() -> bool:
    return getattr(os, "geteuid", lambda: -1)() == 0


def _state_owner(root: Path) -> tuple[int, int]:
    """The user and group of the state folder (the parent of events/): whose the store's files must be."""
    st = os.stat(root.parent)
    return st.st_uid, st.st_gid


def _tmp_name(f: Path) -> Path:
    return f.with_name(f"{f.name}.{secrets.token_hex(6)}.tmp")


def _refuse_link(path: Path) -> None:
    try:
        if stat.S_ISLNK(os.lstat(path).st_mode):
            raise EventError(f"{path.name} is a symbolic link, so the Hub does not use it. Remove the link.")
    except FileNotFoundError:
        pass


def _open(path: Path, flags: int, mode: int = FILE_MODE) -> int:
    try:
        return os.open(path, flags, mode)
    except OSError as e:
        if e.errno == errno.ELOOP:
            raise EventError(f"{path.name} is a symbolic link, so the Hub does not use it. Remove the link.") from None
        raise


def _read_bytes(path: Path) -> bytes:
    """The file's bytes, never through a link (a link raises EventError); OSError as the file system says."""
    with os.fdopen(_open(path, _READ), "rb") as fh:
        return fh.read()


def _sync_dir(path: Path) -> None:
    """fsync the directory, so a new name or a rename survives a power loss (POSIX only)."""
    if os.name == "nt":
        return
    fd = os.open(path, os.O_RDONLY | _flag("O_DIRECTORY") | _flag("O_CLOEXEC"))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _replace(tmp: Path, f: Path) -> None:
    """os.replace; on Windows a short bounded retry while a reader has `f` open, then a clear error."""
    tries = REPLACE_TRIES if RETRY_REPLACE else 1
    for i in range(tries):
        try:
            os.replace(tmp, f)
            return
        except PermissionError as e:
            if i == tries - 1:
                if not RETRY_REPLACE:
                    raise
                raise EventError(f"{f.name} could not be replaced: another program keeps it open ({e}).") from None
            time.sleep(REPLACE_PAUSE)


_cache: dict[str, tuple[tuple, list[dict]]] = {}       # month file -> (its size and time, its events)


def _utc(now: datetime | None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now.astimezone(timezone.utc) if now.tzinfo else now.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------- elements

def _party(p, types: tuple[str, ...], what: str) -> dict:
    if isinstance(p, str):
        p = {"type": p}
    if not isinstance(p, dict) or p.get("type") not in types:
        raise EventError(f"The {what} type must be one of {', '.join(types)}.")
    return {"type": p["type"], "id": _text(p.get("id") or ""), "name": _text(p.get("name") or "")}


def _element(ev: dict) -> ET.Element:
    a = {"id": str(ev["id"]), "at": ev["at"], "kind": ev["kind"], "severity": ev["severity"],
         "actor": ev["actor"]["type"], "subject": ev["subject"]["type"]}
    for tag, party in (("actor", ev["actor"]), ("subject", ev["subject"])):
        for f in ("id", "name"):
            if party[f]:
                a[f"{tag}-{f}"] = party[f]
    if ev["condition"]:
        a["condition"], a["state"] = ev["condition"]["key"], ev["condition"]["state"]
    el = ET.Element("event", a)
    for name, value in ev["data"].items():
        ET.SubElement(el, "v", {"name": name}).text = value
    return el


def _dump(el: ET.Element) -> bytes:
    return ET.tostring(el, encoding="utf-8", short_empty_elements=False)


def _event(el: ET.Element) -> dict | None:
    try:
        cond = el.get("condition")
        return {"id": int(el.get("id")), "at": el.get("at", ""), "kind": el.get("kind", ""),
                "severity": el.get("severity", "info"),
                "subject": {"type": el.get("subject", ""), "id": el.get("subject-id", ""),
                            "name": el.get("subject-name", "")},
                "actor": {"type": el.get("actor", ""), "id": el.get("actor-id", ""), "name": el.get("actor-name", "")},
                "data": {v.get("name", ""): v.text or "" for v in el.findall("v")},
                "condition": {"key": cond, "state": el.get("state", "")} if cond else None}
    except (TypeError, ValueError):
        return None


def _parse(raw: bytes) -> list[dict]:
    """The events of a month file's bytes: the whole file when it parses (closing tag added), else every complete
    <event> element on its own, so a torn last element (or one damaged in the middle) costs only itself."""
    text = raw.decode("utf-8", errors="replace")
    out: list[dict] = []
    try:
        root = ET.fromstring(text.rstrip() + ("" if text.rstrip().endswith("</events>") else "\n</events>"))
        elements = list(root.iter("event"))
    except ET.ParseError:
        elements = []
        for m in _EVENT.finditer(text):
            try:
                elements.append(ET.fromstring(m.group(0)))
            except ET.ParseError:
                continue
    for el in elements:
        ev = _event(el)
        if ev:
            out.append(ev)
    return out


def _read_file(path: Path) -> list[dict]:
    """The events of a month file, parsed again only when its size or time changed (a month is read often, and
    only the newest one changes)."""
    try:
        st = os.lstat(path)
        sig = (st.st_size, st.st_mtime_ns, st.st_ino)
        hit = _cache.get(str(path))
        if hit and hit[0] == sig:
            return hit[1]
        evs = _parse(_read_bytes(path))
        _cache[str(path)] = (sig, evs)
        return evs
    except (OSError, EventError):
        _cache.pop(str(path), None)
        return []


# ---------------------------------------------------------------- locking

class _FileLock:
    """An exclusive lock on events/.lock: flock where there is one, msvcrt byte lock on Windows."""

    def __init__(self, path: Path, needed: bool, give=None):
        self.path, self.needed, self.give, self.fd = path, needed, give, None

    def __enter__(self):
        try:
            try:
                self.fd = _open(self.path, _OPEN)
            except FileNotFoundError:
                try:
                    self.fd = _open(self.path, _NEW)
                except FileExistsError:          # another process made it a moment ago
                    self.fd = _open(self.path, _OPEN)
        except PermissionError:
            if self.needed:                      # a reader that cannot open the lock file reads without it
                raise
            return self
        if self.give:
            self.give(self.fd)
        if fcntl:
            fcntl.flock(self.fd, fcntl.LOCK_EX)
        else:
            while True:
                try:
                    os.lseek(self.fd, 0, os.SEEK_SET)
                    msvcrt.locking(self.fd, msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(0.01)
        return self

    def __exit__(self, *exc):
        if self.fd is not None:
            if not fcntl:
                os.lseek(self.fd, 0, os.SEEK_SET)
                msvcrt.locking(self.fd, msvcrt.LK_UNLCK, 1)
            os.close(self.fd)                    # closing drops the flock
            self.fd = None


_shared: dict[str, tuple[threading.Lock, threading.Condition]] = {}
_shared_guard = threading.Lock()


def _shared_for(root: Path) -> tuple[threading.Lock, threading.Condition]:
    with _shared_guard:
        return _shared.setdefault(str(root), (threading.Lock(), threading.Condition()))


# ---------------------------------------------------------------- the store

class EventStore:
    """The store under `root` (default: `<state>/events`, found at each call so a changed state folder is followed)."""

    def __init__(self, root: Path | str | None = None):
        self._root = Path(root) if root is not None else None

    @property
    def root(self) -> Path:
        return self._root if self._root is not None else config.paths().state / "events"

    # ---- files
    def _months(self) -> list[Path]:
        try:
            return sorted(p for p in self.root.iterdir() if _MONTH.match(p.name))
        except OSError:
            return []

    def _give(self, fd: int) -> None:
        """Mode 0644 and, as root, the state folder's owner (only when it differs), on a file this process opened."""
        st = os.fstat(fd)
        if hasattr(os, "fchmod") and stat.S_IMODE(st.st_mode) != FILE_MODE:
            os.fchmod(fd, FILE_MODE)
        if _is_root():
            uid, gid = _state_owner(self.root)
            if (st.st_uid, st.st_gid) != (uid, gid):
                os.fchown(fd, uid, gid)

    def _guard(self) -> None:
        _refuse_link(self.root)

    def _ensure_root(self) -> None:
        """events/ exists, is no link, has the state folder's mode bits and, as root, its owner."""
        self._guard()
        self.root.mkdir(parents=True, exist_ok=True)
        self._guard()
        st, state = os.lstat(self.root), os.stat(self.root.parent)
        if stat.S_IMODE(st.st_mode) != stat.S_IMODE(state.st_mode):
            os.chmod(self.root, stat.S_IMODE(state.st_mode))
        if _is_root():
            uid, gid = _state_owner(self.root)
            if (st.st_uid, st.st_gid) != (uid, gid):
                os.lchown(self.root, uid, gid)

    def _counter(self) -> int:
        """The id the next event gets. A missing or unreadable next-id is rebuilt from the newest events on disk."""
        try:
            n = int(_read_bytes(self.root / "next-id").decode("ascii").strip())
            if n >= 1:
                return n
        except (OSError, ValueError, EventError):
            pass
        top = 0
        for p in self._months():                          # by id, not by name: the clock may have stepped back
            top = max([top] + [e["id"] for e in _read_file(p)])
        top = max([top, self._high_water()] + [e["id"] for e in self._load_conditions().values()])
        return top + 1

    def _high_water(self) -> int:
        """The highest id ever given, recorded by prune before it deletes a month (so ids are never reused)."""
        try:
            return int(_read_bytes(self.root / "high-water").decode("ascii").strip())
        except (OSError, ValueError, EventError):
            return 0

    def _put_counter(self, n: int) -> None:
        self._atomic(self.root / "next-id", f"{n}\n".encode("ascii"))

    def _atomic(self, f: Path, data: bytes) -> None:
        """Write `f` through a new file only this process made (O_EXCL | O_NOFOLLOW), then rename it over `f`. A link
        at `f` is refused; a name planted for the temporary file is skipped."""
        _refuse_link(f)
        for _ in range(20):
            tmp = _tmp_name(f)
            try:
                fd = _open(tmp, _NEW)
                break
            except FileExistsError:
                continue
        else:
            raise OSError(errno.EEXIST, "no free name for the temporary file")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
                self._give(fh.fileno())
            _replace(tmp, f)
            _sync_dir(f.parent)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _append(self, path: Path, month: str, chunk: bytes) -> None:
        header = f'<events version="{VERSION}" month="{month}">\n'.encode("ascii")
        try:
            fd, existed = _open(path, _OPEN), True
        except FileNotFoundError:
            fd, existed = _open(path, _NEW), False
        with os.fdopen(fd, "r+b") as fh:
            self._give(fh.fileno())
            size = fh.seek(0, os.SEEK_END)
            if existed:
                fh.seek(max(size - len(_END), 0))
                tail = fh.read()
                if not (tail == _END or (size == len(header) and self._head(fh, size) == header)):
                    self._cut_torn_tail(fh, header)       # a crash left half an element (or half a header)
            else:
                fh.write(header)
            fh.seek(0, os.SEEK_END)
            fh.write(chunk + b"\n")
            fh.flush()
            os.fsync(fh.fileno())
        if not existed:
            _sync_dir(path.parent)

    @staticmethod
    def _head(fh, n: int) -> bytes:
        fh.seek(0)
        return fh.read(n)

    @staticmethod
    def _cut_torn_tail(fh, header: bytes) -> None:
        fh.seek(0)
        data = fh.read()
        cut = data.rfind(_END)
        keep = cut + len(_END) if cut >= 0 else (len(header) if data.startswith(header) else 0)
        fh.truncate(keep)
        if keep == 0:
            fh.seek(0)
            fh.write(header)
        fh.seek(0, os.SEEK_END)

    # ---- conditions
    def _load_conditions(self) -> dict[str, dict]:
        try:
            root = ET.fromstring(_read_bytes(self.root / "conditions.xml"))
        except (OSError, EventError, ET.ParseError):
            return {}
        out = {}
        for el in root.iter("event"):
            ev = _event(el)
            if ev and ev["condition"]:
                out[ev["condition"]["key"]] = ev
        return out

    def _save_conditions(self, conds: dict[str, dict]) -> None:
        root = ET.Element("conditions", {"version": VERSION})
        for ev in sorted(conds.values(), key=lambda e: e["id"]):
            root.append(_element(ev))
        ET.indent(root, space="  ")
        self._atomic(self.root / "conditions.xml", _dump(root) + b"\n")

    # ---- write
    def write(self, kind: str, subject, actor, data: dict | None = None, *, severity: str | None = None,
              key: str | None = None, now: datetime | None = None) -> dict:
        """Write one event and return it (the dict `read` returns). `subject` and `actor` are {type, id, name} (id
        and name optional; a bare string is the type). `severity` is the kind's own unless the kind allows two
        (storage.low: warn or bad). `key` is the condition key's suffix when it is not the subject id (a check row's
        key). A kind that raises a condition raises it (once: one already raised stays, unless this is worse); a
        kind that clears one clears it, whether or not it was raised."""
        k = event_kinds.get(kind)
        if k is None:
            raise EventError(f"Unknown event kind {kind!r}.")
        if not k.emitted:
            raise EventError(f"The event kind {kind} is reserved for a later phase and cannot be written yet.")
        sev = severity or k.severity
        if sev not in k.severities:
            raise EventError(f"{kind} has severity {' or '.join(k.severities)}, not {sev!r}.")
        subject = _party(subject, event_kinds.SUBJECT_TYPES, "subject")
        actor = _party(actor, event_kinds.ACTOR_TYPES, "actor")
        values = {}
        for name, value in (data or {}).items():
            if name not in k.values:
                raise EventError(f"{kind} has no value called {name!r}. It has: {', '.join(k.values) or 'none'}.")
            if value is not None:
                values[name] = _text(value)
        ckey = event_kinds.condition_key(k, subject["id"], None if key is None else _text(key))
        if ckey is not None and ckey.endswith(":"):
            raise EventError(f"{kind} needs a subject id (or a key) for its condition.")
        at = _utc(now)
        ev = {"id": 0, "at": at.strftime("%Y-%m-%dT%H:%M:%SZ"), "kind": kind, "severity": sev, "subject": subject,
              "actor": actor, "data": values,
              "condition": {"key": ckey, "state": "raised" if k.condition == event_kinds.RAISES else "cleared"}
              if ckey else None}
        tlock, cond = _shared_for(self.root)
        with tlock:
            self._ensure_root()
            month = self.root / f"{ev['at'][:7]}.xml"
            for f in (month, self.root / "next-id", self.root / "conditions.xml"):
                _refuse_link(f)                              # before anything is written
            with _FileLock(self.root / ".lock", needed=True, give=self._give):
                n = self._counter()
                ev["id"] = n
                self._put_counter(n + 1)
                self._append(month, ev["at"][:7], _dump(_element(ev)))
                self._conditions_for(ev)
        with cond:
            cond.notify_all()
        return ev

    @staticmethod
    def _apply(conds: dict[str, dict], ev: dict) -> bool:
        """Raise or clear the condition of one event in `conds`; True when `conds` changed."""
        c = ev["condition"]
        if not c:
            return False
        if c["state"] == "raised":
            cur = conds.get(c["key"])
            if cur is not None and (event_kinds.SEVERITIES.index(ev["severity"])
                                    <= event_kinds.SEVERITIES.index(cur["severity"])):
                return False                             # raised once: it stays as it was until it gets worse
            conds[c["key"]] = ev
            return True
        return conds.pop(c["key"], None) is not None

    def _conditions_for(self, ev: dict) -> None:
        """Bring conditions.xml up to the event just appended. The event is committed by now, so a failure here is
        not the caller's error: it is logged and a marker (conditions-stale, holding the first id not applied) makes
        the next write or `conditions()` replay the events from the log (`_heal`)."""
        try:
            self._heal()
            if ev["condition"]:
                conds = self._load_conditions()
                if self._apply(conds, ev):
                    self._save_conditions(conds)
        except (OSError, EventError) as e:
            log.warning("event %s is written but conditions.xml was not updated (%s); it is repaired at the next "
                        "write or read", ev["id"], e)
            try:
                if not (self.root / "conditions-stale").exists():
                    self._atomic(self.root / "conditions-stale", f"{ev['id']}\n".encode("ascii"))
            except (OSError, EventError):
                pass

    def _heal(self) -> None:
        """If a marker says conditions.xml missed events, replay those from the month files (in id order), save, and
        remove the marker. Called under the file lock."""
        marker = self.root / "conditions-stale"
        try:
            first = int(_read_bytes(marker).decode("ascii").strip())
        except (OSError, EventError):
            return
        except ValueError:
            first = 0
        conds = self._load_conditions()
        for ev in self._events_after(first - 1, ()):
            self._apply(conds, ev)
        self._save_conditions(conds)
        marker.unlink(missing_ok=True)

    # ---- read
    def last_id(self) -> int:
        """The id of the newest event (0 when there is none)."""
        tlock, _ = _shared_for(self.root)
        with tlock:
            self._guard()
            try:
                with _FileLock(self.root / ".lock", needed=False):
                    return self._counter() - 1
            except OSError:
                return 0

    def _events_after(self, since: int, kinds: tuple[str, ...]) -> list[dict]:
        out: list[dict] = []
        for path in self._months():                      # every month: by id, not by name (the clock can step back)
            out += [e for e in _read_file(path) if e["id"] > since and (not kinds or e["kind"].startswith(kinds))]
        out.sort(key=lambda e: e["id"])
        return out

    def read(self, since: int = 0, limit: int = LIMIT_DEFAULT, kinds=None, wait: float = 0) -> dict:
        """Events newer than `since`, oldest first, at most `limit` (1 to 1000), whose kind starts with one of
        `kinds` (a list or a comma-separated string of prefixes; none = all). `wait` (0 to 55 s) blocks until such an
        event exists; the answer is empty after the time. Returns {"events": [...], "next": id}: continue with
        since=next."""
        since = max(int(since or 0), 0)
        limit = min(max(int(limit or LIMIT_DEFAULT), 1), LIMIT_MAX)
        if isinstance(kinds, str):
            kinds = kinds.split(",")
        prefixes = tuple(p.strip() for p in (kinds or ()) if p and p.strip())
        deadline = time.monotonic() + min(max(float(wait or 0), 0.0), WAIT_MAX)
        _, cond = _shared_for(self.root)
        seen = None                                      # the newest id looked at, so a wait reads only on news
        while True:
            newest = self.last_id()
            if seen is None or newest > seen:
                seen = newest
                evs = copy.deepcopy(self._events_after(since, prefixes)[:limit])
                if evs:
                    return {"events": evs, "next": evs[-1]["id"]}
            left = deadline - time.monotonic()
            if left <= 0:
                return {"events": [], "next": since}
            with cond:
                cond.wait(min(POLL, left))               # a writer in this process wakes it at once; another
                                                         # process is noticed by the next look at next-id

    def conditions(self) -> list[dict]:
        """The conditions raised now: the event that raised each, oldest first."""
        tlock, _ = _shared_for(self.root)
        with tlock:
            self._guard()
            if (self.root / "conditions-stale").exists():
                try:
                    with _FileLock(self.root / ".lock", needed=True, give=self._give):
                        self._heal()
                except (OSError, EventError) as e:
                    log.warning("conditions.xml could not be repaired yet (%s)", e)
            return sorted(self._load_conditions().values(), key=lambda e: e["id"])

    def is_raised(self, key: str) -> bool:
        return key in {e["condition"]["key"] for e in self.conditions()}

    # ---- retention
    def prune(self, keep_days: int = KEEP_DAYS, now: datetime | None = None) -> list[str]:
        """Delete whole month files that ended more than `keep_days` ago (30 to 3650; out of range is clamped),
        nothing else. Returns the file names deleted. The daily job calls it with the setting events.keep_days."""
        keep_days = min(max(int(keep_days), KEEP_MIN), KEEP_MAX)
        cutoff = _utc(now) - timedelta(days=keep_days)
        gone = []
        tlock, _ = _shared_for(self.root)
        with tlock:
            old = []
            for path in self._months():
                y, m = (int(g) for g in _MONTH.match(path.name).groups())
                if 1 <= m <= 12 and datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=timezone.utc) <= cutoff:
                    old.append(path)                     # the month ended before the cutoff
            if old:
                self._guard()
                with _FileLock(self.root / ".lock", needed=True, give=self._give):
                    self._atomic(self.root / "high-water", f"{self._counter() - 1}\n".encode("ascii"))
                    for path in old:                     # the highest id is recorded first: ids are never reused
                        path.unlink(missing_ok=True)
                        _cache.pop(str(path), None)
                        gone.append(path.name)
                    _sync_dir(self.root)
        return gone


# ---------------------------------------------------------------- the Hub's own store

def store() -> EventStore:
    return EventStore()


def write(kind: str, subject, actor, data: dict | None = None, **kw) -> dict:
    return store().write(kind, subject, actor, data, **kw)


def read(since: int = 0, limit: int = LIMIT_DEFAULT, kinds=None, wait: float = 0) -> dict:
    return store().read(since, limit, kinds, wait)


def conditions() -> list[dict]:
    return store().conditions()


def is_raised(key: str) -> bool:
    return store().is_raised(key)


def last_id() -> int:
    return store().last_id()


def prune(keep_days: int = KEEP_DAYS, now: datetime | None = None) -> list[str]:
    return store().prune(keep_days, now)
