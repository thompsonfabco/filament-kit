#!/usr/bin/env python3
"""The end-to-end scenarios of tools/e2e/run.sh (docs/testing-e2e.md). Run by run.sh as root; not on its own.

  python3 -I tools/e2e/e2e.py --work DIR [--only a,d,c,b,e,f,g] [--previous vX.Y.Z]

Builds two signed releases of this checkout with a throwaway ed25519 key, serves them from a fake GitHub releases
API (`python3 -m http.server` on 127.0.0.1) and drives the real install, the reader API, the manual add and the
updater against them. With --previous, scenario f builds that tag from its own files too: a real update from it and a
real rollback to it. Everything listens on 127.0.0.1. Results go to DIR/results.json and stdout; logs of every
command to DIR/log/. Exit 0 when no scenario failed (a skip says why). Cleaning the host is run.sh's job.

Never prints a key or a token: the throwaway private key stays in DIR (0600), tokens only in this process.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import hashlib
import os
import re
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parents[1]
sys.path.insert(0, str(SRC / "tools"))
sys.path.insert(0, str(HERE))

import sign_release  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ed25519  # noqa: E402

OWNER_REPO = "e2e/filament-kit"
PUBLIC_URL = "https://kit.e2e.test/filament"
STATION_SERVER = "192.0.2.10"           # TEST-NET-1: a documentation address, never routed
SERIAL = "E2E00000000016"
UID = "4:c7:96:11:9:22:89"
SLOT = "P3"                             # unit P = AMS id 15, slot 3 = tray id 2
SLOT_ADDR = (15, 2)
ETC, STATE, OPT = Path("/etc/filament-kit"), Path("/var/lib/filament-kit"), Path("/opt/filament-kit")
VENV_PY = OPT / "venv" / "bin" / "python"
KIT = "https://127.0.0.1:8710"
WEB = "http://127.0.0.1:8101"
SPOOLMAN = "http://127.0.0.1:7912/api/v1"
TREE_PARTS = ("get.sh", "install", "tools", "server", "station/panel/firmware", "printer-pack", "LICENSE", "THIRD-PARTY.md")
IGNORE = shutil.ignore_patterns(".venv", "__pycache__", "*.egg-info", "build", "dist", ".pytest_cache", "*.pyc")


class Skip(Exception):
    pass


class Fail(Exception):
    pass


# ---------------------------------------------------------------- small helpers

class Run:
    def __init__(self, work: Path):
        self.work = work
        self.logs = work / "log"
        self.logs.mkdir(parents=True, exist_ok=True)
        self.n = 0
        self.results: list[dict] = []
        self.env = dict(os.environ, PIP_CACHE_DIR=str(work / "pipcache"), DEBIAN_FRONTEND="noninteractive")

    def sh(self, cmd: list[str], *, name: str, log: bool = True, timeout: float = 1800, env: dict | None = None,
           input_text: str | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess:
        """Run a command with no terminal (a new session: get.sh and install.sh then ask nothing)."""
        self.n += 1
        r = subprocess.run(["setsid", "-w", *cmd], input=input_text,
                           stdin=None if input_text is not None else subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=timeout, env=env or self.env, cwd=cwd)
        f = self.logs / f"{self.n:02d}-{name}.log"
        body = (f"$ {' '.join(cmd)}\nexit {r.returncode}\n--- stdout\n{r.stdout}\n--- stderr\n{r.stderr}\n"
                if log else f"$ {' '.join(cmd)}\nexit {r.returncode}\n(output not logged: it holds a token)\n")
        f.write_text(body, encoding="utf-8")
        return r

    def check(self, scenario: str, what: str, ok: bool, detail: str = "") -> bool:
        print(f"  {'ok  ' if ok else 'FAIL'} {what}" + ("" if ok or not detail else f"\n       {detail[-600:]}"),
              flush=True)
        self.results.append({"scenario": scenario, "check": what, "ok": bool(ok),
                             **({} if ok else {"detail": detail[-2000:]})})
        return ok


def http(method: str, url: str, *, body=None, headers: dict | None = None, timeout: float = 30,
         raw: bytes | None = None, ctype: str | None = None) -> tuple[int, bytes]:
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    h = dict(headers or {})
    if data is not None:
        h.setdefault("Content-Type", ctype or "application/json")
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE        # the kit's own self-signed certificate on 127.0.0.1
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def jhttp(method: str, url: str, **kw) -> tuple[int, object]:
    code, data = http(method, url, **kw)
    try:
        return code, json.loads(data or b"null")
    except ValueError:
        return code, data.decode("utf-8", "replace")


def wait_for(fn, timeout: float, step: float = 1.0):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = fn()
            if last:
                return last
        except Exception as e:  # noqa: BLE001 - keep trying until the deadline
            last = e
        time.sleep(step)
    return None


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def installed_version() -> str | None:
    if not VENV_PY.exists():
        return None
    r = subprocess.run([str(VENV_PY), "-I", "-c", "import filament_kit; print(filament_kit.__version__)"],
                       capture_output=True, text=True)
    return r.stdout.strip() or None


def read_cfg() -> dict:
    return json.loads((ETC / "config.json").read_text(encoding="utf-8"))


def write_cfg(cfg: dict) -> None:
    f = ETC / "config.json"
    tmp = f.with_name("config.json.e2e")
    tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    shutil.chown(tmp, "root", "filament-kit")
    os.chmod(tmp, 0o640)
    os.replace(tmp, f)


def kit_python(code: str, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    """Run Python in the kit's venv as the service user (as the CLI would), with no terminal."""
    return subprocess.run(["runuser", "-u", "filament-kit", "--", str(VENV_PY), "-I", "-c", code],
                          capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL,
                          env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8", **(env_extra or {})})


def root_python(code: str) -> subprocess.CompletedProcess:
    """Python in the kit's venv as root: what the root helper and `sudo filament-kit` do."""
    return subprocess.run([str(VENV_PY), "-I", "-c", code], capture_output=True, text=True, timeout=120,
                          stdin=subprocess.DEVNULL, env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"})


def units_active(*units: str) -> dict[str, str]:
    out = {}
    for u in units:
        r = subprocess.run(["systemctl", "is-active", u], capture_output=True, text=True)
        out[u] = r.stdout.strip()
    return out


# ---------------------------------------------------------------- releases and the fake GitHub API

class Releases:
    def __init__(self, run: Run):
        self.run = run
        self.work = run.work
        self.www = self.work / "www"
        self.www.mkdir()
        self.priv = ed25519.Ed25519PrivateKey.generate()
        self.key = self.work / "release-key.pem"
        fd = os.open(self.key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(self.priv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                             serialization.NoEncryption()))
        self.pub = base64.b64encode(self.priv.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
        self.port = free_port()
        self.api = f"http://127.0.0.1:{self.port}"
        self.server = None
        self.built: dict[str, Path] = {}           # version -> dist folder
        self.tree: Path | None = None

    # -- the tree and the builds
    def copy_tree(self, dest: Path) -> Path:
        for part in TREE_PARTS:
            s, d = SRC / part, dest / part
            if s.is_dir():
                shutil.copytree(s, d, ignore=IGNORE)
            else:
                d.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(s, d)
        return dest

    def build_env(self) -> dict:
        """A throwaway venv with `build` for make_release.sh's `python3 -m build` (WSL has no uv)."""
        venv = self.work / "buildvenv"
        if not venv.exists():
            r = self.run.sh(["python3", "-m", "venv", str(venv)], name="buildvenv")
            if r.returncode:
                raise Fail(f"cannot make the build venv: {r.stderr[-400:]}")
            r = self.run.sh([str(venv / "bin" / "python"), "-m", "pip", "install", "-q", "build"], name="pip-build")
            if r.returncode:
                raise Fail(f"cannot install the build package: {r.stderr[-400:]}")
        return dict(self.run.env, PATH=f"{venv / 'bin'}:{os.environ.get('PATH', '/usr/bin:/bin')}")

    def base_version(self) -> str:
        m = re.search(r'^__version__ = "([^"]+)"', (SRC / "server/filament_kit/__init__.py").read_text(), re.M)
        return m[1]

    def build(self, version: str) -> Path:
        """dist/ of a release built from a copy of this checkout carrying the throwaway key and `version`."""
        tree = self.copy_tree(self.work / f"tree-{version}")
        sign_release.set_pubkey(tree, self.pub)
        for rel, pat in (("server/filament_kit/__init__.py", r'^__version__ = "[^"]+"'),
                         ("server/pyproject.toml", r'^version = "[^"]+"')):
            f = tree / rel
            text = f.read_text(encoding="utf-8")
            new = re.sub(pat, pat.split(" = ")[0].lstrip("^") + f' = "{version}"', text, count=1, flags=re.M)
            if not re.search(pat.replace('[^"]+', re.escape(version)), new, re.M):
                raise Fail(f"cannot set version {version} in {rel}")
            f.write_text(new, encoding="utf-8")
        dist = self.work / f"dist-{version}"
        env = dict(self.build_env(), FK_DIST=str(dist), FK_NO_APP="1", FK_LIBRARY_SRC=str(self.work / "no-library"))
        r = self.run.sh(["bash", str(tree / "tools" / "make_release.sh")], name=f"make-release-{version}", env=env,
                        cwd=tree)
        if r.returncode or not (dist / f"filament-kit-{version}.tar.gz").is_file():
            raise Fail(f"make_release.sh {version} failed: {r.stderr[-800:]}")
        self.built[version] = dist
        if self.tree is None:
            self.tree = tree
        return dist

    # -- publishing on the fake API
    def _sign(self, sums: Path, key: Path | None = None) -> None:
        r = self.run.sh(["python3", "-I", str(self.tree / "tools" / "sign_release.py"), "--root", str(self.tree),
                         "sign", str(sums), "--key-file", str(key or self.key)], name="sign")
        if r.returncode:
            raise Fail(f"sign_release.py sign failed: {r.stderr[-400:]}")

    def build_previous(self, tag: str) -> tuple[Path, str, Path]:
        """(tree, version, dist) of `tag` as it was released, by its own make_release.sh, with the throwaway key. The tree
        isn't named tree-*: run.sh's clean-up takes the current uninstall.sh from one of those."""
        tree = self.work / f"previous-{tag}"
        tree.mkdir()
        r = self.run.sh(["bash", "-c", 'set -o pipefail; git -c safe.directory="*" -C "$1" archive --format=tar "refs/tags/$2" '
                         '| tar -x -C "$3"', "archive", str(SRC), tag, str(tree)], name=f"archive-{tag}")
        if r.returncode:
            raise Fail(f"cannot read tag {tag} from {SRC} (a clone with its tags, not a worktree of another OS): {r.stderr[-400:]}")
        sign_release.set_pubkey(tree, self.pub)
        m = re.search(r'^__version__ = "([^"]+)"', (tree / "server/filament_kit/__init__.py").read_text(encoding="utf-8"), re.M)
        dist = self.work / f"dist-{tag}"
        env = dict(self.build_env(), FK_DIST=str(dist), FK_NO_APP="1", FK_LIBRARY_SRC=str(self.work / "no-library"))
        r = self.run.sh(["bash", str(tree / "tools" / "make_release.sh")], name=f"make-release-{tag}", env=env, cwd=tree)
        if r.returncode or not (dist / f"filament-kit-{m[1]}.tar.gz").is_file():
            raise Fail(f"make_release.sh of {tag} failed: {r.stderr[-800:]}")
        return tree, m[1], dist

    def publish(self, version: str, *, repo: str = OWNER_REPO, hardware: bytes | None = None,
                tamper_tarball: bool = False, foreign_sig: bool = False, latest: bool = True,
                dist: Path | None = None) -> None:
        """Put release `version` on the fake API under `repo` (replacing it): the tarball and bambu_hardware.xml
        (or `hardware` instead), SHA256SUMS of both, signed with the throwaway key."""
        dist = dist or self.built[version]
        out = self.www / "dl" / repo / version
        shutil.rmtree(out, ignore_errors=True)
        out.mkdir(parents=True)
        tar = f"filament-kit-{version}.tar.gz"
        shutil.copy2(dist / tar, out / tar)
        (out / "bambu_hardware.xml").write_bytes(hardware if hardware is not None
                                                 else (dist / "bambu_hardware.xml").read_bytes())
        lines = [f"{hashlib.sha256((out / n).read_bytes()).hexdigest()}  {n}\n" for n in (tar, "bambu_hardware.xml")]
        (out / "SHA256SUMS").write_text("".join(lines), encoding="ascii")
        if foreign_sig:                 # signed, but by another (throwaway) key than the one get.sh carries
            sig = ed25519.Ed25519PrivateKey.generate().sign((out / "SHA256SUMS").read_bytes())
            (out / "SHA256SUMS.sig").write_text(base64.b64encode(sig).decode() + "\n", encoding="ascii")
        else:
            self._sign(out / "SHA256SUMS")
        if tamper_tarball:
            data = bytearray((out / tar).read_bytes())
            data[len(data) // 2] ^= 0x01
            (out / tar).write_bytes(bytes(data))
        doc = {"tag_name": f"v{version}", "assets": [
            {"name": n, "url": f"{self.api}/dl/{repo}/{version}/{n}"} for n in sorted(os.listdir(out))]}
        rel = self.www / "repos" / repo / "releases"
        (rel / "tags").mkdir(parents=True, exist_ok=True)
        (rel / "tags" / f"v{version}").write_text(json.dumps(doc), encoding="utf-8")
        if latest:
            (rel / "latest").write_text(json.dumps(doc), encoding="utf-8")

    def serve(self) -> None:
        log = open(self.work / "log" / "http-server.log", "wb")
        self.server = subprocess.Popen(["python3", "-I", "-m", "http.server", str(self.port), "--bind", "127.0.0.1",
                                        "--directory", str(self.www)], stdout=log, stderr=subprocess.STDOUT,
                                       stdin=subprocess.DEVNULL)
        if not wait_for(lambda: http("GET", f"{self.api}/")[0] == 200, 20, 0.3):
            raise Fail("the fake release server did not start")

    def stop(self) -> None:
        if self.server is not None:
            self.server.terminate()
            try:
                self.server.wait(10)
            except subprocess.TimeoutExpired:
                self.server.kill()

    def get_sh(self, args: list[str], name: str) -> subprocess.CompletedProcess:
        return self.run.sh(["bash", str(self.tree / "get.sh"), "--api", self.api, *args], name=name, timeout=3600)


# ---------------------------------------------------------------- scenarios

def nothing_installed() -> list[str]:
    return [str(p) for p in (OPT, ETC, STATE, Path("/usr/local/bin/filament-kit")) if p.exists()]


def uninstall(run: Run, rel: Releases, name: str) -> None:
    run.sh(["bash", str(rel.tree / "install" / "uninstall.sh"), "--purge"], name=name, input_text="purge\n",
           timeout=600)


def version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(x) for x in version.split("."))


class E2E:
    def __init__(self, run: Run, rel: Releases, previous: str | None = None):
        self.run, self.rel = run, rel
        self.previous = previous
        self.v1 = rel.base_version()
        major, minor, patch = (int(x) for x in self.v1.split("."))
        self.v2 = f"{major}.{minor}.{patch + 1}"
        self.token: str | None = None          # the kit API token (paired in d)
        self.spool: dict | None = None         # the spool d added (with the tag c scans)
        self.printer = None
        self.installed = False                 # a) installed the kit (the later scenarios need it)
        self.v1_published = False              # v1 is on the fake release server under OWNER_REPO

    # ---- a) fake release server and get.sh
    def a_install(self, sc="a") -> None:
        rel, run = self.rel, self.run
        rel.publish(self.v1)
        self.v1_published = True
        rel.publish(self.v1, repo="e2e/tampered", tamper_tarball=True)
        rel.publish(self.v1, repo="e2e/badsig", foreign_sig=True)
        rel.serve()
        for repo, what in (("e2e/tampered", "tampered tarball"), ("e2e/badsig", "bad signature")):
            r = rel.get_sh(["--repo", repo, "--modules", "server"], f"get-{repo.split('/')[1]}")
            run.check(sc, f"{what}: get.sh refuses", r.returncode != 0 and "nothing was installed" in r.stderr,
                      r.stderr)
            left = nothing_installed()
            run.check(sc, f"{what}: nothing installed", not left, ", ".join(left))
        r = rel.get_sh(["--repo", OWNER_REPO, "--modules", "spoolman,server,printers,web",
                        "--set", f"web.public_url={PUBLIC_URL}"], "get-install")
        run.check(sc, f"get.sh installs {self.v1} (spoolman,server,printers,web, no terminal)",
                  r.returncode == 0 and f"verified filament-kit {self.v1}" in r.stderr, r.stdout[-1500:] + r.stderr)
        if r.returncode:
            raise Fail("install failed; see the log")
        self.installed = True
        act = units_active("spoolman.service", "filament-kit.service", "filament-kit-web.service")
        run.check(sc, "spoolman, filament-kit and filament-kit-web active", set(act.values()) == {"active"}, str(act))
        code, info = jhttp("GET", f"{KIT}/api/info")
        run.check(sc, "kit API answers with the installed version",
                  code == 200 and isinstance(info, dict) and info.get("version") == self.v1, str(info))
        code, _ = http("GET", f"{SPOOLMAN}/info")
        run.check(sc, "Spoolman answers (real Spoolman 0.27, downloaded by the spoolman module)", code == 200)
        # active isn't listening yet: the web unit takes a moment to bind its port
        code, body = wait_for(lambda: (lambda c: c if c[0] == 200 else None)(http("GET", f"{WEB}/health")), 60, 1) or (0, b"")
        run.check(sc, "web unit answers /health", code == 200 and body.strip() == b"ok", body[:200].decode())
        # the phone web app is the kit server's own (the user's decision, 2026-11-09): no web module needed for it
        code, body = http("GET", f"{KIT}/intake")
        run.check(sc, "the kit server serves the phone web app at /intake", code == 200 and b"data-base='/intake'" in body,
                  body[:300].decode(errors="replace"))
        code, plist = jhttp("GET", f"{KIT}/intake/api/printers")
        run.check(sc, "its Printers tab reaches this server's API over the loopback with its own pairing",
                  code == 200, str(plist)[:300])
        st = run.sh(["/usr/local/bin/filament-kit", "status"], name="status-after-install")
        run.check(sc, "filament-kit status exits 0", st.returncode == 0, st.stdout[-1500:])
        kept = OPT / "releases" / self.v1
        run.check(sc, "verified release kept for rollback",
                  sorted(os.listdir(kept)) == ["SHA256SUMS", "SHA256SUMS.sig", f"filament-kit-{self.v1}.tar.gz"]
                  if kept.is_dir() else False, str(kept))

    # ---- the host state a scenario starts from
    # Scenarios leave the host as they end: e leaves a station, f the previous release, b a held rollback. So each
    # scenario names the state it needs (NEEDS) and prepare() brings the host there first, rebuilding only what is
    # missing: in the order a,d,c,b,e nothing is rebuilt, after e or f the next scenario gets a fresh install.
    def _v1_on_server(self) -> None:
        if not self.v1_published:
            self.rel.publish(self.v1)
            self.v1_published = True
        if self.rel.server is None:
            self.rel.serve()

    def _is_server_v1(self) -> bool:
        if installed_version() != self.v1:
            return False
        try:
            mods = read_cfg().get("modules") or {}
        except (OSError, ValueError):
            return False
        return bool(mods.get("server")) and bool(mods.get("spoolman"))

    def _token_works(self) -> bool:
        if self.token is None or self.spool is None:
            return False
        code, spools = jhttp("GET", f"{KIT}/api/spools", headers={"Authorization": f"Bearer {self.token}"})
        return code == 200 and isinstance(spools, dict) and \
            self.spool.get("id") in [s.get("id") for s in spools.get("spools", [])]

    def prepare(self, key: str) -> None:
        need = NEEDS.get(key)
        run, rel = self.run, self.rel
        if need is None:
            return
        if need == "clean":
            if nothing_installed():
                print("  (known state: no kit; uninstalling what the last scenario left)", flush=True)
                uninstall(run, rel, f"known-state-{key}-uninstall")
            return
        self._v1_on_server()
        if need == "release":
            return
        if not self._is_server_v1():
            print(f"  (known state: {self.v1} installed by get.sh; the host has {installed_version() or 'no kit'})",
                  flush=True)
            if nothing_installed():
                uninstall(run, rel, f"known-state-{key}-uninstall")
            r = rel.get_sh(["--repo", OWNER_REPO, "--version", self.v1, "--modules", "spoolman,server,printers,web",
                            "--set", f"web.public_url={PUBLIC_URL}"], f"known-state-{key}-install")
            run.check(key, f"known state: get.sh installs {self.v1} (spoolman,server,printers,web)",
                      r.returncode == 0 and self._is_server_v1(), r.stdout[-1500:] + r.stderr[-800:])
            if r.returncode:
                raise Fail("could not bring the host to the known state; see the log")
            self.installed = True
            self.token = self.spool = None          # the pairing and the spool went with the old install
            if self.printer is not None:            # and the printer entry: g then has none to compare
                self.printer.close()
                self.printer = None
            wait_for(lambda: http("GET", f"{SPOOLMAN}/info")[0] == 200 or None, 120, 2)
            wait_for(lambda: jhttp("GET", f"{KIT}/api/info")[0] == 200 or None, 90, 2)
        if need == "seeded" and not self._token_works():
            print("  (known state: pairing the e2e phone and adding its spool with the tag)", flush=True)
            self._seed(key)

    def _seed(self, sc: str) -> None:
        """What d leaves for c and g: a paired token and one opened spool whose filament has the tag UID."""
        r = kit_python("from filament_kit import pairing; print(pairing.issue('e2e').code)")
        code, body = jhttp("POST", f"{KIT}/api/pair", body={"code": r.stdout.strip()})
        if code != 200 or not isinstance(body, dict) or not body.get("token"):
            raise Fail(f"known state: pairing refused: {code}")
        self.token = body["token"]
        auth = {"Authorization": f"Bearer {self.token}"}
        code, added = jhttp("POST", f"{KIT}/api/intake/add", headers=auth,
                            body={"items": [SEED_ITEM], "dry_run": False, "tag": UID})
        if code != 200 or not isinstance(added, dict) or len(added.get("spool_ids") or []) != 1:
            raise Fail(f"known state: adding the spool failed: {code} {added}")
        code, sp = jhttp("GET", f"{SPOOLMAN}/spool/{added['spool_ids'][0]}")
        self.spool = sp if code == 200 and isinstance(sp, dict) else None
        self.run.check(sc, "known state: paired, one spool with the tag", self._token_works(), f"{code}")

    # ---- d) manual add without AI
    def d_manual_add(self, sc="d") -> None:
        run = self.run
        cfg = read_cfg()
        on = {k for k, v in (cfg.get("modules") or {}).items() if v}
        run.check(sc, "ai_intake is off and there is no API key",
                  "ai_intake" not in on and not (ETC / "anthropic_key").exists(), str(sorted(on)))
        r = kit_python("from filament_kit import pairing; print(pairing.issue('e2e').code)")
        code_txt = r.stdout.strip()
        if r.returncode or not re.fullmatch(r"\d{6}", code_txt):
            raise Fail(f"cannot issue a pairing code: {r.stderr[-400:]}")
        code, body = jhttp("POST", f"{KIT}/api/pair", body={"code": code_txt})
        if code != 200 or not isinstance(body, dict) or not body.get("token"):
            raise Fail(f"pairing refused: {code}")
        self.token = body["token"]
        auth = {"Authorization": f"Bearer {self.token}"}
        code, body = jhttp("POST", f"{KIT}/api/intake/read", headers=auth, raw=b"--x--\r\n",
                           ctype="multipart/form-data; boundary=x")
        run.check(sc, "AI label reading is off: /api/intake/read answers module_off",
                  code == 409 and isinstance(body, dict) and body.get("module") == "ai_intake", f"{code} {body}")
        item = SEED_ITEM
        def spool_count() -> int:
            c, spools = jhttp("GET", f"{SPOOLMAN}/spool?allow_archived=true")
            if c != 200 or not isinstance(spools, list):
                raise Fail(f"cannot list Spoolman's spools: {c}")
            return len(spools)
        n_before = spool_count()
        code, dry = jhttp("POST", f"{KIT}/api/intake/add", headers=auth, body={"items": [item], "dry_run": True})
        n_after = spool_count()
        run.check(sc, "dry run answers dry and adds no spool to Spoolman",
                  code == 200 and isinstance(dry, dict) and dry.get("dry") is True and n_after == n_before,
                  f"{code} {dry} spools {n_before} -> {n_after}")
        code, added = jhttp("POST", f"{KIT}/api/intake/add", headers=auth,
                            body={"items": [item], "dry_run": False, "tag": UID})
        ok = code == 200 and isinstance(added, dict) and len(added.get("spool_ids") or []) == 1
        ok = ok and any("linked tag" in x for x in added.get("lines") or [])
        run.check(sc, "manual add of an opened spool with a tag answers one spool id, tag linked", ok,
                  f"{code} {added}")
        if not ok:
            raise Fail("manual add failed")
        sid = added["spool_ids"][0]
        code, sp = jhttp("GET", f"{SPOOLMAN}/spool/{sid}")
        f = (sp or {}).get("filament") or {} if isinstance(sp, dict) else {}
        run.check(sc, "the spool is in Spoolman with its filament, vendor and tag",
                  code == 200 and f.get("name") == "E2E PLA Red" and (f.get("vendor") or {}).get("name") ==
                  "E2E Test Co" and json.loads(((sp.get("extra") or {}).get("nfc_id")) or "null") == UID,
                  json.dumps(sp)[:600])
        self.spool = sp

    # ---- c) fake 16-unit printer through the reader API
    def c_printer(self, sc="c") -> None:
        run = self.run
        if self.spool is None:
            raise Skip("needs the spool scenario d adds")
        import fake_printer
        code = secrets.token_hex(4)                  # a throwaway Access Code for the fake printer only
        self.printer = fake_printer.Broker(SERIAL, code, self.run.work / "printer-certs")
        # what `filament-kit config` -> Printers -> add printer does (registry.upsert of a fresh, configured entry)
        r = kit_python("import os\nfrom filament_kit.bridge import registry\n"
                       f"registry.upsert(registry.Printer({SERIAL!r}, 'E2E H2D', 'O1D', '127.0.0.1', "
                       "os.environ['FK_E2E_CODE'], True))", env_extra={"FK_E2E_CODE": code})
        if r.returncode:
            raise Fail(f"cannot add the printer: {r.stderr[-400:]}")
        # the reader token, made as the docs say: sudo filament-kit reader token
        r = run.sh(["/usr/local/bin/filament-kit", "reader", "token", "--name", "e2e"], name="reader-token",
                   log=False)
        m = re.search(r"only this once:\s+(\S+)", r.stdout)
        run.check(sc, "sudo filament-kit reader token makes a token", r.returncode == 0 and m is not None,
                  r.stderr[-400:])
        if not m:
            raise Fail("no reader token")
        rt = {"X-Auth-Token": m[1]}
        reader = f"{WEB}/reader"

        def connected():
            c, lst = jhttp("GET", f"{reader}/printers", headers=rt)
            if c != 200 or not any(p.get("id") == SERIAL for p in lst):
                return None
            c, slots = jhttp("GET", f"{reader}/printers/{SERIAL}/slots", headers=rt)
            return slots if c == 200 and isinstance(slots, list) and len(slots) > 2 else None

        slots = wait_for(connected, 90, 2)
        run.check(sc, "the kit connects to the fake printer (TLS, pinned leaf, Access Code)",
                  bool(slots) and self.printer.connects >= 1,
                  f"connects={self.printer.connects} auth_failures={self.printer.auth_failures}")
        if not slots:
            raise Fail("no slots from the reader API")
        code, plist = jhttp("GET", f"{reader}/printers", headers=rt)
        run.check(sc, "GET reader/printers lists the printer", code == 200 and
                  [p.get("id") for p in plist] == [SERIAL] and plist[0].get("name") == "E2E H2D", str(plist))
        labels = [s.get("label") for s in slots if s.get("label")]
        run.check(sc, "GET .../slots: 16 AMS x 4 + 8 HT + 2 externals = 74 slots, every one labelled",
                  len(slots) == 74 and len(labels) == 74, f"{len(slots)} entries, {len(labels)} labels: {labels}")
        run.check(sc, "every slot label is unique (also ignoring case) and at most 40 bytes",
                  len({x.lower() for x in labels}) == len(labels) and all(len(x.encode()) <= 40 for x in labels),
                  str(labels))
        run.check(sc, "labels run A1..P4, HT-A..HT-H, Ext-L, Ext-R",
                  labels[:2] == ["A1", "A2"] and "P4" in labels and "HT-H" in labels and labels[-2:] ==
                  ["Ext-L", "Ext-R"], str(labels))
        self._seed_preset()
        before = len(self.printer.writes())
        code, res = jhttp("POST", f"{reader}/scan", headers=rt,
                          body={"uid": UID, "printer": SERIAL, "slot": SLOT, "dry_run": False}, timeout=30)
        run.check(sc, f"POST reader/scan into {SLOT} answers set", code == 200 and isinstance(res, dict) and
                  res.get("status") == "set", f"{code} {res}")
        time.sleep(8)                # confirmation, the pushall after the command, any retry would show by now
        writes = self.printer.writes()[before:]
        run.check(sc, "the printer got exactly one ams_filament_setting", len(writes) == 1, json.dumps(writes)[:800])
        if writes:
            w = writes[0]
            run.check(sc, f"... for AMS {SLOT_ADDR[0]} tray {SLOT_ADDR[1]} with the preset's filament id",
                      (int(w["ams_id"]), int(w["tray_id"])) == SLOT_ADDR and w.get("tray_info_idx") == self.fid,
                      json.dumps(w))
        code, sp = jhttp("GET", f"{SPOOLMAN}/spool/{self.spool['id']}")
        run.check(sc, f"Spoolman shows the spool in the printer's {SLOT}",
                  code == 200 and str((sp or {}).get("location") or "").endswith(f"AMS {SLOT}"),
                  str((sp or {}).get("location")))
        # the CLI asks the running server, which holds the printer (a live bug: its own second connection got nothing)
        r = run.sh(["/usr/local/bin/filament-kit", "printer", "report", SERIAL], name="printer-report-cli")
        run.check(sc, "filament-kit printer report goes through the running server", r.returncode == 0
                  and "Printer report saved:" in r.stdout and "could not be reached" not in r.stdout,
                  r.stdout[-800:] + r.stderr[-400:])

    def _seed_preset(self) -> None:
        """A one-preset build for the spool's filament, as the PC sync and `profiles build` would leave it (the
        reader loads only with the user's exact preset)."""
        fil = self.spool["filament"]
        self.fid = "P0e2e001"
        stamp = "20261103-000000"
        line = "e2e-test-co--pla"
        name = "E2E Test Co PLA @Bambu Lab H2D 0.4 nozzle"
        build = {"stamp": stamp, "presets": [{
            "line_id": line, "target": "bambu_studio", "printer": "Bambu Lab H2D", "nozzle": "0.4",
            "filament_id": self.fid, "name": name, "filament_type": "PLA",
            "nozzle_temp_min": 190, "nozzle_temp_max": 230}],
            "lines": {line: {"vendor": "E2E Test Co", "product": "PLA", "filament_id": self.fid}},
            "filaments": {str(fil["id"]): line}}
        prof = STATE / "profiles"
        (prof / "builds" / stamp).mkdir(parents=True, exist_ok=True)
        (prof / "builds" / stamp / "BUILD.json").write_text(json.dumps(build), encoding="utf-8")
        (prof / "current.json").write_text(json.dumps({"stamp": stamp, "created": time.time(), "presets": 1,
                                                       "problems": []}), encoding="utf-8")
        subprocess.run(["chown", "-R", "filament-kit:filament-kit", str(prof)], check=True)

    # ---- b) updater and the hardware data feed
    def b_updater(self, sc="b") -> None:
        run, rel = self.run, self.rel
        cfg = read_cfg()
        cfg["updates"] = {"api": rel.api, "repo": OWNER_REPO}
        write_cfg(cfg)
        fk = "/usr/local/bin/filament-kit"
        r = run.sh([fk, "update", "--check"], name="update-check-same")
        run.check(sc, "update --check: up to date", r.returncode == 0 and "up to date" in r.stdout, r.stdout + r.stderr)
        hw = (rel.built[self.v2] / "bambu_hardware.xml").read_bytes()
        hw11 = hw.replace(b'<bambu-hardware version="1">', b'<bambu-hardware version="1.1">', 1)
        assert hw11 != hw
        rel.publish(self.v2, hardware=hw11)
        r = run.sh([fk, "update", "--check"], name="update-check-newer")
        run.check(sc, f"update --check sees {self.v2}", r.returncode == 0 and f"{self.v2} is available" in r.stdout,
                  r.stdout + r.stderr)
        r = run.sh([fk, "update"], name="update", timeout=3600)
        run.check(sc, f"update installs {self.v2}", r.returncode == 0 and installed_version() == self.v2,
                  r.stdout[-1500:] + r.stderr[-800:])
        act = wait_for(lambda: (lambda a: a if set(a.values()) == {"active"} else None)(
            units_active("spoolman.service", "filament-kit.service", "filament-kit-web.service")), 60, 2)
        run.check(sc, "services active again after the update", bool(act))
        code, info = jhttp("GET", f"{KIT}/api/info")
        run.check(sc, "kit API answers the new version", code == 200 and info.get("version") == self.v2, str(info))
        ov = ETC / "bambu_hardware.xml"
        run.check(sc, "hardware feed: release's newer file (1.1) installed as the override",
                  ov.is_file() and ov.read_bytes() == hw11, r.stdout[-600:])
        hw12 = hw.replace(b'<bambu-hardware version="1">', b'<bambu-hardware version="1.2">', 1)
        rel.publish(self.v2, hardware=hw12)
        r = run.sh([fk, "update"], name="update-feed-1.2")
        run.check(sc, "hardware feed: a newer valid file (1.2) swaps in, the old one kept as .previous",
                  r.returncode == 0 and ov.read_bytes() == hw12 and
                  (ETC / "bambu_hardware.xml.previous").read_bytes() == hw11, r.stdout + r.stderr)
        bad = hw.replace(b'<bambu-hardware version="1">', b'<bambu-hardware version="1.3">', 1) \
            .replace(b'name="H2D"', b'name=""', 1)
        rel.publish(self.v2, hardware=bad)
        r = run.sh([fk, "update"], name="update-feed-invalid")
        run.check(sc, "hardware feed: an invalid (signed) file is refused, the installed one stays",
                  r.returncode == 1 and "not installed" in r.stderr and ov.read_bytes() == hw12, r.stdout + r.stderr)
        rel.publish(self.v2, hardware=hw12)               # leave a good release in place
        r = run.sh([fk, "update", "--rollback"], name="rollback", timeout=3600)
        run.check(sc, f"update --rollback restores {self.v1}", r.returncode == 0 and installed_version() == self.v1,
                  r.stdout[-1500:] + r.stderr[-800:])
        code, info = wait_for(lambda: (lambda c: c if c[0] == 200 else None)(jhttp("GET", f"{KIT}/api/info")),
                              60, 2) or (0, {})
        run.check(sc, "kit API answers the old version after the rollback",
                  code == 200 and info.get("version") == self.v1, str(info))
        r = run.sh([fk, "update", "--check"], name="update-check-held")
        run.check(sc, "update --check: the rolled-back version is held from the timer",
                  r.returncode == 0 and "rolled back earlier" in r.stdout, r.stdout + r.stderr)

    # ---- e) station upgraded by the updater keeps its server address
    def e_station(self, sc="e") -> None:
        run, rel = self.run, self.rel
        uninstall(run, rel, "uninstall-server")
        left = nothing_installed()
        run.check(sc, "the server install is purged first", not left, ", ".join(left))
        r = rel.get_sh(["--repo", OWNER_REPO, "--version", self.v1, "--mode", "station", "--server", STATION_SERVER],
                       "get-station")
        run.check(sc, f"get.sh installs {self.v1} in station mode", r.returncode == 0,
                  r.stdout[-1500:] + r.stderr[-800:])
        if r.returncode:
            raise Fail("station install failed")
        cfg = read_cfg()
        run.check(sc, "station.allow is the server address", (cfg.get("station") or {}).get("allow") ==
                  [STATION_SERVER], str(cfg.get("station")))
        cfg["updates"] = {"api": rel.api, "repo": OWNER_REPO}
        write_cfg(cfg)
        r = run.sh(["/usr/local/bin/filament-kit", "update"], name="update-station", timeout=3600)
        run.check(sc, f"update installs {self.v2} on the station", r.returncode == 0 and installed_version() == self.v2,
                  r.stdout[-1500:] + r.stderr[-800:])
        cfg = read_cfg()
        on = sorted(k for k, v in (cfg.get("modules") or {}).items() if v)
        run.check(sc, "after the update: still station mode with the same server address",
                  on == ["station"] and (cfg.get("station") or {}).get("allow") == [STATION_SERVER], f"{on} {cfg}")
        drop = Path("/etc/systemd/system/filament-kit-station.service.d")
        text = "".join(p.read_text() for p in drop.glob("*.conf")) if drop.is_dir() else ""
        run.check(sc, "the station unit's allow list still names the server", STATION_SERVER in text, text[-600:])

    # ---- f) a real update from the last released tag, and a real rollback to it
    def _still_works(self, sc: str, when: str, auth: dict, spool_id: int, version: str) -> None:
        run = self.run
        act = wait_for(lambda: (lambda a: a if set(a.values()) == {"active"} else None)(
            units_active("spoolman.service", "filament-kit.service", "filament-kit-web.service")), 90, 2)
        run.check(sc, f"{when}: services active", bool(act))
        code, info = wait_for(lambda: (lambda c: c if c[0] == 200 else None)(jhttp("GET", f"{KIT}/api/info")), 90, 2) or (0, {})
        run.check(sc, f"{when}: kit API answers {version}", code == 200 and info.get("version") == version, str(info))
        code, body = jhttp("GET", f"{KIT}/api/printers", headers=auth)
        run.check(sc, f"{when}: the paired phone's token still works", code == 200, f"{code} {body}")
        code = wait_for(lambda: http("GET", f"{SPOOLMAN}/spool/{spool_id}")[0] == 200, 60, 2)
        run.check(sc, f"{when}: the spool is still in Spoolman", bool(code))

    def f_cross_tag(self, sc="f") -> None:
        run, rel = self.run, self.rel
        if not self.previous:
            raise Skip("no --previous tag given")
        if nothing_installed():
            uninstall(run, rel, "uninstall-before-cross-tag")
        left = nothing_installed()
        run.check(sc, "starts from a host with no kit on it", not left, ", ".join(left))
        tree, old, dist = rel.build_previous(self.previous)
        if version_tuple(old) >= version_tuple(self.v2):
            raise Fail(f"{self.previous} is {old}, not older than this checkout's {self.v2}")
        repo = "e2e/cross-tag"
        rel.publish(old, repo=repo, dist=dist)
        if rel.server is None:
            rel.serve()
        r = run.sh(["bash", str(tree / "get.sh"), "--api", rel.api, "--repo", repo, "--modules", "spoolman,server,printers,web",
                    "--set", f"web.public_url={PUBLIC_URL}"], name="get-previous", timeout=3600)
        run.check(sc, f"{self.previous}'s own get.sh installs {old}", r.returncode == 0 and installed_version() == old,
                  r.stdout[-1500:] + r.stderr[-800:])
        if r.returncode:
            raise Fail("install of the previous release failed; see the log")
        r = kit_python("from filament_kit import pairing; print(pairing.issue('e2e').code)")
        code, body = jhttp("POST", f"{KIT}/api/pair", body={"code": r.stdout.strip()})
        if code != 200 or not isinstance(body, dict) or not body.get("token"):
            raise Fail(f"pairing on {old} refused: {code}")
        auth = {"Authorization": f"Bearer {body['token']}"}
        wait_for(lambda: http("GET", f"{SPOOLMAN}/info")[0] == 200, 60, 2)
        code, fil = jhttp("POST", f"{SPOOLMAN}/filament", body={"name": "E2E cross-tag PLA", "density": 1.24, "diameter": 1.75})
        code2, spool = jhttp("POST", f"{SPOOLMAN}/spool", body={"filament_id": fil.get("id") if isinstance(fil, dict) else None})
        if code != 200 or code2 != 200 or not isinstance(spool, dict):
            raise Fail(f"cannot add a spool on {old}: {code} {code2}")
        cfg = read_cfg()
        cfg["updates"] = {"api": rel.api, "repo": repo}
        write_cfg(cfg)
        modules_before = cfg.get("modules")
        rel.publish(self.v2, repo=repo)
        fk = "/usr/local/bin/filament-kit"
        r = run.sh([fk, "update"], name="cross-tag-update", timeout=3600)
        run.check(sc, f"{old}'s own updater installs {self.v2}", r.returncode == 0 and installed_version() == self.v2,
                  r.stdout[-1500:] + r.stderr[-800:])
        self._still_works(sc, f"after the update to {self.v2}", auth, spool["id"], self.v2)
        run.check(sc, "after the update: the same modules are on", read_cfg().get("modules") == modules_before,
                  str(read_cfg().get("modules")))
        r = run.sh([fk, "update", "--rollback"], name="cross-tag-rollback", timeout=3600)
        run.check(sc, f"this checkout's rollback restores {old}", r.returncode == 0 and installed_version() == old,
                  r.stdout[-1500:] + r.stderr[-800:])
        self._still_works(sc, f"after the rollback to {old}", auth, spool["id"], old)
        r = run.sh([fk, "update", "--check"], name="cross-tag-check")
        run.check(sc, f"{old} still runs its own commands after the rollback", r.returncode == 0, r.stdout + r.stderr)


    # ---- g) a backup zip brings the kit back on a wiped, freshly installed machine
    def _kit_state(self, auth: dict) -> dict:
        """What has to be the same after a restore, as the kit's own API, Spoolman and its files answer it."""
        out: dict = {"modules": sorted(k for k, v in (read_cfg().get("modules") or {}).items() if v)}
        out["cert"] = hashlib.sha256((ETC / "cert.pem").read_bytes()).hexdigest() if (ETC / "cert.pem").exists() else None
        code, spools = jhttp("GET", f"{KIT}/api/spools", headers=auth)
        out["paired"] = code
        out["spools"] = sorted(s.get("id") for s in spools.get("spools", [])) if isinstance(spools, dict) else spools
        code, tag = jhttp("GET", f"{KIT}/api/tags/{UID}", headers=auth)
        out["tag"] = (code, (tag or {}).get("spool", {}).get("id") if isinstance(tag, dict) else None)
        code, printers = jhttp("GET", f"{KIT}/api/printers", headers=auth)
        out["printers"] = sorted(p.get("id") for p in printers.get("printers", [])) if isinstance(printers, dict) else code
        return out

    def g_backup_restore(self, sc="g") -> None:
        run, rel = self.run, self.rel
        if self.token is None or self.spool is None:
            raise Skip("needs the pairing and the spool of scenario d")
        auth = {"Authorization": f"Bearer {self.token}"}
        fk = "/usr/local/bin/filament-kit"
        version = installed_version()
        r = root_python("from filament_kit import setup_code, trusted\n"
                        "print(setup_code.ensure())\nprint(trusted.add('e2e browser', '192.0.2.20')[1])")
        lines = r.stdout.split()
        if r.returncode or len(lines) != 2:
            raise Fail(f"cannot read the setup code or trust a computer: {r.stderr[-400:]}")
        code, trust = lines
        before = self._kit_state(auth)
        run.check(sc, "before: paired, the spool and its tag answer", before["paired"] == 200 and
                  self.spool["id"] in (before["spools"] or []) and before["tag"][0] == 200, json.dumps(before))
        out_dir = run.work / "backup-g"
        out_dir.mkdir(exist_ok=True)
        r = run.sh([fk, "backup", "create", "--out", str(out_dir)], name="backup-create")
        zips = sorted(out_dir.glob("filament-kit-backup-*.zip"))
        run.check(sc, "sudo filament-kit backup create writes one standard zip",
                  r.returncode == 0 and len(zips) == 1 and zipfile.is_zipfile(zips[0]), r.stdout + r.stderr[-600:])
        if not zips:
            raise Fail("no backup zip")
        with zipfile.ZipFile(zips[0]) as zf:
            names = zf.namelist()
        run.check(sc, "the zip holds the manifest, the Spoolman database and the kit's folders",
                  {"manifest.xml", "spoolman/spoolman.db", "files/etc/filament-kit/config.json",
                   "files/etc/filament-kit/cert.pem", "files/var/lib/filament-kit/devices.json"} <= set(names),
                  str(names[:40]))
        uninstall(run, rel, "uninstall-before-restore")
        left = nothing_installed()
        run.check(sc, "the machine is wiped (uninstall --purge)", not left, ", ".join(left))
        r = rel.get_sh(["--repo", OWNER_REPO, "--version", version, "--modules", "spoolman,server"],
                       "get-fresh-for-restore")
        run.check(sc, f"a fresh install of {version} (spoolman, server)", r.returncode == 0, r.stderr[-1500:])
        if r.returncode:
            raise Fail("the fresh install failed")
        fresh = self._kit_state(auth)
        run.check(sc, "the fresh install does not know the phone", fresh["paired"] == 401, json.dumps(fresh))
        r = run.sh([fk, "restore", "--yes", str(zips[0])], name="restore", timeout=3600)
        run.check(sc, "sudo filament-kit restore --yes <zip> succeeds", r.returncode == 0 and "Restored." in r.stdout,
                  r.stdout[-2500:] + r.stderr[-1500:])
        act = wait_for(lambda: (lambda a: a if set(a.values()) == {"active"} else None)(
            units_active("spoolman.service", "filament-kit.service", "filament-kit-web.service")), 120, 2)
        run.check(sc, "after the restore: spoolman, filament-kit and filament-kit-web active", bool(act),
                  str(units_active("spoolman.service", "filament-kit.service", "filament-kit-web.service")))
        wait_for(lambda: jhttp("GET", f"{KIT}/api/info")[0] == 200 or None, 90, 2)
        after = wait_for(lambda: (lambda s: s if s["paired"] == 200 else None)(self._kit_state(auth)), 90, 2) \
            or self._kit_state(auth)
        for key, what in (("modules", "the same modules"), ("cert", "the same certificate (phones pair as before)"),
                          ("paired", "the phone's token works without pairing again"), ("spools", "the same spools"),
                          ("tag", "the tag finds its spool"), ("printers", "the same printers")):
            run.check(sc, f"after the restore: {what}", after[key] == before[key],
                      f"before {before[key]!r}, after {after[key]!r}")
        r = root_python("import sys\nfrom filament_kit import setup_code, trusted\n"
                        f"print(bool(setup_code.check({code!r})), trusted.status({trust!r})['trusted'])")
        run.check(sc, "after the restore: the same setup code, and the trusted computer is still trusted",
                  r.stdout.split() == ["True", "True"], r.stdout + r.stderr[-400:])
        st = run.sh([fk, "status"], name="status-after-restore")
        run.check(sc, "filament-kit status exits 0", st.returncode == 0, st.stdout[-1500:])
        kept = sorted(Path("/var/backups/filament-kit").glob("pre-restore-*.zip"))
        run.check(sc, "what the fresh install had is kept as a pre-restore zip", len(kept) == 1, str(kept))
        if self.printer is not None:
            code_, plist = wait_for(lambda: (lambda c: c if c[0] == 200 and c[1].get("printers") else None)(
                jhttp("GET", f"{KIT}/api/printers", headers=auth)), 60, 2) or (0, {})
            run.check(sc, "after the restore: the printer is back in the kit", code_ == 200 and
                      SERIAL in [p.get("id") for p in plist.get("printers", [])], str(plist)[:400])

SEED_ITEM = {"vendor": "E2E Test Co", "name": "E2E PLA Red", "material": "PLA", "color_hex": "cc0000",
             "net": 1000, "tare": 200, "density": 1.24, "count": 1, "nozzle": 210, "bed": 60,
             "sealed": False}          # an opened spool: only then is the tag linked

# The state each scenario starts from (E2E.prepare): "clean" no kit; "release" v1 on the fake release server;
# "server" this checkout's v1 installed by get.sh with spoolman,server,printers,web; "seeded" that plus the
# e2e pairing and the spool with its tag (what d leaves); None: the scenario sets itself up (f).
NEEDS = {"a": "clean", "d": "server", "c": "seeded", "b": "server", "e": "release", "f": None, "g": "seeded"}

SCENARIOS = {
    "a": ("a) fake release server: get.sh install, tampered tarball, bad signature", "a_install"),
    "d": ("d) manual add without AI (server mode, no API key)", "d_manual_add"),
    "c": ("c) fake 16-unit printer through the reader API", "c_printer"),
    "b": ("b) updater: check, update, hardware feed, rollback", "b_updater"),
    "e": ("e) station upgraded by the updater keeps its server address", "e_station"),
    "f": ("f) the last released tag: real update from it, real rollback to it", "f_cross_tag"),
    "g": ("g) backup zip, wipe, fresh install, restore: the same kit comes back", "g_backup_restore"),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--only", default="a,d,c,b,e")
    ap.add_argument("--previous", help="a tag of this repo, vX.Y.Z: adds scenario f")
    args = ap.parse_args()
    if args.previous and not re.fullmatch(r"v\d+\.\d+\.\d+", args.previous):
        ap.error("--previous takes a tag like v0.4.0")
    run = Run(Path(args.work))
    rel = Releases(run)
    e2e = E2E(run, rel, args.previous)
    want = [s for s in args.only.split(",") if s]
    if args.previous and "f" not in want:
        want.append("f")
    status: dict[str, str] = {}
    try:
        print(f"==> building releases {e2e.v1} and {e2e.v2} (throwaway key)", flush=True)
        rel.build(e2e.v1)
        rel.build(e2e.v2)
        for key in want:
            title, meth = SCENARIOS[key]
            print(f"\n==> {title}", flush=True)
            if key not in ("a", "f") and "a" in want and not e2e.installed:     # f installs its own
                status[key] = "skip: the install (a) failed"
                print(f"  SKIP {status[key]}")
                continue
            n = len(run.results)
            try:
                e2e.prepare(key)
                getattr(e2e, meth)()
                bad = [r for r in run.results[n:] if not r["ok"]]
                status[key] = "fail" if bad else "pass"
            except Skip as e:
                status[key] = f"skip: {e}"
                print(f"  SKIP {e}")
            except Exception as e:  # noqa: BLE001 - one scenario's crash is its failure, the others still run
                status[key] = "fail"
                run.check(key, f"{type(e).__name__}: {e}", False, traceback.format_exc())
    finally:
        if e2e.printer is not None:
            e2e.printer.close()
        rel.stop()
        (run.work / "results.json").write_text(json.dumps({"scenarios": status, "checks": run.results}, indent=2),
                                               encoding="utf-8")
    print("\n==> results")
    for key in want:
        print(f"  {key}: {status.get(key, 'not run')}")
    return 0 if all(not s.startswith("fail") and s != "not run" for s in (status.get(k, "not run") for k in want)) \
        else 1


if __name__ == "__main__":
    sys.exit(main())
