"""filament-kit-sync: pair this PC with a filament-kit server, run one sync, show status, unpair.

The only module that reads the real environment (%APPDATA% for Bambu Studio and Orca Slicer, %LOCALAPPDATA% for
the sync's own files, %ProgramFiles% and the uninstall registry for the Orca Slicer install); the hidden
--appdata / --localappdata options override the first two. On Linux it reads $HOME and the XDG folders instead
(studio.LinuxLayout, store.linux_data_dir), unless --appdata / --localappdata are given (the tests' Windows-style
trees), and has two more commands: install-timer / uninstall-timer (the systemd user timer, fksync.timer). The pairing token is
read from stdin (inside the pasted link, or from the server after the 6-digit code), never from the
command line, and is never printed or logged.
"""
import argparse
import contextlib
import json
import os
import re
import sys
import time
from pathlib import Path

from fksync import __version__, client, store, studio, sync, timer  # absolute: PyInstaller runs this file as a script

BUSY_PAIR = "A sync run is in progress; try again in a minute. Nothing was changed."
APP = "filament-kit-sync"
_HOST = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,252})$")


def _out(msg: str = "", end: str = "\n") -> None:
    if sys.stdout is not None:  # the windowed task exe has no console
        print(msg, end=end, flush=True)


def _ask(prompt: str) -> str:
    _out(prompt + " ", end="")
    line = sys.stdin.readline() if sys.stdin is not None else ""
    return line.strip()


def _grouped(fp: str) -> str:
    return " ".join(fp[i:i + 4] for i in range(0, len(fp), 4))


def _parse_address(text: str) -> tuple[str, int]:
    host, port = text.strip(), client.DEFAULT_PORT
    if host.lower().startswith("https://"):
        host = host[8:].rstrip("/")
    if host.count(":") == 1:
        host, _, p = host.partition(":")
        if not p.isdigit() or not 1 <= int(p) <= 65535:
            raise ValueError(f"{p!r} is not a port number")
        port = int(p)
    if not _HOST.match(host):
        raise ValueError(f"{host!r} is not a server name or IPv4 address")
    return host, port


# --- commands ------------------------------------------------------------------------------------

def _finish_pair(dirs: store.AppDirs, cfg: dict, token: str, appdata: Path | None = None,
                 layout: studio.LinuxLayout | None = None) -> int:
    """Save the new pairing and prove it, keeping the one in place until then: a stale or mistyped link must not break
    a setup that works. The caller holds the lock. Refused (401, another certificate): the old one comes back. Not
    reached: the new one stays, since a link's token is claimed on first use and a blip must not force a new link."""
    old = {}
    try:
        old = store.load_config(dirs)
    except ValueError:
        pass
    had_old = bool(old.get("host")) and dirs.token.exists()
    for key in ("variant", "user_id", "orca_user_id", "orca_install", "secondaries"):  # survive re-pairing
        if key in old:
            cfg[key] = old[key]
    store.set_pair_aside(dirs)
    store.save_config(dirs, cfg)
    store.save_token(dirs, token)
    c = client.Client(cfg, token, timeout=20)
    try:
        info = c.info()
        st = c.state()
    except (client.CertChanged, client.ApiError, client.Offline) as e:
        if isinstance(e, client.CertChanged) or (isinstance(e, client.ApiError) and e.status == 401):
            store.restore_pair_aside(dirs)
            if had_old:
                _out(f"The new link did not work ({e}); your previous pairing is unchanged.")
            else:
                _out(f"Not paired: {e}")
            if isinstance(e, client.ApiError):
                _out("The link has expired or was already used: run 'sudo filament-kit pair --pc' again for a new one.")
            return 1
        store.drop_pair_aside(dirs)
        _out(f"Saved, but not confirmed yet: {e}. It is tried again within 10 minutes.")
        return 1
    cfg["device"] = st.get("you")
    store.save_config(dirs, cfg)
    store.drop_pair_aside(dirs)
    store.log(dirs, f"paired with {info.get('name', 'the server')} at {cfg['host']}:{cfg['port']} "
                    f"(device {cfg['device']})")
    _out(f"Paired with {info.get('name', 'the server')} ({cfg['host']}:{cfg['port']}). "
         "The sync runs every 10 minutes and waits while Bambu Studio (or Orca Slicer) is open "
         "('filament-kit-sync status' shows a wait).")
    owner = st.get("owner")
    if owner and owner != st.get("you"):
        _out("Another pairing owns the sync for this server (another PC, or this PC's earlier pairing). On the server: "
             f"sudo filament-kit unpair {owner}")
    if appdata is not None or layout is not None:   # information only: the pairing is done whatever this finds
        try:
            folders, _why = studio.primary(appdata, cfg, sync.load_state(dirs).get("folder"), layout=layout)
            _out(f"Bambu Studio folder: {folders.user_filament}")
        except studio.NotFound as e:
            _out(e.message)
    return 0


