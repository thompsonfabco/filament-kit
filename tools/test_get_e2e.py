#!/usr/bin/env python3
"""End-to-end test of get.sh on Linux (WSL Ubuntu): a local fake GitHub releases server, a throwaway release key,
and fake releases whose install.sh only records how it was run. Runs get.sh as root (sudo -n) the way the README
does (`... | sudo bash -s -- ...`), with and without a terminal.

  python3 tools/test_get_e2e.py          (needs python3-cryptography, sudo without a password, `script`)

Cases: good release (piped, no terminal; and with a terminal), bad signature, bad hash, no public key in get.sh,
a token file (never sent to a non-GitHub host, never printed), --version. Leaves nothing behind except what it
removes itself: /opt/filament-kit/releases/<test version> is deleted at the end.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import sign_release  # noqa: E402

VERSIONS = ("7.7.1", "7.7.2")
KEEP = Path("/opt/filament-kit/releases")


def tarball(version: str, record: Path) -> bytes:
    # stty, as apt does: it must not stop install.sh for good. Classic sudo starts a piped command in the background and
    # makes it the foreground job at this first touch, so fg= is read after it: then it must be the foreground job.
    stub = ("#!/usr/bin/env bash\n"
            f"{{ echo \"args=$*\"; if [ -t 0 ]; then echo tty=yes; else echo tty=no; fi\n"
            "  if [ -t 0 ]; then stty \"$(stty -g)\" && echo stty=ok; fi\n"
            "  read -r pg tp < <(ps -o pgid=,tpgid= -p $$)\n"
            "  if [ \"$pg\" = \"$tp\" ]; then echo fg=yes; else echo fg=no; fi\n"
            # --set keys=1 (run_get_keys): three keys without Enter must arrive, and the terminal must not echo them
            "  case \"$*\" in *keys=1*) echo STUB-READY >/dev/tty; IFS= read -r -s -n3 -t 20 k; echo \"keys=$k\" ;; "
            "esac\n"
            f"  id -u; }} > {record}\n")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        ti = tarfile.TarInfo(f"filament-kit-{version}/install.sh")
        ti.size, ti.mode = len(stub), 0o755
        tf.addfile(ti, io.BytesIO(stub.encode()))
    return buf.getvalue()


class Server:
    def __init__(self, priv, record: Path, *, tamper_sig=False, tamper_tar=False):
        self.releases = {}
        for v in VERSIONS:
            tar = tarball(v, record)
            sums = f"{hashlib.sha256(tar).hexdigest()}  filament-kit-{v}.tar.gz\n".encode()
            sig = priv.sign(sums)
            if tamper_sig:
                sig = sig[:5] + bytes([sig[5] ^ 4]) + sig[6:]
            if tamper_tar:
                tar = tar[:-3] + bytes([tar[-3] ^ 1]) + tar[-2:]
            self.releases[v] = {f"filament-kit-{v}.tar.gz": tar, "SHA256SUMS": sums,
                                "SHA256SUMS.sig": base64.b64encode(sig) + b"\n"}
        self.seen: list[tuple[str, dict]] = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                outer.seen.append((self.path, dict(self.headers)))
                base = f"http://127.0.0.1:{self.server.server_address[1]}"
                p = self.path
                ver = VERSIONS[-1] if p == "/repos/o/r/releases/latest" else \
                    p.removeprefix("/repos/o/r/releases/tags/v") if p.startswith("/repos/o/r/releases/tags/v") \
                    else None
                if ver in outer.releases:
                    doc = {"tag_name": f"v{ver}", "assets": [
                        {"name": n, "url": f"{base}/repos/o/r/releases/assets/{ver}/{n}"}
                        for n in outer.releases[ver]]}
                    return self._send(200, json.dumps(doc).encode())
                if p.startswith("/repos/o/r/releases/assets/"):
                    self.send_response(302)
                    self.send_header("Location", base + "/dl/" + p.removeprefix("/repos/o/r/releases/assets/"))
                    self.end_headers()
                    return None
                if p.startswith("/dl/"):
                    v, _, n = p[4:].partition("/")
                    if n in outer.releases.get(v, {}):
                        return self._send(200, outer.releases[v][n])
                return self._send(404, b"{}")

            def _send(self, code, body):
                self.send_response(code)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.api = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def leftover_tmp() -> list[str]:
    return sorted(str(p) for p in Path("/tmp").glob("filament-kit-get.*"))


def run_get(get_sh: Path, args: list[str], *, tty: bool, env_extra: dict | None = None, piped: bool = True,
            timeout: float = 300):
    """`cat get.sh | sudo bash -s -- args` (or `sudo bash get.sh args` with piped=False); without tty in a new
    session (no controlling terminal), with tty inside `script` (a pseudo-terminal). A job stopped on the terminal
    never ends: the timeout turns that into a failed run (returncode None)."""
    quoted = " ".join(f"'{a}'" for a in args)
    env = " ".join(f"{k}={v}" for k, v in (env_extra or {}).items())
    line = (f"cat '{get_sh}' | sudo -n {env} bash -s -- {quoted}" if piped
            else f"sudo -n {env} bash '{get_sh}' {quoted}")
    if tty:
        cmd = ["script", "-qec", line, "/dev/null"]
    else:
        cmd = ["setsid", "-w", "bash", "-c", line]
    try:
        return subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        subprocess.run(["sudo", "-n", "pkill", "-KILL", "-f", "filament-kit-get[.]"], capture_output=True)
        out = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        return subprocess.CompletedProcess(cmd, None, out, "timed out (stopped on the terminal?)")


def run_get_keys(get_sh: Path, args: list[str], *, piped: bool) -> tuple[int | None, bytes, bool]:
    """get.sh in a pty of our own (the person's terminal); once install.sh is ready, type three keys and no Enter.
    Returns (exit code, everything the terminal showed, the terminal echoes and edits lines again afterwards)."""
    import pty
    import select
    import time
    quoted = " ".join(f"'{a}'" for a in [*args, "--modules", "server", "--set", "keys=1"])
    line = (f"cat '{get_sh}' | sudo -n bash -s -- {quoted}" if piped else f"sudo -n bash '{get_sh}' {quoted}")
    pid, fd = pty.fork()
    if pid == 0:
        os.execvp("bash", ["bash", "-c", line])
    screen, typed, end = b"", False, time.time() + 90
    while time.time() < end:
        if select.select([fd], [], [], 0.3)[0]:
            try:
                chunk = os.read(fd, 65536)
            except OSError:
                break
            if not chunk:
                break
            screen += chunk
        if not typed and b"STUB-READY" in screen:
            typed = True
            time.sleep(0.3)
            for b in b"xyz":
                os.write(fd, bytes([b]))
                time.sleep(0.1)
    else:
        os.kill(pid, 9)
    _, status = os.waitpid(pid, 0)
    import termios
    try:
        lflag = termios.tcgetattr(fd)[3]            # the pty's settings, read on the master side
        restored = bool(lflag & termios.ECHO) and bool(lflag & termios.ICANON)
    except termios.error:
        restored = False
    os.close(fd)
    return (os.waitstatus_to_exitcode(status) if time.time() < end else None), screen, restored


def main() -> int:
    if os.name != "posix" or subprocess.run(["sudo", "-n", "true"]).returncode != 0:
        print("needs Linux and sudo without a password")
        return 2
    failures = []

    def check(name, cond, detail=""):
        print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"\n     {detail}"))
        if not cond:
            failures.append(name)

    work = Path(tempfile.mkdtemp(prefix="fk-get-e2e."))
    os.chmod(work, 0o755)
    record = work / "record.txt"
    priv = ed25519.Ed25519PrivateKey.generate()
    pub = base64.b64encode(priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
    # a copy of the tree with the throwaway key in release.py and get.sh
    tree = work / "repo"
    (tree / "server/filament_kit").mkdir(parents=True)
    shutil.copy(ROOT / "server/filament_kit/release.py", tree / "server/filament_kit/release.py")
    shutil.copy(ROOT / "get.sh", tree / "get.sh")
    sign_release.set_pubkey(tree, pub)
    get_sh = tree / "get.sh"
    before_tmp = leftover_tmp()
    secret = "ghp_E2E_SECRET_never_shown"
    tok = work / "token"
    tok.write_text(secret + "\n")
    os.chmod(tok, 0o644)          # root reads it through sudo; the test user wrote it

    try:
        srv = Server(priv, record)
        try:
            # 1. good, piped, no terminal, with options passed through and a token file
            record.unlink(missing_ok=True)
            r = run_get(get_sh, ["--api", srv.api, "--repo", "o/r", "--mode", "server", "--token-file", str(tok)],
                        tty=False)
            rec = record.read_text() if record.exists() else ""
            check("good release installs (no terminal)", r.returncode == 0 and "args=--mode server" in rec,
                  f"rc={r.returncode} rec={rec!r} err={r.stderr[-800:]}")
            check("no terminal: install.sh gets no tty", "tty=no" in rec, rec)
            check("install.sh runs as root", rec.strip().endswith("\n0") or rec.strip().split("\n")[-1] == "0", rec)
            check("verified version said", "verified filament-kit 7.7.2" in r.stderr, r.stderr[-400:])
            check("token never sent to a non-GitHub host", all("Authorization" not in h for _, h in srv.seen))
            check("token never printed", secret not in r.stdout + r.stderr)
            check("temp folder removed", leftover_tmp() == before_tmp, str(leftover_tmp()))
            kept = KEEP / "7.7.2"
            listing = subprocess.run(["sudo", "-n", "ls", str(kept)], capture_output=True, text=True).stdout.split()
            check("verified release kept for rollback", sorted(listing) == sorted(
                ["SHA256SUMS", "SHA256SUMS.sig", "filament-kit-7.7.2.tar.gz"]), str(listing))

            # 2. with a terminal (script's pty): install.sh can ask its questions, piped and downloaded first. Piped,
            # sudo (use_pty) runs bash as a background job. Under sudo-rs get.sh must make install.sh the foreground job,
            # or its first touch of the terminal (a question, apt) stops it for good; classic sudo does that itself at
            # that touch, and reads no keys if get.sh does it. Run this under both: `sudo` -> /usr/bin/sudo.ws on PATH.
            for piped, form in ((True, "curl | sudo bash"), (False, "sudo bash get.sh")):
                record.unlink(missing_ok=True)
                r = run_get(get_sh, ["--api", srv.api, "--repo", "o/r"], tty=True, piped=piped, timeout=90)
                rec = record.read_text() if record.exists() else ""
                check(f"with a terminal ({form}): install.sh gets the tty", r.returncode == 0 and "tty=yes" in rec,
                      f"rc={r.returncode} rec={rec!r} out={r.stdout[-600:]} err={r.stderr[-300:]}")
                check(f"with a terminal ({form}): install.sh is the foreground job and can use the terminal",
                      "fg=yes" in rec and "stty=ok" in rec, rec)
                # keys reach install.sh one by one (the module menu, a masked secret), and the person's terminal
                # neither echoes them nor stays changed afterwards
                record.unlink(missing_ok=True)
                code, screen, restored = run_get_keys(get_sh, ["--api", srv.api, "--repo", "o/r"], piped=piped)
                rec = record.read_text() if record.exists() else ""
                shown = screen.split(b"STUB-READY", 1)[-1]
                check(f"with a terminal ({form}): keys arrive without Enter", code == 0 and "keys=xyz" in rec,
                      f"rc={code} rec={rec!r} screen={screen[-400:]!r}")
                check(f"with a terminal ({form}): typed keys are not echoed", b"xyz" not in shown, repr(shown[-300:]))
                check(f"with a terminal ({form}): the terminal is put back", restored)

            # which sudo, in any language: `Sudo version` is translated. A fake sudo answers as a German one does.
            fake = work / "fakes"
            fake.mkdir()
            for name, text in (("sudo", "Sudo version 1.9.15p5"), ("sudo-rs", "sudo-rs 0.2.13")):
                (fake / name).write_text('#!/bin/sh\n[ "$LC_ALL" = C ] && echo "%s" || echo "%s"\n'
                                         % (text, text.replace("Sudo version", "Sudo-Version")))
                (fake / name).chmod(0o755)
                got = subprocess.run(
                    ["bash", "-c", 'eval "$(sed -n "/^fk_classic_sudo() {/,/^}/p" "$1")"; fake=$2; readlink() { echo "$fake"; }; '
                                   'fk_classic_sudo', "-", str(get_sh), str(fake / name)],
                    env={**os.environ, "LANG": "de_DE.UTF-8", "LC_ALL": "de_DE.UTF-8", "LANGUAGE": "de"})
                check(f"{name} is told apart under a German locale", (got.returncode == 0) == (name == "sudo"),
                      f"rc={got.returncode}")

            # 3. --version
            record.unlink(missing_ok=True)
            r = run_get(get_sh, ["--api", srv.api, "--repo", "o/r", "--version", "7.7.1"], tty=False)
            check("--version installs that release", r.returncode == 0 and "verified filament-kit 7.7.1" in r.stderr,
                  r.stderr[-400:])
        finally:
            srv.close()

        for name, kw in (("bad signature", {"tamper_sig": True}), ("bad hash", {"tamper_tar": True})):
            srv = Server(priv, record, **kw)
            try:
                record.unlink(missing_ok=True)
                subprocess.run(["sudo", "-n", "rm", "-rf", str(KEEP / "7.7.2")])
                r = run_get(get_sh, ["--api", srv.api, "--repo", "o/r"], tty=False)
                check(f"{name}: refused", r.returncode != 0 and not record.exists(),
                      f"rc={r.returncode} err={r.stderr[-600:]}")
                check(f"{name}: says nothing was installed", "nothing was installed" in r.stderr, r.stderr[-600:])
                check(f"{name}: nothing kept", subprocess.run(["sudo", "-n", "test", "-e", str(KEEP / "7.7.2")])
                      .returncode != 0)
                if name == "bad signature":
                    check("bad signature: tarball never downloaded",
                          not any(p.endswith(".tar.gz") for p, _ in srv.seen), str([p for p, _ in srv.seen]))
                check(f"{name}: temp folder removed", leftover_tmp() == before_tmp, str(leftover_tmp()))
            finally:
                srv.close()

        # 4. the get.sh in the repo before the owner sets a key: refuses before downloading
        srv = Server(priv, record)
        try:
            record.unlink(missing_ok=True)
            plain = work / "get-nokey.sh"
            shutil.copy(ROOT / "get.sh", plain)
            if 'PUBKEY = ""' in plain.read_text():
                r = run_get(plain, ["--api", srv.api, "--repo", "o/r"], tty=False)
                check("no public key: refused before any download",
                      r.returncode != 0 and not record.exists() and srv.seen == [], r.stderr[-400:])
            else:
                print("skip no-key case: the repo's get.sh already carries a key")
        finally:
            srv.close()

        # 5. not root
        r = subprocess.run(["bash", str(get_sh), "--api", "http://127.0.0.1:9"], capture_output=True, text=True)
        check("not root: refused", r.returncode != 0 and "run as root" in r.stderr, r.stderr)
    finally:
        for v in VERSIONS:
            subprocess.run(["sudo", "-n", "rm", "-rf", str(KEEP / v)])
        subprocess.run(["sudo", "-n", "rmdir", "--ignore-fail-on-non-empty", str(KEEP), str(KEEP.parent)],
                       capture_output=True)
        shutil.rmtree(work, ignore_errors=True)

    print(f"\n{'FAILED: ' + ', '.join(failures) if failures else 'all get.sh cases passed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
