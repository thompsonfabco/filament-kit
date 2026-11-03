"""The updater: module `updates` (off by default) and `filament-kit update [--check|--rollback]` (spec R 2.5).

`update` finds the latest release, downloads and verifies it exactly as get.sh does (`release.fetch`: the
signature over SHA256SUMS, then the tarball's hash), keeps it in /opt/filament-kit/releases/<version>/, stops the
kit's services, runs the release's install.sh in upgrade mode (no questions; it ends with `modules apply`, which
starts them again) and keeps the version it replaced for `--rollback`. The module's timers are stopped too. If
install.sh fails, raises or the updater gets SIGTERM, the stopped units are started again; a failed install then
reinstalls the version that was running (from its kept copy) and the failed version is not retried by the timer
until a newer release appears (`update` by hand tries it again). Nothing is touched while a printer is
mapping or loading: the printers' mapping.lock files are held for the whole install. The timer
(filament-kit-update.timer, daily) runs `update --scheduled`, which does nothing unless the module is on and
`updates.schedule` (daily or weekly) says a check is due, and never reinstalls a version that was rolled back.

Settings (config.json, all optional): "updates": {"schedule": "daily"|"weekly", "token_file": a root-only file
with a GitHub token for a private repo, "repo": "owner/name", "api": "https://api.github.com"}. The token can also
come from FK_GITHUB_TOKEN; it is never printed.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

try:
    import fcntl
except ImportError:  # Windows dev PCs: tests only
    fcntl = None

from . import __version__, config, modules, release
from .release import ReleaseError

SCHEDULES = {"daily": 20 * 3600, "weekly": 6.5 * 86400}
STATE = "state.json"
MODULE = "updates"


class Busy(Exception):
    """A printer is mapping or loading."""


def settings(cfg: dict) -> dict:
    u = cfg.get("updates") if isinstance(cfg.get("updates"), dict) else {}
    s = {"schedule": u.get("schedule") or "daily", "token_file": u.get("token_file") or None,
         "repo": u.get("repo") or release.REPO, "api": u.get("api") or release.API}
    if s["schedule"] not in SCHEDULES:
        raise ReleaseError(f"updates.schedule must be one of {', '.join(SCHEDULES)}, not {s['schedule']!r}")
    return s


def store() -> Path:
    return config.paths().opt / "releases"


def current_version() -> str:
    return __version__


def _read_state() -> dict:
    try:
        st = json.loads((store() / STATE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return st if isinstance(st, dict) else {}


def _write_state(**changes) -> None:
    st = _read_state()
    st.update(changes)
    d = store()
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / (STATE + ".tmp")
    tmp.write_text(json.dumps(st, indent=2), encoding="utf-8")
    os.replace(tmp, d / STATE)


def default_fetcher(cfg: dict) -> release.Fetcher:
    s = settings(cfg)
    return release.Fetcher(s["api"], release.read_token(s["token_file"]))


def _newer(a: str, b: str) -> bool:
    return release.parse_version(a) > release.parse_version(b)


def _kept(version: str) -> bool:
    try:
        release.verify_dir(store() / version, version)
        return True
    except (ReleaseError, OSError):
        return False


def _download(fetcher: release.Fetcher, repo: str, version: str) -> None:
    """Fetch and verify `version` into store/<version>/ (replacing a broken copy)."""
    tmp = store() / ".download"
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        ver, _ = release.fetch(tmp, repo=repo, version=version, fetcher=fetcher)
        release.keep(ver, tmp, store())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _prune(keep: set[str]) -> None:
    for d in store().iterdir():
        if d.is_dir() and not d.name.startswith(".") and d.name not in keep:
            shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------- printers

@contextmanager
def printers_idle():
    """Hold every printer's mapping.lock (LOCK_EX, not waiting) for the install: a mapping job holds it LOCK_EX
    and a load's write phase LOCK_SH, so either one makes this raise Busy, and neither can start meanwhile."""
    held = []
    try:
        root = config.paths().state / "printers"
        if fcntl is not None and root.is_dir():
            for lock in sorted(root.glob("*/mapping.lock")):
                fh = open(lock, "a")
                try:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    fh.close()
                    raise Busy(lock.parent.name) from None
                held.append(fh)
        yield
    finally:
        for fh in held:
            fh.close()


