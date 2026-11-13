"""A signed release of the local label reader (filament-kit-vision) on a GitHub API look-alike (tests only).

`make_release(priv, version, ...)` builds the assets the kit expects (local_intake_install's docstring): the code
tarball with install/filament-kit-vision.sh, a CPU model asset, a GPU adapter asset, manifest.json, SHA256SUMS and its
ed25519 signature. `Served(files_by_version)` answers /repos/o/r/releases/latest and tags/v<version>, with assets
behind a 302 as GitHub does.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import tarfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

INSTALLER = b"#!/bin/bash\necho fake installer \"$@\"\n"


def code_tarball(version: str, *, extra: tarfile.TarInfo | None = None, script: bool = True) -> bytes:
    buf = io.BytesIO()
    top = f"filament-kit-vision-{version}"
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for d in (top, f"{top}/install"):
            ti = tarfile.TarInfo(d)
            ti.type, ti.mode = tarfile.DIRTYPE, 0o755
            tf.addfile(ti)
        files = {f"{top}/README.md": b"reader\n"}
        if script:
            files[f"{top}/install/filament-kit-vision.sh"] = INSTALLER
        for name, data in files.items():
            ti = tarfile.TarInfo(name)
            ti.size, ti.mode = len(data), 0o755
            tf.addfile(ti, io.BytesIO(data))
        if extra is not None:
            tf.addfile(extra, io.BytesIO(b"x" * extra.size) if extra.size else None)
    return buf.getvalue()


def manifest(version: str, **over) -> dict:
    m = {"version": version, "api_version": "1.0", "kit_min": "0.5.0",
         "tiers": {"cpu": {"assets": [f"cpu-models-{version}.tar.gz"], "download_mb": 180, "disk_mb": 420,
                           "minutes": 3},
                   "gpu": {"assets": [f"cpu-models-{version}.tar.gz", f"gpu-adapter-{version}.tar.gz"],
                           "download_mb": 900, "disk_mb": 9800, "minutes": 25,
                           "fetched_at_install": "the base vision model from its publisher (about 5 GB)"},
                   "auto": {"assets": [f"cpu-models-{version}.tar.gz", f"gpu-adapter-{version}.tar.gz"],
                            "download_mb": 900, "disk_mb": 9800, "minutes": 25}}}
    m.update(over)
    return m


def make_release(priv, version: str = "0.1.0", *, manifest_over: dict | None = None, tarball: bytes | None = None,
                 tamper_asset: bool = False, tamper_sig: bool = False) -> dict[str, bytes]:
    files = {f"filament-kit-vision-{version}.tar.gz": tarball if tarball is not None else code_tarball(version),
             f"cpu-models-{version}.tar.gz": b"CPU MODELS " + version.encode(),
             f"gpu-adapter-{version}.tar.gz": b"GPU ADAPTER " + version.encode(),
             "manifest.json": json.dumps(manifest(version, **(manifest_over or {}))).encode()}
    sums = "".join(f"{hashlib.sha256(d).hexdigest()}  {n}\n" for n, d in files.items()).encode()
    sig = priv.sign(sums)
    if tamper_sig:
        sig = bytes([sig[0] ^ 1]) + sig[1:]
    if tamper_asset:
        files[f"cpu-models-{version}.tar.gz"] += b"!"
    return {**files, "SHA256SUMS": sums, "SHA256SUMS.sig": base64.b64encode(sig) + b"\n"}


def pubkey(priv) -> str:
    from cryptography.hazmat.primitives import serialization
    raw = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode("ascii")


class Served:
    """`releases`: {version: {name: bytes}}; the newest version (by the order given) is "latest"."""

    def __init__(self, releases: dict[str, dict[str, bytes]]):
        self.releases = releases
        self.requests: list[str] = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                outer.requests.append(self.path)
                base = f"http://127.0.0.1:{self.server.server_address[1]}"
                latest = list(outer.releases)[-1]
                for ver, files in outer.releases.items():
                    if self.path == f"/repos/o/r/releases/tags/v{ver}" or (
                            self.path == "/repos/o/r/releases/latest" and ver == latest):
                        body = json.dumps({"tag_name": f"v{ver}", "body": f"reader {ver}", "assets": [
                            {"name": n, "url": f"{base}/repos/o/r/releases/assets/{ver}/{n}"} for n in files]})
                        return self._send(200, body.encode())
                if self.path.startswith("/repos/o/r/releases/assets/"):
                    ver, name = self.path.rsplit("/", 2)[1:]
                    self.send_response(302)
                    self.send_header("Location", f"{base}/dl/{ver}/{name}")
                    self.end_headers()
                    return None
                if self.path.startswith("/dl/"):
                    ver, name = self.path[4:].split("/", 1)
                    if name in outer.releases.get(ver, {}):
                        return self._send(200, outer.releases[ver][name])
                return self._send(404, b"{}")

            def _send(self, code, body):
                self.send_response(code)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.api = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def downloaded(self) -> list[str]:
        return [p.split("/", 3)[3] for p in self.requests if p.startswith("/dl/")]

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
