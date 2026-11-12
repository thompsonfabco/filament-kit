"""The Printer Station reader tokens (`FK_STATE/web/reader_tokens`, XML, sha256 of each token only): made, listed and
revoked by `filament-kit reader token | tokens | revoke` and the server's /setup page, checked by the web unit's
reader API (web/reader.py, which re-exports these). No `mcp` import here: the kit server uses it too."""
from __future__ import annotations

import datetime
import hashlib
import hmac
import logging
import os
import re
import secrets
import threading
import time
from pathlib import Path
from xml.sax.saxutils import quoteattr

import defusedxml.ElementTree as DET
from defusedxml import DefusedXmlException

from . import config, pairing

log = logging.getLogger(__name__)


def token_file() -> Path:
    return config.paths().state / "web" / "reader_tokens"


# ---------- tokens ----------

MAX_TOKENS = 64
MAX_FILE = 256 * 1024
TOKEN_ID = re.compile(r"r[0-9]{1,6}")
SHA256 = re.compile(r"[0-9a-f]{64}")


class TokenFileError(Exception):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _clean_name(name) -> str:
    n = " ".join(str(name or "").split())[:64]
    return n or "reader"


def parse_tokens(data: bytes, where: str = "reader_tokens") -> tuple[list[dict], int]:
    """(tokens [{id, name, sha256, created}], the next id number) of a reader_tokens file; TokenFileError lists
    every problem."""
    errors: list[str] = []
    try:
        root = DET.fromstring(data, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except (DET.ParseError, DefusedXmlException, ValueError) as e:
        raise TokenFileError([f"{where}: not valid XML: {e}"]) from None
    if root.tag != "reader-tokens":
        raise TokenFileError([f"{where}: the root element must be <reader-tokens>, not <{root.tag}>"])
    out, seen = [], set()
    nxt = root.get("next-id", "1")
    if not re.fullmatch(r"[1-9][0-9]{0,6}", nxt):
        errors.append(f"{where}: next-id must be a whole number from 1")
        nxt = "1"
    for i, el in enumerate(root):
        at = f"{where}: token {i + 1}"
        if el.tag != "token":
            errors.append(f"{at}: unknown element <{el.tag}>")
            continue
        tid, digest = el.get("id") or "", el.get("sha256") or ""
        if not TOKEN_ID.fullmatch(tid):
            errors.append(f"{at}: id must look like r1")
        elif tid in seen:
            errors.append(f"{at}: id {tid} appears twice")
        if not SHA256.fullmatch(digest):
            errors.append(f"{at}: sha256 must be 64 lowercase hex digits")
        seen.add(tid)
        out.append({"id": tid, "name": _clean_name(el.get("name")), "sha256": digest,
                    "created": (el.get("created") or "")[:40]})
    if len(out) > MAX_TOKENS:
        errors.append(f"{where}: more than {MAX_TOKENS} tokens")
    if errors:
        raise TokenFileError(errors)
    return out, max([int(nxt)] + [int(t["id"][1:]) + 1 for t in out])


def render_tokens(tokens: list[dict], next_id: int = 1) -> bytes:
    lines = ['<?xml version="1.0" encoding="utf-8"?>',
             "<!-- filament-kit reader tokens: sha256 of each token (the tokens themselves are not kept). "
             "Change with: filament-kit reader token | tokens | revoke -->",
             f'<reader-tokens version="1" next-id="{int(next_id)}">']
    for t in tokens:
        lines.append(f"  <token id={quoteattr(t['id'])} name={quoteattr(t['name'])} sha256={quoteattr(t['sha256'])}"
                     f" created={quoteattr(t['created'])}/>")
    lines.append("</reader-tokens>")
    return ("\n".join(lines) + "\n").encode("utf-8")


class TokenStore:
    """The reader tokens (hashed). `check` re-reads the file when it changed (the CLI writes it as root)."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else token_file()
        self._lock = threading.Lock()
        self._stamp: tuple | None = None
        self._tokens: list[dict] = []
        self.errors: list[str] = []

    def _read(self) -> tuple[list[dict], int]:
        """Strict read for a change: ([], 1) when there is no file, TokenFileError when it does not validate."""
        try:
            # never through a link: root (the CLI) writes this file in a folder the kit server's user owns
            with os.fdopen(os.open(self.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)), "rb") as f:
                data = f.read(MAX_FILE + 1)
        except FileNotFoundError:
            return [], 1
        except OSError as e:
            raise TokenFileError([f"{self.path}: cannot read: {e.strerror or e}"]) from None
        if len(data) > MAX_FILE:
            raise TokenFileError([f"{self.path}: larger than {MAX_FILE} bytes"])
        return parse_tokens(data, str(self.path))

    def _refresh(self) -> None:
        try:
            st = os.stat(self.path)
            stamp = (st.st_mtime_ns, st.st_size, st.st_ino)
        except FileNotFoundError:
            stamp = None
        except OSError:
            stamp = ("unreadable", time.time())
        if stamp == self._stamp and stamp is not None:
            return
        self._stamp = stamp
        try:
            self._tokens, self.errors = self._read()[0], []
        except TokenFileError as e:
            self._tokens, self.errors = [], e.errors        # fail closed
            log.error("reader tokens refused (no reader is accepted until fixed): %s", e)

    def check(self, token: str | None) -> bool:
        if not token or not isinstance(token, str):
            return False
        digest = _hash(token)
        with self._lock:
            self._refresh()
            hashes = [t["sha256"] for t in self._tokens]
        ok = False
        for h in hashes:            # compare against every one: no early exit
            ok |= hmac.compare_digest(digest, h)
        return ok

    def list(self) -> list[dict]:
        with self._lock:
            return [{k: t[k] for k in ("id", "name", "created")} for t in self._read()[0]]

    def _write(self, tokens: list[dict], next_id: int) -> None:
        pairing.make_state_dir(self.path.parent)
        pairing._write_atomic(self.path, render_tokens(tokens, next_id), 0o644, state_owned=True)

    def issue(self, name: str | None = None) -> tuple[str, str]:
        """A new token: (id, token). The token is returned once and only its sha256 is written."""
        with self._lock:
            tokens, n = self._read()
            if len(tokens) >= MAX_TOKENS:
                raise TokenFileError([f"already {MAX_TOKENS} reader tokens: revoke one first"])
            tok = secrets.token_urlsafe(32)
            tid = f"r{n}"
            now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
            tokens.append({"id": tid, "name": _clean_name(name), "sha256": _hash(tok), "created": now})
            self._write(tokens, n + 1)
            return tid, tok

    def revoke(self, ref: str) -> bool:
        """Remove the token with that id (or the only one with that name)."""
        with self._lock:
            tokens, n = self._read()
            hit = [t for t in tokens if t["id"] == ref] or [t for t in tokens if t["name"] == ref]
            if len(hit) != 1:
                return False
            self._write([t for t in tokens if t is not hit[0]], n)
            return True
