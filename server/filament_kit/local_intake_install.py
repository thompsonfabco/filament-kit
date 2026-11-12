"""Install, upgrade and remove the local label reader (the `local_intake` module) from its own signed releases.

The reader is a separate program in its own repository (filament-kit-image). The kit ships none of its code: this
file downloads a release, checks it the way the kit checks its own (`release.py`: ed25519 over SHA256SUMS, the key
pinned here), unpacks it and runs that release's installer. The scheme is in the handoff
`2026-11-12-1214-server-builder-release-signing-scheme.md`; the release layout this file expects:

    SHA256SUMS, SHA256SUMS.sig                         every asset below, signed with the module's own key
    manifest.json                                      {"version", "api_version": "1.x", "kit_min": "X.Y.Z",
                                                        "tiers": {"cpu": {"assets": [...], "disk_mb", "minutes",
                                                                          "download_mb"?}, "gpu": {...}, ...}}
    filament-kit-image-<version>.tar.gz                the code; top folder filament-kit-image-<version>/ with
                                                        install/filament-kit-image.sh
    the tier's model assets (named in the manifest)    put next to the code, given to the installer by --assets

The installer runs as `bash install/filament-kit-image.sh --tier T --port P --bind 127.0.0.1 --user
filament-kit-image --prefix <PREFIX> --assets <dir>` (and `--uninstall --prefix <PREFIX>`); it owns its systemd unit,
is idempotent (an upgrade is the newer release's installer over the old one), and exits 0 only when /v1/health
answers. The kit then switches the module on, points `local_intake.url` at it and checks its health.

Kept: the release folder of the installed version and of the one before (for its --uninstall), under STORE; what is
installed in <state>/local-intake.json.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tarfile
import time
from pathlib import Path, PurePosixPath
from typing import Callable

from . import config, local_reader, release

# The module's release key: ed25519, the raw 32 bytes in base64, as release.PUBKEY. A PLACEHOLDER until the module's
# first signed release: empty means no release can be verified, so nothing is installed. Replace it with the key the
# module's owner prints (its own key pair, never the kit's).
MODULE_PUBKEY = ""
MODULE_REPO = "thompsonfabco/filament-kit-image"
NAME = "filament-kit-image"
MANIFEST = "manifest.json"
STORE = Path("/opt/filament-kit/local-intake")
PREFIX = "/opt/filament-kit-image"
SERVICE_USER = "filament-kit-image"
DEFAULT_PORT = 7915
LIMIT_MANIFEST = 256 << 10
LIMIT_ASSET = 8 << 30            # a model file: the GPU adapter is large
HEALTH_WAIT = 180                # seconds after the installer: the first start loads the models
API_MAJOR = local_reader.API_MAJOR


class InstallError(Exception):
    """The release could not be found, checked or installed; the message says which and what to do."""


def settings(cfg: dict) -> dict:
    li = cfg.get("local_intake") if isinstance(cfg.get("local_intake"), dict) else {}
    u = cfg.get("updates") if isinstance(cfg.get("updates"), dict) else {}
    return {"repo": li.get("repo") or MODULE_REPO, "api": li.get("api") or release.API,
            "token_file": li.get("token_file") or u.get("token_file") or None,
            "pubkey": MODULE_PUBKEY}                    # never from config.json: only the key pinned in the code


def default_fetcher(cfg: dict) -> release.Fetcher:
    s = settings(cfg)
    return release.Fetcher(s["api"], release.read_token(s["token_file"]))


def store() -> Path:
    return Path(os.environ.get("FK_LOCAL_INTAKE_STORE") or STORE)


def _state_file() -> Path:
    return config.paths().state / "local-intake.json"


def installed() -> dict | None:
    """{version, tier, port, prefix, at} of the installed reader, or None."""
    try:
        d = json.loads(_state_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) and isinstance(d.get("version"), str) else None


def _write_state(d: dict | None) -> None:
    f = _state_file()
    if d is None:
        f.unlink(missing_ok=True)
        return
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=2), encoding="utf-8")
    os.replace(tmp, f)


def code_name(version: str) -> str:
    return f"{NAME}-{version}.tar.gz"


def _kit_version() -> tuple[int, int, int]:
    from . import __version__
    return release.parse_version(__version__.split("-")[0])


def _manifest(raw: bytes, version: str) -> dict:
    try:
        m = json.loads(raw)
    except ValueError:
        raise InstallError("the release's manifest.json is not JSON") from None
    if not isinstance(m, dict) or m.get("version") != version or not isinstance(m.get("tiers"), dict):
        raise InstallError("the release's manifest.json does not describe this release")
    major = local_reader._major(m.get("api_version"))
    if major != API_MAJOR:
        raise InstallError(f"this reader release speaks API {m.get('api_version')!r}; this kit speaks {API_MAJOR}.x: "
                           + ("update the kit first" if major and major > API_MAJOR else "use a newer reader release"))
    kit_min = m.get("kit_min")
    if kit_min is not None:
        try:
            if _kit_version() < release.parse_version(str(kit_min)):
                raise InstallError(f"this reader release needs filament-kit {kit_min} or later: update the kit first")
        except release.ReleaseError:
            raise InstallError(f"the release's kit_min {kit_min!r} is not a version") from None
    for t, d in m["tiers"].items():
        if not isinstance(d, dict) or not isinstance(d.get("assets"), list) or \
                not all(isinstance(a, str) and _plain_name(a) for a in d["assets"]):
            raise InstallError(f"the release's manifest.json has a bad entry for tier {t!r}")
    return m


def _plain_name(name: str) -> bool:
    return bool(name) and "/" not in name and "\\" not in name and not name.startswith(".") and len(name) < 200


def _tier_entry(m: dict, tier: str) -> dict:
    if tier not in m["tiers"]:
        raise InstallError(f"this release has no {tier} tier (it has: {', '.join(sorted(m['tiers']))})")
    return m["tiers"][tier]


def _mb(v) -> int | None:
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 else None


def plan(cfg: dict, *, tier: str | None = None, version: str | None = None,
         fetcher: release.Fetcher | None = None) -> dict:
    """What an install would do, before anything is downloaded beyond the signed list and the manifest: the
    version, the installed one, and per tier the download, disk and time the release states. Raises InstallError."""
    fetcher = fetcher or default_fetcher(cfg)
    s = settings(cfg)
    rel, table, sums, sig = _signed(fetcher, s, version)
    m = _manifest(_get_listed(fetcher, rel, table, MANIFEST, LIMIT_MANIFEST), rel["version"])
    tiers = {}
    for t, d in sorted(m["tiers"].items()):
        tiers[t] = {"download_mb": _mb(d.get("download_mb")), "disk_mb": _mb(d.get("disk_mb")),
                    "minutes": _mb(d.get("minutes")), "assets": list(d["assets"]),
                    "fetched_at_install": str(d.get("fetched_at_install") or "")[:200]}
    tier = tier or local_reader.settings(cfg)["tier"]
    have = installed()
    return {"version": rel["version"], "installed": have["version"] if have else None,
            "installed_tier": have.get("tier") if have else None, "tier": tier, "tiers": tiers,
            "upgrade": bool(have) and release.parse_version(rel["version"]) > release.parse_version(have["version"]),
            "same": bool(have) and have["version"] == rel["version"] and have.get("tier") == tier,
            "notes": rel.get("notes", "")[:2000]}


def plan_text(p: dict) -> list[str]:
    """The lines the CLI and the page show before the owner confirms."""
    lines = []
    if p["installed"]:
        lines.append(f"Installed: version {p['installed']} ({p['installed_tier'] or '?'} tier).")
    t = p["tiers"].get(p["tier"])
    if t is None:
        return lines + [f"Release {p['version']} has no {p['tier']} tier (it has: {', '.join(p['tiers'])})."]
    what = "Upgrade to" if p["upgrade"] else ("Reinstall" if p["same"] else "Install")
    parts = []
    if t["download_mb"] is not None:
        parts.append(f"download about {t['download_mb']} MB")
    if t["disk_mb"] is not None:
        parts.append(f"about {t['disk_mb']} MB of disk")
    if t["minutes"] is not None:
        parts.append(f"about {t['minutes']} min")
    lines.append(f"{what} the local label reader {p['version']}, {p['tier']} tier: " + (", ".join(parts) or
                                                                                         "sizes not stated") + ".")
    if t["fetched_at_install"]:
        lines.append(f"The installer also fetches: {t['fetched_at_install']}.")
    others = [f"{k}: {v['download_mb'] or '?'} MB download, {v['disk_mb'] or '?'} MB disk"
              for k, v in p["tiers"].items() if k != p["tier"]]
    if others:
        lines.append("Other tiers: " + "; ".join(others) + ".")
    return lines


def _signed(fetcher: release.Fetcher, s: dict, version: str | None):
    if not s["pubkey"]:
        raise InstallError("this kit has no release key for the local reader yet (it comes with the reader's first "
                           "signed release): nothing can be installed")
    try:
        release.public_key(s["pubkey"])
        rel = fetcher.release(s["repo"], version)
        for need in (release.SUMS, release.SIG, MANIFEST, code_name(rel["version"])):
            if need not in rel["assets"]:
                raise InstallError(f"reader release {rel['version']} has no {need}")
        sums = fetcher.get(rel["assets"][release.SUMS], release.LIMIT_SUMS)
        sig = fetcher.get(rel["assets"][release.SIG], release.LIMIT_SIG)
        table = release.verify_sums(sums, sig, s["pubkey"])
    except release.ReleaseError as e:
        raise InstallError(str(e).replace("filament-kit release", "reader release")) from None
    return rel, table, sums, sig


def _get_listed(fetcher, rel: dict, table: dict, name: str, limit: int) -> bytes:
    import hashlib
    if name not in table:
        raise InstallError(f"the signed {release.SUMS} does not list {name}")
    try:
        data = fetcher.get(rel["assets"][name], limit)
    except release.ReleaseError as e:
        raise InstallError(str(e)) from None
    if hashlib.sha256(data).hexdigest() != table[name]:
        raise InstallError(f"{name} does not match its hash in the signed {release.SUMS}: nothing was installed")
    return data


def _save_listed(fetcher, rel: dict, table: dict, name: str, dest: Path) -> None:
    if name not in table:
        raise InstallError(f"the signed {release.SUMS} does not list {name}")
    if name not in rel["assets"]:
        raise InstallError(f"reader release {rel['version']} has no {name}")
    try:
        fetcher.save(rel["assets"][name], dest / name, LIMIT_ASSET)
        release.check_hash(dest / name, table)
    except release.ReleaseError as e:
        (dest / name).unlink(missing_ok=True)
        raise InstallError(str(e)) from None


def _extract_code(tarball: Path, version: str, dest: Path) -> Path:
    """Unpack the verified code tarball: plain files and folders under filament-kit-image-<version>/ only."""
    top = f"{NAME}-{version}"
    with tarfile.open(tarball, "r:gz") as tf:
        members = tf.getmembers()
        for mbr in members:
            p = PurePosixPath(mbr.name)
            if (p.is_absolute() or ".." in p.parts or not p.parts or p.parts[0] != top or mbr.issym()
                    or mbr.islnk() or not (mbr.isfile() or mbr.isdir())):
                raise InstallError(f"the reader's tarball holds an unexpected entry {mbr.name!r}; nothing was installed")
        if hasattr(tarfile, "data_filter"):
            tf.extractall(dest, members=members, filter="data")
        else:
            tf.extractall(dest, members=members)
    root = dest / top
    if not (root / "install" / f"{NAME}.sh").is_file():
        raise InstallError(f"the reader's tarball has no {top}/install/{NAME}.sh")
    return root


def default_run(cmd: list[str], log: Callable[[str], None]) -> int:
    """Run the installer with its output going to `log`, line by line (the page's job log, the terminal)."""
    p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         errors="replace")
    assert p.stdout is not None
    for line in p.stdout:
        log(line.rstrip("\n"))
    return p.wait()


