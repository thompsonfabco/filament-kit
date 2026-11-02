"""One sync run (port of filament-ops fpsync.main, over the pinned HTTPS API instead of a share).

  1. Bambu Studio running -> `studio_running`, nothing else (not even a server call).
  2. An install that crashed part-way (marker `installing.json`) is finished first: the same build is
     downloaded and installed again, bypassing the live-hash gate (the live folder is ahead of the
     build only because of that install; the installer still refuses real in-app edits).
  3. The user filament folder and system/BBL/filament are uploaded when their tree hash differs from
     the server's (zip limits are checked before anything is sent).
  4. An install whose `installed(stamp)` report failed is reported again.
  5. No build -> `no_build` (a build is requested, at most every 15 min). The build already
     installed -> `up_to_date`. A build made from other live presets -> a rebuild is requested
     (`rebuild_requested`), re-sent only after 15 min (`waiting` until then; `state.json`
     `requested: {live_hash, at}`). A build made from exactly these live presets -> download,
     install (backup stamp `%Y%m%d-%H%M%S` of `now`), upload the live folder again, `installed(stamp)`.
  `uploaded` is returned when this run uploaded something and the build step had nothing to do
  (`no_build` / `up_to_date`).

Every outcome and the stale-preset list are logged in one line each. Errors other than an install
refusal or `409 other_pc` propagate (the caller logs them; the next scheduled run retries).
"""
import json
import shutil
import tempfile
import time
from pathlib import Path
from typing import Callable

from . import installer, store, zips
from .client import ApiError
from .studio import StudioFolders
from .treehash import tree_hash

REQUEST_RETRY = 15 * 60
LIVE_MAX = zips.LIVE_MAX
SYSTEM_MAX = zips.SYSTEM_MAX

OUTCOMES = ("studio_running", "uploaded", "no_build", "up_to_date", "rebuild_requested", "waiting", "installed",
            "refused", "other_pc")


def marker_path(dirs: store.AppDirs) -> Path:
    return dirs.base / "installing.json"


