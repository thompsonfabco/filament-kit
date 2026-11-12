"""Finds this PC's Bambu Studio data folders and tells whether Bambu Studio is running.

Folder choice (Decision "Bambu Studio folder choice"): from %APPDATA%\\BambuStudio and
%APPDATA%\\BambuStudioBeta take the root whose BambuStudio.conf is newest (a root without a conf
is ranked by its newest user/*/filament dir; a root with no user filament dir is skipped); within it, the user/<id> whose filament dir is
newest. A pin from the sync config (`variant`, `user_id`) wins over both choices. That folder is the primary, and it
stays the primary once the sync has recorded it (`primary`: only a pin, or the folder going away, changes it). Every
other usable root is a secondary (`secondaries`): the PC sync installs each build there too.

Orca Slicer (locate_orca; None when %APPDATA%\\OrcaSlicer has no user/<id>/filament dir, and the sync is then
Bambu Studio only): the user folder is the config pin `orca_user_id`, else OrcaSlicer.conf's
`app.preset_folder` when that folder exists, else the newest user/<id>/filament dir. Orca's user filament
folder is flat (no base/). The install dir (only needed for OrcaFilamentLibrary.opc) is the config pin
`orca_install`, else the uninstall registry entry (HKLM/HKCU, DisplayName "OrcaSlicer...": InstallLocation,
else the folder of DisplayIcon / UninstallString), else the newest `<Program Files>\\OrcaSlicer*` holding
orca-slicer.exe; it may be missing. The packed library is `<install>\\resources\\profiles\\OrcaFilamentLibrary.opc`,
else `%APPDATA%\\OrcaSlicer\\system\\OrcaFilamentLibrary.opc` (Ruling L).

Linux (a LinuxLayout instead of `appdata`; checked against the slicers' sources, see LinuxLayout): Bambu Studio's
roots are $XDG_CONFIG_HOME (else ~/.config)/BambuStudio and .../BambuStudioBeta, and the same two names under the
Flatpak's ~/.var/app/com.bambulab.BambuStudio/config; the choice rule is the one above over all four. Orca Slicer's
root is the newest (same rule, OrcaSlicer.conf) of $XDG_CONFIG_HOME/OrcaSlicer and the Flatpak ones (today's id and
the old io.github.softfever one); its install is the resources folder (<share>/OrcaSlicer from a distro package or
the Flatpak, <prefix>/resources from a tarball) and the library is `<install>/profiles/OrcaFilamentLibrary.opc`,
else the same `<root>/system` copy. "Running" is read from /proc, and when /proc cannot be read it is "running".

The caller passes `appdata` (and the Program Files folders) or a LinuxLayout; only fksync.__main__ reads the real
environment.
"""
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Mapping

VARIANTS = ("BambuStudio", "BambuStudioBeta")
CONF = "BambuStudio.conf"
_USER_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")  # same rule as PUT /api/sync/live?user_id=