def _port(cfg: dict) -> int:
    from urllib.parse import urlparse
    u = urlparse(local_reader.settings(cfg)["url"])
    if u.hostname in ("127.0.0.1", "localhost", "::1") and u.port:
        return u.port
    return DEFAULT_PORT


def install(cfg: dict, *, tier: str | None = None, version: str | None = None,
            fetcher: release.Fetcher | None = None, run: Callable[..., int] | None = None,
            say: Callable[[str], None] = print, health_wait: float = HEALTH_WAIT) -> dict:
    """Download, verify, unpack and install the reader on this machine; returns the new installed record. The
    caller switches the module on and applies (cli.cmd_local_intake_install). Raises InstallError; on a failure
    before the installer ran nothing on the machine changed."""
    fetcher = fetcher or default_fetcher(cfg)
    run = run or default_run
    s = settings(cfg)
    tier = tier or local_reader.settings(cfg)["tier"]
    if tier not in local_reader.TIERS:
        raise InstallError(f"tier must be one of {', '.join(local_reader.TIERS)}")
    rel, table, sums, sig = _signed(fetcher, s, version)
    ver = rel["version"]
    m = _manifest(_get_listed(fetcher, rel, table, MANIFEST, LIMIT_MANIFEST), ver)
    entry = _tier_entry(m, tier)
    home = store()
    work = home / f".{ver}.partial"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    try:
        assets = work / "assets"
        assets.mkdir()
        say(f"Downloading the local label reader {ver} ({tier} tier) and checking each file against the signed list...")
        _save_listed(fetcher, rel, table, code_name(ver), work)
        for name in entry["assets"]:
            _save_listed(fetcher, rel, table, name, assets)
        root = _extract_code(work / code_name(ver), ver, work)
        (work / release.SUMS).write_bytes(sums)
        (work / release.SIG).write_bytes(sig)
        (work / MANIFEST).write_text(json.dumps(m), encoding="utf-8")
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise
    final = home / ver
    shutil.rmtree(final, ignore_errors=True)
    os.replace(work, final)
    root = final / root.name
    port = _port(cfg)
    cmd = ["bash", str(root / "install" / f"{NAME}.sh"), "--tier", tier, "--port", str(port), "--bind", "127.0.0.1",
           "--user", SERVICE_USER, "--prefix", PREFIX, "--assets", str(final / "assets")]
    say("Running the reader's own installer (this can take a while)...")
    rc = run(cmd, say)
    if rc != 0:
        raise InstallError(f"the reader's installer failed (exit {rc}); its output is above. The kit's settings were "
                           "not changed")
    before = installed()
    rec = {"version": ver, "tier": tier, "port": port, "prefix": PREFIX, "at": int(time.time()),
           "previous": before["version"] if before and before["version"] != ver else
           (before or {}).get("previous")}
    _write_state(rec)
    _prune(keep={ver, rec.get("previous")})
    return rec


