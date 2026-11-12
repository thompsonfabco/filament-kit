"""FTPS client for a Bambu printer's SD card: implicit TLS on port 990, user `bblp`, password = the Access Code.

Ported from the owner's H2D usage tracker (`usage_tracker.py`, proven on hardware): the control connection is TLS
from the first byte (implicit FTPS), and the printer only accepts data connections that resume the control
connection's TLS session, so every data channel is wrapped with `session=<control session>`. The printer has no
MLSD; listings are NLST (names only).

The printer's leaf is checked against its pin (`tlspin`, trust on first use) on the live control socket, after
the handshake and before USER/PASS: a changed leaf raises `tlspin.CertChanged` and the Access Code is never sent.
(This is `tlspin.check` done on the very socket the code would go over, as `tlspin.connect` does for the camera.)

The Access Code is never logged and never part of a repr; ftplib debugging stays off."""
from __future__ import annotations

import ftplib
import io
import logging
import ssl

from . import registry, tlspin

log = logging.getLogger(__name__)

PORT = 990
USER = "bblp"
TIMEOUT = 20.0


class FtpsError(Exception):
    """The printer could not be reached, refused the login, or refused a command. The message never contains
    the Access Code."""


class _ImplicitFTP_TLS(ftplib.FTP_TLS):
    """FTP_TLS with implicit TLS (the socket is wrapped as soon as ftplib sets it) and data-channel session
    reuse (required by the printer)."""

    def __init__(self, *a, **k):
        self._sock = None
        super().__init__(*a, **k)

    @property
    def sock(self):
        return self._sock

    @sock.setter
    def sock(self, v):
        if v is not None and not isinstance(v, ssl.SSLSocket):
            v = self.context.wrap_socket(v)
        self._sock = v

    def ntransfercmd(self, cmd, rest=None):
        conn, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
        if self._prot_p:
            conn = self.context.wrap_socket(conn, session=self.sock.session)
            conn.unwrap = _quiet_unwrap(conn.unwrap)
        return conn, size


def _quiet_unwrap(unwrap):
    """A data channel the printer closes without sending anything (an empty listing) can fail its TLS shutdown
    (`SHUTDOWN_WHILE_IN_INIT`). The shutdown proves nothing: ftplib still reads the 226 on the control channel,
    which says whether the transfer worked."""
    def quiet():
        try:
            return unwrap()
        except (ssl.SSLError, OSError):
            return None
    return quiet


class Client:
    """`with Client(printer) as c: c.upload(path, data)` — one logged-in FTPS session to `printer`'s SD card.

    Raises `tlspin.CertChanged` on entry when the leaf is not the pinned one (nothing was sent), `FtpsError`
    for anything else."""

    def __init__(self, printer: registry.Printer, timeout: float = TIMEOUT):
        self.printer = printer
        self.timeout = timeout
        self._ftp: _ImplicitFTP_TLS | None = None

    def __repr__(self) -> str:
        return f"ftps.Client({self.printer.serial}, {self.printer.ip}:{PORT})"

    def __enter__(self) -> Client:
        ftp = _ImplicitFTP_TLS(context=tlspin.context())
        try:
            ftp.connect(self.printer.ip, PORT, timeout=self.timeout)
            tlspin.check_socket(self.printer, ftp.sock)       # before USER/PASS: no code to a changed leaf
            ftp.login(USER, self.printer.access_code)
            ftp.prot_p()
        except tlspin.CertChanged:
            ftp.close()
            raise
        except (ftplib.all_errors + (ValueError,)) as e:
            ftp.close()
            raise FtpsError(f"cannot open FTPS to printer {self.printer.serial}: {_why(e)}") from None
        self._ftp = ftp
        return self

    def __exit__(self, *exc) -> None:
        ftp, self._ftp = self._ftp, None
        if ftp is None:
            return
        try:
            ftp.quit()
        except ftplib.all_errors:
            pass
        finally:
            ftp.close()

    def _do(self, what: str, fn, *a):
        if self._ftp is None:
            raise FtpsError("FTPS client is not open")
        try:
            return fn(*a)
        except ftplib.all_errors as e:
            raise FtpsError(f"{what} on printer {self.printer.serial} failed: {_why(e)}") from None

    def upload(self, path: str, data: bytes) -> None:
        self._do(f"upload {path}", self._ftp.storbinary, f"STOR {path}", io.BytesIO(data))

    def download(self, path: str, limit: int | None = None) -> bytes:
        """The file's bytes; FtpsError when it is larger than `limit` bytes (None: no cap)."""
        buf = io.BytesIO()

        def take(chunk: bytes) -> None:
            if limit is not None and buf.tell() + len(chunk) > limit:
                raise _TooBig()
            buf.write(chunk)
        try:
            self._do(f"download {path}", self._ftp.retrbinary, f"RETR {path}", take)
        except _TooBig:
            raise FtpsError(f"download {path} on printer {self.printer.serial} failed: larger than {limit} bytes") from None
        return buf.getvalue()

    def nlst(self, d: str) -> list[str]:
        return self._do(f"list {d}", self._ftp.nlst, d)

    def delete(self, path: str) -> None:
        self._do(f"delete {path}", self._ftp.delete, path)


class _TooBig(Exception):
    pass


def _why(e: BaseException) -> str:
    # ftplib error texts are the server's reply lines; neither they nor socket errors carry the password
    return f"{type(e).__name__}: {e}".strip()
