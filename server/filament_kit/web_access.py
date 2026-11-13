"""What the web unit's own user (`filament-kit-web`) may touch, and the copy of its state on upgrade (apply's
`web_state` step, run as root before the web unit starts).

The web unit faces the internet (Claude's connector), so it runs as its own user, not in the filament-kit group:
the setup page's root helper socket (0660 root:filament-kit, SO_PEERCRED) and the server's own files stay out of
its reach. It gets exactly what it uses, as POSIX ACLs (acl.py) on named files and folders:

  its own folder  /var/lib/filament-kit-web (750, its owner): the OAuth store (oauth.json), the kit API token
                  (kit_token), the Web Push keys and subscriptions, its failed label reads kept for retry
                  (failed/, FK_FAILED_DIR in its unit); copied here once from /var/lib/filament-kit/web/
                  (migrate; the originals stay there, as they were, for `update --rollback` to 0.3.0)
  settings        /etc/filament-kit: pass (x); config.json, web_passphrase and anthropic_key: read (r); every
                  root writer of these keeps the grant
                  (config.save, cli.write_passphrase, cli.write_key)
  kit state       /var/lib/filament-kit: pass (x); web/ (reader_tokens, 644): read; profiles/, library/,
                  library-local/, reader-fw/: read, also what is made there later (default ACLs);
                  the locks both units take (inventory.lock, profiles/*.lock): read; a lock is taken on a
                  read-only fd (pairing.open_lock), so the web user writes nothing of the kit's
  the kit API     everything it would otherwise write in the kit's state, so that no folder of the kit has to be
                  writable by it: preset lines and build requests (/api/profiles/web/*), the shared label-read cap
                  (/api/intake/cap/*) and the order history (/api/intake/orders, served to the web unit's device
                  only); its pairing token is made here as root when missing

No folder of the kit is writable by it. Root still works here on folders that other users own (the state folder is
the kit server's user's, the web folder the web unit's), so every step goes through nofollow.py: descriptors and
O_NOFOLLOW, never a name that might be a link; a link found is skipped with a warning. Everything else in the
state folder (printers.xml and printers.json with Access Codes, devices.json, pending.json ...) is 600 and out of its reach;
nothing in /etc beyond the files above."""
from __future__ import annotations

import os
import shutil
import stat
from datetime import datetime, timezone
from pathlib import Path

from . import acl, config, nofollow, pairing

KEEP_IN_STATE = ("reader_tokens",)          # stays in state/web/: the CLI and the setup page write it
MARKER = ".migrated"                       # in the web folder: the one-time copy from state/web/ is done
# the locks both units take (flock works on a read-only fd: pairing.open_lock); made here, read by the web user
LOCK_FILES = ("inventory.lock", "profiles/lines.lock", "profiles/live.lock", "profiles/state.lock",
              "profiles/build.lock")
RW_TREES = ()                              # no folder of the kit is writable by the web user
RO_TREES = ("profiles", "library", "library-local", "reader-fw")
ETC_FILES = ("config.json", "web_passphrase", "anthropic_key")
WEB_ROLE = pairing.WEB_ROLE                # devices.json "role" of the web unit's pairing (the web-only routes)


def _own_tree(dfd: int, where, uid: int, gid: int, chown) -> None:
    """`uid:gid` on the folder `dfd` and every regular file and folder below it (links skipped, never walked)."""
    chown(dfd, uid, gid)
    for parent, name, path in nofollow.walk(dfd, where):
        fd = nofollow.open_node(name, parent, path)
        if fd is not None:
            try:
                chown(fd, uid, gid)
            finally:
                os.close(fd)