# ---------------------------------------------------------------- install

def _units(cfg: dict) -> tuple[list[str], list[str]]:
    """(services, timers and path units) of the modules that are on."""
    on = modules.enabled(cfg)
    units = [u for n, m in modules.MODULES.items() if n in on for u in m.units]
    return [u for u in units if u.endswith(".service")], [u for u in units if not u.endswith(".service")]


def _systemctl(run, verb: str, units: list[str]) -> None:
    if units and os.environ.get("FK_NO_SYSTEMD") != "1":
        run(["systemctl", verb, *units])


def default_run(cmd: list[str]) -> int:
    return subprocess.run(cmd, stdin=subprocess.DEVNULL, check=False).returncode


@contextmanager
def _sigterm_exits():
    """SIGTERM (systemctl stop, shutdown) raises SystemExit, so the `finally` that starts the kit again runs."""
    def _exit(signum, frame):
        raise SystemExit(128 + signum)
    try:
        old = signal.signal(signal.SIGTERM, _exit)
    except ValueError:                  # not the main thread
        old = None
    try:
        yield
    finally:
        if old is not None:
            signal.signal(signal.SIGTERM, old)


def _start_again(run, services: list[str], timers: list[str]) -> None:
    """Best effort: a failure here must not hide the install's own error."""
    for group in (services, timers):
        try:
            _systemctl(run, "start", group)
        except Exception as e:          # noqa: BLE001 - keep going, say what failed
            print(f"error: could not start {', '.join(group)}: {e}", file=sys.stderr)


def _install(cfg: dict, version: str, run: Callable[[list[str]], int]) -> bool:
    """Re-verify the kept release, unpack it, stop the module timers and services, run its install.sh (whose
    `modules apply` starts them again). Unless install.sh succeeded, whatever happened (a failure, an exception,
    SIGTERM), the stopped units are started again before this returns or raises."""
    tarball = release.verify_dir(store() / version, version)
    work = store() / ".work"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(mode=0o700, parents=True)
    ok = False
    services, timers = _units(cfg)
    stopped: tuple[list[str], list[str]] = ([], [])
    try:
        with _sigterm_exits():
            root = release.extract(tarball, version, work)
            print(f"stopping {', '.join(timers + services) or 'nothing'}; installing filament-kit {version}")
            stopped = (services, timers)
            _systemctl(run, "stop", timers)
            _systemctl(run, "stop", services)
            try:
                rc = run(["bash", str(root / "install.sh")])
            except OSError as e:
                print(f"error: cannot run install.sh of {version}: {e}", file=sys.stderr)
                rc = -1
            ok = rc == 0
            if not ok:
                print(f"error: install.sh of {version} failed (exit {rc})", file=sys.stderr)
            return ok
    finally:
        if not ok and (stopped[0] or stopped[1]):
            print("starting the kit's services again", file=sys.stderr)
            _start_again(run, *stopped)
        shutil.rmtree(work, ignore_errors=True)


def _require_root() -> bool:
    if os.environ.get("FK_NO_SYSTEMD") != "1" and hasattr(os, "geteuid") and os.geteuid() != 0:
        print("error: run as root: sudo filament-kit update", file=sys.stderr)
        return False
    return True


def _installed() -> bool:
    return (config.paths().etc / "config.json").is_file()


def due(cfg: dict, now: float) -> bool:
    last = _read_state().get("last_ok_at")
    return not isinstance(last, (int, float)) or now - last >= SCHEDULES[settings(cfg)["schedule"]]


# ---------------------------------------------------------------- commands

def check(cfg: dict, *, fetcher: release.Fetcher | None = None) -> int:
    try:
        s = settings(cfg)
        latest = (fetcher or default_fetcher(cfg)).release(s["repo"])["version"]
        cur = current_version()
        newer = _newer(latest, cur)
    except ReleaseError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    held = _read_state().get("held")
    if newer:
        note = " (rolled back earlier: the timer skips it; `sudo filament-kit update` installs it)" \
            if held == latest else ""
        print(f"installed {cur}; {latest} is available{note}: sudo filament-kit update")
    else:
        print(f"installed {cur}; latest release {latest}: up to date")
    return 0


