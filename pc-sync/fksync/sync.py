"""One sync run (port of filament-ops fpsync.main, over the pinned HTTPS API instead of a share).

  1. Bambu Studio running -> `studio_running`, nothing else (not even a server call).
  2. `state()`; when the server already has another sync PC (`owner not in (None, you)`) ->
     `other_pc` before anything is sent.
  3. An install that crashed part-way (marker `installing.json`, written by the installer's
     before_write hook right after the backup, naming it) is resumed only when every staged preset's
     live .json still equals the build's copy or the backup's copy (missing in both counts as equal).
     Then the same build is installed again without the live-hash gate. If any differs, it was edited
     in Bambu Studio since: the marker is dropped and the normal path follows (upload, rebuild). The
     half-installed build is then kept as dirs.partial and named in every live upload
     (`partial=<stamp>`, `state.json` `partial: {stamp, at}`) until an install succeeds (ruling S28):
     its values in the live folder are not in-app edits, for the server nor for the installer.
  4. The user filament folder and system/BBL/filament are uploaded when their tree hash differs from
     the server's (zip limits are checked before anything is sent). An upload the server rejects
     (400/413) is recorded in `state.json` `rejected.<kind>` `{kind, hash, at, error}` and that same
     hash is not sent again for UPLOAD_BACKOFF (6 h, fixed). The hash the server returns is recorded in
     `uploaded.<kind>` `{local, server}`; when it differs from ours that is logged once, the upload is
     not repeated while both stay the same, and a build with that server hash counts as built from
     these live presets.
  5. An install whose `installed(stamp)` report failed is reported again, before any upload: after an
     install the live folder is re-uploaded only once the server has recorded the install, so the
     server never pairs the new live folder with the old installed build (which would turn every
     generated change into an "in-app edit").
  6. No build -> `no_build` (a build is requested, at most every 15 min). The build already
     installed -> `up_to_date`, unless a generated preset was changed in Bambu Studio since that
     install (it differs from its dirs.installed copy by `inapp.diff`, or is gone); then a rebuild is
     requested like below (rulings S29b, S31: Studio's own .info rewrites, bookkeeping keys and the
     owner's own presets never ask for one; they are only uploaded). A build made from other live presets -> a rebuild is requested
     (`rebuild_requested`), re-sent only after 15 min (`waiting` until then; `state.json`
     `requested: {live_hash, at}`). A build made from exactly these live presets -> download,
     install (backup stamp `%Y%m%d-%H%M%S` of `now`), upload the live folder again, `installed(stamp)`.
  `uploaded` is returned when this run uploaded something and the build step had nothing to do
  (`no_build` / `up_to_date`).

Every outcome and the stale-preset list are logged in one line each. Errors other than an install
refusal, a rejected upload or `409 other_pc` propagate (the caller logs them; the next run retries).
"""
import json
import shutil
import tempfile
import time
from pathlib import Path
from typing import Callable

from . import inapp, installer, store, zips
from .client import ApiError
from .studio import StudioFolders
from .treehash import tree_hash

REQUEST_RETRY = 15 * 60
UPLOAD_BACKOFF = 6 * 3600
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


