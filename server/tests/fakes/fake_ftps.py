"""A fake Bambu printer FTPS server (tests only): implicit TLS from the first byte, user `bblp`, NLST but no MLSD,
and, like the real printer, data connections must resume the control connection's TLS session.

Built on pyftpdlib (pyOpenSSL underneath). The leaf comes from `fake_certs.Leaf`; no cert files are written."""
from __future__ import annotations

import threading
from pathlib import Path

from OpenSSL import SSL
from OpenSSL.SSL import _lib as _ssl_lib
from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import TLS_DTPHandler, TLS_FTPHandler
from pyftpdlib.servers import ThreadedFTPServer

from .fake_certs import Leaf


def _session_reused(conn: SSL.Connection) -> bool:
    return bool(_ssl_lib.SSL_session_reused(conn._ssl))


class FakeFtps:
    """`root` is the printer's SD card (`cache/` exists). `commands` records each control command name (never
    an argument); `data_conns` / `refused_data` count data connections with / without session reuse."""

    def __init__(self, leaf: Leaf, root: Path, code: str):
        self.root = Path(root)
        (self.root / "cache").mkdir(parents=True, exist_ok=True)
        self.commands: list[str] = []
        self.data_conns = 0
        self.refused_data = 0
        self.connections = 0
        fake = self

        ctx = SSL.Context(SSL.TLS_SERVER_METHOD)
        ctx.use_certificate(leaf.cert)
        ctx.use_privatekey(leaf.key)
        ctx.set_session_id(b"fake-bambu")
        ctx.set_session_cache_mode(SSL.SESS_CACHE_SERVER)

        class Dtp(TLS_DTPHandler):
            def handle_ssl_established(self):
                if not _session_reused(self.socket):   # vsftpd's require_ssl_reuse, as on the printer
                    fake.refused_data += 1
                    self.cmd_channel.respond("522 SSL connection failed: session reuse required")
                    self.close()
                    return
                fake.data_conns += 1
                super().handle_ssl_established()

        class Handler(TLS_FTPHandler):
            ssl_context = ctx
            dtp_handler = Dtp
            authorizer = DummyAuthorizer()
            banner = "fake Bambu FTPS ready"

            def handle(self):                      # implicit TLS: handshake first, banner afterwards
                fake.connections += 1
                self.secure_connection(self.ssl_context)

            def handle_ssl_established(self):
                TLS_FTPHandler.handle(self)

            def process_command(self, cmd, *args, **kwargs):
                fake.commands.append(cmd)
                if cmd in ("MLSD", "MLST"):
                    self.respond("500 Unknown command")
                    return
                super().process_command(cmd, *args, **kwargs)

        Handler.authorizer.add_user("bblp", code, str(self.root), perm="elradfmwMT")
        self.server = ThreadedFTPServer(("127.0.0.1", 0), Handler)
        self.server.max_cons = 16
        self.port = self.server.socket.getsockname()[1]
        self._thread = threading.Thread(target=self.server.serve_forever, kwargs={"timeout": 0.1},
                                        daemon=True)
        self._thread.start()

    def close(self):
        self.server.close_all()
        self._thread.join(timeout=5)