def _copy(src_dir: int, dst_dir: int, name: str, where, dwhere, uid: int, gid: int, chown) -> bool:
    """Copy `name` (a regular file, or a folder of them) from `src_dir` into `dst_dir` by descriptor, only what
    `dst_dir` does not have yet: a link, FIFO or device is skipped (logged), no link is followed on either side and
    nothing is written over (each file made with O_CREAT | O_EXCL | O_NOFOLLOW). A copy is `uid:gid` with the
    source's permission bits (what the move gave). True when anything was copied."""
    st = nofollow.lstat_at(name, src_dir)
    if st is None:
        return False
    if not (stat.S_ISREG(st.st_mode) or stat.S_ISDIR(st.st_mode)):
        nofollow.skipped(where, "a symbolic link" if stat.S_ISLNK(st.st_mode) else "not a regular file or folder")
        return False
    if stat.S_ISDIR(st.st_mode):
        try:
            s = nofollow.open_dir_at(src_dir, name, where)
        except (FileNotFoundError, nofollow.LinkRefused):
            nofollow.skipped(where, "changed while it was being copied")
            return False
        try:
            got = os.fstat(s)
            if (got.st_dev, got.st_ino) != (st.st_dev, st.st_ino):
                nofollow.skipped(where, "changed while it was being copied")
                return False
            try:
                os.mkdir(name, 0o700, dir_fd=dst_dir)      # mkdir never follows a link at the name
                made = True
            except FileExistsError:
                made = False                              # a folder already there: only what it lacks
            try:
                d = nofollow.open_dir_at(dst_dir, name, dwhere)
            except (FileNotFoundError, nofollow.LinkRefused):
                nofollow.skipped(dwhere, "a symbolic link or not a folder (nothing copied into it)")
                return False
            try:
                if made:
                    chown(d, uid, gid)
                copied = made
                for child in sorted(os.listdir(s)):
                    copied |= _copy(s, d, child, f"{where}/{child}", f"{dwhere}/{child}", uid, gid, chown)
                if made:
                    os.fchmod(d, stat.S_IMODE(got.st_mode) & 0o777)
            finally:
                os.close(d)
        finally:
            os.close(s)
        return copied
    fd = nofollow.open_node(name, src_dir, where, dirs=False)
    if fd is None:
        return False
    try:
        try:
            out = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow.NOFOLLOW |
                          getattr(os, "O_CLOEXEC", 0), 0o600, dir_fd=dst_dir)
        except FileExistsError:
            return False                                  # already there (or a name planted there): left alone
        done = False
        try:
            with os.fdopen(out, "wb") as fo, os.fdopen(os.dup(fd), "rb") as fi:
                chown(fo.fileno(), uid, gid)
                shutil.copyfileobj(fi, fo)
                fo.flush()
                os.fchmod(fo.fileno(), stat.S_IMODE(os.fstat(fd).st_mode) & 0o777)
            done = True
        finally:
            if not done:                                  # no half copy left behind to block the next try
                try:
                    os.unlink(name, dir_fd=dst_dir)       # unlink never follows a link
                except OSError:
                    pass
        return True
    finally:
        os.close(fd)


def _mark(wfd: int, where, copied: list[str], uid: int, gid: int, chown) -> None:
    """The one-time marker (MARKER) in the web folder: when, and the names copied. Made the safe way (O_EXCL |
    O_NOFOLLOW in the folder's descriptor), the web user's, 0600; an existing name is left alone."""
    try:
        fd = os.open(MARKER, os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow.NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
                     0o600, dir_fd=wfd)
    except FileExistsError:
        nofollow.skipped(where, "already there (left alone)")
        return
    text = (f"copied {datetime.now(timezone.utc).isoformat(timespec='seconds')} from "
            f"{config.paths().state / 'web'} (the originals stay there for `update --rollback` to 0.3.0)\n"
            + "".join(f"{n}\n" for n in copied))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        chown(f.fileno(), uid, gid)
        os.fchmod(f.fileno(), 0o600)
        f.write(text)


def migrate(web_uid: int, web_gid: int, chown=None) -> list[str]:
    """Make the web unit's folder and copy its files there from state/web/, once. The originals stay in state/web/
    untouched, so `update --rollback` to 0.3.0 (which reads only there) keeps them. Only what the web folder lacks
    is copied (an earlier move's files are never written over); then MARKER is written and later runs copy
    nothing, so a file the web unit removed (a revoked push subscription) never comes back from the old copy.
    Returns the names copied. No link is copied, followed or changed; `chown(fd, uid, gid)` (default os.fchown)."""
    chown = chown or os.fchown
    p = config.paths()
    p.web.mkdir(parents=True, exist_ok=True)
    copied = []
    wfd = nofollow.open_dir(p.web)
    try:
        os.fchmod(wfd, 0o750)
        done = nofollow.lstat_at(MARKER, wfd) is not None
        old = p.state / "web"
        try:
            ofd = nofollow.open_dir(p.state, "web")
        except FileNotFoundError:
            ofd = None
        except nofollow.LinkRefused:
            nofollow.skipped(old, "a symbolic link or not a folder")
            ofd, done = None, True                # no marker: a fixed folder is still copied by a later apply
        if ofd is not None:
            try:
                if not done:
                    for name in sorted(os.listdir(ofd)):
                        if name in KEEP_IN_STATE or name.startswith(KEEP_IN_STATE[0] + ".") or name == MARKER:
                            continue
                        if _copy(ofd, wfd, name, old / name, p.web / name, web_uid, web_gid, chown):
                            copied.append(name)
                tok = nofollow.open_node(KEEP_IN_STATE[0], ofd, old / KEEP_IN_STATE[0], dirs=False)
                if tok is not None:
                    try:
                        os.fchmod(tok, 0o644)      # hashes only; the folder is the kit's (750 + the web user's read)
                    finally:
                        os.close(tok)
            finally:
                os.close(ofd)
        if not done:
            _mark(wfd, p.web / MARKER, copied, web_uid, web_gid, chown)
        # what was copied, and what a root CLI put here before the user existed
        _own_tree(wfd, p.web, web_uid, web_gid, chown)
    finally:
        os.close(wfd)
    return copied


