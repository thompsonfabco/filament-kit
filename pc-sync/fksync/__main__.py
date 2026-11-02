"""filament-kit-sync: pair this PC with a filament-kit server, run one sync, show status, unpair.

The only module that reads the real environment (%APPDATA% for Bambu Studio, %LOCALAPPDATA% for the
sync's own files); the hidden --appdata / --localappdata options override both. The pairing token is
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

from . import __version__, client, store, studio, sync

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
    for key in ("variant", "user_id"):  # a pinned Bambu Studio folder survives re-pairing
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
         "The sync runs every 10 minutes and waits while Bambu Studio is open.")
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
        fp = client.fetch_fingerprint(host, port)
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
    cfg = {"host": host, "port": port, "fp": fp, "ips": []}
    try:
        token = client.Client(cfg, None, timeout=20).pair(code)
    except client.ApiError as e:
        _out(f"Not paired: {e.message or e.code}")
        return 1
    except (client.Offline, client.CertChanged) as e:
        _out(f"Not paired: {e}")
        return 1
    return _finish_pair(dirs, cfg, token)


def cmd_run(dirs: store.AppDirs, appdata: Path, quiet: bool) -> int:
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
                folders = studio.locate(appdata, cfg)
                c = client.Client(cfg, token)
                outcome = sync.run_once(c, folders, dirs, running=studio.running, now=time.time(), echo=echo)
            except studio.NotFound as e:
                return _fail(dirs, echo, e.message)
            except client.ApiError as e:
                if e.status == 401:
                    return _fail(dirs, echo, f"the server no longer accepts this PC (unpaired?); run '{APP} pair'")
                return _fail(dirs, echo, str(e))
            except (client.Offline, client.CertChanged) as e:
                return _fail(dirs, echo, str(e))
            except Exception as e:  # noqa: BLE001 - the scheduled task logs it and retries next run
                return _fail(dirs, echo, f"{type(e).__name__}: {e}")
    except store.AlreadyRunning:
        if echo:
            echo("Another sync run is in progress.")
        return 0
    return 0 if outcome in sync.OUTCOMES else 1


def _fail(dirs: store.AppDirs, echo, msg: str) -> int:
    store.log(dirs, f"error: {msg}")
    if echo:
        echo(f"error: {msg}")
    return 1


def cmd_status(dirs: store.AppDirs, appdata: Path) -> int:
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
        f = studio.locate(appdata, cfg)
        pin = " (pinned in the config)" if cfg.get("variant") or cfg.get("user_id") else ""
        _out(f"Bambu Studio:    {f.variant}, user {f.user_id}{pin}")
        _out(f"Preset folder:   {f.user_filament}")
    except studio.NotFound as e:
        _out(f"Bambu Studio:    {e.message}")
    st = sync.load_state(dirs)
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


# --- entry ---------------------------------------------------------------------------------------

def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=APP, description="Sync Bambu Studio filament presets with a filament-kit server.")
    p.add_argument("--version", action="version", version=f"{APP} {__version__}")
    p.add_argument("--appdata", help=argparse.SUPPRESS)
    p.add_argument("--localappdata", help=argparse.SUPPRESS)
    sub = p.add_subparsers(dest="cmd", required=True, metavar="{pair,run,status,unpair}")
    sub.add_parser("pair", help="pair this PC with the server (paste the link from 'sudo filament-kit pair --pc')")
    r = sub.add_parser("run", help="run one sync now (the scheduled task runs this every 10 minutes)")
    r.add_argument("--quiet", action="store_true", help="print nothing (the log still gets every line)")
    sub.add_parser("status", help="show the server, the Bambu Studio folder, the last run and the installed build")
    sub.add_parser("unpair", help="forget the server and delete this PC's token")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    appdata = Path(args.appdata or os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    local = Path(args.localappdata or os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    dirs = store.AppDirs(local / APP)
    if args.cmd == "pair":
        dirs.ensure()
        return cmd_pair(dirs)
    if args.cmd == "run":
        return cmd_run(dirs, appdata, args.quiet)
    if args.cmd == "status":
        return cmd_status(dirs, appdata)
    return cmd_unpair(dirs)


if __name__ == "__main__":
    sys.exit(main())
