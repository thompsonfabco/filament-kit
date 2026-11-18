"""lasttag: read-only HTTP view of nfc2klipper's last NFC tag, for the filament-kit server (its tag sources).

GET /last-tag -> {"status": "ok", "nfc_id": "...", "spool_id": ..., "read_at": "<ISO local time>", "read_at_unix": ...,
                  "age_seconds": ...}   (nfc2klipper's IPC get_state, nothing else; read_at is null until a tap
                  after the backend started, or if the backend lacks the local read_at patch)
Answers only the addresses listed in the `allow` file next to this script (one per line; written by the
filament-kit printer pack). No writes, no other routes. Runs as the lasttag systemd service on port 5002
(LASTTAG_PORT changes it) with nfc2klipper's venv Python (for its lib.ipc client); lives outside ~/nfc2klipper so
updates don't touch it.

It serves HTTPS with a self-signed certificate it makes itself the first time it starts, with the `openssl` program
and Python's own ssl module (nothing to install): cert.pem and key.pem (0600) in tls/ under the unit's state folder
(STATE_DIRECTORY, set by the unit's StateDirectory=lasttag), or beside this script without one. The kit server pins
the certificate's SHA-256 the first time it reads the address (trust on first use). Only when no certificate can be
made (no openssl, a folder it may not write: a unit from before this version) does it serve plain HTTP, and says so
in the journal; the kit then shows that the tag service is not using HTTPS.
"""
import datetime, hashlib, json, os, socket, ssl, subprocess, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

NFC = os.path.expanduser("~/nfc2klipper")
sys.path.insert(0, NFC)
from lib.ipc import IPCClient  # noqa: E402

ALLOW_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "allow")
with open(ALLOW_FILE, encoding="utf-8") as _f:
    ALLOW = {line.strip() for line in _f if line.strip() and not line.startswith("#")} | {"127.0.0.1"}
CLIENT = IPCClient(os.path.join(NFC, "nfc2klipper.sock"))
PORT = int(os.environ.get("LASTTAG_PORT") or "5002")


def tls_dir():
    base = os.environ.get("STATE_DIRECTORY", "").split(":")[0] or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "tls")


def local_addresses():
    try:
        return subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=5).stdout.split()
    except (OSError, subprocess.SubprocessError):
        return []


def make_cert(dest):
    """cert.pem and key.pem (EC P-256, 10 years, 0600 key) in `dest`, by the openssl program. The key is written
    first and the certificate last, each under a temporary name, so a certificate that exists is a whole one."""
    host = socket.gethostname().split(".")[0]
    names = [f"DNS:{host}", f"DNS:{host}.local", "DNS:localhost", "IP:127.0.0.1"] + [f"IP:{a}" for a in local_addresses()
                                                                                    if ":" not in a]
    os.makedirs(dest, mode=0o700, exist_ok=True)
    key, cert = os.path.join(dest, "key.pem"), os.path.join(dest, "cert.pem")
    old = os.umask(0o077)
    try:
        subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
                        "-nodes", "-days", "3650", "-subj", f"/CN={host}", "-addext",
                        "subjectAltName=" + ",".join(names), "-keyout", key + ".new", "-out", cert + ".new"],
                       check=True, capture_output=True, timeout=60)
        os.chmod(key + ".new", 0o600)
        os.chmod(cert + ".new", 0o644)
        os.replace(key + ".new", key)
        os.replace(cert + ".new", cert)
    finally:
        os.umask(old)
        for leftover in (key + ".new", cert + ".new"):
            if os.path.exists(leftover):
                os.unlink(leftover)
    return cert, key


def fingerprint(cert_path):
    with open(cert_path, encoding="ascii") as f:
        return hashlib.sha256(ssl.PEM_cert_to_DER_cert(f.read())).hexdigest()


def tls_context():
    """(SSLContext, fingerprint) for the service's certificate, made when there is none; None when it cannot be made."""
    dest = tls_dir()
    cert, key = os.path.join(dest, "cert.pem"), os.path.join(dest, "key.pem")
    try:
        if not (os.path.exists(cert) and os.path.exists(key)):
            make_cert(dest)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(cert, key)
        return ctx, fingerprint(cert)
    except (OSError, ssl.SSLError, subprocess.SubprocessError, ValueError) as e:
        print(f"lasttag: no HTTPS certificate ({type(e).__name__}: {e}); serving plain HTTP", file=sys.stderr)
        return None


class Server(ThreadingHTTPServer):
    """One thread per caller; the TLS handshake happens in that thread (do_handshake_on_connect=False), so a caller
    that stalls in it holds no one else up."""
    daemon_threads = True
    context = None

    def get_request(self):
        sock, addr = self.socket.accept()
        if self.context is not None:
            sock = self.context.wrap_socket(sock, server_side=True, do_handshake_on_connect=False)
        return sock, addr

    def handle_error(self, request, client_address):
        pass  # a failed handshake or a dropped caller: nothing to log


class Handler(BaseHTTPRequestHandler):
    server_version = "lasttag"
    sys_version = ""
    timeout = 10

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.client_address[0] not in ALLOW:
            return self._send(403, {"status": "error", "message": "forbidden"})
        if self.path != "/last-tag":
            return self._send(404, {"status": "error", "message": "not found"})
        try:
            s = CLIENT.send_request({"command": "get_state"})
        except Exception as e:  # backend down or restarting
            return self._send(503, {"status": "error", "message": f"nfc2klipper backend: {e}"})
        at = s.get("read_at")  # unix time; needs the local read_at patch in nfc2klipper_backend.py
        self._send(200, {"status": s.get("status"), "nfc_id": s.get("nfc_id"), "spool_id": s.get("spool_id"),
                         "read_at": datetime.datetime.fromtimestamp(at).astimezone().isoformat(timespec="seconds") if at else None,
                         "read_at_unix": at, "age_seconds": round(time.time() - at) if at else None})

    def log_message(self, fmt, *args):
        pass  # one journal line per poll is noise


if __name__ == "__main__":
    server = Server(("0.0.0.0", PORT), Handler)
    got = tls_context()
    if got:
        server.context = got[0]
        print(f"lasttag: HTTPS on port {PORT}, certificate fingerprint {got[1]}", file=sys.stderr, flush=True)
    server.serve_forever()