def cmd_pair(dirs: store.AppDirs, appdata: Path | None = None, layout: studio.LinuxLayout | None = None) -> int:
    text = _ask("Paste the pairing link, or type the server address:")
    if not text:
        _out("Nothing entered.")
        return 1
    if text.lower().startswith("fkit:"):
        try:
            link = client.parse_link(text)
        except ValueError as e:
            _out(f"That link does not work: {e}.")
            return 1
        cfg = {"host": link.host, "port": link.port, "fp": link.fp, "ips": list(link.ips)}
        try:
            with store.single_instance(dirs):
                store.recover_interrupted_pair(dirs)
                return _finish_pair(dirs, cfg, link.token, appdata, layout)
        except store.AlreadyRunning:
            _out(BUSY_PAIR)
            return 1

    try:
        host, port = _parse_address(text)
    except ValueError as e:
        _out(f"That address does not work: {e}.")
        return 1
    try:
        fp, ip = client.fetch_peer(host, port)
    except client.Offline as e:
        _out(f"Could not reach the server: {e}")
        return 1
    _out(f"The server at {host}:{port} shows this certificate fingerprint:")
    _out(f"  {_grouped(fp)}")
    if _ask("Does this match the fingerprint shown by 'sudo filament-kit pair'? [y/N]").lower() not in ("y", "yes"):
        _out("Not paired. Check that you typed the right address.")
        return 1
    code = _ask("6-digit code:")
    if not re.fullmatch(r"[0-9]{6}", code):
        _out("The code is the 6 digits shown by 'sudo filament-kit pair'. Not paired.")
        return 1
    cfg = {"host": host, "port": port, "fp": fp, "ips": [ip]}  # the IP connected to: fallback if the name stops resolving
    try:
        with store.single_instance(dirs):      # before the code is spent
            store.recover_interrupted_pair(dirs)
            try:
                token = client.Client(cfg, None, timeout=20).pair(code)
            except client.ApiError as e:
                _out(f"Not paired: {e.message or e.code}")
                return 1
            except (client.Offline, client.CertChanged) as e:
                _out(f"Not paired: {e}")
                return 1
            return _finish_pair(dirs, cfg, token, appdata, layout)
    except store.AlreadyRunning:
        _out(BUSY_PAIR)
        return 1


