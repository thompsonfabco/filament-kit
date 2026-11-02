"""Test-only TLS server on 127.0.0.x with a self-signed certificate (needs `cryptography`, test extra).

Every connection's first line is recorded in `server.received` (b"" when the client sent nothing),
so a test can prove that the pinned client wrote no request bytes after a fingerprint mismatch.
"""
import datetime
import hashlib
import ipaddress
import json
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


def make_cert(dest: Path, name: str = "fk-test") -> tuple[Path, Path, str]:
    """(cert.pem, key.pem, sha256 hex of the DER leaf) for a self-signed cert valid for 127.0.0.x."""
    dest.mkdir(parents=True, exist_ok=True)
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = datetime.datetime.now(datetime.timezone.utc)
    san = [x509.DNSName("localhost")] + [x509.IPAddress(ipaddress.ip_address(f"127.0.0.{i}")) for i in (1, 2, 3)]
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=30))
            .add_extension(x509.SubjectAlternativeName(san), critical=False)
            .sign(key, hashes.SHA256()))
    cert_pem, key_pem = dest / f"{name}.pem", dest / f"{name}.key"
    cert_pem.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_pem.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    fp = hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()
    return cert_pem, key_pem, fp


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def handle_one_request(self):
        try:
            self.raw_requestline = self.rfile.readline(65537)
        except (OSError, ssl.SSLError):
            self.raw_requestline = b""
        self.server.received.append(self.raw_requestline)
        if not self.raw_requestline:
            self.close_connection = True
            return
        if not self.parse_request():
            return
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""
        self.server.requests.append({"method": self.command, "path": self.path,
                                     "auth": self.headers.get("Authorization"), "body": body,
                                     "type": self.headers.get("Content-Type")})
        status, ctype, payload = self.server.respond(self.command, self.path, body)
        if isinstance(payload, (dict, list)):
            payload = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
        self.wfile.flush()


class _Server(ThreadingHTTPServer):
    """TLS per connection in the handler thread; a failed handshake is recorded as b"" (no bytes)."""

    ssl_context: ssl.SSLContext

    def finish_request(self, request, client_address):
        try:
            tls = self.ssl_context.wrap_socket(request, server_side=True)
        except (OSError, ssl.SSLError):
            self.received.append(b"")
            return
        self.RequestHandlerClass(tls, client_address, self)


class TlsServer:
    """Serves `respond(method, path, body) -> (status, content_type, dict|bytes)` over TLS."""

    def __init__(self, cert: Path, key: Path, host: str = "127.0.0.1", port: int = 0, respond=None):
        self.httpd = _Server((host, port), _Handler)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
        self.httpd.ssl_context = ctx
        self.httpd.received = []
        self.httpd.requests = []
        self.httpd.respond = respond or (lambda m, p, b: (200, "application/json", {"name": "fk", "api": 1}))
        self.httpd.handle_error = lambda *a: None
        self.host, self.port = host, self.httpd.server_address[1]
        self._t = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def received(self):
        return self.httpd.received

    def wait_received(self, n: int = 1, timeout: float = 5) -> list:
        """The recorded first lines once at least n connections were handled (the handler runs in a thread)."""
        end = time.monotonic() + timeout
        while len(self.httpd.received) < n and time.monotonic() < end:
            time.sleep(0.01)
        return self.httpd.received

    @property
    def requests(self):
        return self.httpd.requests

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *a):
        self.httpd.shutdown()
        self.httpd.server_close()
