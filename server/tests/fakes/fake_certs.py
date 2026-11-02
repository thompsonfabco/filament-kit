"""Self-signed printer leaves for the TLS pinning tests (EC keys: fast to make, no files unless asked for)."""
from __future__ import annotations

import datetime as dt
import hashlib
import ssl
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


class Leaf:
    def __init__(self, cn: str | None = None):
        self.key = ec.generate_private_key(ec.SECP256R1())
        attrs = [x509.NameAttribute(NameOID.COMMON_NAME, cn)] if cn else \
            [x509.NameAttribute(NameOID.ORGANIZATION_NAME, "fake printer")]
        name = x509.Name(attrs)
        now = dt.datetime.now(dt.timezone.utc)
        self.cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                     .public_key(self.key.public_key()).serial_number(x509.random_serial_number())
                     .not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=30))
                     .sign(self.key, hashes.SHA256()))
        self.der = self.cert.public_bytes(serialization.Encoding.DER)
        self.fp = hashlib.sha256(self.der).hexdigest()

    def server_ctx(self, dest: Path) -> ssl.SSLContext:
        """A TLS server context presenting this leaf (cert/key written under `dest`)."""
        dest = Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        cert, key = dest / f"{self.fp[:12]}.pem", dest / f"{self.fp[:12]}.key"
        cert.write_bytes(self.cert.public_bytes(serialization.Encoding.PEM))
        key.write_bytes(self.key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                               serialization.NoEncryption()))
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
        return ctx


class FakeTlsSock:
    """What `on_socket_open` gets from paho: only `getpeercert(binary_form=True)` is used."""

    def __init__(self, der: bytes | None):
        self.der = der

    def getpeercert(self, binary_form=False):
        return self.der if binary_form else {}