def cmd_run(dirs: store.AppDirs, appdata: Path | None, quiet: bool, layout: studio.LinuxLayout | None = None) -> int:
    echo = None if quiet else _out
    dirs.ensure()
    try:
        with store.single_instance(dirs):
            cfg, token = {}, None
            try:
                store.recover_interrupted_pair(dirs)
                cfg = store.load_config(dirs)
                token = store.load_token(dirs)
                if not cfg.get("host") or not cfg.get("fp") or not token:
                    store.log(dirs, f"error: this PC is not paired; run '{APP} pair'")
                    if echo:
                        echo(f"This PC is not paired; run '{APP} pair'.")
                    return 1
                folders, why = studio.primary(appdata, cfg, sync.load_state(dirs).get("folder"), layout=layout)
                others, on = _secondaries(appdata, cfg, folders, layout)
                orca = _locate_orca(appdata, cfg, warn=lambda m: _warn(dirs, echo, m), layout=layout)
                c = client.Client(cfg, token, log=lambda m: store.log(dirs, m))
                outcome = sync.run_once(c, folders, dirs, running=studio.running, now=time.time(), echo=echo,
                                        orca=orca, orca_running=studio.orca_running, others=others,
                                        secondaries=on, change_reason=why)
            except studio.NotFound as e:
                return _fail(dirs, echo, e.message, "no_studio", cfg, token)
            except client.ApiError as e:
                if e.status == 401:
                    return _fail(dirs, echo, f"the server no longer accepts this PC (unpaired?); run '{APP} pair'",
                                 "refused")
                return _fail(dirs, echo, str(e), "server", cfg, token)
            except client.Offline as e:  # the PC is away from home, the server is off: try next run
                store.log(dirs, f"warning: {e}")
                _remember_error(dirs, "offline", str(e))
                if echo:
                    echo(f"warning: {e}")
                return 0
            except client.CertChanged as e:
                return _fail(dirs, echo, str(e), "certificate")
            except Exception as e:  # noqa: BLE001 - the scheduled task logs it and retries next run
                return _fail(dirs, echo, f"{type(e).__name__}: {e}", "crash", cfg, token)
    except store.AlreadyRunning:
        if echo:
            echo("Another sync run is in progress.")
        return 0
    # `refused` includes a stale build, which heals itself; `other_pc` needs someone to act
    return 0 if outcome in sync.OUTCOMES and outcome != "other_pc" else 1


def _secondaries(appdata: Path | None, cfg: dict, primary: studio.StudioFolders,
                 layout: studio.LinuxLayout | None = None) -> tuple[list[studio.StudioFolders], bool]:
    """(this PC's other usable Bambu Studio folders, whether builds are installed there too: config `secondaries`,
    default on; off keeps the single-folder sync)."""
    return studio.secondaries(appdata, primary, layout=layout), cfg.get("secondaries", True) is not False


def _when(t) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(t)))
    except (TypeError, ValueError, OverflowError, OSError):
        return "unknown"


def _differ_line(variant: str, names, key: str | None = None) -> None:
    """Kept presets that differ from the build. The primary's updates are accepted on the server; another folder's
    with apply-updates --folder on this PC (`key`)."""
    names = [n for n in names or [] if isinstance(n, str)]
    if names:
        more = f", and {len(names) - 20} more" if len(names) > 20 else ""
        how = (f"; to take the build's copies: {APP} apply-updates --folder {key} --all (or --name <preset>)" if key
               else "; to take the generated ones: sudo filament-kit profiles apply-updates")
        _out(f"Kept, differ:    {variant}: {len(names)} ({', '.join(names[:20])}{more}){how}")


def _program_files() -> list[Path]:
    out = []
    for var in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        v = os.environ.get(var)
        if v and Path(v) not in out:
            out.append(Path(v))
    return out


def _locate_orca(appdata: Path | None, cfg: dict, warn=None, layout: studio.LinuxLayout | None = None):
    """This PC's Orca Slicer folders, or None (Bambu Studio only). A stale `orca_user_id` / `orca_install` pin
    (e.g. Orca upgraded into a new folder) is warned about and ignored: discovery runs without it."""
    kw = ({"layout": layout} if layout is not None
          else {"program_files": _program_files(), "registry": studio._registry_entries})
    try:
        return studio.locate_orca(appdata, cfg, **kw)
    except studio.NotFound as e:
        if warn:
            warn(f"{e.message} Ignoring the Orca Slicer pin and looking for Orca Slicer instead.")
        unpinned = {k: v for k, v in cfg.items() if k not in ("orca_user_id", "orca_install")}
        return studio.locate_orca(appdata, unpinned, **kw)