class NotFound(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class StudioFolders:
    root: Path
    variant: str
    user_id: str
    user_filament: Path
    system_filament: Path


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _user_filament_dirs(root: Path) -> list[tuple[float, str, Path]]:
    """(mtime, user_id, filament dir) for every user/<id>/filament dir with a valid id."""
    out = []
    try:
        users = list((root / "user").iterdir())
    except OSError:
        return out
    for user in users:
        fil = user / "filament"
        if _USER_ID.match(user.name) and fil.is_dir():
            m = _mtime(fil)
            if m is not None:
                out.append((m, user.name, fil))
    return out


def _root_rank(root: Path, conf_name: str = CONF) -> float | None:
    """The root's rank, or None when it has no user/*/filament dir (a root it could never use)."""
    dirs = _user_filament_dirs(root)
    if not dirs:
        return None
    conf = _mtime(root / conf_name)
    return conf if conf is not None else max(d[0] for d in dirs)


def _pick_root(roots: dict[str, Path], conf: str) -> str | None:
    """The name of the root whose conf is newest (else newest user filament dir); None when none is usable."""
    ranked = [(r, n) for n, p in roots.items() if p.is_dir() and (r := _root_rank(p, conf)) is not None]
    return max(ranked)[1] if ranked else None


def locate(appdata: Path | None, pin: dict | None = None, *, layout: "LinuxLayout | None" = None) -> StudioFolders:
    """`layout`: this Linux PC's folders (then `appdata` is unused); None: Windows, appdata/<variant>."""
    roots = dict(layout.studio_roots()) if layout else {v: Path(appdata) / v for v in VARIANTS}
    pin = pin or {}
    variant, user_id = pin.get("variant"), pin.get("user_id")

    if variant:
        if not isinstance(variant, str) or variant not in roots:
            raise NotFound(f"Bambu Studio variant {variant!r} in the sync config is not one of {', '.join(roots)}.")
        root = roots[variant]
        if not root.is_dir():
            raise NotFound(f"Bambu Studio folder {root} (pinned variant {variant}) does not exist.")
    else:
        variant = _pick_root(roots, CONF)
        if variant is None:
            where = (f"neither {roots[VARIANTS[0]]} nor {roots[VARIANTS[1]]}" if layout is None
                     else "none of " + ", ".join(str(p) for p in roots.values()))
            raise NotFound(f"Bambu Studio not found: {where} "
                           "has a user filament folder. Open Bambu Studio once (and sign in, if you use an "
                           "account), then run the sync again.")
        root = roots[variant]

    if user_id:
        if not _USER_ID.match(str(user_id)):
            raise NotFound(f"Bambu Studio user id {user_id!r} in the sync config is not valid.")
        user_filament = root / "user" / user_id / "filament"
        if not user_filament.is_dir():
            raise NotFound(f"Bambu Studio user folder {user_filament} (pinned user_id {user_id}) does not exist.")
    else:
        dirs = _user_filament_dirs(root)
        if not dirs:
            raise NotFound(f"Bambu Studio folder {root} has no user filament folder. Open Bambu Studio once "
                           "(and sign in, if you use an account), then run the sync again.")
        _, user_id, user_filament = max(dirs)

    return StudioFolders(root=root, variant=variant, user_id=user_id, user_filament=user_filament,
                         system_filament=root / "system" / "BBL" / "filament")


def primary(appdata: Path | None, pin: dict | None, recorded: dict | None, *,
            layout: "LinuxLayout | None" = None) -> tuple[StudioFolders, str | None]:
    """(the primary folder, why it is not the recorded one or None). Once a primary is recorded (sync state
    `folder` {variant, user_id}) it stays that folder, whichever app was opened last. It changes only when the config
    pins another folder (`variant` / `user_id`), or when the recorded folder is gone or has no user filament folder
    any more. With nothing recorded yet, `locate`'s rule picks it (pin, else the newest conf)."""
    pin = pin or {}
    rec = recorded if isinstance(recorded, dict) else {}
    variant, user_id = rec.get("variant"), rec.get("user_id")
    if not (isinstance(variant, str) and isinstance(user_id, str)):
        return locate(appdata, pin, layout=layout), None
    if pin.get("variant") or pin.get("user_id"):
        f = locate(appdata, pin, layout=layout)
        if (f.variant, f.user_id) == (variant, user_id):
            return f, None
        keys = " and ".join(f'"{k}"' for k in ("variant", "user_id") if pin.get(k))
        return f, f"the sync config pins {f.variant} user {f.user_id} ({keys})"
    roots = dict(layout.studio_roots()) if layout else {v: Path(appdata) / v for v in VARIANTS}
    root = roots.get(variant)
    if root is not None and _USER_ID.match(user_id) and (root / "user" / user_id / "filament").is_dir():
        return StudioFolders(root=root, variant=variant, user_id=user_id,
                             user_filament=root / "user" / user_id / "filament",
                             system_filament=root / "system" / "BBL" / "filament"), None
    f = locate(appdata, pin, layout=layout)
    return f, f"{variant} user {user_id} no longer has a Bambu Studio user filament folder"


def secondaries(appdata: Path | None, primary: StudioFolders, *,
                layout: "LinuxLayout | None" = None) -> list[StudioFolders]:
    """Every other usable Bambu Studio root: on Windows the other of BambuStudio / BambuStudioBeta, on
    Linux the other three of the four roots, in that order. Usable: it has a user/<id>/filament dir. Its user is the
    primary's id when that folder exists there, else its own newest (the pins pick the primary only)."""
    roots = dict(layout.studio_roots()) if layout else {v: Path(appdata) / v for v in VARIANTS}
    out = []
    for variant, root in roots.items():
        if variant == primary.variant or Path(root) == Path(primary.root) or not root.is_dir():
            continue
        dirs = _user_filament_dirs(root)
        if not dirs:
            continue
        same = [d for d in dirs if d[1] == primary.user_id]
        _, user_id, user_filament = same[0] if same else max(dirs)
        out.append(StudioFolders(root=root, variant=variant, user_id=user_id, user_filament=user_filament,
                                 system_filament=root / "system" / "BBL" / "filament"))
    return out


def folder_key(f: StudioFolders) -> str:
    """The local store's name for one Bambu Studio user folder: `<variant>-<user id>` ("BambuStudioBeta-123",
    "Flatpak-BambuStudio-123"), safe as a folder name."""
    return re.sub(r"[^A-Za-z0-9_-]+", "-", f"{f.variant}-{f.user_id}")


def _tasklist(image: str = "bambu-studio.exe") -> str:
    return subprocess.run(
        ["tasklist", "/fo", "csv", "/nh", "/fi", f"IMAGENAME eq {image}"],
        capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    ).stdout


def _running(image: str, tasklist: Callable[[], str] | None, proc: Path | None, app: "_LinuxApp") -> bool:
    if tasklist is None:
        if proc is not None or sys.platform.startswith("linux"):
            return _proc_running(app, PROC if proc is None else proc)
        if sys.platform != "win32":
            return False
        return image in (_tasklist(image) or "").lower()
    return image in (tasklist() or "").lower()


def running(tasklist: Callable[[], str] | None = None, *, proc: Path | None = None) -> bool:
    """True when Bambu Studio is running: bambu-studio.exe on Windows, /proc on Linux (unsure: True).
    Always False elsewhere unless a tasklist is given."""
    return _running("bambu-studio.exe", tasklist, proc, _BAMBU_APP)


def orca_running(tasklist: Callable[[], str] | None = None, *, proc: Path | None = None) -> bool:
    """True when Orca Slicer is running: orca-slicer.exe on Windows, /proc on Linux (unsure: True).
    Always False elsewhere unless a tasklist is given."""
    return _running("orca-slicer.exe", tasklist, proc, _ORCA_APP)


# --- Linux: the running check --------------------------------------------------------------------

PROC = Path("/proc")


@dataclass(frozen=True)
class _LinuxApp:
    prefix: str                 # a process name (comm, argv[0]) that starts with it, '-' / '_' / ' ' dropped
    flatpak_ids: tuple[str, ...]
    icon: str                   # <app key>.png next to AppRun inside the app's AppImage mount


# Names checked against the sources: the binary is bambu-studio / orca-slicer (CMake SLIC3R_APP_CMD, also inside
# the Flatpaks); the AppImages are named BambuStudio_*.AppImage / OrcaSlicer_Linux_*.AppImage, their runtime keeps
# running under that name, and the app inside is renamed AppRun with <SLIC3R_APP_KEY>.png beside it.
_BAMBU_APP = _LinuxApp("bambustudio", ("com.bambulab.BambuStudio",), "BambuStudio.png")
_ORCA_APP = _LinuxApp("orcaslicer", ("com.orcaslicer.OrcaSlicer", "io.github.softfever.OrcaSlicer"), "OrcaSlicer.png")


def _norm_name(name: str) -> str:
    return name.lower().replace("-", "").replace("_", "").replace(" ", "")


def _proc_matches(app: _LinuxApp, comm: str, argv: list[str]) -> bool:
    arg0 = Path(argv[0]).name if argv else ""
    if any(_norm_name(n).startswith(app.prefix) for n in (comm, arg0) if n):
        return True
    if any(a.split("//", 1)[0] in app.flatpak_ids for a in argv):        # flatpak run <id>[//branch]
        return True
    if arg0 == "AppRun" or comm == "AppRun":
        mount = Path(argv[0]).parent if argv and Path(argv[0]).is_absolute() else None
        if mount is None:
            return True                                                 # an AppImage we cannot place: unsure
        try:
            return (mount / app.icon).exists() or not mount.is_dir()
        except OSError:
            return True
    return False


def _proc_running(app: _LinuxApp, proc: Path) -> bool:
    """Any process of this user that is the app; True when /proc cannot be listed. Another user's slicer only
    writes that user's folders, so their processes (another st_uid on /proc/<pid>) are skipped."""
    uid = os.getuid() if hasattr(os, "getuid") else None
    try:
        pids = [d for d in proc.iterdir() if d.name.isdigit()]
    except OSError:
        return True
    for d in pids:
        try:
            if uid is not None and d.stat().st_uid != uid:
                continue
            comm = (d / "comm").read_text(encoding="utf-8", errors="replace").strip()
            raw = (d / "cmdline").read_bytes()
        except OSError:                                                 # gone mid-read, or unreadable: skipped
            continue
        argv = [a.decode("utf-8", errors="replace") for a in raw.split(b"\0") if a]
        if _proc_matches(app, comm, argv):
            return True
    return False


# --- Orca Slicer -------------------------------------------------------------------------------

ORCA = "OrcaSlicer"
ORCA_CONF = "OrcaSlicer.conf"
ORCA_EXE = "orca-slicer.exe"
LIBRARY_OPC = "OrcaFilamentLibrary.opc"
_UNINSTALL = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
_UNINSTALL_WOW = r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"


@dataclass(frozen=True)
class OrcaFolders:
    root: Path                  # %APPDATA%\OrcaSlicer
    user_id: str
    user_filament: Path         # flat: <name>.json + <name>.info
    system_bbl: Path            # Orca's unpacked BBL system presets (system\BBL\filament)
    install: Path | None
    library_opc: Path | None


def _conf_preset_folder(root: Path) -> str | None:
    """app.preset_folder from OrcaSlicer.conf (JSON, then Orca's '# MD5 checksum' line); None if unreadable.
    Nothing else of the conf is read (it also holds printer access codes)."""
    try:
        text = (root / ORCA_CONF).read_text(encoding="utf-8")
        conf = json.loads(text[:text.rindex("}") + 1])
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    app = conf.get("app") if isinstance(conf, dict) else None
    folder = app.get("preset_folder") if isinstance(app, dict) else None
    return folder if isinstance(folder, str) and _USER_ID.match(folder) else None


def _registry_entries() -> list[dict]:
    """Uninstall entries (HKLM, HKLM WOW6432Node, HKCU) whose DisplayName starts with OrcaSlicer."""
    if sys.platform != "win32":
        return []
    import winreg
    out = []
    for hive, path in ((winreg.HKEY_LOCAL_MACHINE, _UNINSTALL), (winreg.HKEY_LOCAL_MACHINE, _UNINSTALL_WOW),
                       (winreg.HKEY_CURRENT_USER, _UNINSTALL)):
        try:
            root = winreg.OpenKey(hive, path)
        except OSError:
            continue
        with root:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(root, i)
                except OSError:
                    break
                i += 1
                entry = {}
                try:
                    with winreg.OpenKey(root, sub) as k:
                        for name in ("DisplayName", "InstallLocation", "DisplayIcon", "UninstallString"):
                            try:
                                entry[name] = str(winreg.QueryValueEx(k, name)[0])
                            except OSError:
                                pass
                except OSError:
                    continue
                if entry.get("DisplayName", "").startswith(ORCA):
                    out.append(entry)
    return out


def _exe_dir(value: str) -> Path | None:
    """The folder of a registry path value: '"C:\\x\\Uninstall.exe"' or 'C:\\x\\orca-slicer.exe,0'."""
    v = (value or "").strip()
    v = v[1:].partition('"')[0] if v.startswith('"') else v.partition(",")[0]
    return Path(v).parent if v else None


def _is_install(path: Path | None) -> bool:
    return path is not None and (path / ORCA_EXE).is_file()


def _orca_install(pin: str | None, program_files: Iterable[Path], registry: Callable[[], list[dict]]) -> Path | None:
    if pin:
        p = Path(pin)
        if not _is_install(p):
            raise NotFound(f"Orca Slicer install folder {p} (orca_install in the sync config) has no {ORCA_EXE}.")
        return p
    try:
        entries = registry() or []
    except OSError:
        entries = []
    for e in entries:
        if not str(e.get("DisplayName", "")).startswith(ORCA):
            continue
        for cand in (Path(e["InstallLocation"]) if e.get("InstallLocation") else None,
                     _exe_dir(e.get("DisplayIcon", "")), _exe_dir(e.get("UninstallString", ""))):
            if _is_install(cand):
                return cand
    found = []
    for pf in program_files:
        try:
            dirs = [d for d in Path(pf).glob(f"{ORCA}*") if _is_install(d)]
        except OSError:
            continue
        found += [(m, str(d), d) for d in dirs if (m := _mtime(d / ORCA_EXE)) is not None]
    return max(found)[2] if found else None


def _orca_install_linux(pin: str | None, layout: "LinuxLayout", flatpak_id: str | None) -> Path | None:
    """The resources folder (holding profiles/) of the Orca Slicer that owns this data root, else of any install."""
    if pin:
        p = Path(pin)
        for cand in (p, p / "resources"):
            if (cand / "profiles").is_dir():
                return cand
        raise NotFound(f"Orca Slicer install folder {p} (orca_install in the sync config) has no profiles folder.")
    for cand in layout.orca_installs(flatpak_id):
        if (cand / "profiles").is_dir():
            return cand
    return None


def locate_orca(appdata: Path | None, pin: dict | None = None, *, program_files: Iterable[Path] = (),
                registry: Callable[[], list[dict]] = _registry_entries,
                layout: "LinuxLayout | None" = None) -> OrcaFolders | None:
    """This PC's Orca Slicer folders, or None when Orca Slicer has no user filament folder here.
    `layout`: this Linux PC's folders (then `appdata`, `program_files` and `registry` are unused)."""
    pin = pin or {}
    flatpak_id = None
    if layout is None:
        root = Path(appdata) / ORCA
    else:
        roots = {name: (path, fid) for name, path, fid in layout.orca_roots()}
        name = _pick_root({n: r[0] for n, r in roots.items()}, ORCA_CONF)
        if name is None and not pin.get("orca_user_id"):
            return None
        root, flatpak_id = roots[name or next(iter(roots))]
    user_id = pin.get("orca_user_id")
    if user_id:
        if not _USER_ID.match(str(user_id)):
            raise NotFound(f"Orca Slicer user id {user_id!r} in the sync config is not valid.")
        user_filament = root / "user" / user_id / "filament"
        if not user_filament.is_dir():
            raise NotFound(f"Orca Slicer user folder {user_filament} (pinned orca_user_id {user_id}) does not exist.")
    else:
        dirs = _user_filament_dirs(root)
        if not dirs:
            return None
        folder = _conf_preset_folder(root)
        chosen = [d for d in dirs if d[1] == folder]
        _, user_id, user_filament = chosen[0] if chosen else max(dirs)
    if layout is None:
        install = _orca_install(pin.get("orca_install"), program_files, registry)
        packed = (install / "resources" / "profiles" / LIBRARY_OPC) if install else None
    else:
        install = _orca_install_linux(pin.get("orca_install"), layout, flatpak_id)
        packed = (install / "profiles" / LIBRARY_OPC) if install else None
    opc = None
    for cand in (packed,
                 root / "system" / LIBRARY_OPC):
        if cand is not None and cand.is_file():
            opc = cand
            break
    return OrcaFolders(root=root, user_id=user_id, user_filament=user_filament,
                       system_bbl=root / "system" / "BBL" / "filament", install=install, library_opc=opc)


# --- Linux: where the slicers keep their folders -------------------------------------------------

BAMBU_FLATPAK = "com.bambulab.BambuStudio"
ORCA_FLATPAKS = ("com.orcaslicer.OrcaSlicer", "io.github.softfever.OrcaSlicer")   # today's id, then the old one


@dataclass(frozen=True)
class LinuxLayout:
    """This Linux user's slicer folders. Checked against the sources (see the report of task LINUX):
    - Bambu Studio GUI_App::init_app_config: $XDG_CONFIG_HOME (unset or empty: ~/.config) + "/BambuStudio", with
      "Beta" appended for the beta builds (BBL_INTERNAL_TESTING); an AppImage uses the same folder.
    - Orca Slicer default_data_dir(): the same $XDG_CONFIG_HOME rule + "/OrcaSlicer" (a portable data_dir beside
      the binary is not looked for: pin it with the sync config instead). Its Flatpak moved from
      io.github.softfever.OrcaSlicer to com.orcaslicer.OrcaSlicer and copies the old folder on first start.
    - Flatpak sets XDG_CONFIG_HOME to ~/.var/app/<id>/config inside the sandbox, whatever the host has.
    - Orca resources: SLIC3R_FHS builds (distro packages and the Flatpak, prefix /app) install them as
      <prefix>/share/OrcaSlicer; tarball / AppImage builds keep <bin>/../resources (an AppImage's is only
      mounted while it runs, so the <data>/system copy is used then).
    """
    home: Path
    xdg_config: Path
    system_flatpak: Path = Path("/var/lib/flatpak")
    share_dirs: tuple[Path, ...] = (Path("/usr/share"), Path("/usr/local/share"))
    opt_dirs: tuple[Path, ...] = (Path("/opt"),)
    user_flatpak: Path | None = field(default=None)

    @classmethod
    def from_env(cls, env: Mapping[str, str], **kw) -> "LinuxLayout":
        home = Path(env.get("HOME") or Path.home())
        xdg = env.get("XDG_CONFIG_HOME")
        data = env.get("XDG_DATA_HOME")
        user_flatpak = (Path(data) if data else home / ".local" / "share") / "flatpak"
        return cls(home=home, xdg_config=Path(xdg) if xdg else home / ".config", user_flatpak=user_flatpak, **kw)

    def _flatpak_config(self, app_id: str) -> Path:
        return self.home / ".var" / "app" / app_id / "config"

    def studio_roots(self) -> list[tuple[str, Path]]:
        fp = self._flatpak_config(BAMBU_FLATPAK)
        return ([(v, self.xdg_config / v) for v in VARIANTS]
                + [(f"Flatpak {v}", fp / v) for v in VARIANTS])

    def orca_roots(self) -> list[tuple[str, Path, str | None]]:
        new, old = ORCA_FLATPAKS
        return [(ORCA, self.xdg_config / ORCA, None),
                (f"Flatpak {ORCA}", self._flatpak_config(new) / ORCA, new),
                (f"Flatpak {ORCA} (io.github.softfever)", self._flatpak_config(old) / ORCA, old)]

    def _flatpak_share(self, app_id: str) -> list[Path]:
        bases = [b for b in (self.user_flatpak, self.system_flatpak) if b is not None]
        return [b / "app" / app_id / "current" / "active" / "files" / "share" / ORCA for b in bases]

    def orca_installs(self, flatpak_id: str | None) -> list[Path]:
        """Resources folders to try, best first: this Flatpak's own (user, then system installation) for a
        Flatpak data root; else the native ones (<share>/OrcaSlicer, /opt/OrcaSlicer*/resources)."""
        if flatpak_id:
            return self._flatpak_share(flatpak_id)
        out = [d / ORCA for d in self.share_dirs]
        for opt in self.opt_dirs:
            try:
                out += sorted(d / "resources" for d in Path(opt).glob(f"{ORCA}*"))
            except OSError:
                continue
        return out