def load_state(dirs: store.AppDirs) -> dict:
    try:
        st = json.loads(dirs.state.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return st if isinstance(st, dict) else {}


def _save_state(dirs: store.AppDirs, st: dict) -> None:
    store._write_atomic(dirs.state, (json.dumps(st, indent=2, sort_keys=True) + "\n").encode("utf-8"))


class _Run:
    def __init__(self, client, folders: StudioFolders, dirs: store.AppDirs, running, install, now: float,
                 echo: Callable[[str], None] | None):
        self.c, self.f, self.d = client, folders, dirs
        self.running, self.install_fn, self.now, self.echo = running, install, now, echo
        self.st = load_state(dirs)
        self.uploaded = False

    def log(self, msg: str) -> None:
        store.log(self.d, msg)
        if self.echo:
            self.echo(msg)

    def save(self) -> None:
        _save_state(self.d, self.st)

    def finish(self, outcome: str, detail: str) -> str:
        self.log(f"{outcome}: {detail}")
        self.st["last"] = {"outcome": outcome, "at": self.now, "detail": detail}
        self.save()
        return outcome

    # --- uploads --------------------------------------------------------------------------

    def upload_live(self) -> str:
        here = tree_hash(self.f.user_filament)
        data = zips.pack(self.f.user_filament, LIVE_MAX)
        self.c.upload("live", data, user_id=self.f.user_id)
        self.uploaded = True
        self.log(f"uploaded the live presets ({len(data)} bytes, {self.f.variant} user {self.f.user_id})")
        return here

    def uploads(self, server: dict) -> str:
        here = tree_hash(self.f.user_filament)
        system = tree_hash(self.f.system_filament)
        # both checked against the limits before either is sent
        live_zip = zips.pack(self.f.user_filament, LIVE_MAX) if server.get("live_hash") != here else None
        sys_zip = zips.pack(self.f.system_filament, SYSTEM_MAX) if server.get("system_hash") != system else None
        if live_zip is not None:
            self.c.upload("live", live_zip, user_id=self.f.user_id)
            self.uploaded = True
            self.log(f"uploaded the live presets ({len(live_zip)} bytes, {self.f.variant} user {self.f.user_id})")
        if sys_zip is not None:
            self.c.upload("system", sys_zip)
            self.uploaded = True
            self.log(f"uploaded the Bambu Studio system presets ({len(sys_zip)} bytes)")
        return here

    # --- rebuild requests -----------------------------------------------------------------

    def request(self, here: str) -> bool:
        """Ask for a rebuild for `here` unless one was asked less than 15 min ago; True when sent."""
        req = self.st.get("requested") or {}
        if req.get("live_hash") == here and self.now - float(req.get("at") or 0) < REQUEST_RETRY:
            return False
        self.c.rebuild(here)
        self.st["requested"] = {"live_hash": here, "at": self.now}
        self.save()
        return True

    # --- install --------------------------------------------------------------------------

    def report(self, stamp: str) -> None:
        self.st["report"] = stamp
        self.save()
        try:
            self.c.installed(stamp)
        except ApiError as e:
            if e.status != 404:
                raise
            self.log(f"build {stamp} is no longer on the server; its install was not recorded there")
        self.st.pop("report", None)
        self.save()

    def install(self, stamp: str, expect_hash: str | None) -> str:
        """Download, install, re-upload, report. expect_hash None: finishing an interrupted install."""
        data = self.c.build(stamp)
        work = Path(tempfile.mkdtemp(prefix=".download.", suffix=".tmp", dir=self.d.base))
        try:
            build_dir = work / "build"
            try:
                meta = zips.unpack_build(data, build_dir)
            except ValueError as e:
                self._clear_marker()
                return self.finish("refused", f"build {stamp}: {e}")
            if meta.get("stamp") not in (None, stamp) or (
                    expect_hash is not None and meta.get("live_hash") not in (None, expect_hash)):
                self._clear_marker()
                return self.finish("refused", f"build {stamp}: its BUILD.json does not match the server's state")
            store._write_atomic(marker_path(self.d), json.dumps({"stamp": stamp, "at": self.now}).encode())
            try:
                res = self.install_fn(build_dir, self.f, self.d, running=self.running,
                                      stamp_now=time.strftime("%Y%m%d-%H%M%S", time.localtime(self.now)))
            except installer.Refused as e:
                if e.code == "studio_running":
                    if expect_hash is not None:
                        self._clear_marker()  # nothing was written; a normal run decides again
                    return self.finish("studio_running", f"Bambu Studio started; build {stamp} not installed yet")
                self._clear_marker()
                return self.finish("refused", f"install of build {stamp} refused ({e.code}): {e.reason}")
            # an OSError here propagates with the marker kept: the next run finishes this install
        finally:
            shutil.rmtree(work, ignore_errors=True)
        self._clear_marker()
        self.st["stale"] = list(res.stale)
        self.st["installed"] = {"stamp": stamp, "at": self.now}
        self.st.pop("requested", None)
        self.st["report"] = stamp
        self.save()
        if res.stale:
            self.log(f"{len(res.stale)} presets are no longer generated; delete them in Bambu Studio: "
                     + ", ".join(res.stale))
        self.upload_live()
        self.report(stamp)
        return self.finish("installed", f"installed build {stamp} ({len(res.installed)} presets, "
                                        f"backup {res.backup.name})")

    def _clear_marker(self) -> None:
        marker_path(self.d).unlink(missing_ok=True)

    def _marker(self) -> dict | None:
        try:
            m = json.loads(marker_path(self.d).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            self._clear_marker()
            return None
        return m if isinstance(m, dict) and isinstance(m.get("stamp"), str) else None

    # --- the run --------------------------------------------------------------------------

    def run(self) -> str:
        if self.running():
            return self.finish("studio_running", "Bambu Studio is open; trying again next run")
        server = self.c.state()

        marker = self._marker()
        if marker is not None:
            stamp = marker["stamp"]
            self.log(f"finishing the interrupted install of build {stamp}")
            try:
                return self.install(stamp, None)
            except ApiError as e:
                if e.status != 404:
                    raise
                self._clear_marker()
                self.log(f"build {stamp} of the interrupted install is no longer on the server")
                server = self.c.state()

        here = self.uploads(server)

        pending = self.st.get("report")
        if pending:
            self.report(pending)
            server = self.c.state()

        build = server.get("build")
        if not build:
            sent = self.request(here)
            if self.uploaded:
                return self.finish("uploaded", "no build on the server yet" + ("; asked for one" if sent else ""))
            return self.finish("no_build", "no build on the server yet" + ("; asked for one" if sent else ""))
        stamp = build.get("stamp")
        installed = (server.get("installed") or {}).get("stamp")
        if installed == stamp:
            if self.uploaded:
                return self.finish("uploaded", f"build {stamp} is installed; the server has your latest presets")
            return self.finish("up_to_date", f"build {stamp} is installed")
        if build.get("live_hash") != here:
            if self.request(here):
                return self.finish("rebuild_requested",
                                   f"build {stamp} predates your latest Bambu Studio presets; asked for a rebuild")
            return self.finish("waiting", f"waiting for the rebuild asked at "
                                          f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self.st['requested']['at']))}")
        return self.install(stamp, here)


def run_once(client, folders: StudioFolders, dirs: store.AppDirs, *, running: Callable[[], bool],
             install=installer.install, now: float, echo: Callable[[str], None] | None = None) -> str:
    dirs.ensure()
    r = _Run(client, folders, dirs, running, install, now, echo)
    try:
        return r.run()
    except ApiError as e:
        if e.status == 409 and e.code == "other_pc":
            return r.finish("other_pc", "another PC is the sync PC for this server; unpair it on the server "
                                        f"('sudo filament-kit unpair <id>') to sync from this one ({e.message})")
        raise