def _warn(dirs: store.AppDirs, echo, msg: str) -> None:
    store.log(dirs, f"warning: {msg}")
    if echo:
        echo(f"warning: {msg}")


def _remember_error(dirs: store.AppDirs, kind: str, detail: str) -> None:
    """For `status`: what the last run hit. The next run that gets to its end clears it (sync.Run.finish)."""
    st = sync.load_state(dirs)
    st["last_error"] = {"class": kind, "detail": detail, "at": time.time()}
    sync._save_state(dirs, st)


def _fail(dirs: store.AppDirs, echo, msg: str, kind: str, cfg: dict | None = None, token: str | None = None) -> int:
    """Log it, keep it for `status`, and when the server can be told, tell it the class: never `msg`, which can hold a
    path with the Bambu Studio user folder. `cfg`/`token` are left out for a failure that means it can't be told."""
    store.log(dirs, f"error: {msg}")
    if echo:
        echo(f"error: {msg}")
    _remember_error(dirs, kind, msg)
    outcome = sync.REPORTED_FAILURES.get(kind)
    if outcome and cfg and cfg.get("host") and token:
        sync.report_failure(dirs, client.Client(cfg, token, timeout=10), outcome)
    return 1


def cmd_status(dirs: store.AppDirs, appdata: Path | None, layout: studio.LinuxLayout | None = None) -> int:
    with contextlib.suppress(store.AlreadyRunning):
        with store.single_instance(dirs):
            store.recover_interrupted_pair(dirs)
    try:
        cfg = store.load_config(dirs)
    except ValueError as e:
        _out(str(e))
        cfg = {}
    paired = bool(cfg.get("host")) and store.load_token(dirs) is not None
    if cfg.get("host"):
        ips = f" (also {', '.join(cfg['ips'])})" if cfg.get("ips") else ""
        _out(f"Server:          {cfg['host']}:{cfg.get('port', client.DEFAULT_PORT)}{ips}"
             f"{'' if paired else ' - not paired'}")
        _out(f"Fingerprint:     {_grouped(str(cfg.get('fp', '')))}")
        if cfg.get("device"):
            _out(f"Device id:       {cfg['device']}")
    else:
        _out(f"Server:          not paired; run '{APP} pair'")
    st = sync.load_state(dirs)
    f = None
    try:
        f, why = studio.primary(appdata, cfg, st.get("folder"), layout=layout)
        pin = " (pinned in the config)" if cfg.get("variant") or cfg.get("user_id") else ""
        _out(f"Bambu Studio:    {f.variant}, user {f.user_id}{pin}")
        _out(f"Preset folder:   {f.user_filament}")
        _out(f"Primary:         {f.variant} (its presets are uploaded and builds are made from them; it stays this "
             f"folder whichever app you open last; to use another, set \"variant\" (and \"user_id\") in "
             f"{dirs.config})" + (f"; changes at the next run because {why}" if why else ""))
    except studio.NotFound as e:
        _out(f"Bambu Studio:    {e.message}")
    if f is not None:
        others, on = _secondaries(appdata, cfg, f, layout)
        if not others:
            _out("Also installs:   none (no other Bambu Studio folder on this PC)")
        elif not on:
            _out("Also installs:   none (secondaries is off in the config; "
                 + "; ".join(f"{o.variant}, user {o.user_id}" for o in others) + " is not synced)")
        for o in others if on else []:
            rec = sync.load_state(store.AppDirs(dirs.base / "folders" / studio.folder_key(o)))
            stamp = (rec.get("installed") or {}).get("stamp")
            err = f"; last try failed: {rec['error']}" if rec.get("error") else ""
            _out(f"Also installs:   {o.variant}, user {o.user_id}: "
                 + (f"build {stamp}" if stamp else "nothing installed yet") + err)
    w = st.get("waiting")
    if isinstance(w, dict) and w.get("since"):
        _out(f"Waiting:         for {w.get('app') or 'Bambu Studio'} to close since {_when(w['since'])} "
             f"({int(w.get('skipped_runs') or 0)} runs skipped)")
    try:
        o = _locate_orca(appdata, cfg, warn=lambda m: _out(f"Orca Slicer:     {m}"), layout=layout)
        if o is None:
            _out("Orca Slicer:     not found on this PC (only Bambu Studio is synced)")
        else:
            pin = " (pinned in the config)" if cfg.get("orca_user_id") == o.user_id else ""
            _out(f"Orca Slicer:     user {o.user_id}{pin}")
            _out(f"Orca folder:     {o.user_filament}")
            _out(f"Orca install:    {o.install or 'not found'}"
                 + ("" if o.library_opc else " (no OrcaFilamentLibrary.opc: its presets are not uploaded)"))
            note = (st.get("orca") or {}).get("note")
            if note:
                _out(f"Orca Slicer:     {note}")
    except studio.NotFound as e:
        _out(f"Orca Slicer:     {e.message}")
    failed = st.get("last_error") if isinstance(st.get("last_error"), dict) else None
    if failed:
        when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(failed.get("at") or 0)))
        if failed.get("class") == "offline":
            _out(f"Last try:        could not reach the server at {when}; the next run tries again: {failed.get('detail')}")
        else:
            _out(f"Last run:        FAILED at {when}: {failed.get('detail')}")
    for kind, rec in (st.get("rejected") or {}).items():
        if isinstance(rec, dict):
            _out(f"Upload refused:  the server refused the {kind} upload: {rec.get('error')}. It is tried again later.")
    partial = st.get("partial") if isinstance(st.get("partial"), dict) else None
    if partial:
        _out(f"Install stopped: build {partial.get('stamp')} was not fully installed; the next run finishes it.")
    last = st.get("last") or {}
    if last:
        when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(last.get("at") or 0)))
        _out(f"Last run:        {last.get('outcome')} at {when}: {last.get('detail', '')}")
    else:
        _out("Last run:        none yet")
    stamp = None
    try:
        stamp = json.loads((dirs.installed / "BUILD.json").read_text(encoding="utf-8")).get("stamp")
    except (OSError, ValueError, AttributeError):
        pass
    _out(f"Installed build: {stamp or 'none yet'}")
    if f is not None:
        _differ_line(f.variant, st.get("differing"))
        others, on = _secondaries(appdata, cfg, f, layout)
        for o in others if on else []:
            rec = sync.load_state(store.AppDirs(dirs.base / "folders" / studio.folder_key(o)))
            _differ_line(o.variant, rec.get("differing"), studio.folder_key(o))
    stale = st.get("stale") or []
    if stale:
        _out(f"No longer generated (delete them in Bambu Studio): {', '.join(stale)}")
    else:
        _out("No longer generated: none")
    stale_orca = st.get("stale_orca") or []
    if stale_orca:
        _out(f"No longer generated in Orca Slicer (delete them in Orca Slicer): {', '.join(stale_orca)}")
    _out(f"Log:             {dirs.log_file}")
    return 0


