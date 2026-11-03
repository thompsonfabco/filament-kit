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
    stub = ("#!/usr/bin/env bash\n"
            f"{{ echo \"args=$*\"; if [ -t 0 ]; then echo tty=yes; else echo tty=no; fi; id -u; }} > {record}\n")
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


def run_get(get_sh: Path, args: list[str], *, tty: bool, env_extra: dict | None = None):
    """`cat get.sh | sudo bash -s -- args`; without tty in a new session (no controlling terminal), with tty
    inside `script` (a pseudo-terminal)."""
    quoted = " ".join(f"'{a}'" for a in args)
    line = f"cat '{get_sh}' | sudo -n {' '.join(f'{k}={v}' for k, v in (env_extra or {}).items())} " \
           f"bash -s -- {quoted}"
    if tty:
        cmd = ["script", "-qec", line, "/dev/null"]
    else:
        cmd = ["setsid", "-w", "bash", "-c", line]
    return subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300)


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

            # 2. with a terminal (script's pty): install.sh can ask its questions
            record.unlink(missing_ok=True)
            r = run_get(get_sh, ["--api", srv.api, "--repo", "o/r"], tty=True)
            rec = record.read_text() if record.exists() else ""
            check("with a terminal: install.sh gets the tty", r.returncode == 0 and "tty=yes" in rec,
                  f"rc={r.returncode} rec={rec!r} out={r.stdout[-600:]}")

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