def _folders(sfd: int, state: Path, folders: list[str], uid: int, gid: int, chown) -> int:
    """A descriptor of state/<folders>, each part made (owned by the kit) when missing, none opened through a
    link (nofollow.LinkRefused). The caller closes it unless it is `sfd`."""
    fd = sfd
    for i, part in enumerate(folders):
        try:
            os.mkdir(part, 0o755, dir_fd=fd)
            made = True
        except FileExistsError:
            made = False
        try:
            nfd = nofollow.open_dir_at(fd, part, state.joinpath(*folders[:i + 1]))
        finally:
            if fd != sfd:
                os.close(fd)
        if made:
            chown(nfd, uid, gid)
        fd = nfd
    return fd


def shared_files(kit_uid: int, kit_gid: int, chown=None) -> None:
    """The files both units write in place exist (owned by the kit), so the web user never has to create them.
    Made with O_CREAT | O_EXCL | O_NOFOLLOW; an existing one is opened without following a link, and a link (even
    a dangling one) is left alone with a warning. `chown` as in migrate."""
    chown = chown or os.fchown
    state = config.paths().state
    state.mkdir(parents=True, exist_ok=True)
    sfd = nofollow.open_dir(state)
    try:
        for name in LOCK_FILES:
            *folders, base = name.split("/")
            try:
                dfd = _folders(sfd, state, folders, kit_uid, kit_gid, chown)
            except nofollow.LinkRefused:
                nofollow.skipped(state / name, "a folder on its way is a symbolic link")
                continue
            try:
                fd, made = nofollow.create_or_open(base, dfd, 0o644, state / name)
                if fd is None:
                    continue
                try:
                    if made:
                        chown(fd, kit_uid, kit_gid)
                    os.fchmod(fd, 0o644)
                finally:
                    os.close(fd)
            finally:
                if dfd != sfd:
                    os.close(dfd)
    finally:
        os.close(sfd)


def pair(web_uid: int, web_gid: int, chown=None) -> bool:
    """Pair the web unit with the kit API as root when it has no token yet (the kit's pairings are not its to
    write), its device marked WEB_ROLE. False when there is nothing to pair with yet (no certificate). A link at
    kit_token (the folder is the web user's) is removed, never read or written through."""
    chown = chown or os.fchown
    from .web import slots
    w = config.paths().web
    f = w / "kit_token"
    w.mkdir(parents=True, exist_ok=True)
    wfd = nofollow.open_dir(w)
    try:
        st = nofollow.lstat_at(f.name, wfd)
        if st is not None and stat.S_ISLNK(st.st_mode):
            nofollow.skipped(f, "a symbolic link (removed; the web unit is paired again)")
            os.unlink(f.name, dir_fd=wfd)
            st = None
        if st is not None or not (config.paths().etc / "cert.pem").exists():
            return st is not None
        slots.pair_token(f, role=WEB_ROLE)
        fd = nofollow.open_node(f.name, wfd, f, dirs=False)
        if fd is not None:
            try:
                chown(fd, web_uid, web_gid)
            finally:
                os.close(fd)
    finally:
        os.close(wfd)
    return True


def mark_web_device() -> int:
    """Give WEB_ROLE to the web unit's pairings made before roles existed: the device named slots.DEVICE_NAME, a
    name only the web unit's pairing uses (phones, PCs and stations are named by the kit). Root (apply). Returns how
    many were marked."""
    from .web import slots
    return pairing.set_role_by_name(slots.DEVICE_NAME, WEB_ROLE)


def grant(web_uid: int, kit_uid: int, cfg: dict | None = None) -> list[str]:  # cfg: unused since slot_service went
    """The web user's ACLs (module docstring). Returns the paths granted. Never through a link: each file is
    opened without following one, below a folder opened the same way (acl.grant_at)."""
    if not acl.supported():
        return []
    p, done = config.paths(), []
    R, W, X = acl.R, acl.W, acl.X

    def one(base: Path, rel: str, perm: int, default=None, tree=False):
        *folders, name = rel.split("/")
        try:
            dfd = nofollow.open_dir(base, *folders)
        except FileNotFoundError:
            return
        except nofollow.LinkRefused:
            nofollow.skipped(base / rel, "a folder on its way is a symbolic link")
            return
        try:
            if acl.grant_at(dfd, name, {web_uid: perm}, default, tree=tree, where=base / rel):
                done.append(str(base / rel))
        finally:
            os.close(dfd)
    etc_parent, state_parent = p.etc.parent, p.state.parent
    one(etc_parent, p.etc.name, X)
    for name in ETC_FILES:
        one(p.etc, name, R)
    one(state_parent, p.state.name, X)
    one(p.state, "web", R | X)
    for name in LOCK_FILES:
        one(p.state, name, R)
    for name in RW_TREES:
        one(p.state, name, R | W | X, {web_uid: R | W | X, kit_uid: R | W | X}, tree=True)
    for name in RO_TREES:
        one(p.state, name, R | X, {web_uid: R | X}, tree=True)
    return done
