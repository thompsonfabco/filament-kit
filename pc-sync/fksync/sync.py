"""One sync run (port of filament-ops fpsync.main, over the pinned HTTPS API instead of a share).

  1. Bambu Studio running -> `studio_running`; the only server call is the heartbeat (at most one an hour, see
     "A wait for a running slicer" below), nothing else.
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
     generated change into an "in-app edit"). `state.json` `live_owed` is set before that report and
     cleared by a successful live upload; while it is set the live folder is sent even when its hash
     equals the server's (the server waits for it, ruling S32).
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

  Existing presets are never replaced (the owner's rule, 2026-11-06): an install writes only the presets the
  slicer does not have yet (installer step 6). The updates the owner accepted on the server
  (`sudo filament-kit profiles apply-updates`; state `accepted_updates: {stamp, base, orca}`) are the only ones
  written over an existing preset: with the build they belong to when it is installed, or, for the build that is
  already installed (nothing changed in the app since), by installing it again with them. The report names what
  was written (`installed(stamp, trees, written)`, kept as `report_written` while it is owed), and the server
  clears those from its list; an interrupted install resumes with the same accepted names (marker `accept`).

  An install refused as `stale_build` asks for a rebuild (same 15 min limiter): the server built from
  these live presets, so only a new build can settle the difference.

Orca Slicer (`orca` given: this PC has it; None: everything above, Bambu Studio only, exactly as before):
  - Orca is synced only when the server's state says `orca_target: true` (it makes Orca presets) and carries
    `orca_live_hash` (a server without Orca support would ignore `target=orca` and take the zip as the Bambu
    Studio live folder). Otherwise (also a server without the `orca_target` key), or after a 404 for a
    target=orca upload, Orca is skipped entirely: no running check, no zip, no upload; one log line,
    `state.json` `orca.note` (shown by `status`), retried after UPLOAD_BACKOFF for a 404 (B-I2).
  - Orca Slicer running counts like Bambu Studio running (`studio_running`), checked right after `state()`.
  - Orca's user filament folder (`orca_live`) and its system presets (`orca_system`, zips.orca_system) are
    uploaded with `?target=orca` by the same rules (hash compare, 6 h backoff on 400/413, `orca_live_owed`
    after an install).
  - Orca never holds up Bambu Studio (Ruling Z). An Orca upload the server refused (400/413) or that could not
    be packed (too large, unreadable) is not tried again for UPLOAD_BACKOFF, `orca_live_owed` included; while
    the Orca live folder is not on the server, Orca is not synced this run. A build whose `orca_live_hash` is not
    this PC's Orca live hash asks for a rebuild, but its Bambu Studio presets are installed all the same; its
    orca/ tree is installed only when Orca is synced this run and the build was made from exactly these Orca
    presets (else "Orca presets not installed this run" is logged). An Orca preset changed since the install
    (dirs.installed/orca, kept from the last Orca install by a base/-only install) asks for a rebuild too. The
    installed build whose orca/ did not go in (`state.json` `installed.trees`) is caught up once Orca syncs
    again (B-I1): its orca/ is installed when it was made from these Orca presets, else a rebuild is asked for. An interrupted install is resumed with the trees it was
    started with (marker `orca`), and only when Orca's presets are untouched as well. One `installed(stamp,
    trees)` report covers both trees and says which went in (["base"] or ["base", "orca"], Ruling AB: the
    server diffs the Orca folder against the last build whose orca/ was installed); a report still owed after
    a crash keeps its trees (`state.json` `report_trees`).

Every Bambu Studio folder of this PC (`others`, `secondaries`):
  - The primary is the folder studio.locate picks (pin, else newest conf); everything above is the primary's alone:
    uploads, the build gate, in-app edit detection, rebuild requests, `installed(stamp)` reports. Its records stay
    where they always were (dirs.installed, backups, partial, installing.json, state.json); state `folder`
    {key, variant, user_id, root} says whose they are.
  - Each other usable folder (studio.secondaries: the other of BambuStudio / BambuStudioBeta on Windows, the other
    three roots on Linux) is a secondary, with its own records under dirs.base/folders/<variant>-<user id>/
    (installed/, backups/, installing.json, state.json {variant, user_id, root, installed {stamp, at}, last,
    differing, stale, skipped, owed_accept, error}). After the primary installs build X, and on a later
    `up_to_date` / `uploaded` run when a secondary has not had X, X goes into each secondary (installer
    `secondary=True`): only presets that folder does not have, plus the updates the owner accepted (owed to a
    secondary, `owed_accept`, until written there); a preset edited there since its last install is never written
    over, one deleted there is not added again. A secondary never uploads, never asks for a rebuild and never
    stops the primary: a failure is logged, kept in its state.json (`error`, shown by `status`) and retried next
    run; an interrupted secondary install (its own marker) is finished by the next one. Config
    `secondaries: false`: only the primary is written.
  - Same-name presets that differ from the build and were kept are logged in one line per folder (count and names)
    and kept for `status` (state `differing`, and each secondary's).
  - Another folder becoming the primary (stable <-> Beta; or an older state.json without `folder` whose install
    snapshot matches another folder better) is that folder's first sync, logged: the old primary's records move to
    its secondary record, the new one starts with no snapshot, partial or marker (its secondary record gives up
    only its backups), and its live folder is uploaded with `fresh=1` (state `fresh_owed` until sent), so the
    server forgets the other folder's install too and lists differing same-name presets as updates instead of
    reading them as in-app edits. The server's state is read again after that upload.

A wait for a running slicer: a run that ends `studio_running` counts in state `waiting` {since,
skipped_runs, app} (shown by `status`); after LOUD_AFTER (24 h) its log line becomes a WARNING with the age and the
last installed build. It sends `heartbeat(outcome, waiting_since, app)` at most every HEARTBEAT_EVERY (1 h; state
`heartbeat` {at, outcome}); the first run after the wait sends one more with its own outcome, so the server stops
showing the wait. A heartbeat that fails is logged and never changes the outcome.

Every outcome and the stale-preset list are logged in one line each. Errors other than an install
refusal, a rejected upload or `409 other_pc` propagate (the caller logs them; the next run retries).
"""
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Callable