def cmd_apply_updates(dirs: store.AppDirs, key: str, names: list[str] | None, dry_run: bool) -> int:
    dirs.ensure()
    try:
        with store.single_instance(dirs):
            return sync.apply_folder_updates(dirs, key, names, dry_run=dry_run, running=studio.running,
                                             now=time.time(), echo=_out)
    except store.AlreadyRunning:
        _out("A sync run is in progress; try again in a minute.")
        return 1


def cmd_unpair(dirs: store.AppDirs) -> int:
    try:
        cfg = store.load_config(dirs)
    except ValueError:
        cfg = {}
    dirs.token.unlink(missing_ok=True)
    dirs.config.unlink(missing_ok=True)
    store.log(dirs, "unpaired this PC (token and config removed)")
    dev = cfg.get("device")
    _out("This PC is unpaired: its token is deleted.")
    _out(f"On the server, also run 'sudo filament-kit unpair {dev or '<id>'}' so another PC can become the sync PC.")
    return 0


def _self_exe() -> Path:
    """The program the timer should start: the frozen build itself, else this console script."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable)
    return Path(sys.argv[0]).resolve()


def cmd_timer(on: bool) -> int:
    """The units go where the user manager reads them and its stamp is where the manager writes it (the manager's
    XDG folders, which may differ from this shell's); the service gets this shell's XDG folders (timer.XDG_VARS)."""
    sc = timer.systemctl_user
    mgr = timer.manager_env(sc)
    where = os.environ if mgr is None else {"HOME": mgr.get("HOME") or os.environ.get("HOME", ""),
                                            **{v: mgr[v] for v in timer.XDG_VARS if mgr.get(v)}}
    units = timer.units_dir(where)
    if on:
        return timer.install(units, _self_exe(), env=os.environ, systemctl=sc, echo=_out)
    return timer.uninstall(units, stamp=timer.stamp_file(where), systemctl=sc, echo=_out)


def _linux() -> bool:
    return sys.platform.startswith("linux")


# --- entry ---------------------------------------------------------------------------------------

def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=APP, description="Sync Bambu Studio (and Orca Slicer) filament presets with a "
                                                      "filament-kit server.")
    p.add_argument("--version", action="version", version=f"{APP} {__version__}")
    p.add_argument("--appdata", help=argparse.SUPPRESS)
    p.add_argument("--localappdata", help=argparse.SUPPRESS)
    cmds = "pair,run,status,unpair,apply-updates" + (",install-timer,uninstall-timer" if _linux() else "")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="{" + cmds + "}")
    sub.add_parser("pair", help="pair this PC with the server (paste the link from 'sudo filament-kit pair --pc')")
    r = sub.add_parser("run", help="run one sync now (the scheduled task runs this every 10 minutes)")
    r.add_argument("--quiet", action="store_true", help="print nothing (the log still gets every line)")
    sub.add_parser("status", help="show the server, the Bambu Studio folders (the one uploaded and the others it "
                                  "installs into) and Orca Slicer's, a wait for a slicer to close, the last run "
                                  "and the installed build")
    sub.add_parser("unpair", help="forget the server and delete this PC's token")
    au = sub.add_parser("apply-updates", help="in one of the other Bambu Studio folders, replace presets listed as "
                                              "differing ('status': Kept, differ) with the build's copy")
    au.add_argument("--folder", required=True, help="the folder, as <variant>-<user id> (e.g. BambuStudioBeta-123)")
    which = au.add_mutually_exclusive_group(required=True)
    which.add_argument("--name", action="append", help="one listed preset (repeat for more)")
    which.add_argument("--all", action="store_true", help="every listed preset of that folder")
    au.add_argument("--dry-run", action="store_true", help="only show what would be written")
    if _linux():
        sub.add_parser("install-timer", help="run the sync every 10 minutes (a systemd user timer; no root)")
        sub.add_parser("uninstall-timer", help="stop and remove the systemd user timer")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.cmd in ("install-timer", "uninstall-timer"):
        return cmd_timer(args.cmd == "install-timer")
    layout = None
    if _linux() and not args.appdata and not args.localappdata:
        layout = studio.LinuxLayout.from_env(os.environ)
        appdata, dirs = None, store.AppDirs(store.linux_data_dir(os.environ))
    else:
        appdata = Path(args.appdata or os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        local = Path(args.localappdata or os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        dirs = store.AppDirs(local / APP)
    if args.cmd == "pair":
        dirs.ensure()
        return cmd_pair(dirs, appdata, layout)
    if args.cmd == "run":
        return cmd_run(dirs, appdata, args.quiet, layout)
    if args.cmd == "status":
        return cmd_status(dirs, appdata, layout)
    if args.cmd == "apply-updates":
        return cmd_apply_updates(dirs, args.folder, None if args.all else args.name, args.dry_run)
    return cmd_unpair(dirs)


if __name__ == "__main__":
    sys.exit(main())
