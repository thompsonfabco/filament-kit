"""POSIX ACLs on Linux without the `acl` package: the `system.posix_acl_access` / `system.posix_acl_default`
extended attributes, read and written directly (format of linux/posix_acl_xattr.h, version 2).

Used to give the web unit's own user (filament-kit-web, never in the filament-kit group) exactly the files and
folders it needs from the kit server's state and settings (apply's `web_state`, and every root writer of a file
the web reads: config.json, web_passphrase, anthropic_key). A grant keeps the entries already there, adds or
replaces the named users given and recomputes the mask. Everything is a no-op where xattrs or ACLs are not
supported (Windows, a file system without ACLs): `supported()` says which."""
from __future__ import annotations

import os
import stat
import struct
from pathlib import Path

from . import nofollow

ACCESS, DEFAULT = "system.posix_acl_access", "system.posix_acl_default"
VERSION = 2
USER_OBJ, USER, GROUP_OBJ, GROUP, MASK, OTHER = 0x01, 0x02, 0x04, 0x08, 0x10, 0x20
UNDEFINED = 0xFFFFFFFF
R, W, X = 4, 2, 1


def supported() -> bool:
    return hasattr(os, "setxattr")


def encode(entries: list[tuple[int, int, int]]) -> bytes:
    """(tag, perm, id) entries -> the xattr value, sorted as the kernel wants (by tag, then id)."""
    out = struct.pack("<I", VERSION)
    for tag, perm, eid in sorted(entries, key=lambda e: (e[0], e[2])):
        out += struct.pack("<HHI", tag, perm, eid)
    return out


def decode(data: bytes) -> list[tuple[int, int, int]]:
    if len(data) < 4 or struct.unpack("<I", data[:4])[0] != VERSION or (len(data) - 4) % 8:
        raise ValueError("not a POSIX ACL")
    return [struct.unpack("<HHI", data[i:i + 8]) for i in range(4, len(data), 8)]


def _read(target, name: str) -> list[tuple[int, int, int]] | None:
    """The ACL `name` of a path (never through a link) or an open descriptor."""
    try:
        if isinstance(target, int):
            return decode(os.getxattr(target, name))
        return decode(os.getxattr(target, name, follow_symlinks=False))
    except OSError:
        return None


def _base(mode: int) -> list[tuple[int, int, int]]:
    return [(USER_OBJ, (mode >> 6) & 7, UNDEFINED), (GROUP_OBJ, (mode >> 3) & 7, UNDEFINED),
            (OTHER, mode & 7, UNDEFINED)]


def _with_users(entries: list[tuple[int, int, int]], users: dict[int, int]) -> list[tuple[int, int, int]]:
    """`entries` with the named users of `users` set (uid -> perm) and the mask recomputed (the union of the named
    entries and the owning group, as setfacl does)."""
    kept = [e for e in entries if e[0] != MASK and not (e[0] == USER and e[2] in users)]
    kept += [(USER, perm, uid) for uid, perm in users.items()]
    mask = 0
    for tag, perm, _ in kept:
        if tag in (USER, GROUP, GROUP_OBJ):
            mask |= perm
    if any(t in (USER, GROUP) for t, _, _ in kept):
        kept.append((MASK, mask, UNDEFINED))
    return kept


def _grant_fd(fd: int, users: dict[int, int], default: dict[int, int] | None) -> None:
    st = os.fstat(fd)
    acc = _read(fd, ACCESS) or _base(st.st_mode)
    os.setxattr(fd, ACCESS, encode(_with_users(acc, users)))
    if default and stat.S_ISDIR(st.st_mode):
        dfl = _read(fd, DEFAULT) or [(USER_OBJ, 7, UNDEFINED), (GROUP_OBJ, 5, UNDEFINED), (OTHER, 5, UNDEFINED)]
        os.setxattr(fd, DEFAULT, encode(_with_users(dfl, default)))


def grant(path, users: dict[int, int], default: dict[int, int] | None = None) -> None:
    """Give each uid in `users` its perm (R/W/X bits) on `path`; on a folder `default` also becomes inherited by
    what is made in it later. Never follows a symbolic link: the file itself is opened with O_NOFOLLOW and changed
    through its descriptor (a link, FIFO or device is left alone). The folders on the way are the caller's to
    trust; grant_at works below a folder descriptor."""
    path = Path(path)
    try:
        dfd = nofollow.open_dir(path.parent)
    except nofollow.LinkRefused:
        return
    try:
        grant_at(dfd, path.name, users, default, where=path)
    finally:
        os.close(dfd)


def grant_at(dir_fd: int, name: str, users: dict[int, int], default: dict[int, int] | None = None, *,
             tree: bool = False, where=None) -> bool:
    """`grant` on `name` in the folder `dir_fd`; with `tree`, on everything below it too, X only on folders (like
    setfacl's capital X), never walking into or acting on a link (nofollow.walk / open_node). False when `name`
    is missing or was skipped."""
    where = where if where is not None else name
    fd = nofollow.open_node(name, dir_fd, where)
    if fd is None:
        return False
    try:
        _grant_fd(fd, users, default)
        if tree and stat.S_ISDIR(os.fstat(fd).st_mode):
            files = {u: p & ~X for u, p in users.items()}
            for parent, child, path in nofollow.walk(fd, where):
                cfd = nofollow.open_node(child, parent, path)
                if cfd is None:
                    continue
                try:
                    is_dir = stat.S_ISDIR(os.fstat(cfd).st_mode)
                    _grant_fd(cfd, users if is_dir else files, default if is_dir else None)
                finally:
                    os.close(cfd)
    finally:
        os.close(fd)
    return True


def revoke(path, uids) -> bool:
    """Take the named-user entries of `uids` off `path`'s access ACL (the mask recomputed, as setfacl -x does). Never
    follows a link (the file is opened as `grant` opens it). False when there was nothing to take or no file."""
    path = Path(path)
    try:
        dfd = nofollow.open_dir(path.parent)
    except (FileNotFoundError, nofollow.LinkRefused):
        return False
    try:
        fd = nofollow.open_node(path.name, dfd, path)
        if fd is None:
            return False
        try:
            acc = _read(fd, ACCESS)
            if not acc or not any(t == USER and e in uids for t, _p, e in acc):
                return False
            kept = [x for x in acc if not (x[0] == USER and x[2] in uids)]
            os.setxattr(fd, ACCESS, encode(_with_users(kept, {})))
            return True
        finally:
            os.close(fd)
    finally:
        os.close(dfd)


def grant_tree(path, users: dict[int, int], default: dict[int, int] | None = None) -> None:
    """`grant` on `path` and everything below it (grant_at with tree)."""
    path = Path(path)
    try:
        dfd = nofollow.open_dir(path.parent)
    except (FileNotFoundError, nofollow.LinkRefused):
        return
    try:
        grant_at(dfd, path.name, users, default, tree=True, where=path)
    finally:
        os.close(dfd)


def users_of(path, name: str = ACCESS) -> dict[int, int]:
    """uid -> perm of the named users on `path` (for tests and checks)."""
    return {eid: perm for tag, perm, eid in (_read(Path(path), name) or []) if tag == USER}
