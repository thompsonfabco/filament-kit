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
import json
import os
import re
import sys
import time
from pathlib import Path

from fksync import __version__, client, store, studio, sync, timer  # absolute: PyInstaller runs this file as a script

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

def _finish_pair(dirs: store.AppDirs, cfg: dict, token: str) -> int:
    old = {}
    try:
        old = store.load_config(dirs)
    except ValueError:
        pass
    for key in ("variant", "user_id", "orca_user_id", "orca_install"):  # pinned app folders survive re-pairing
        if key in old:
            cfg[key] = old[key]
    store.save_config(dirs, cfg)
    store.save_token(dirs, token)
    c = client.Client(cfg, token, timeout=20)
    try:
        info = c.info()
        st = c.state()
    except (client.Offline, client.CertChanged, client.ApiError) as e:
        _out(f"Saved, but the server could not be checked: {e}")
        if isinstance(e, client.ApiError) and e.status == 401:
            _out("The link has expired or was already used: run 'sudo filament-kit pair --pc' again for a new one.")
        return 1
    cfg["device"] = st.get("you")
    store.save_config(dirs, cfg)
    store.log(dirs, f"paired with {info.get('name', 'the server')} at {cfg['host']}:{cfg['port']} "
                    f"(device {cfg['device']})")
    _out(f"Paired with {info.get('name', 'the server')} ({cfg['host']}:{cfg['port']}). "
         "The sync runs every 10 minutes and waits while Bambu Studio (or Orca Slicer) is open.")
    return 0


def cmd_pair(dirs: store.AppDirs) -> int:
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
        return _finish_pair(dirs, cfg, link.token)

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
        token = client.Client(cfg, None, timeout=20).pair(code)
    except client.ApiError as e:
        _out(f"Not paired: {e.message or e.code}")
        return 1
    except (client.Offline, client.CertChanged) as e:
        _out(f"Not paired: {e}")
        return 1
    return _finish_pair(dirs, cfg, token)


def cmd_run(dirs: store.AppDirs, appdata: Path | None, quiet: bool, layout: studio.LinuxLayout | None = None) -> int:
    echo = None if quiet else _out
    dirs.ensure()
    try:
        with store.single_instance(dirs):
            try:
                cfg = store.load_config(dirs)
                token = store.load_token(dirs)
                if not cfg.get("host") or not cfg.get("fp") or not token:
                    store.log(dirs, f"error: this PC is not paired; run '{APP} pair'")
                    if echo:
                        echo(f"This PC is not paired; run '{APP} pair'.")
                    return 1
                folders = studio.locate(appdata, cfg, layout=layout)
                orca = _locate_orca(appdata, cfg, warn=lambda m: _warn(dirs, echo, m), layout=layout)
                c = client.Client(cfg, token, log=lambda m: store.log(dirs, m))
                outcome = sync.run_once(c, folders, dirs, running=studio.running, now=time.time(), echo=echo,
                                        orca=orca, orca_running=studio.orca_running)
            except studio.NotFound as e:
                return _fail(dirs, echo, e.message)
            except client.ApiError as e:
                if e.status == 401:
                    return _fail(dirs, echo, f"the server no longer accepts this PC (unpaired?); run '{APP} pair'")
                return _fail(dirs, echo, str(e))
            except client.Offline as e:  # the PC is away from home, the server is off: try next run
                store.log(dirs, f"warning: {e}")
                if echo:
                    echo(f"warning: {e}")
                return 0
            except client.CertChanged as e:
                return _fail(dirs, echo, str(e))
            except Exception as e:  # noqa: BLE001 - the scheduled task logs it and retries next run
                return _fail(dirs, echo, f"{type(e).__name__}: {e}")
    except store.AlreadyRunning:
        if echo:
            echo("Another sync run is in progress.")
        return 0
    return 0 if outcome in sync.OUTCOMES else 1


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


def _fail(dirs: store.AppDirs, echo, msg: str) -> int:
    store.log(dirs, f"error: {msg}")
    if echo:
        echo(f"error: {msg}")
    return 1


def cmd_status(dirs: store.AppDirs, appdata: Path | None, layout: studio.LinuxLayout | None = None) -> int:
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
    try:
        f = studio.locate(appdata, cfg, layout=layout)
        pin = " (pinned in the config)" if cfg.get("variant") or cfg.get("user_id") else ""
        _out(f"Bambu Studio:    {f.variant}, user {f.user_id}{pin}")
        _out(f"Preset folder:   {f.user_filament}")
    except studio.NotFound as e:
        _out(f"Bambu Studio:    {e.message}")
    st = sync.load_state(dirs)
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
    units = timer.units_dir(os.environ)
    if on:
        return timer.install(units, _self_exe(), echo=_out)
    return timer.uninstall(units, stamp=timer.stamp_file(os.environ), echo=_out)


def _linux() -> bool:
    return sys.platform.startswith("linux")


# --- entry ---------------------------------------------------------------------------------------

def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=APP, description="Sync Bambu Studio (and Orca Slicer) filament presets with a "
                                                      "filament-kit server.")
    p.add_argument("--version", action="version", version=f"{APP} {__version__}")
    p.add_argument("--appdata", help=argparse.SUPPRESS)
    p.add_argument("--localappdata", help=argparse.SUPPRESS)
    cmds = "pair,run,status,unpair" + (",install-timer,uninstall-timer" if _linux() else "")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="{" + cmds + "}")
    sub.add_parser("pair", help="pair this PC with the server (paste the link from 'sudo filament-kit pair --pc')")
    r = sub.add_parser("run", help="run one sync now (the scheduled task runs this every 10 minutes)")
    r.add_argument("--quiet", action="store_true", help="print nothing (the log still gets every line)")
    sub.add_parser("status", help="show the server, the Bambu Studio and Orca Slicer folders, the last run and the "
                                  "installed build")
    sub.add_parser("unpair", help="forget the server and delete this PC's token")
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
        return cmd_pair(dirs)
    if args.cmd == "run":
        return cmd_run(dirs, appdata, args.quiet, layout)
    if args.cmd == "status":
        return cmd_status(dirs, appdata, layout)
    return cmd_unpair(dirs)


if __name__ == "__main__":
    sys.exit(main())
