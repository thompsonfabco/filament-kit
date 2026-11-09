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

Hardware data feed (Ruling BG): after the program check (up to date or updated), the latest release's
`bambu_hardware.xml` asset is verified the same way (the signature over SHA256SUMS, then the file's hash),
validated with `bridge.hardware.validate` and only then put in place of the override
/etc/filament-kit/bambu_hardware.xml (atomic replace while no printer is mapping or loading, else the next run
tries again; the feed's earlier file is kept as bambu_hardware.xml.previous). It is installed only when there is no
override or the override is the feed's own file (its sha256 is in state.json `hardware`): a hand-made or hand-edited
override is never replaced or moved. It is installed only when its root `version` is newer than both the kit's
bundled file and the feed's file in place, so an older feed never shadows a newer kit's own file; the feed's file is
moved aside to .previous once the kit's bundled file is as new. A file that fails any check is never installed and
the run returns 1.

Settings (config.json, all optional): "updates": {"schedule": "daily"|"weekly", "token_file": a root-only file
with a GitHub token for a private repo, "repo": "owner/name", "api": "https://api.github.com"}. The token can also
come from FK_GITHUB_TOKEN; it is never printed.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
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
HW_ASSET = "bambu_hardware.xml"
NOTES_LIMIT = 32 * 1024         # characters of a release's notes kept for the setup console
BUSY_TEXT = "a printer is mapping or loading; try again when it is done"
# (release asset, module with BUNDLED/override_path/validate/file_version/MAX_BYTES, state.json key). The Bambu key
# stays "hardware" so existing installs keep recognising the file their feed installed.
HW_ASSETS = (("bambu_hardware.xml", "filament_kit.bridge.hardware", "hardware"),
             ("klipper_hardware.xml", "filament_kit.bridge.klipper.hardware", "hardware_klipper"))


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


def version_text() -> str:
    """The version to show: `current_version()`, or its -nightly.YYYYMMDD form on a nightly build (install.sh leaves the
    tarball's NIGHTLY file in resources/). Only for showing: the updater compares `current_version()`."""
    cur = current_version()
    try:
        text = (config.paths().opt / "resources" / "NIGHTLY").read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return cur
    return text if re.fullmatch(re.escape(cur) + r"-nightly\.\d{8}", text) else cur


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
                fh = open(lock, "rb")   # a lock needs no write access: the root helper's filesystem is read-only
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
    """SIGTERM (systemctl stop, shutdown) and SIGHUP (an SSH session that lost its terminal) raise SystemExit, so
    the `finally` that starts the kit again runs."""
    def _exit(signum, frame):
        raise SystemExit(128 + signum)
    old = {}
    for name in ("SIGTERM", "SIGHUP"):
        sig = getattr(signal, name, None)       # no SIGHUP on Windows
        if sig is None:
            continue
        try:
            old[sig] = signal.signal(sig, _exit)
        except ValueError:              # not the main thread
            pass
    try:
        yield
    finally:
        for sig, handler in old.items():
            signal.signal(sig, handler)


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

def going_back(notes: str) -> str:
    """The "Going back ..." section of a release's notes (what a rollback from that release means), or ""."""
    out: list[str] = []
    for line in notes.splitlines():
        head = line.lstrip("#* ").lower().startswith("going back")
        if not out:
            if head:
                out.append(line)
        elif line.startswith("#"):
            break
        else:
            out.append(line)
    return "\n".join(out).strip()


def _remember(latest: str, notes: str, back: str, now: float) -> None:
    """What the last check found, for the setup console (the server may not reach GitHub itself; the page reads this
    file). Best effort: `update --check` works for anyone, and only root can write here."""
    try:
        _write_state(latest={"version": latest, "notes": notes[:NOTES_LIMIT], "going_back": back[:NOTES_LIMIT],
                             "at": now})
    except OSError:
        pass


def _note_release(fetcher: release.Fetcher, repo: str, rel: dict, now: float) -> tuple[str, str]:
    """Save what `rel` says for the console; (its notes, what a rollback from the installed version means)."""
    latest, cur = rel["version"], current_version()
    notes = rel.get("notes") or ""
    try:        # a rollback leaves the installed version: what it says about that
        mine = notes if latest == cur else fetcher.release(repo, cur).get("notes") or ""
    except ReleaseError:
        mine = ""
    back = going_back(mine)
    _remember(latest, notes, back, now)
    return notes, back


def check_info(cfg: dict, *, fetcher: release.Fetcher | None = None, now: float | None = None) -> dict:
    """{installed, latest, newer, held, notes, going_back}: the latest release, what it says, and what a rollback
    from the installed version means. Raises ReleaseError when the latest release cannot be read."""
    s = settings(cfg)
    fetcher = fetcher or default_fetcher(cfg)
    rel = fetcher.release(s["repo"])
    latest, cur = rel["version"], current_version()
    newer = _newer(latest, cur)
    notes, back = _note_release(fetcher, s["repo"], rel, time.time() if now is None else now)
    return {"installed": cur, "latest": latest, "newer": newer, "held": _read_state().get("held"), "notes": notes,
            "going_back": back}


def check(cfg: dict, *, fetcher: release.Fetcher | None = None) -> int:
    try:
        info = check_info(cfg, fetcher=fetcher)
    except ReleaseError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    cur, latest = info["installed"], info["latest"]
    if info["newer"]:
        note = " (rolled back earlier: the timer skips it; `sudo filament-kit update` installs it)" \
            if info["held"] == latest else ""
        print(f"installed {cur}; {latest} is available{note}: sudo filament-kit update")
    else:
        print(f"installed {cur}; latest release {latest}: up to date")
    return 0


def summary() -> dict:
    """{installed, latest, newer, checked_at} from what the last check saved (no network)."""
    st = _read_state()
    cur = current_version()
    seen = st.get("latest") if isinstance(st.get("latest"), dict) else {}
    latest = seen.get("version") if isinstance(seen.get("version"), str) else None
    try:
        newer = bool(latest) and _newer(latest, cur)
    except ReleaseError:
        latest, newer = None, False
    return {"installed": cur, "latest": latest, "newer": newer, "checked_at": seen.get("at")}


def view(cfg: dict) -> dict:
    """The setup console's Updates tab, from local files only: the installed version, what the last check found, and
    whether an update or a rollback would be refused now (the same words the commands use). Never touches the
    network: the kit server may not reach GitHub, so "Check now" is a job that runs `check_info` as root."""
    st = _read_state()
    seen = st.get("latest") if isinstance(st.get("latest"), dict) else {}
    target = st.get("previous") if isinstance(st.get("previous"), str) else None
    if target and not _kept(target):
        target = None
    try:
        schedule = settings(cfg)["schedule"]
    except ReleaseError:
        schedule = None
    return {**summary(), "notes": seen.get("notes") or "", "going_back": seen.get("going_back") or "",
            "held": st.get("held"), "failed": st.get("failed"), "previous": target,
            "module_on": MODULE in modules.enabled(cfg), "schedule": schedule,
            "update_refused": job_refusal("update"), "rollback_refused": job_refusal("rollback", verified=target)}


def idle_problem() -> str | None:
    """Why an update may not start now, in the words of the command; names no printer (the console shows this without
    the setup code). A look only: a lock held for an instant, as the install itself takes it."""
    try:
        with printers_idle():
            return None
    except Busy:
        return BUSY_TEXT
    except OSError:     # a lock this process cannot open: the job itself decides
        return None


def job_refusal(name: str, *, verified: str | None = None) -> str | None:
    """Why the setup console's job `name` (update, rollback) would be refused now, or None; the job checks again, and
    the commands' own guards are the ones that hold. `verified`: the rollback target, already checked by `_kept` (the
    root helper has no use for the signature code, and the job checks it anyway)."""
    problem = idle_problem()
    if problem:
        return problem
    if name != "rollback":
        return None
    target = verified or _read_state().get("previous")
    if not isinstance(target, str):
        return "no verified earlier version is kept; nothing to roll back to"
    try:
        on = _modules_unfit(target)
    except (OSError, ValueError, ReleaseError) as e:
        return f"cannot check config.json's modules for the rollback: {e}"
    return _unfit_text(target, on) if on else None


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
        rel = fetcher.release(s["repo"])
        latest = rel["version"]
        cur = current_version()
        _note_release(fetcher, s["repo"], rel, now)     # the console shows it, and the timer keeps it fresh
        if not _newer(latest, cur):
            _write_state(last_ok_at=now)
            print(f"filament-kit {cur} is up to date")
            return _feed(fetcher, rel)
        st = _read_state()
        if scheduled and st.get("held") == latest:
            _write_state(last_ok_at=now)
            print(f"{latest} was rolled back; the timer leaves it (sudo filament-kit update installs it)")
            return _feed(fetcher, rel)
        if scheduled and st.get("failed") == latest:
            _write_state(last_ok_at=now)
            print(f"installing {latest} failed before; the timer waits for a newer release "
                  "(sudo filament-kit update tries it again)")
            return _feed(fetcher, rel)
        if not _kept(cur):
            try:
                _download(fetcher, s["repo"], cur)
            except ReleaseError as e:
                print(f"warning: no verified copy of the installed {cur} for a rollback: {e}", file=sys.stderr)
        _download(fetcher, s["repo"], latest)
        with printers_idle():
            kept = _kept(cur)
            old_previous = st.get("previous")
            # Before anything changes: a half-done install (killed, timed out, an exception) can still roll back,
            # and the timer does not retry it tomorrow. Success clears `failed`.
            _write_state(failed=latest, last_ok_at=now, **({"previous": cur} if kept else {}))
            try:
                ok = _install(cfg, latest, run)
            except ReleaseError:        # re-verify or unpack refused it: nothing was stopped or changed
                _write_state(previous=old_previous)
                raise
            if not ok:
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
    return _feed_after_install(cfg, fetcher, rel, run)


# ---------------------------------------------------------------- hardware data feed

def _vtext(v: tuple[int, int]) -> str:
    return f"{v[0]}.{v[1]}"


def _feed(fetcher: release.Fetcher, rel: dict) -> int:
    """Every hardware data asset (HW_ASSETS); one that fails does not stop the others."""
    rc = 0
    for asset in HW_ASSETS:
        name = asset[0]
        try:
            hardware_feed(fetcher, rel, asset)
        except ReleaseError as e:
            print(f"error: hardware data: {e}", file=sys.stderr)
            rc = 1
        except OSError as e:
            print(f"error: hardware data: cannot install {name}: {e}", file=sys.stderr)
            rc = 1
    return rc


def feed_now(cfg: dict, *, fetcher: release.Fetcher | None = None) -> int:
    """`update --feed` (internal): the hardware data for the latest release, in this process."""
    try:
        s = settings(cfg)
        fetcher = fetcher or default_fetcher(cfg)
        return _feed(fetcher, fetcher.release(s["repo"]))
    except ReleaseError as e:
        print(f"error: hardware data: {e}", file=sys.stderr)
        return 1


def _feed_after_install(cfg: dict, fetcher: release.Fetcher, rel: dict, run: Callable[[list[str]], int]) -> int:
    """After an install this process is the old program over the new one's files: the feed imports the hardware modules
    lazily, so a changed name or a new Python version would end a good update in a traceback. The new program does it."""
    exe = config.paths().opt / "venv" / "bin" / "filament-kit"
    if not exe.is_file():       # a checkout or a test: there is no new program
        return _feed(fetcher, rel)
    try:
        return 0 if run([str(exe), "update", "--feed"]) == 0 else 1
    except OSError as e:
        print(f"error: hardware data: cannot run the new program: {e}", file=sys.stderr)
        return 1


def _fsync_dir(d: Path) -> None:
    """Make a rename in `d` durable (POSIX; Windows has no directory fsync)."""
    if os.name != "posix":
        return
    fd = os.open(d, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_write(path: Path, data: bytes) -> None:
    """Write `path` as a whole: a temporary file, fsync, os.replace, then the folder fsync."""
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    _fsync_dir(path.parent)


def _feed_owned(ov: Path, key: str = "hardware") -> bool | None:
    """None: no override file; True: the override is the file the feed installed (its sha256 is in state.json);
    False: a hand-made (or hand-edited) override, which the feed never touches."""
    if not ov.is_file():
        return None
    mine = (_read_state().get(key) or {}).get("sha256")
    return bool(mine) and hmac.compare_digest(release.file_sha256(ov), mine)


def _busy_note(e: Busy, name: str = HW_ASSET) -> None:
    print(f"hardware data: printer {e} is mapping or loading; {name} is left as it is, the next run tries again")


def _retire_feed_file(ov: Path, bundled_v: tuple[int, int] | None, hardware=None, key: str = "hardware",
                      name: str = HW_ASSET) -> None:
    """The override this feed installed, once the kit's bundled file is as new: move it to .previous (it would win
    per element over the newer bundled data). A hand-made override is never touched."""
    if hardware is None:
        from .bridge import hardware
    if bundled_v is None or not _feed_owned(ov, key):
        return
    have = hardware.file_version(ov.read_bytes())
    if have is None or have > bundled_v:
        return
    try:
        with printers_idle():
            os.replace(ov, ov.with_name(ov.name + ".previous"))
            _fsync_dir(ov.parent)
    except Busy as e:
        _busy_note(e, name)
        return
    _write_state(**{key: None})
    print(f"hardware data: the kit's own file (version {_vtext(bundled_v)}) is as new as the one the feed "
          f"installed ({_vtext(have)}); that one is moved aside to {ov.name}.previous")


def hardware_feed(fetcher: release.Fetcher, rel: dict, asset: tuple = HW_ASSETS[0]) -> None:
    """Install the release's hardware data file `asset` (an HW_ASSETS entry; bambu_hardware.xml by default) as the
    override when it is verified, valid and newer (module doc). Raises ReleaseError when a file fails a check
    (nothing is installed then)."""
    import importlib
    HW_ASSET, module, key = asset
    hardware = importlib.import_module(module)
    ov = hardware.override_path()
    bundled_v = hardware.file_version(hardware.BUNDLED.read_bytes())
    _retire_feed_file(ov, bundled_v, hardware, key, HW_ASSET)
    url = rel["assets"].get(HW_ASSET)
    if url is None:
        return
    if _feed_owned(ov, key) is False:
        print(f"hardware data: hand-made override in place; hardware feed not installed ({ov} is left as it is)")
        have = hardware.file_version(ov.read_bytes())
        if bundled_v is not None and (have is None or have <= bundled_v):
            print(f"hardware data: {ov} (version {_vtext(have) if have else 'none'}) is not newer than the kit's "
                  f"own (version {_vtext(bundled_v)}), so it is ignored; give it a higher version, or remove it "
                  f"to let the feed install release data")
        return
    for need in (release.SUMS, release.SIG):
        if need not in rel["assets"]:
            raise ReleaseError(f"release {rel['version']} has no {need}; {HW_ASSET} not installed")
    sums = fetcher.get(rel["assets"][release.SUMS], release.LIMIT_SUMS)
    sig = fetcher.get(rel["assets"][release.SIG], release.LIMIT_SIG)
    try:
        table = release.verify_sums(sums, sig)
    except ReleaseError as e:
        raise ReleaseError(f"{e}; {HW_ASSET} not installed") from None
    want = table.get(HW_ASSET)
    if want is None:
        raise ReleaseError(f"the signed {release.SUMS} does not list {HW_ASSET}; not installed")
    data = fetcher.get(url, hardware.MAX_BYTES)
    if not hmac.compare_digest(hashlib.sha256(data).hexdigest(), want):
        raise ReleaseError(f"{HW_ASSET} does not match its hash in the signed {release.SUMS}; not installed")
    where = f"release {rel['version']} {HW_ASSET}"
    errors = hardware.validate(data, where)
    if errors:
        raise ReleaseError(f"{errors[0]}" + (f" (and {len(errors) - 1} more)" if len(errors) > 1 else "")
                           + "; not installed")
    new_v = hardware.file_version(data)
    if new_v is None:
        raise ReleaseError(f"{where} has no version; not installed")
    if bundled_v is not None and new_v <= bundled_v:
        print(f"hardware data: the kit's own file (version {_vtext(bundled_v)}) is as new as release "
              f"{rel['version']}'s ({_vtext(new_v)}); nothing to install")
        return
    try:
        with printers_idle():
            if _feed_owned(ov, key) is False:     # changed by hand while this ran
                print("hardware data: hand-made override in place; hardware feed not installed")
                return
            old = ov.read_bytes() if ov.is_file() else None      # the feed's own earlier file
            if old is not None:
                have = hardware.file_version(old)
                if old == data or (have is not None and have >= new_v):
                    return
            ov.parent.mkdir(parents=True, exist_ok=True)
            if old is not None:
                _atomic_write(ov.with_name(ov.name + ".previous"), old)
            _atomic_write(ov, data)
    except Busy as e:
        _busy_note(e, HW_ASSET)
        return
    _write_state(**{key: {"version": _vtext(new_v), "sha256": want, "release": rel["version"]}})
    print(f"hardware data: installed {HW_ASSET} version {_vtext(new_v)} from release {rel['version']} as {ov}")


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


def _unknown_to(target: str) -> tuple[dict, list[str]]:
    """(config.json as it is, the modules it names that `target` does not know)."""
    f = config.paths().etc / "config.json"
    raw = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    old = release.parse_version(target)
    mods = raw.get("modules") if isinstance(raw, dict) else None
    if not isinstance(mods, dict):
        return raw, []
    return raw, [n for n, since in modules.NEWER.items() if old < since and n in mods]


def _modules_unfit(target: str) -> list[str]:
    """The modules that are on and that `target` does not have."""
    raw, unknown = _unknown_to(target)
    return [n for n in unknown if raw["modules"][n]]


def _unfit_text(target: str, on: list[str]) -> str:
    return (f"filament-kit {target} has no {', '.join(on)} module; run "
            + " and ".join(f"`sudo filament-kit modules disable {n}`" for n in on) + " first")


def _modules_fit(target: str) -> bool:
    """Before installing `target`: refuse when a module it does not know is on, and drop such a module's false
    entry from config.json (the newer release wrote it when it was switched off). False on refusal."""
    try:
        raw, unknown = _unknown_to(target)
    except (OSError, ValueError, ReleaseError) as e:
        print(f"error: cannot check config.json's modules for the rollback: {e}", file=sys.stderr)
        return False
    mods = raw.get("modules") if isinstance(raw, dict) else None
    on = [n for n in unknown if mods[n]]
    if on:
        print(f"error: {_unfit_text(target, on)}", file=sys.stderr)
        return False
    if unknown:
        for n in unknown:
            del mods[n]
        config.save(raw)
        print(f"Removed {', '.join(unknown)} (off) from config.json's modules: filament-kit {target} does not know it.")
    return True


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
    if not _modules_fit(target):
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