def _read_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


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

    def _needs_upload(self, kind: str, here: str, server_hash) -> bool:
        if server_hash == here:
            return False
        rec = (self.st.get("uploaded") or {}).get(kind) or {}
        if rec.get("local") == here and rec.get("server") and rec.get("server") == server_hash:
            return False  # the server hashes our upload differently; already logged, nothing new to send
        rej = (self.st.get("rejected") or {}).get(kind) or {}
        if rej.get("hash") == here and self.now - float(rej.get("at") or 0) < UPLOAD_BACKOFF:
            return False
        return True

    def _partial(self) -> str | None:
        p = self.st.get("partial") or {}
        return p.get("stamp") if isinstance(p.get("stamp"), str) else None

    def _send(self, kind: str, data: bytes, here: str) -> None:
        label = "live presets" if kind == "live" else "Bambu Studio system presets"
        try:
            if kind != "live":
                res = self.c.upload(kind, data)
            elif self._partial():
                res = self.c.upload(kind, data, user_id=self.f.user_id, partial=self._partial())
            else:
                res = self.c.upload(kind, data, user_id=self.f.user_id)
        except ApiError as e:
            if e.status not in (400, 413):
                raise
            err = f"{e.status} {e.code}: {e.message}"
            self.st.setdefault("rejected", {})[kind] = {"kind": kind, "hash": here, "at": self.now, "error": err}
            self.save()
            self.log(f"the server refused the {label} upload ({err}); not sending this version again for "
                     f"{UPLOAD_BACKOFF // 3600} h")
            return
        self.uploaded = True
        (self.st.get("rejected") or {}).pop(kind, None)
        returned = res.get(f"{kind}_hash") if isinstance(res, dict) else None
        prev = (self.st.get("uploaded") or {}).get(kind) or {}
        self.st.setdefault("uploaded", {})[kind] = {"local": here, "server": returned}
        self.save()
        extra = self.f.variant + " user " + self.f.user_id if kind == "live" else ""
        self.log(f"uploaded the {label} ({len(data)} bytes{', ' + extra if extra else ''})")
        if returned and returned != here and not (prev.get("local") == here and prev.get("server") == returned):
            self.log(f"the server's hash of the {label} ({returned}) differs from this PC's ({here})")

    def upload_live(self) -> None:
        here = tree_hash(self.f.user_filament)
        self._send("live", zips.pack(self.f.user_filament, LIVE_MAX), here)

    def uploads(self, server: dict) -> str:
        here = tree_hash(self.f.user_filament)
        system = tree_hash(self.f.system_filament)
        # both checked against the limits before either is sent
        live_zip = (zips.pack(self.f.user_filament, LIVE_MAX)
                    if self._needs_upload("live", here, server.get("live_hash")) else None)
        sys_zip = (zips.pack(self.f.system_filament, SYSTEM_MAX)
                   if self._needs_upload("system", system, server.get("system_hash")) else None)
        if live_zip is not None:
            self._send("live", live_zip, here)
        if sys_zip is not None:
            self._send("system", sys_zip, system)
        return here

    def accepted_hashes(self, here: str) -> set[str]:
        """Live hashes that mean "built from exactly these live presets"."""
        out = {here}
        rec = (self.st.get("uploaded") or {}).get("live") or {}
        if rec.get("local") == here and rec.get("server"):
            out.add(rec["server"])
        return out

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

    def _download(self, stamp: str, work: Path):
        """(build_dir, BUILD.json) or (None, refusal text)."""
        data = self.c.build(stamp)
        build_dir = work / "build"
        try:
            return build_dir, zips.unpack_build(data, build_dir)
        except ValueError as e:
            return None, f"build {stamp}: {e}"

    def _write_marker(self, stamp: str, backup: Path) -> None:
        store._write_atomic(marker_path(self.d),
                            json.dumps({"stamp": stamp, "backup": backup.name, "at": self.now}).encode())

    def _install(self, stamp: str, build_dir: Path, resuming: bool) -> str:
        try:
            res = self.install_fn(build_dir, self.f, self.d, running=self.running,
                                  stamp_now=time.strftime("%Y%m%d-%H%M%S", time.localtime(self.now)),
                                  before_write=lambda backup: self._write_marker(stamp, backup))
        except installer.Refused as e:
            if e.code == "studio_running":
                if not resuming:
                    self._clear_marker()  # nothing was written by this attempt
                return self.finish("studio_running", f"Bambu Studio started; build {stamp} not installed yet")
            self._clear_marker()
            return self.finish("refused", f"install of build {stamp} refused ({e.code}): {e.reason}")
        # an OSError propagates with the marker kept: the next run resumes this install (or not, see run())
        self._clear_marker()
        self._clear_partial()
        self.st["stale"] = list(res.stale)
        self.st["installed"] = {"stamp": stamp, "at": self.now}
        self.st.pop("requested", None)
        self.st["report"] = stamp
        self.save()
        if res.stale:
            self.log(f"{len(res.stale)} presets are no longer generated; delete them in Bambu Studio: "
                     + ", ".join(res.stale))
        self.report(stamp)                  # first: a failed report must not leave the new live folder uploaded
        self.upload_live()
        return self.finish("installed", f"installed build {stamp} ({len(res.installed)} presets, "
                                        f"backup {res.backup.name})")

    def install(self, stamp: str, accepted: set[str]) -> str:
        work = Path(tempfile.mkdtemp(prefix=".download.", suffix=".tmp", dir=self.d.base))
        try:
            build_dir, meta = self._download(stamp, work)
            if build_dir is None:
                return self.finish("refused", meta)
            if meta.get("stamp") not in (None, stamp) or meta.get("live_hash") not in (None, *accepted):
                return self.finish("refused", f"build {stamp}: its BUILD.json does not match the server's state")
            return self._install(stamp, build_dir, resuming=False)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def resume(self, marker: dict) -> str | None:
        """Finish an interrupted install, or None when it must not be resumed (marker dropped)."""
        stamp = marker["stamp"]
        work = Path(tempfile.mkdtemp(prefix=".download.", suffix=".tmp", dir=self.d.base))
        try:
            try:
                build_dir, meta = self._download(stamp, work)
            except ApiError as e:
                if e.status != 404:
                    raise
                self._clear_marker()
                self.log(f"build {stamp} of the interrupted install is no longer on the server; not resuming it")
                return None
            if build_dir is None:
                self._clear_marker()
                self.log(f"interrupted install not resumed: {meta}")
                return None
            backup = self.d.backups / str(marker.get("backup") or "\0missing")
            live = self.f.user_filament / "base"
            edited = []
            for p in sorted((build_dir / "base").glob("*.json")):
                now = _read_bytes(live / p.name)
                if now == p.read_bytes():
                    continue
                if backup.is_dir() and now == _read_bytes(backup / "base" / p.name):
                    continue  # untouched since the backup (missing in both also matches)
                edited.append(p.stem)
            if edited:
                self._keep_partial(stamp, build_dir)
                self._clear_marker()
                self.log(f"interrupted install of build {stamp} not resumed: edited in Bambu Studio since: "
                         + ", ".join(edited[:20]))
                return None
            self.log(f"finishing the interrupted install of build {stamp}")
            return self._install(stamp, build_dir, resuming=True)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _keep_partial(self, stamp: str, build_dir: Path) -> None:
        """Keep the half-installed build (dirs.partial) and name it in live uploads until an install (S28)."""
        tmp = Path(tempfile.mkdtemp(prefix=".partial.", suffix=".tmp", dir=self.d.base))
        try:
            shutil.copytree(build_dir, tmp / "partial")
            shutil.rmtree(self.d.partial, ignore_errors=True)
            (tmp / "partial").rename(self.d.partial)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.st["partial"] = {"stamp": stamp, "at": self.now}
        self.save()

    def _clear_partial(self) -> None:
        shutil.rmtree(self.d.partial, ignore_errors=True)
        self.st.pop("partial", None)

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
        owner, you = server.get("owner"), server.get("you")
        if owner not in (None, you):
            return self._other_pc(f"the server's sync PC is device {owner}")

        marker = self._marker()
        if marker is not None:
            done = self.resume(marker)
            if done is not None:
                return done
            server = self.c.state()

        pending = self.st.get("report")
        if pending:
            self.report(pending)
            server = self.c.state()

        here = self.uploads(server)

        build = server.get("build")
        if not build:
            sent = self.request(here)
            if self.uploaded:
                return self.finish("uploaded", "no build on the server yet" + ("; asked for one" if sent else ""))
            return self.finish("no_build", "no build on the server yet" + ("; asked for one" if sent else ""))
        stamp = build.get("stamp")
        installed = (server.get("installed") or {}).get("stamp")
        if installed == stamp:
            if self.changed_since_install():
                # a generated preset changed in Bambu Studio since this install (S29b, S31): rebuild
                if self.request(here):
                    return self.finish("rebuild_requested", f"build {stamp} is installed; your Bambu Studio "
                                                            "changes since then were sent and a rebuild asked for")
                at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.st["requested"]["at"]))
                return self.finish("waiting", f"waiting for the rebuild asked at {at}")
            if self.uploaded:
                return self.finish("uploaded", f"build {stamp} is installed; the server has your latest presets")
            return self.finish("up_to_date", f"build {stamp} is installed")
        accepted = self.accepted_hashes(here)
        if build.get("live_hash") not in accepted:
            if self.request(here):
                return self.finish("rebuild_requested",
                                   f"build {stamp} predates your latest Bambu Studio presets; asked for a rebuild")
            return self.finish("waiting", f"waiting for the rebuild asked at "
                                          f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self.st['requested']['at']))}")
        return self.install(stamp, accepted)

    def changed_since_install(self) -> bool:
        """A generated preset of the installed build differs from its live copy by inapp.diff, or is gone."""
        snap = self.d.installed / "base"
        if not snap.is_dir():
            return False
        live = self.f.user_filament / "base"
        for p in sorted(snap.glob("*.json")):
            try:
                old = inapp.load(p)
            except (OSError, UnicodeDecodeError, ValueError):
                continue
            target = live / p.name
            if not target.exists():
                return True
            try:
                now = inapp.load(target)
            except (OSError, UnicodeDecodeError, ValueError):
                return True
            if inapp.diff(old, now):
                return True
        return False

    def _other_pc(self, why: str) -> str:
        return self.finish("other_pc", f"another PC is the sync PC for this server ({why}); unpair it on the "
                                       "server ('sudo filament-kit unpair <id>') to sync from this one")


def run_once(client, folders: StudioFolders, dirs: store.AppDirs, *, running: Callable[[], bool],
             install=installer.install, now: float, echo: Callable[[str], None] | None = None) -> str:
    dirs.ensure()
    r = _Run(client, folders, dirs, running, install, now, echo)
    try:
        return r.run()
    except ApiError as e:
        if e.status == 409 and e.code == "other_pc":
            return r._other_pc(e.message)
        raise