def _prune(keep: set) -> None:
    home = store()
    if not home.is_dir():
        return
    for d in home.iterdir():
        if d.is_dir() and d.name not in keep:
            shutil.rmtree(d, ignore_errors=True)


def wait_healthy(cfg: dict, seconds: float = HEALTH_WAIT, sleep: Callable[[float], None] = time.sleep) -> dict:
    """The reader's health, asked until it is usable or `seconds` have passed."""
    end = time.monotonic() + seconds
    while True:
        h = local_reader.health(cfg)
        if h["ok"] or time.monotonic() >= end:
            return h
        sleep(3)


def remove(*, run: Callable[..., int] | None = None, say: Callable[[str], None] = print) -> bool:
    """Run the installed release's installer with --uninstall and forget the release folders. True when something
    was installed. The caller switches the module off and applies."""
    run = run or default_run
    have = installed()
    if have is None:
        return False
    root = store() / have["version"] / f"{NAME}-{have['version']}"
    script = root / "install" / f"{NAME}.sh"
    if not script.is_file():
        raise InstallError(f"the installed release's files are gone ({script}); remove the reader by hand: "
                           f"{NAME}'s own uninstaller, then delete {_state_file()}")
    say("Running the reader's own uninstaller...")
    rc = run(["bash", str(script), "--uninstall", "--prefix", str(have.get("prefix") or PREFIX)], say)
    if rc != 0:
        raise InstallError(f"the reader's uninstaller failed (exit {rc}); its output is above. Nothing was changed")
    _write_state(None)
    shutil.rmtree(store(), ignore_errors=True)
    return True
