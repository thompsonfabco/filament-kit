"""What the web unit's own user (`filament-kit-web`) may touch, and the move of its state on upgrade (apply's
`web_state` step, run as root before the web unit starts).

The web unit faces the internet (Claude's connector), so it runs as its own user, not in the filament-kit group:
the setup page's root helper socket (0660 root:filament-kit, SO_PEERCRED) and the server's own files stay out of
its reach. It gets exactly what it uses, as POSIX ACLs (acl.py) on named files and folders:

  its own folder  /var/lib/filament-kit-web (750, its owner): the OAuth store (oauth.json), the kit API token
                  (kit_token), the Web Push keys and subscriptions, its failed label reads kept for retry
                  (failed/, FK_FAILED_DIR in its unit); moved here from /var/lib/filament-kit/web/
  settings        /etc/filament-kit: pass (x); config.json, web_passphrase, anthropic_key and the owner's H2D slot
                  token (slot_service.token_file): read (r); every root writer of these keeps the grant
                  (config.save, cli.write_passphrase, cli.write_key)
  kit state       /var/lib/filament-kit: pass (x); web/ (reader_tokens, 644): read; profiles/, library/,
                  library-local/, reader-fw/: read, also what is made there later (default ACLs);
                  the locks both units take (inventory.lock, profiles/*.lock): read; a lock is taken on a
                  read-only fd (pairing.open_lock), so the web user writes nothing of the kit's
  the kit API     everything it would otherwise write in the kit's state (Ruling CG): preset lines and build
                  requests (/api/profiles/web/*), the shared label-read cap (/api/intake/cap/*) and the order
                  history (/api/intake/orders); its pairing token is made here as root when missing

No folder of the kit is writable by it, so it cannot plant a link that the kit or root would follow. Everything
else in the state folder (printers.json with Access Codes, devices.json, pending.json ...) is 600 and out of its
reach; nothing in /etc beyond the files above."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from . import acl, config

KEEP_IN_STATE = ("reader_tokens",)          # stays in state/web/: the CLI and the setup page write it
# the locks both units take (flock works on a read-only fd: pairing.open_lock); made here, read by the web user
LOCK_FILES = ("inventory.lock", "profiles/lines.lock", "profiles/live.lock", "profiles/state.lock",
              "profiles/build.lock")
RW_TREES = ()                              # no folder of the kit is writable by the web user
RO_TREES = ("profiles", "library", "library-local", "reader-fw")
ETC_FILES = ("config.json", "web_passphrase", "anthropic_key")


def migrate(web_uid: int, web_gid: int, chown=None) -> list[str]:
    """Make the web unit's folder and move its files there from state/web/ (never over a file already moved).
    Returns the names moved."""
    chown = chown or os.chown
    p = config.paths()
    p.web.mkdir(parents=True, exist_ok=True)
    os.chmod(p.web, 0o750)
    chown(p.web, web_uid, web_gid)
    old = p.state / "web"
    moved = []
    if old.is_dir():
        for f in sorted(old.iterdir()):
            if f.name in KEEP_IN_STATE or f.name.startswith(KEEP_IN_STATE[0] + ".") or f.is_symlink():
                continue
            dest = p.web / f.name
            if dest.exists():
                continue
            shutil.move(str(f), str(dest))
            for q in [dest, *(dest.rglob("*") if dest.is_dir() else [])]:
                chown(q, web_uid, web_gid)
            moved.append(f.name)
    for q in p.web.rglob("*"):              # also what a root CLI (migrate-ops) put here before the user existed
        if not q.is_symlink():
            chown(q, web_uid, web_gid)
    tokens = old / KEEP_IN_STATE[0]
    if tokens.is_file():
        os.chmod(tokens, 0o644)              # hashes only; the folder is the kit's (750 + the web user's read)
    return moved


def shared_files(kit_uid: int, kit_gid: int, chown=None) -> None:
    """The files both units write in place exist (owned by the kit), so the web user never has to create them."""
    chown = chown or os.chown
    state = config.paths().state
    state.mkdir(parents=True, exist_ok=True)
    for name in LOCK_FILES:
        f = state / name
        if not f.parent.exists():
            f.parent.mkdir(parents=True)
            chown(f.parent, kit_uid, kit_gid)
        if not f.exists():
            f.write_text("", encoding="utf-8")
            chown(f, kit_uid, kit_gid)
        if not f.is_symlink():
            os.chmod(f, 0o644)


def pair(web_uid: int, web_gid: int, chown=None) -> bool:
    """Pair the web unit with the kit API as root when it has no token yet (the kit's pairings are not its to
    write). False when there is nothing to pair with yet (no certificate)."""
    chown = chown or os.chown
    from .web import slots
    f = config.paths().web / "kit_token"
    if f.exists() or not (config.paths().etc / "cert.pem").exists():
        return f.exists()
    slots.pair_token(f)
    chown(f, web_uid, web_gid)
    return True


def grant(web_uid: int, kit_uid: int, cfg: dict | None = None) -> list[str]:
    """The web user's ACLs (module docstring). Returns the paths granted."""
    if not acl.supported():
        return []
    p, done = config.paths(), []
    R, W, X = acl.R, acl.W, acl.X

    def one(path: Path, perm: int, default=None, tree=False):
        if path.exists() and not path.is_symlink():
            (acl.grant_tree if tree else acl.grant)(path, {web_uid: perm}, default)
            done.append(str(path))
    one(p.etc, X)
    for name in ETC_FILES:
        one(p.etc / name, R)
    one(p.state, X)
    one(p.state / "web", R | X)
    for name in LOCK_FILES:
        one(p.state / name, R)
    for name in RW_TREES:
        one(p.state / name, R | W | X, {web_uid: R | W | X, kit_uid: R | W | X}, tree=True)
    for name in RO_TREES:
        one(p.state / name, R | X, {web_uid: R | X}, tree=True)
    cfg = cfg if cfg is not None else config.load()
    svc = cfg.get("slot_service")
    token = svc.get("token_file") if isinstance(svc, dict) else None
    if token:                                  # the owner's H2D slot token (printer_set_slot), re-granted on save
        one(Path(token), R)
    return done
