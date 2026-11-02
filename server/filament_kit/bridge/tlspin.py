"""Per-printer TLS pinning (trust on first use) for every printer port: MQTT 8883, RTSPS 322, JPEG 6000, FTPS 990.

Bambu printers present a self-signed leaf (the owner's H2D: one leaf on all four ports, `CN=<serial>`), so CA
verification is off and the leaf itself is the identity. The pin is the lowercase hex SHA-256 of the DER leaf
(the same format as `pairing.fingerprint`), stored in the registry as `cert_fp`. The first leaf seen is pinned,
but only when its CN, if it has one, is the printer's serial; every later connection must present the pinned
leaf, otherwise `CertChanged` and the caller must not send the Access Code. Re-adding the printer with its code
clears the pin (`registry.set_code`, CLI add).

Logs carry the serial and fingerprints only, never the Access Code."""
from __future__ import annotations

import hashlib
import logging
import socket
import ssl

from cryptography import x509
from cryptography.x509.oid import NameOID

from . import registry

log = logging.getLogger(__name__)


class CertChanged(Exception):
    """The printer presented a leaf other than its pin (`expected`), or, on first use, a leaf naming another
    printer (`expected` == ""). `actual` is the presented leaf's fingerprint."""

    def __init__(self, expected: str, actual: str, reason: str = ""):
        self.expected, self.actual = expected, actual
        super().__init__(reason or f"the printer's certificate changed (pinned {expected[:16]}…, "
                                   f"presented {actual[:16]}…)")


def context() -> ssl.SSLContext:
    """TLS client context without CA or hostname verification. Only ever used together with `check` /
    `check_socket`: the pin is the verification."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def fingerprint(der: bytes) -> str:
    return hashlib.sha256(der).hexdigest()


def _cn(der: bytes) -> str | None:
    try:
        attrs = x509.load_der_x509_certificate(der).subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    except ValueError:
        return None
    return str(attrs[0].value) if attrs else None


def _leaf_der(ip: str, port: int, timeout: float) -> bytes:
    with socket.create_connection((ip, port), timeout=timeout) as raw:
        with context().wrap_socket(raw) as s:
            der = s.getpeercert(binary_form=True)
    if not der:
        raise ssl.SSLError(f"{ip}:{port} presented no certificate")
    return der


def leaf_fp(ip: str, port: int, timeout: float = 5) -> str:
    """Fingerprint of the leaf `ip:port` presents (a handshake only, nothing is sent). Raises OSError."""
    return fingerprint(_leaf_der(ip, port, timeout))


def check_der(printer: registry.Printer, der: bytes, port: int | None = None) -> str:
    """Verify a presented leaf against `printer`'s pin, pinning it on first use. Updates `printer.cert_fp` and
    returns the fingerprint; raises CertChanged."""
    fp = fingerprint(der)
    where = f"printer {printer.serial} ({printer.ip}{f':{port}' if port else ''})"
    if printer.cert_fp:
        if fp != printer.cert_fp:
            log.warning("%s: certificate changed: pinned %s, presented %s; not sending the Access Code",
                        where, printer.cert_fp, fp)
            raise CertChanged(printer.cert_fp, fp)
        return fp
    cn = _cn(der)
    if cn is not None and cn != printer.serial:
        log.warning("%s: certificate %s is for %r, not this printer; not pinned, not sending the Access Code",
                    where, fp, cn)
        raise CertChanged("", fp, "the printer's certificate names another printer")
    stored = registry.pin(printer.serial, fp)
    if stored != fp:  # someone else pinned another leaf first
        log.warning("%s: certificate changed: pinned %s, presented %s; not sending the Access Code",
                    where, stored, fp)
        printer.cert_fp = stored
        raise CertChanged(stored, fp)
    printer.cert_fp = fp
    log.info("%s: pinned certificate %s", where, fp)
    return fp


def check_socket(printer: registry.Printer, sock) -> str:
    """`check_der` on the leaf of an established TLS socket (the very socket the Access Code would go over)."""
    der = sock.getpeercert(binary_form=True)
    if not der:
        raise ssl.SSLError("the printer presented no certificate")
    try:
        port = sock.getpeername()[1]
    except (OSError, AttributeError, IndexError, TypeError):
        port = None
    return check_der(printer, der, port)


def check(printer: registry.Printer, port: int, timeout: float = 5) -> None:
    """Handshake with `printer.ip:port` and verify its leaf (pins on first use). Raises CertChanged, or OSError
    when the printer cannot be reached. A separate connection: prefer `connect` / `check_socket` when the
    Access Code goes over a socket you open yourself."""
    check_der(printer, _leaf_der(printer.ip, port, timeout), port)


def connect(printer: registry.Printer, port: int, timeout: float = 10) -> ssl.SSLSocket:
    """A TLS socket to `printer.ip:port` whose leaf already passed the pin check. Raises CertChanged / OSError."""
    raw = socket.create_connection((printer.ip, port), timeout=timeout)
    try:
        s = context().wrap_socket(raw)
    except BaseException:
        raw.close()
        raise
    try:
        check_socket(printer, s)
    except BaseException:
        s.close()
        raise
    return s
