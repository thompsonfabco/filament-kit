"""The first-run file (R82 section 4 point 6): what the Getting started panel needs that cannot be computed.

One XML file, `firstrun.xml`, in the Hub's STATE folder (never beside the config file: the Hub cannot write there):

    <firstrun version="1" hidden="false" finished="false"><answered what="name"/>...</firstrun>

  - `hidden`: the owner pressed Hide, or the Hub was updated from a version without the panel, or restored from a backup.
  - `finished`: every shown step was done and the panel said "All set" once; it never shows again.
  - `answered`: the three steps whose "done" is a fact of the past, not of the present: `name`, `storage`, `features`
    (the installer's question was answered, the page saved it once, or Keep was pressed).

Owned like storage.xml: the state folder's owner, mode 644, written by a temporary file and a rename under a lock,
never through a symbolic link. Written by the installer (as root) and by the Hub process itself (Hide, Show, Keep, the
marks); never through the root helper. A start never fails for it: a file that is missing, unreadable, a link or not
valid reads as hidden, and a write that fails returns False and changes nothing else.

Run as a program (`python -I -m filament_kit.firstrun new [WHAT...] | mark WHAT | hidden`) for install.sh.
"""
from __future__ import annotations

import errno
import logging
import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import quoteattr

import defusedxml.ElementTree as DET
from defusedxml import DefusedXmlException

from . import config, locks, pairing

log = logging.getLogger("filament_kit.firstrun")

FILE = "firstrun.xml"
VERSION = "1"
MODE = 0o644
MARKS = ("name", "storage", "features")         # the steps answered once (their ids in the panel's contract)

_LOCK = locks.ProcessLock(lambda: config.paths().state / "firstrun.lock")


@dataclass(frozen=True)
class FirstRun:
    hidden: bool = True              # no file (an updated Hub) or an unreadable one: hidden
    finished: bool = False
    answered: frozenset = frozenset()
    present: bool = False            # the file exists and was read

    @property
    def shows(self) -> bool:
        """Does the panel show: a file of this version or later is there, not hidden, not finished."""
        return self.present and not self.hidden and not self.finished


def _file() -> Path:
    return config.paths().state / FILE


def _to_xml(st: FirstRun) -> str:
    marks = "".join(f"<answered what={quoteattr(w)}/>" for w in MARKS if w in st.answered)
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<firstrun version={quoteattr(VERSION)} '
            f'hidden={quoteattr(str(st.hidden).lower())} finished={quoteattr(str(st.finished).lower())}>'
            f"{marks}</firstrun>\n")


def _from_xml(data: bytes) -> FirstRun:
    root = DET.fromstring(data)
    if root.tag != "firstrun":
        raise ValueError("not a firstrun file")
    flag = lambda v: str(v).strip().lower() == "true"          # noqa: E731
    marks = frozenset(e.get("what") for e in root.findall("answered") if e.get("what") in MARKS)
    return FirstRun(hidden=flag(root.get("hidden")), finished=flag(root.get("finished")),
                    answered=marks, present=True)


def _read() -> FirstRun | None:
    """The file as written, None when there is none. Raises OSError or ValueError for one that cannot be read."""
    f = _file()
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(f, flags)
    except FileNotFoundError:
        return None
    except OSError as e:
        if e.errno == errno.ELOOP:
            raise ValueError(f"{f.name} is a symbolic link") from None
        raise
    with os.fdopen(fd, "rb") as fh:
        data = fh.read(65536)
    try:
        return _from_xml(data)
    except (DET.ParseError, DefusedXmlException, UnicodeDecodeError) as e:
        raise ValueError(f"{f.name} is not valid: {e}") from None


def load() -> FirstRun:
    """The saved state; never raises. A missing or unreadable file reads as hidden (the panel is not forced on a Hub
    that was installed before it, and a broken file changes nothing else)."""
    try:
        return _read() or FirstRun()
    except (OSError, ValueError) as e:
        log.warning("first-run file not read, the Getting started panel stays hidden: %s", e)
        return FirstRun()


def _write(st: FirstRun) -> None:
    f = _file()
    try:
        if stat.S_ISLNK(os.lstat(f).st_mode):
            raise OSError(errno.ELOOP, f"{f.name} is a symbolic link")
    except FileNotFoundError:
        pass
    pairing.make_state_dir(f.parent)
    pairing._write_atomic(f, _to_xml(st).encode("utf-8"), MODE, state_owned=True)


def _change(update, create: bool = False) -> bool:
    """Read, let `update(state)` return the new one (or None for no change), write: under the lock. False when nothing
    was written because the file cannot be used or the write failed; never raises."""
    try:
        with _LOCK:
            try:
                now = _read()
            except (OSError, ValueError):
                return False                     # an unreadable file is left as it is
            if now is None and not create:
                now = FirstRun()
            new = update(now or FirstRun(hidden=False, present=True))
            if new is None or new == now:
                return now is not None
            _write(FirstRun(new.hidden, new.finished, new.answered, True))
            return True
    except OSError as e:
        log.warning("first-run file not written: %s", e)
        return False


def install_first(answered=()) -> bool:
    """The installer's first install: make the file with the panel shown and the steps the installer asked marked. A
    file that is already there is not touched (a re-run is not a first install)."""
    marks = frozenset(w for w in answered if w in MARKS)
    try:
        with _LOCK:
            if _file().exists() or os.path.islink(_file()):
                return False
            _write(FirstRun(hidden=False, answered=marks, present=True))
            return True
    except OSError as e:
        log.warning("first-run file not written: %s", e)
        return False


def mark(what: str) -> bool:
    """Step `what` (name, storage, features) is answered: saved on the page once, asked by the installer, or Keep."""
    if what not in MARKS:
        raise ValueError(f"unknown step {what!r}")
    return _change(lambda s: FirstRun(s.hidden, s.finished, s.answered | {what}, True))


def set_hidden(hidden: bool) -> bool:
    """Hide this list (True) or Show (False)."""
    return _change(lambda s: FirstRun(bool(hidden), s.finished, s.answered, True))


def finish() -> bool:
    """Every shown step is done and "All set" was said once: the panel is gone for good."""
    return _change(lambda s: FirstRun(s.hidden, True, s.answered, True))


def hide_after_restore() -> bool:
    """A Hub restored from a backup starts hidden: the backup's file (if it carried one) is hidden, and a backup from
    before the panel gets a hidden file."""
    return _change(lambda s: FirstRun(True, s.finished, s.answered, True), create=True)


def _main(argv: list[str]) -> int:
    if argv[:1] == ["new"] and all(w in MARKS for w in argv[1:]):
        install_first(argv[1:])
        return 0
    if len(argv) == 2 and argv[0] == "mark" and argv[1] in MARKS:
        return 0 if mark(argv[1]) else 1
    print("usage: python -I -m filament_kit.firstrun new [name|storage|features ...] | mark name|storage|features",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