from . import inapp, installer, store, studio, zips
from .client import ApiError, CertChanged, Offline
from .studio import OrcaFolders, StudioFolders
from .treehash import tree_hash

REQUEST_RETRY = 15 * 60
UPLOAD_BACKOFF = 6 * 3600
HEARTBEAT_EVERY = 3600          # at most one heartbeat an hour while a slicer stays open
LOUD_AFTER = 24 * 3600          # a wait longer than this gets a louder log line
BAMBU, ORCA = installer.BAMBU, installer.ORCA
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


LABELS = {"live": "live presets", "system": "Bambu Studio system presets",
          "orca_live": "Orca Slicer live presets", "orca_system": "Orca Slicer system presets"}
ORCA_UNSUPPORTED = ("the server does not take Orca Slicer presets (update filament-kit on the server); "
                    "only Bambu Studio is synced")
ORCA_NO_TARGET = ("the server makes no Orca Slicer presets (no Orca printers are set up there); only Bambu Studio "
                  "is synced")


class _Run:
    def __init__(self, client, folders: StudioFolders, dirs: store.AppDirs, running, install, now: float,
                 echo: Callable[[str], None] | None, orca: OrcaFolders | None = None,
                 orca_running: Callable[[], bool] | None = None, others: list[StudioFolders] | None = None,
                 secondaries: bool = True, change_reason: str | None = None):
        self.c, self.f, self.d = client, folders, dirs
        self.running, self.install_fn, self.now, self.echo = running, install, now, echo
        self.o, self.orca_running = orca, orca_running or (lambda: False)
        self.others = list(others or [])                        # the other usable Bambu Studio folders
        self.sec = self.others if secondaries else []           # the ones installed into
        self.st = load_state(dirs)
        self.uploaded = False
        self.change_reason = change_reason      # why the primary is not the recorded folder (studio.primary)
        self.fresh_sent = False     # this run sent the live folder as a first sync (a primary change)
        self.orca_on = False        # this run syncs Orca Slicer (set by uploads())

    def log(self, msg: str) -> None:
        store.log(self.d, msg)
        if self.echo:
            self.echo(msg)

    def save(self) -> None:
        _save_state(self.d, self.st)

    def finish(self, outcome: str, detail: str, app: str = BAMBU) -> str:
        if outcome == "studio_running":
            detail = self._waiting(app, detail)
        self.log(f"{outcome}: {detail}")
        self.st["last"] = {"outcome": outcome, "at": self.now, "detail": detail}
        self.save()
        if outcome == "studio_running":
            w = self.st["waiting"]
            self._heartbeat(outcome, w["since"], w["app"])
        else:
            if self.st.pop("waiting", None) is not None:
                self.save()
            if (self.st.get("heartbeat") or {}).get("outcome") == "studio_running":
                self._heartbeat(outcome, None, None)        # the wait is over: said once
        return outcome

    # --- the wait for a running slicer -------------------------------------------------

    def _waiting(self, app: str, detail: str) -> str:
        """Count this run in `waiting` {since, skipped_runs, app}; after LOUD_AFTER the line says how long."""
        w = self.st.get("waiting") if isinstance(self.st.get("waiting"), dict) else {}
        since = w.get("since") if isinstance(w.get("since"), (int, float)) else self.now
        self.st["waiting"] = {"since": since, "skipped_runs": int(w.get("skipped_runs") or 0) + 1, "app": app}
        age = self.now - since
        if age < LOUD_AFTER:
            return detail
        stamp = (self.st.get("installed") or {}).get("stamp") or "never"
        return (f"WARNING: waiting {_age(age)} for {app} to close; presets not installed since {stamp} "
                f"(close {app} to let the sync run)")

    def _heartbeat(self, outcome: str, since: float | None, app: str | None) -> None:
        """Tell the server: at most one an hour while waiting, once when the wait is over. A heartbeat
        that cannot be sent is logged and never changes the run."""
        hb = self.st.get("heartbeat") or {}
        if (outcome == "studio_running" and hb.get("outcome") == outcome
                and self.now - float(hb.get("at") or 0) < HEARTBEAT_EVERY):
            return
        self.st["heartbeat"] = {"at": self.now, "outcome": outcome}
        self.save()
        try:
            self.c.heartbeat(outcome, since, app)
        except ApiError as e:
            why = ("the server does not take heartbeats (update filament-kit on the server)" if e.status == 404
                   else str(e))
            store.log(self.d, f"heartbeat not sent: {why}")
        except (Offline, CertChanged) as e:
            store.log(self.d, f"heartbeat not sent: {e}")

    # --- uploads --------------------------------------------------------------------------

    def _needs_upload(self, kind: str, here: str, server_hash) -> bool:
        if server_hash == here:
            return False
        rec = (self.st.get("uploaded") or {}).get(kind) or {}
        if rec.get("local") == here and rec.get("server") and rec.get("server") == server_hash:
            return False  # the server hashes our upload differently; already logged, nothing new to send
        return not self._backed_off(kind, here)

    def _backed_off(self, kind: str, here: str | None) -> bool:
        """This version (`here`) of `kind` was refused or could not be packed less than UPLOAD_BACKOFF ago (a record
        without a hash: the pack failed before hashing; any version waits)."""
        rej = (self.st.get("rejected") or {}).get(kind) or {}
        return bool(rej) and rej.get("hash") in (None, here) and self.now - float(rej.get("at") or 0) < UPLOAD_BACKOFF

    def _failed(self, kind: str, here: str | None, err: str) -> None:
        """An Orca upload that could not be made (pack too large, unreadable): backed off like a refusal."""
        self.st.setdefault("rejected", {})[kind] = {"kind": kind, "hash": here, "at": self.now, "error": err}
        self.save()

    def _partial(self) -> str | None:
        p = self.st.get("partial") or {}
        return p.get("stamp") if isinstance(p.get("stamp"), str) else None

    def _send(self, kind: str, data: bytes, here: str) -> None:
        label = LABELS[kind]
        try:
            if kind == "orca_live" and self._partial():
                res = self.c.upload(kind, data, partial=self._partial())   # S28 for Orca too (Ruling O)
            elif kind != "live":
                res = self.c.upload(kind, data)
            elif self.st.get("fresh_owed"):          # this folder's first sync: the server forgets the pairing
                kw = {"partial": self._partial()} if self._partial() else {}
                res = self.c.upload(kind, data, user_id=self.f.user_id, fresh=True, **kw)
                self.fresh_sent = True
                self.st.pop("fresh_owed", None)
                if not (isinstance(res, dict) and res.get("fresh") is True):
                    self.log("warning: the server did not confirm this Bambu Studio folder's first sync (update "
                             "filament-kit on the server); it may read this folder's presets as edits of the "
                             "other folder's install")
            elif self._partial():
                res = self.c.upload(kind, data, user_id=self.f.user_id, partial=self._partial())
            else:
                res = self.c.upload(kind, data, user_id=self.f.user_id)
        except ApiError as e:
            if e.status == 404 and kind.startswith("orca_"):
                self._orca_off(f"{ORCA_UNSUPPORTED} (404 for the {label} upload)", unsupported=True)
                return
            if e.status not in (400, 413):
                raise
            err = f"{e.status} {e.code}: {e.message}"
            self.st.setdefault("rejected", {})[kind] = {"kind": kind, "hash": here, "at": self.now, "error": err}
            self.save()
            self.log(f"the server refused the {label} upload ({err}); not sending this version again for "
                     f"{UPLOAD_BACKOFF // 3600} h")
            return
        self.uploaded = True
        if kind in ("live", "orca_live"):
            self.st.pop(f"{kind}_owed", None)
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
        if self.orca_on and self.o is not None:
            h = None
            try:
                h = tree_hash(self.o.user_filament)
                data = zips.pack(self.o.user_filament, LIVE_MAX)
            except (zips.TooLarge, OSError) as e:   # orca_live_owed stays set, but backed off like a refusal
                self._failed("orca_live", h, str(e))
                self.log(f"Orca Slicer live presets not uploaded: {e}; not tried again for "
                         f"{UPLOAD_BACKOFF // 3600} h")
                return
            self._send("orca_live", data, h)

    # --- Orca on / off --------------------------------------------------------------------

    def _orca_off(self, note: str, unsupported: bool = False) -> None:
        """Skip Orca Slicer for this run; log the reason once (and keep it for `status`)."""
        self.orca_on = False
        prev = self.st.get("orca") or {}
        rec = {"note": note, "at": self.now}
        if unsupported:
            rec["unsupported_at"] = self.now
        elif prev.get("note") == note and prev.get("at"):
            rec["at"] = prev["at"]
        self.st["orca"] = rec
        self.save()
        if prev.get("note") != note:
            self.log(note)

    def _orca_wanted(self, server: dict) -> bool:
        if self.o is None:
            self.st.pop("orca", None)
            return False
        if "orca_live_hash" not in server:  # an older server: target=orca would land in the Bambu live folder
            self._orca_off(ORCA_UNSUPPORTED)
            return False
        if server.get("orca_target") is not True:   # B-I2: no Orca printers there (or a server without the key)
            self._orca_off(ORCA_NO_TARGET)
            return False
        prev = self.st.get("orca") or {}
        if prev.get("unsupported_at") and self.now - float(prev["unsupported_at"]) < UPLOAD_BACKOFF:
            return False                    # a 404 for target=orca not long ago
        if prev:
            self.st.pop("orca", None)
            self.save()
        return True

    def uploads(self, server: dict) -> str:
        here = tree_hash(self.f.user_filament)
        system = tree_hash(self.f.system_filament)
        self.orca_on = self._orca_wanted(server)
        # all checked against the limits before any is sent
        owed = bool(self.st.get("live_owed") or self.st.get("fresh_owed"))   # an install was reported (or the
        # folder changed: its first sync); the live upload did not arrive yet
        live_zip = (zips.pack(self.f.user_filament, LIVE_MAX)
                    if owed or self._needs_upload("live", here, server.get("live_hash")) else None)
        sys_zip = (zips.pack(self.f.system_filament, SYSTEM_MAX)
                   if self._needs_upload("system", system, server.get("system_hash")) else None)
        orca = []
        if self.orca_on:
            kind, h = "orca_live", None
            try:
                h = olive = tree_hash(self.o.user_filament)
                owed = self.st.get("orca_live_owed") and not self._backed_off("orca_live", olive)
                if owed or self._needs_upload("orca_live", olive, server.get("orca_live_hash")):
                    orca.append(("orca_live", zips.pack(self.o.user_filament, LIVE_MAX), olive))
                elif server.get("orca_live_hash") != olive and self._backed_off("orca_live", olive):
                    self.orca_on = False        # refused not long ago: Orca is not synced until it is retried
                    self.log("Orca Slicer not synced this run: its live presets were refused or could not be "
                             f"sent less than {UPLOAD_BACKOFF // 3600} h ago")
                kind, h = "orca_system", None
                if self.orca_on and not self._backed_off("orca_system", None):
                    osys_zip, osys = zips.orca_system(self.o, SYSTEM_MAX)
                    if self._needs_upload("orca_system", osys, server.get("orca_system_hash")):
                        orca.append(("orca_system", osys_zip, osys))
            except (zips.TooLarge, OSError) as e:   # an Orca problem (size, unreadable .opc or folder) must
                self._failed(kind, h, str(e))       # not stop the Bambu Studio sync; backed off like a refusal
                self.log(f"Orca Slicer not synced this run: {e}; not tried again for {UPLOAD_BACKOFF // 3600} h")
                self.orca_on, orca = False, []
        if live_zip is not None:
            self._send("live", live_zip, here)
        if sys_zip is not None:
            self._send("system", sys_zip, system)
        for kind, data, h in orca:
            if self.orca_on:                # a 404 on orca_live turns Orca off for the rest of this run
                self._send(kind, data, h)
                if kind == "orca_live" and self._backed_off("orca_live", h):
                    self.orca_on = False    # refused now (400/413): the server has no Orca live presets of ours
        return here

    def accepted_hashes(self, here: str, kind: str = "live") -> set[str]:
        """Live hashes that mean "built from exactly these live presets"."""
        out = {here}
        rec = (self.st.get("uploaded") or {}).get(kind) or {}
        if rec.get("local") == here and rec.get("server"):
            out.add(rec["server"])
        return out

    def orca_accepted(self) -> set[str] | None:
        """This PC's Orca live hashes a build may have been made from; None when Orca is not synced this run."""
        if not self.orca_on or self.o is None:
            return None
        return self.accepted_hashes(tree_hash(self.o.user_filament), "orca_live")

    # --- rebuild requests -----------------------------------------------------------------

    def request(self, here: str) -> bool:
        """Ask for a rebuild for `here` unless one was asked less than 15 min ago for the same live presets
        (Bambu Studio's, and Orca Slicer's when it is synced); True when sent."""
        req = self.st.get("requested") or {}
        orca = tree_hash(self.o.user_filament) if self.orca_on and self.o is not None else None
        if (req.get("live_hash") == here and req.get("orca_live_hash") == orca
                and self.now - float(req.get("at") or 0) < REQUEST_RETRY):
            return False
        if orca is not None:
            self.c.rebuild(here, orca)
        else:
            self.c.rebuild(here)
        self.st["requested"] = {"live_hash": here, "at": self.now}
        if orca is not None:
            self.st["requested"]["orca_live_hash"] = orca
        self.save()
        return True

    # --- install --------------------------------------------------------------------------

    def report(self, stamp: str, trees: list[str] | None = None, written: dict | None = None) -> None:
        trees = list(trees) if trees else ["base"]
        written = written if isinstance(written, dict) else None    # owed by an older PC sync: it wrote them all
        self.st["report"] = stamp
        self.st["report_trees"] = trees
        self.st["report_written"] = written
        self.save()
        try:
            self.c.installed(stamp, trees, written=written)
        except ApiError as e:
            if e.status != 404:
                raise
            self.log(f"build {stamp} is no longer on the server; its install was not recorded there")
        self.st.pop("report", None)
        self.st.pop("report_trees", None)
        self.st.pop("report_written", None)
        self.save()

    def _download(self, stamp: str, work: Path):
        """(build_dir, BUILD.json) or (None, refusal text)."""
        data = self.c.build(stamp)
        build_dir = work / "build"
        try:
            return build_dir, zips.unpack_build(data, build_dir)
        except ValueError as e:
            return None, f"build {stamp}: {e}"

    def _write_marker(self, stamp: str, backup: Path, with_orca: bool, accept: dict | None = None) -> None:
        m = {"stamp": stamp, "backup": backup.name, "at": self.now, "orca": with_orca}
        if accept:
            m["accept"] = accept
        store._write_atomic(marker_path(self.d), json.dumps(m).encode())

    def accepted(self, server: dict, stamp: str) -> dict:
        """The updates the owner accepted for build `stamp` ({"base"|"orca": [names]}, only the non-empty ones;
        Orca's only when Orca is synced this run)."""
        acc = server.get("accepted_updates")
        if not isinstance(acc, dict) or acc.get("stamp") != stamp:
            return {}
        out = {}
        for tree in ("base", "orca"):
            names = acc.get(tree)
            if tree == "orca" and not self.orca_on:
                continue
            if isinstance(names, list) and any(isinstance(n, str) for n in names):
                out[tree] = sorted(n for n in names if isinstance(n, str))
        return out

    def _install(self, stamp: str, build_dir: Path, resuming: bool, with_orca: bool = True,
                 accept: dict | None = None) -> str:
        """Install the build; its orca/ tree only `with_orca` (and when this PC has Orca Slicer). `accept`: the
        accepted updates, the only existing presets written over."""
        with_orca = with_orca and self.o is not None
        kw = {"orca": self.o, "orca_running": self.orca_running} if with_orca else {}
        if accept:
            kw["accept"] = accept
        try:
            res = self.install_fn(build_dir, self.f, self.d, running=self.running,
                                  stamp_now=time.strftime("%Y%m%d-%H%M%S", time.localtime(self.now)),
                                  before_write=lambda backup: self._write_marker(stamp, backup, with_orca, accept),
                                  **kw)
        except installer.Refused as e:
            if e.code == "studio_running":
                if not resuming:
                    self._clear_marker()  # nothing was written by this attempt
                app = ORCA if e.reason == installer.ORCA_RUNNING else BAMBU
                return self.finish("studio_running", f"{app} started; build {stamp} not installed yet", app)
            self._clear_marker()
            detail = f"install of build {stamp} refused ({e.code}): {e.reason}"
            if e.code == "stale_build" and self.request(tree_hash(self.f.user_filament)):
                detail += "; asked for a rebuild"     # server and PC disagree: only a new build can settle it
            return self.finish("refused", detail)
        # an OSError propagates with the marker kept: the next run resumes this install (or not, see run())
        self._clear_marker()
        self._clear_partial()
        self.st["stale"] = list(res.stale)
        installed_orca = list(getattr(res, "installed_orca", []) or [])
        stale_orca = list(getattr(res, "stale_orca", []) or [])
        if self.o is not None:
            self.st["stale_orca"] = stale_orca
        self.st.pop("requested", None)
        trees = ["base", "orca"] if with_orca and (build_dir / "orca").is_dir() else ["base"]
        written = {"base": list(res.installed)}
        if "orca" in trees:
            written["orca"] = installed_orca
        kept = list(getattr(res, "kept", []) or []) + list(getattr(res, "kept_orca", []) or [])
        # orca_synced: Orca was synced and the build made from its presets (its orca/ in, or it had none)
        self.st["installed"] = {"stamp": stamp, "at": self.now, "trees": trees, "orca_synced": bool(with_orca)}
        self.st["report"] = stamp
        self.st["report_trees"] = trees
        self.st["report_written"] = written
        self.st["live_owed"] = True             # until upload_live() succeeds (S32)
        if installed_orca:
            self.st["orca_live_owed"] = True
        self.st["differing"] = list(getattr(res, "differing", []) or [])
        self.save()
        if res.stale:
            self.log(f"{len(res.stale)} presets are no longer generated; delete them in Bambu Studio: "
                     + ", ".join(res.stale))
        if stale_orca:
            self.log(f"{len(stale_orca)} Orca Slicer presets are no longer generated; delete them in Orca Slicer: "
                     + ", ".join(stale_orca))
        if kept:
            self.log(f"{len(kept)} presets are already in the slicer and were left as they are (their updates, if "
                     "any, are listed on the server: filament-kit profiles status)")
        self._log_differing(self.f, stamp, self.st["differing"])
        self.report(stamp, trees, written)  # first: a failed report must not leave the new live folder uploaded
        self.upload_live()
        self.secondaries(stamp, build_dir, (accept or {}).get("base"))
        orca = f", {len(installed_orca)} Orca Slicer presets" if installed_orca else ""
        return self.finish("installed", f"installed build {stamp} ({len(res.installed)} presets{orca} written, "
                                        f"{len(kept)} kept, backup {res.backup.name})")

    def install(self, stamp: str, accepted: set[str], accept: dict | None = None,
                orca_extra: set | None = None, updates_only: bool = False) -> str:
        """`accept`: the accepted updates to write; `orca_extra`: more Orca live hashes that count as these Orca
        presets (the installed build's own, when it is installed again for its accepted updates: `updates_only`,
        which installs nothing when none of them can go in this run)."""
        work = Path(tempfile.mkdtemp(prefix=".download.", suffix=".tmp", dir=self.d.base))
        try:
            build_dir, meta = self._download(stamp, work)
            if build_dir is None:
                return self.finish("refused", meta)
            if meta.get("stamp") not in (None, stamp) or meta.get("live_hash") not in (None, *accepted):
                return self.finish("refused", f"build {stamp}: its BUILD.json does not match the server's state")
            orca_ok = self.orca_accepted()
            if orca_ok is not None and orca_extra:
                orca_ok |= orca_extra
            with_orca = orca_ok is not None and meta.get("orca_live_hash") in orca_ok
            if not with_orca and self.o is not None and (build_dir / "orca").is_dir():
                why = ("Orca Slicer is not synced this run" if orca_ok is None
                       else "the build was not made from your current Orca Slicer presets")
                self.log(f"Orca presets not installed this run ({why}); Bambu Studio presets are")
            if accept and not with_orca:
                accept = {t: v for t, v in accept.items() if t != "orca"} or None
            if updates_only and not accept:
                self.secondaries(stamp, build_dir)
                return self.finish("up_to_date", f"build {stamp} is installed; the accepted Orca Slicer updates "
                                                 "wait until its presets can be installed")
            return self._install(stamp, build_dir, resuming=False, with_orca=with_orca, accept=accept)
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
            edited_orca = []
            if self.o is not None and (build_dir / "orca").is_dir() and marker.get("orca", True) is not False:
                obackup = self.d.orca_backups / str(marker.get("backup") or "\0missing")
                for p in sorted((build_dir / "orca").glob("*.json")):
                    now = _read_bytes(self.o.user_filament / p.name)
                    if now == p.read_bytes():
                        continue
                    if obackup.is_dir() and now == _read_bytes(obackup / p.name):
                        continue
                    edited_orca.append(p.stem)
            if edited or edited_orca:
                self._keep_partial(stamp, build_dir)
                self._clear_marker()
                where = ([f"edited in Bambu Studio since: {', '.join(edited[:20])}"] if edited else []) + \
                        ([f"edited in Orca Slicer since: {', '.join(edited_orca[:20])}"] if edited_orca else [])
                self.log(f"interrupted install of build {stamp} not resumed: " + "; ".join(where))
                return None
            self.log(f"finishing the interrupted install of build {stamp}")
            acc = marker.get("accept") if isinstance(marker.get("accept"), dict) else None
            return self._install(stamp, build_dir, resuming=True, with_orca=marker.get("orca", True) is not False,
                                 accept=acc)
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
        self.check_folder()
        server = self.c.state()
        owner, you = server.get("owner"), server.get("you")
        if owner not in (None, you):
            return self._other_pc(f"the server's sync PC is device {owner}")
        # B-I2: Orca Slicer open only matters when the server makes Orca presets (asked after state())
        if self._orca_wanted(server) and self.orca_running():
            return self.finish("studio_running", "Orca Slicer is open; trying again next run", ORCA)

        marker = self._marker()
        if marker is not None:
            done = self.resume(marker)
            if done is not None:
                return done
            server = self.c.state()

        pending = self.st.get("report")
        if pending:
            self.report(pending, self.st.get("report_trees"), self.st.get("report_written"))
            server = self.c.state()

        here = self.uploads(server)
        if self.fresh_sent:                     # the server forgot the other folder's install: read it again
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
            done = self._orca_catch_up(stamp, build, here, server)
            if done is not None:
                return done
            if self.changed_since_install():
                # a generated preset changed in the app since this install (S29b, S31): rebuild
                if self.request(here):
                    return self.finish("rebuild_requested", f"build {stamp} is installed; your "
                                                            f"{self._apps()} changes since then were sent and a "
                                                            "rebuild asked for")
                at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.st["requested"]["at"]))
                return self.finish("waiting", f"waiting for the rebuild asked at {at}")
            accept = self.accepted(server, stamp)
            if accept:
                # the owner accepted updates of this installed build (nothing changed in the app since): install it
                # again with them; the presets it installed are unchanged, so its own live hashes count
                self.log(f"writing {sum(len(v) for v in accept.values())} updates you accepted for build {stamp}")
                return self.install(stamp, self.accepted_hashes(here) | {build.get("live_hash")}, accept,
                                    orca_extra={build.get("orca_live_hash")}, updates_only=True)
            self.secondaries(stamp)
            if self.uploaded:
                return self.finish("uploaded", f"build {stamp} is installed; the server has your latest presets")
            return self.finish("up_to_date", f"build {stamp} is installed")
        accepted = self.accepted_hashes(here)
        if build.get("live_hash") not in accepted:  # only Bambu Studio gates the install (Ruling Z)
            if self.request(here):
                return self.finish("rebuild_requested",
                                   f"build {stamp} predates your latest {self._apps()} presets; asked for a rebuild")
            return self.finish("waiting", f"waiting for the rebuild asked at "
                                          f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self.st['requested']['at']))}")
        orca_ok = self.orca_accepted()
        if orca_ok is not None and "orca_live_hash" in build and build["orca_live_hash"] not in orca_ok \
                and self.request(here):
            self.log(f"build {stamp} predates your latest Orca Slicer presets; asked for a rebuild")
        return self.install(stamp, accepted, self.accepted(server, stamp))

    # --- the other Bambu Studio folders -------------------------------------------

    def _log_differing(self, f: StudioFolders, stamp: str, names: list[str]) -> None:
        if names:
            self.log(f"{len(names)} presets in {f.variant} user {f.user_id} differ from build {stamp} and were kept "
                     "(never replaced; to take the generated ones: filament-kit profiles apply-updates): "
                     + ", ".join(names))

    def secondaries(self, stamp: str, build_dir: Path | None = None, accepted: list | None = None) -> None:
        """Install build `stamp` into each secondary folder that has not had it (or is owed accepted updates, or has
        an interrupted install). `accepted`: the updates the owner accepted that the primary install just wrote,
        owed to every secondary until written there. Never uploads, never asks for a rebuild; a failure is logged,
        kept in that folder's state and retried next run, and never stops the primary."""
        if not self.sec:
            return
        work = None
        try:
            for f in self.sec:
                where = f"{f.variant} user {f.user_id}"
                sd = store.AppDirs(self.d.base / "folders" / studio.folder_key(f))
                sd.ensure()
                rec = load_state(sd)
                rec.update(variant=f.variant, user_id=f.user_id, root=str(f.root))
                if accepted:
                    rec["owed_accept"] = sorted(set(rec.get("owed_accept") or []) | set(accepted))
                _save_state(sd, rec)
                marker = _read_marker(sd)
                if (rec.get("installed") or {}).get("stamp") == stamp and not rec.get("owed_accept") and not marker:
                    continue
                if rec.get("error_stamp") == stamp and self.now - float(rec.get("error_at") or 0) < UPLOAD_BACKOFF:
                    continue                    # failed with this build not long ago; a new build is tried at once
                if build_dir is None:
                    work = Path(tempfile.mkdtemp(prefix=".download.", suffix=".tmp", dir=self.d.base))
                    try:
                        build_dir, meta = self._download(stamp, work)
                    except Exception as e:  # noqa: BLE001 - a secondary never stops the run
                        build_dir, meta = None, f"build {stamp} could not be downloaded: {e}"
                    if build_dir is None:
                        rec.update(error=str(meta), error_stamp=stamp, error_at=self.now)
                        _save_state(sd, rec)
                        self.log(f"{where}: {meta}; trying again in {UPLOAD_BACKOFF // 3600} h, or at the next build")
                        return
                self._secondary(f, sd, rec, stamp, build_dir, marker)
        finally:
            if work is not None:
                shutil.rmtree(work, ignore_errors=True)

    def _secondary(self, f: StudioFolders, sd: store.AppDirs, rec: dict, stamp: str, build_dir: Path,
                   marker: dict | None) -> None:
        where = f"{f.variant} user {f.user_id}"
        names = set(rec.get("owed_accept") or [])
        if marker is not None:
            names |= set((marker.get("accept") or {}).get("base") or [])
            self.log(f"finishing the interrupted install in {where} (build {marker.get('stamp')})")
        accept = {"base": sorted(names)} if names else None

        def mark(backup: Path) -> None:
            m = {"stamp": stamp, "backup": backup.name, "at": self.now}
            if accept:
                m["accept"] = accept
            store._write_atomic(marker_path(sd), json.dumps(m).encode())

        try:
            res = self.install_fn(build_dir, f, sd, running=self.running,
                                  stamp_now=time.strftime("%Y%m%d-%H%M%S", time.localtime(self.now)),
                                  before_write=mark, accept=accept, secondary=True,
                                  trusted_extra=(self.f.system_filament,))
        except Exception as e:  # noqa: BLE001 - a secondary never stops the primary; retried next run
            err = e.reason if isinstance(e, installer.Refused) else f"{type(e).__name__}: {e}"
            if isinstance(e, installer.Refused):
                marker_path(sd).unlink(missing_ok=True)     # refused: nothing was written
            rec.update(error=err, error_stamp=stamp, error_at=self.now)
            rec["last"] = {"outcome": "failed", "at": self.now, "detail": err}
            _save_state(sd, rec)
            self.log(f"install of build {stamp} into {where} failed: {err}; trying again in "
                     f"{UPLOAD_BACKOFF // 3600} h, or at the next build")
            return
        marker_path(sd).unlink(missing_ok=True)
        differing = list(getattr(res, "differing", []) or [])
        rec.update(installed={"stamp": stamp, "at": self.now}, differing=differing, stale=list(res.stale),
                   skipped=list(getattr(res, "skipped", []) or []))
        for key in ("owed_accept", "error", "error_stamp", "error_at"):
            rec.pop(key, None)
        detail = (f"installed build {stamp} into {where} ({len(res.installed)} presets written, "
                  f"{len(getattr(res, 'kept', []) or [])} kept, backup {res.backup.name})")
        rec["last"] = {"outcome": "installed", "at": self.now, "detail": detail}
        _keep_build_copies(sd, build_dir, differing)
        _save_state(sd, rec)
        self.log(detail)
        self._log_differing(f, stamp, differing)
        if rec["skipped"]:
            self.log(f"{len(rec['skipped'])} presets deleted in {where} were not added again: "
                     + ", ".join(rec["skipped"]))

    # --- which folder the install records belong to ------------------------------------

    @staticmethod
    def _folder_rec(f: StudioFolders) -> dict:
        return {"key": studio.folder_key(f), "variant": f.variant, "user_id": f.user_id, "root": str(f.root)}

    def check_folder(self) -> None:
        """The top-level install records (dirs.installed, backups, partial, the marker, state `installed`) belong to
        the folder in state `folder`. When the primary is another folder now, this is that folder's first sync."""
        cur = studio.folder_key(self.f)
        rec = self.st.get("folder")
        if isinstance(rec, dict) and rec.get("key"):
            if rec["key"] != cur:
                old = next((o for o in self.others if studio.folder_key(o) == rec["key"]), None)
                self._primary_changed(rec["key"], f"{rec.get('variant')} user {rec.get('user_id')}", old)
            return
        # an older PC sync's state (one folder, no `folder`): the install snapshot tells whose it is
        old = self._snapshot_owner()
        if old is self.f:
            self.st["folder"] = self._folder_rec(self.f)
            self.save()
        else:
            self._primary_changed(studio.folder_key(old) if old else None,
                                  f"{old.variant} user {old.user_id}" if old else "an unknown folder", old)

    def _snapshot_owner(self) -> StudioFolders | None:
        """The folder the install snapshot belongs to: the one holding most of its presets unchanged, then most of
        them at all (edited in the app since counts: an edit is no reason to drop the snapshot); self.f on a tie, or
        when there is no snapshot or no other folder; None only when no folder holds any of its presets."""
        snap = self.d.installed / "base"
        files = sorted(snap.glob("*.json")) if snap.is_dir() else []
        if not files or not self.others:
            return self.f

        def score(f: StudioFolders) -> tuple[int, int]:
            same = present = 0
            for p in files:
                live = f.user_filament / "base" / p.name
                if not live.is_file():
                    continue
                present += 1
                try:
                    a, b = inapp.load(p), inapp.load(live)
                except (OSError, UnicodeDecodeError, ValueError):
                    continue
                same += not inapp.diff(a, b) and not inapp.diff(b, a)
            return same, present
        mine = score(self.f)
        best = max(self.others, key=score)
        top = score(best)
        if mine >= top and mine[1] > 0:
            return self.f
        return best if top[1] > 0 else None

    def _primary_changed(self, old_key: str | None, old_desc: str, old: StudioFolders | None) -> None:
        """Another folder is the primary now: the old one's records go to its own secondary record (dropped
        when it is not known), the new one starts like a first sync (its secondary record, if any, only gives its
        backups), and the next live upload tells the server (`fresh`)."""
        folders = self.d.base / "folders"
        if old_key:
            dest = store.AppDirs(folders / old_key)
            shutil.rmtree(dest.base, ignore_errors=True)
            dest.ensure()
            for src, dst in ((self.d.installed, dest.installed), (self.d.backups, dest.backups),
                             (marker_path(self.d), marker_path(dest))):
                if src.exists():
                    os.replace(src, dst)
            rec = {"variant": old.variant if old else None, "user_id": old.user_id if old else None,
                   "root": str(old.root) if old else None, "differing": list(self.st.get("differing") or [])}
            inst = self.st.get("installed")
            if isinstance(inst, dict) and inst.get("stamp"):
                rec["installed"] = {"stamp": inst["stamp"], "at": inst.get("at")}
            _save_state(dest, rec)
        else:                                   # whose it was is not known: kept apart, never dropped
            dest = store.AppDirs(folders / time.strftime("unknown-%Y%m%d-%H%M%S", time.localtime(self.now)))
            dest.ensure()
            for src, dst in ((self.d.installed, dest.installed), (marker_path(self.d), marker_path(dest))):
                if src.exists():
                    os.replace(src, dst)
            inst = self.st.get("installed")
            _save_state(dest, {"installed": inst} if isinstance(inst, dict) else {})
        new = store.AppDirs(folders / studio.folder_key(self.f))
        if new.base.is_dir():
            if new.backups.is_dir():
                self.d.backups.mkdir(parents=True, exist_ok=True)
                for b in sorted(new.backups.iterdir()):
                    if not (self.d.backups / b.name).exists():
                        os.replace(b, self.d.backups / b.name)
            shutil.rmtree(new.base, ignore_errors=True)
        self._clear_partial()
        for key in ("installed", "stale", "live_owed", "requested", "differing"):
            self.st.pop(key, None)
        self.st["fresh_owed"] = True
        self.st["folder"] = self._folder_rec(self.f)
        self.save()
        why = f" because {self.change_reason}" if self.change_reason else ""
        self.log(f"Bambu Studio folder changed from {old_desc} to {self.f.variant} user {self.f.user_id}{why}: this "
                 "is that folder's first sync (its presets are uploaded as they are; nothing in it is replaced)")

    def _orca_went_in(self, stamp: str) -> bool:
        """This PC installed build `stamp`'s orca/ tree (state.json `installed.trees`; an older state.json: the
        snapshot has an orca/ tree, which before B-I1 it only had when the Orca tree went in)."""
        inst = self.st.get("installed") or {}
        if inst.get("stamp") == stamp and isinstance(inst.get("trees"), list):
            return "orca" in inst["trees"] or inst.get("orca_synced") is True   # a build without orca/: settled
        return (self.d.installed / "orca").is_dir()

    def _orca_catch_up(self, stamp: str, build: dict, here: str, server: dict) -> str | None:
        """B-I1: the installed build's orca/ tree did not go in (Orca was not synced on that run, e.g. a refused
        Orca upload). Once Orca syncs again: install it when the build was made from these Orca presets, else ask
        for a rebuild. None when there is nothing to catch up (the normal installed-build checks follow)."""
        orca_ok = self.orca_accepted()
        if orca_ok is None or "orca_live_hash" not in build or self._orca_went_in(stamp):
            return None
        if build["orca_live_hash"] in orca_ok:
            if self.changed_since_install(orca=False):
                return None                     # Bambu Studio edits since: those ask for a rebuild first
            self.log(f"installing the Orca Slicer presets of build {stamp} (they did not go in with its install)")
            # the base/ tree is this PC's install of the same build, unchanged since: its live hash may differ
            return self.install(stamp, self.accepted_hashes(here) | {build.get("live_hash")},
                                self.accepted(server, stamp))
        if self.request(here):
            return self.finish("rebuild_requested", f"build {stamp} is installed without your Orca Slicer "
                                                    "presets; they were sent and a rebuild asked for")
        at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.st["requested"]["at"]))
        return self.finish("waiting", f"waiting for the rebuild asked at {at}")

    def _apps(self) -> str:
        return "Bambu Studio / Orca Slicer" if self.orca_on else "Bambu Studio"

    def changed_since_install(self, orca: bool = True) -> bool:
        """A generated preset of the installed build differs from its live copy by inapp.diff, or is gone (Orca's
        only when Orca is synced this run)."""
        if self._changed(self.d.installed / "base", self.f.user_filament / "base"):
            return True
        return orca and self.orca_on and self.o is not None             and self._changed(self.d.installed / "orca", self.o.user_filament)

    @staticmethod
    def _changed(snap: Path, live: Path) -> bool:
        if not snap.is_dir():
            return False
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


