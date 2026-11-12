"""File operations for root on names another user can change (POSIX only).

The kit server's user owns /var/lib/filament-kit, and the web unit's user owns /var/lib/filament-kit-web. When
root (`modules apply`) acts on names in those folders, either user could have swapped a name for a symbolic link
to a file of root's, so nothing here goes through a link:

  - folders are opened one part at a time with O_NOFOLLOW | O_DIRECTORY, and the work below them goes through the
    folder's descriptor (dir_fd), so a part swapped for a link later is never walked through;
  - a file is opened with O_NOFOLLOW and changed through its descriptor (fchmod, fchown, fsetxattr), after
    checking that it is the same regular file or folder that lstat saw (no FIFO or device is opened);
  - a file root creates is made with O_CREAT | O_EXCL | O_NOFOLLOW, so a planted link (dangling or not) is never
    used as the name of a new file.

A link that is skipped is logged as a warning with its path."""
from __future__ import annotations

import logging
import os
import stat
from collections.abc import Iterator
from pathlib import Path

log = logging.getLogger(__name__)

NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_NODE = os.O_RDONLY | NOFOLLOW | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOCTTY", 0) | getattr(os, "O_CLOEXEC", 0)


class LinkRefused(OSError):
    """A folder on the way is a link (or not a folder): nothing below it is touched."""


def skipped(where, why: str = "a symbolic link") -> None:
    log.warning("skipped %s: %s; root does not act through it (remove it if you did not make it)", where, why)


def open_dir(path, *parts: str) -> int:
    """A descriptor of the folder `path`/`parts`, each part opened without following a link (LinkRefused when one
    is a link or not a folder; FileNotFoundError when one is missing). The caller closes it."""
    try:
        fd = os.open(path, os.O_RDONLY | DIRECTORY | NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
    except OSError as e:
        if isinstance(e, FileNotFoundError):
            raise
        raise LinkRefused(e.errno, f"{path} is a link or not a folder", str(path)) from None
    where = Path(path)
    try:
        for part in parts:
            where = where / part
            nfd = open_dir_at(fd, part, where)
            os.close(fd)
            fd = nfd
    except BaseException:
        os.close(fd)
        raise
    return fd


def open_dir_at(dir_fd: int, name: str, where=None) -> int:
    """A descriptor of the folder `name` in `dir_fd`, never through a link (LinkRefused)."""
    try:
        return os.open(name, os.O_RDONLY | DIRECTORY | NOFOLLOW | getattr(os, "O_CLOEXEC", 0), dir_fd=dir_fd)
    except FileNotFoundError:
        raise
    except OSError as e:
        where = where if where is not None else name
        raise LinkRefused(e.errno, f"{where} is a link or not a folder", str(where)) from None


def lstat_at(name: str, dir_fd: int) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None


def open_node(name: str, dir_fd: int, where=None, *, dirs: bool = True) -> int | None:
    """A read-only descriptor of the regular file (or, with `dirs`, folder) `name` in `dir_fd`, never through a
    link: None (a link, a hard-linked file or a FIFO/device logged as skipped) when it is anything else or missing."""
    st = lstat_at(name, dir_fd)
    if st is None:
        return None
    where = where if where is not None else name
    if stat.S_ISLNK(st.st_mode):
        skipped(where)
        return None
    is_dir = stat.S_ISDIR(st.st_mode)
    if not (stat.S_ISREG(st.st_mode) or (dirs and is_dir)):
        skipped(where, "not a regular file" + (" or folder" if dirs else ""))
        return None
    if not is_dir and st.st_nlink > 1:
        skipped(where, "a hard link (another name for a file that may be outside this folder)")
        return None
    try:
        fd = os.open(name, _NODE | (DIRECTORY if is_dir else 0), dir_fd=dir_fd)
    except OSError as e:
        skipped(where, f"could not be opened without following a link ({e.strerror})")
        return None
    got = os.fstat(fd)
    if (got.st_dev, got.st_ino) != (st.st_dev, st.st_ino):
        os.close(fd)
        skipped(where, "changed while it was being opened")
        return None
    return fd


def create_or_open(name: str, dir_fd: int, mode: int, where=None) -> tuple[int | None, bool]:
    """(descriptor, created) of the regular file `name` in `dir_fd`: made with O_EXCL | O_NOFOLLOW when missing,
    else the existing one opened without following a link. (None, False) for a link or anything not a regular
    file (logged)."""
    try:
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | NOFOLLOW | getattr(os, "O_CLOEXEC", 0), mode,
                     dir_fd=dir_fd)
        return fd, True
    except FileExistsError:
        pass
    return open_node(name, dir_fd, where, dirs=False), False


def walk(dir_fd: int, where) -> Iterator[tuple[int, str, str]]:
    """(descriptor of the folder, name, path for messages) of every entry below the folder `dir_fd`, folders
    before their contents; never descends into a link (os.fwalk with follow_symlinks=False on the descriptor)."""
    for rel, dirs, files, fd in os.fwalk(".", dir_fd=dir_fd, follow_symlinks=False):
        base = Path(where) / rel if rel != "." else Path(where)
        for name in [*dirs, *files]:
            yield fd, name, str(base / name)