def update(cfg: dict, *, scheduled: bool = False, fetcher: release.Fetcher | None = None,
           run: Callable[[list[str]], int] = default_run, now: float | None = None) -> int:
    now = time.time() if now is None else now
    if scheduled and MODULE not in modules.enabled(cfg):
        print("the updates module is off; nothing to do")
        return 0
    if not _require_root():
        return 1
    if not _installed():
        print("error: filament-kit is not installed here (no config.json); install it with get.sh",
              file=sys.stderr)
        return 1
    try:
        s = settings(cfg)
        if scheduled and not due(cfg, now):
            print("update check not due yet")
            return 0
        fetcher = fetcher or default_fetcher(cfg)
        latest = fetcher.release(s["repo"])["version"]
        cur = current_version()
        if not _newer(latest, cur):
            _write_state(last_ok_at=now)
            print(f"filament-kit {cur} is up to date")
            return 0
        st = _read_state()
        if scheduled and st.get("held") == latest:
            _write_state(last_ok_at=now)
            print(f"{latest} was rolled back; the timer leaves it (sudo filament-kit update installs it)")
            return 0
        if scheduled and st.get("failed") == latest:
            _write_state(last_ok_at=now)
            print(f"installing {latest} failed before; the timer waits for a newer release "
                  "(sudo filament-kit update tries it again)")
            return 0
        if not _kept(cur):
            try:
                _download(fetcher, s["repo"], cur)
            except ReleaseError as e:
                print(f"warning: no verified copy of the installed {cur} for a rollback: {e}", file=sys.stderr)
        _download(fetcher, s["repo"], latest)
        with printers_idle():
            kept = _kept(cur)
            old_previous = st.get("previous")
            if kept:                    # before anything changes: a half-done install can still roll back
                _write_state(previous=cur)
            if not _install(cfg, latest, run):
                _write_state(failed=latest, last_ok_at=now)
                return _restore(cfg, cur, kept, old_previous, run)
    except Busy as e:
        print(f"{'skipped' if scheduled else 'error'}: printer {e} is mapping or loading; "
              f"{'the next check tries again' if scheduled else 'try again when it is done'}",
              file=sys.stderr if not scheduled else sys.stdout)
        return 0 if scheduled else 1
    except ReleaseError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    _write_state(last_ok_at=now, previous=cur if _kept(cur) else None, held=None, failed=None)
    _prune({latest, cur})
    print(f"updated filament-kit {cur} -> {latest}" + ("" if _kept(cur) else " (no rollback copy)"))
    return 0


def _restore(cfg: dict, cur: str, kept: bool, old_previous, run) -> int:
    """After a failed install: reinstall `cur` from its kept copy. Always returns 1 (the update failed)."""
    if not kept:
        print(f"error: no kept copy of {cur} to go back to; reinstall it by hand: curl -fsSL <get.sh url> | "
              f"sudo bash -s -- --version {cur}", file=sys.stderr)
        return 1
    print(f"reinstalling filament-kit {cur}", file=sys.stderr)
    try:
        restored = _install(cfg, cur, run)
    except ReleaseError as e:
        print(f"error: {e}", file=sys.stderr)
        restored = False
    if restored:
        _write_state(previous=old_previous)
        print(f"filament-kit {cur} is back in place; the update failed", file=sys.stderr)
    else:
        print(f"error: reinstalling {cur} failed too; try again with: sudo filament-kit update --rollback",
              file=sys.stderr)
    return 1


def rollback(cfg: dict, *, run: Callable[[list[str]], int] = default_run) -> int:
    if not _require_root():
        return 1
    cur = current_version()
    st = _read_state()
    target = st.get("previous")
    if not isinstance(target, str) or not _kept(target):
        print(f"error: no verified earlier version is kept in {store()}; nothing to roll back to",
              file=sys.stderr)
        return 1
    try:
        with printers_idle():
            if not _install(cfg, target, run):
                print("error: the rollback failed; the version before is still kept, try again", file=sys.stderr)
                return 1
    except Busy as e:
        print(f"error: printer {e} is mapping or loading; try again when it is done", file=sys.stderr)
        return 1
    except ReleaseError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    held = cur if cur != target else st.get("held")    # after a half-done update this process may say `target`
    _write_state(previous=None, held=held)
    print(f"rolled back filament-kit {cur} -> {target}; settings and data stay as they are."
          + (f" The timer will not install {held} again; `sudo filament-kit update` does." if held else ""))
    return 0