def _age(seconds: float) -> str:
    hours = int(seconds // 3600)
    return f"{hours} hours" if hours < 48 else f"{hours // 24} days"


def _read_marker(dirs: store.AppDirs) -> dict | None:
    try:
        m = json.loads(marker_path(dirs).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return m if isinstance(m, dict) and isinstance(m.get("stamp"), str) else None


def held_dir(sd: store.AppDirs) -> Path:
    """A secondary's copies of the build's version of each preset listed as differing there (apply-updates)."""
    return sd.base / "differing"


def _keep_build_copies(sd: store.AppDirs, build_dir: Path, names: list[str]) -> None:
    held = held_dir(sd)
    shutil.rmtree(held, ignore_errors=True)
    if not names:
        return
    held.mkdir(parents=True)
    for name in names:
        for suffix in (".json", ".info"):
            src = Path(build_dir) / "base" / f"{name}{suffix}"
            if src.is_file():
                shutil.copyfile(src, held / src.name)


def folder_keys(dirs: store.AppDirs) -> list[str]:
    """The secondary folders this PC sync keeps a record of (folders/<variant>-<user id>)."""
    base = dirs.base / "folders"
    if not base.is_dir():
        return []
    return sorted(d.name for d in base.iterdir() if d.is_dir() and not d.name.startswith("unknown-"))


def apply_folder_updates(dirs: store.AppDirs, key: str, names: list[str] | None, *, dry_run: bool,
                         running: Callable[[], bool], now: float, echo: Callable[[str], None]) -> int:
    """`filament-kit-sync apply-updates --folder <key>`: write the build's copy over presets listed as differing in
    that secondary folder (`names`, None: all of them). Backs the folder up first, writes only listed presets, and
    updates that folder's snapshot (the written presets count as the kit's from then on). 0 when done."""
    keys = folder_keys(dirs)
    if key not in keys:
        echo(f"No other Bambu Studio folder {key!r} is synced here. Folders: {', '.join(keys) or 'none'}. (The "
             "primary's updates are accepted on the server: sudo filament-kit profiles apply-updates.)")
        return 1
    sd = store.AppDirs(dirs.base / "folders" / key)
    rec = load_state(sd)
    listed = [n for n in rec.get("differing") or [] if isinstance(n, str)]
    if names is None:
        chosen = list(listed)
    else:
        by = {installer.fold(n): n for n in listed}
        missing = [n for n in names if installer.fold(n) not in by]
        if missing:
            echo(f"Not listed as differing in {key}: {', '.join(missing)}. Listed: {', '.join(listed) or 'none'}.")
            return 1
        chosen = [by[installer.fold(n)] for n in names]
    held = held_dir(sd)
    chosen = [n for n in chosen if (held / f"{n}.json").is_file()]
    if not chosen:
        echo(f"Nothing to write in {key}.")
        return 0
    if dry_run:
        echo(f"Would write the build's copy of {len(chosen)} presets in {key}: {', '.join(chosen)}")
        return 0
    if running():
        echo("Bambu Studio is running; close Bambu Studio, then run this again.")
        return 1
    root, user = rec.get("root"), rec.get("user_id")
    if not (isinstance(root, str) and isinstance(user, str)):
        echo(f"The record of {key} does not name its folder; run the sync once first.")
        return 1
    user_filament = Path(root) / "user" / user / "filament"
    base = user_filament / "base"
    if not base.is_dir():
        echo(f"{base} does not exist.")
        return 1
    try:
        backup = installer._backup(user_filament, sd.backups, time.strftime("%Y%m%d-%H%M%S", time.localtime(now)))
    except installer.Refused as e:
        echo(e.reason)
        return 1
    by_file, by_name = installer._existing(base)
    kept = installer._read_kept(sd.installed)
    written, skipped = [], []
    for name in chosen:
        fname = by_file.get(installer.fold(name)) or by_name.get(installer.fold(name))
        if fname is None:                       # gone, or the owner's inheriting preset in filament/: not ours
            skipped.append(name)
            continue
        installer.write_preset(base, fname, held / f"{name}.json", held / f"{name}.info", user)
        if fname == f"{name}.json":
            (sd.installed / "base").mkdir(parents=True, exist_ok=True)
            shutil.copyfile(base / fname, sd.installed / "base" / fname)
        written.append(name)
        for suffix in (".json", ".info"):
            (held / f"{name}{suffix}").unlink(missing_ok=True)
    if kept is not None:
        (sd.installed / installer.KEPT).write_text(json.dumps({"base": sorted(kept - set(written))}),
                                                   encoding="utf-8")
    rec["differing"] = [n for n in listed if n not in written]
    _save_state(sd, rec)
    msg = (f"wrote the build's copy of {len(written)} presets in {key} (backup {backup.name}): "
           f"{', '.join(written) or 'none'}")
    if skipped:
        msg += f"; not written (no longer in its base folder, or your own preset in filament/): {', '.join(skipped)}"
    store.log(dirs, msg)
    echo(msg)
    return 0


def run_once(client, folders: StudioFolders, dirs: store.AppDirs, *, running: Callable[[], bool],
             install=installer.install, now: float, echo: Callable[[str], None] | None = None,
             orca: OrcaFolders | None = None, orca_running: Callable[[], bool] | None = None,
             others: list[StudioFolders] | None = None, secondaries: bool = True,
             change_reason: str | None = None) -> str:
    """`orca`: this PC's Orca Slicer folders (None: Bambu Studio only); `orca_running` its running check.
    `others`: this PC's other usable Bambu Studio folders (studio.secondaries); `secondaries` (config, default on):
    install each build into them too (off: only `folders`, the primary, is written). `change_reason`: why `folders`
    is not the recorded primary (studio.primary), for the log line."""
    dirs.ensure()
    r = _Run(client, folders, dirs, running, install, now, echo, orca, orca_running, others, secondaries,
             change_reason)
    try:
        return r.run()
    except ApiError as e:
        if e.status == 409 and e.code == "other_pc":
            return r._other_pc(e.message)
        raise
