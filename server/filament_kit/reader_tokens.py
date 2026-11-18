"""The Printer Station reader tokens (`FK_STATE/web/reader_tokens`, XML, sha256 of each token only): made, listed and
revoked by `spoolwarden reader token | tokens | revoke` and the server's /setup page, checked by the web unit's
reader API (web/reader.py, which re-exports these). No `mcp` import here: the kit server uses it too.

What a reader tells us (R83 s9.2): the build number in its `X-Reader-Build` header and when it last called. The web
unit (the only one a reader talks to) hands both to the Hub (`SeenBuffer`, `flush`; the Hub's `record_seen` and
`SeenStore`, see below). `offered_build` is the firmware the kit serves to readers (reader-fw/manifest.json)."""
from __future__ import annotations

import datetime
import hashlib
import hmac
import json
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
             "Change with: spoolwarden reader token | tokens | revoke -->",
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

    def identify(self, token: str | None) -> str | None:
        """The id of the token (`r1`), or None when it is none of ours. As `check`, compares against every one."""
        if not token or not isinstance(token, str):
            return None
        digest = _hash(token)
        with self._lock:
            self._refresh()
            rows = [(t["id"], t["sha256"]) for t in self._tokens]
        found = None
        for tid, h in rows:
            if hmac.compare_digest(digest, h):
                found = tid
        return found

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


# ---------- what each reader tells us: its build and when it last called ----------
#
# A reader calls the web unit, which cannot write the Hub's state. So the web unit keeps the newest value per reader in
# memory (`SeenBuffer`) and hands it to the Hub on a web-only kit route, POST /api/readers/web/seen
# {readers: [{id, build?, seen_at}]} (`post_seen`, `flush`); the Hub's handler is `record_seen`, which keeps the newest in
# `SeenStore`, the Hub's own file (`reader-seen`, XML, in the state folder).

SEEN_FILE = "reader-seen"
SEEN_ROUTE = "/api/readers/web/seen"
SEEN_EVERY = 60.0            # seconds: a reader is handed over at most this often (at once when its build changes)
BUILD = re.compile(r"[0-9]{1,12}")


def seen_file() -> Path:
    return config.paths().state / SEEN_FILE


def parse_build(value) -> int | None:
    """The reader's build from `X-Reader-Build` (digits only, as the firmware's build stamp, a Unix time); an int of
    that size is accepted too."""
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str) or not BUILD.fullmatch(value.strip()):
        return None
    n = int(value.strip())
    return n if n > 0 else None


def _utc(t: float) -> str:
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).isoformat(timespec="seconds")


def parse_time(text) -> datetime.datetime | None:
    """An ISO 8601 time with an offset (UTC when it has none) as an aware datetime, else None."""
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        d = datetime.datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)


class SeenBuffer:
    """The web unit's side, in memory only: the newest {build, seen_at} per reader and what was last handed over.
    `note` after each reader call; `due` is what to send now (a changed build at once, otherwise a reader at most every
    SEEN_EVERY seconds); `sent` after the Hub answered. A call that failed leaves everything due for the next try."""

    def __init__(self, clock=time.time):
        self.clock = clock
        self._lock = threading.Lock()
        self._rows: dict[str, dict] = {}

    def note(self, token_id: str, build: int | None) -> None:
        if not TOKEN_ID.fullmatch(token_id or ""):
            return
        now = self.clock()
        with self._lock:
            r = self._rows.setdefault(token_id, {"build": None, "at": now, "sent_build": None, "sent_at": None,
                                                 "dirty": True, "due_at": None})
            if build is not None:
                r["build"] = build
            r["at"], r["dirty"] = now, True

    def due(self) -> list[dict]:
        now = self.clock()
        with self._lock:
            out = []
            for tid, r in sorted(self._rows.items()):
                changed = r["build"] is not None and r["build"] != r["sent_build"]
                if r["dirty"] and (changed or r["sent_at"] is None or now - r["sent_at"] >= SEEN_EVERY):
                    r["due_at"] = r["at"]
                    out.append({"id": tid, **({"build": r["build"]} if r["build"] is not None else {}),
                                "seen_at": _utc(r["at"])})
            return out

    def sent(self, batch: list[dict]) -> None:
        now = self.clock()
        with self._lock:
            for b in batch:
                r = self._rows.get(b["id"])
                if r is None:
                    continue
                r["sent_build"], r["sent_at"] = b.get("build"), now
                r["dirty"] = r["at"] > (r["due_at"] or 0)        # a call that came after the batch was made is still due


def post_seen(kit, readers: list[dict]) -> dict:
    """Hand the readers' {id, build?, seen_at} to the Hub (`kit`: the web unit's KitApi). Raises what the client raises."""
    return kit.post(SEEN_ROUTE, {"readers": readers})


def flush(buffer: SeenBuffer, kit) -> bool:
    """Send what is due. True when something was handed over. Never raises: a Hub that does not answer leaves the
    newest values in `buffer` for the next reader call."""
    batch = buffer.due()
    if not batch:
        return False
    try:
        post_seen(kit, batch)
    except Exception as e:  # noqa: BLE001 - the reader's own request must not fail for this
        log.info("reader-seen: the Hub did not take it (%s); kept for the next call", type(e).__name__)
        return False
    buffer.sent(batch)
    return True


class SeenStore:
    """{token id: {build, last_seen}} of the readers: the Hub's own file, XML. `merge` is the Hub's (`record_seen`);
    `read` is any reader of the file. Never raises for a file that is missing, unreadable or damaged: nothing is
    known then (a reader's build is "not known" and nothing breaks)."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else seen_file()
        self._lock = threading.Lock()

    def read(self) -> dict[str, dict]:
        try:
            with os.fdopen(os.open(self.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)), "rb") as f:
                data = f.read(MAX_FILE + 1)
            if len(data) > MAX_FILE:
                return {}
            root = DET.fromstring(data, forbid_dtd=True, forbid_entities=True, forbid_external=True)
        except (OSError, DET.ParseError, DefusedXmlException, ValueError):
            return {}
        out: dict[str, dict] = {}
        if root.tag != "reader-seen":
            return out
        for el in list(root)[:MAX_TOKENS]:
            tid = el.get("id") or ""
            if el.tag != "reader" or not TOKEN_ID.fullmatch(tid):
                continue
            b = el.get("build") or ""
            out[tid] = {"build": int(b) if BUILD.fullmatch(b) else None, "last_seen": (el.get("last-seen") or "")[:40]}
        return out

    @staticmethod
    def _render(rows: dict[str, dict]) -> bytes:
        lines = ['<?xml version="1.0" encoding="utf-8"?>',
                 "<!-- filament-kit: the build and last call of each Tag Reader (handed over by the web unit) -->",
                 '<reader-seen version="1">']
        for tid in sorted(rows, key=lambda t: int(t[1:])):
            r = rows[tid]
            build = f" build={quoteattr(str(r['build']))}" if r["build"] is not None else ""
            lines.append(f"  <reader id={quoteattr(tid)}{build} last-seen={quoteattr(r['last_seen'])}/>")
        lines.append("</reader-seen>")
        return ("\n".join(lines) + "\n").encode("utf-8")

    def merge(self, updates: dict[str, dict], known: set[str] | None = None) -> None:
        """Keep the newest `last_seen` per id (and its build; an update with no build keeps the one known). Ids not in
        `known` (revoked tokens) are dropped. OSError when the file cannot be written."""
        with self._lock:
            rows = self.read()
            for tid, u in updates.items():
                old = rows.get(tid)
                new_t = parse_time(u["last_seen"])
                old_t = parse_time(old["last_seen"]) if old else None
                if old is None or old_t is None or new_t >= old_t:
                    rows[tid] = {"build": u["build"] if u["build"] is not None else (old or {}).get("build"),
                                 "last_seen": u["last_seen"]}
                elif old["build"] is None and u["build"] is not None:
                    rows[tid]["build"] = u["build"]
            if known is not None:
                rows = {t: r for t, r in rows.items() if t in known}
            pairing.make_state_dir(self.path.parent)
            pairing._write_atomic(self.path, self._render(rows), 0o644, state_owned=True)


class SeenError(ValueError):
    """The body of the seen route is not {readers: [{id, build?, seen_at}]} (the route answers 400 with the text)."""


def record_seen(readers, store: "TokenStore | None" = None, seen: "SeenStore | None" = None,
                now: float | None = None) -> dict:
    """The Hub's handler of POST /api/readers/web/seen: keep the newest build and last seen of each reader named.
    {"ok": True}, plus `ignored` (the ids that are no reader token of this Hub) when there are any. SeenError for a
    body that is not a list of {id, build?, seen_at} (at most MAX_TOKENS), or a time more than a day ahead; nothing is
    kept then. Ids are checked against the token list, so a revoked reader is ignored."""
    if not isinstance(readers, list) or len(readers) > MAX_TOKENS:
        raise SeenError(f"readers must be a list of at most {MAX_TOKENS} entries")
    horizon = (now if now is not None else time.time()) + 86400
    updates, ignored = {}, []
    for r in readers:
        if not isinstance(r, dict) or not isinstance(r.get("id"), str) or not TOKEN_ID.fullmatch(r["id"]):
            raise SeenError("each reader needs an id like r1")
        at = parse_time(r.get("seen_at"))
        if at is None or at.timestamp() > horizon:
            raise SeenError(f"{r['id']}: seen_at must be a time with an offset, not in the future")
        build = parse_build(r["build"]) if r.get("build") is not None else None
        if r.get("build") is not None and build is None:
            raise SeenError(f"{r['id']}: build must be a whole number")
        prev = updates.get(r["id"])
        if prev is None or at >= parse_time(prev["last_seen"]):
            updates[r["id"]] = {"build": build if build is not None else (prev or {}).get("build"),
                                "last_seen": at.isoformat(timespec="seconds")}
    ids = {t["id"] for t in (store or TokenStore()).list()}
    for tid in list(updates):
        if tid not in ids:
            ignored.append(tid)
            del updates[tid]
    if updates:
        (seen or SeenStore()).merge(updates, known=ids)
    return {"ok": True, **({"ignored": ignored} if ignored else {})}


def offered_build() -> int | None:
    """The firmware build the kit serves to readers (reader-fw/manifest.json, written by `ota_publish.py`), or None
    when none is published or the file is not readable."""
    try:
        with open(config.paths().state / "reader-fw" / "manifest.json", "rb") as f:
            data = json.loads(f.read(MAX_FILE).decode("utf-8"))
    except (OSError, ValueError, RecursionError):
        return None
    b = data.get("build") if isinstance(data, dict) else None
    return b if isinstance(b, int) and not isinstance(b, bool) and b > 0 else None


def readers(store: "TokenStore | None" = None, seen: "SeenStore | None" = None) -> list[dict]:
    """The paired Tag Readers as Devices shows them: [{id, name, created, build, last_seen, out_of_date}]. `build` and
    `last_seen` are None for a reader that never called (or whose record this process cannot read); `out_of_date`
    only when its build is known and lower than `offered_build()`. TokenFileError when the token file is damaged."""
    rows = (store or TokenStore()).list()
    marks = (seen or SeenStore()).read()
    offered = offered_build()
    out = []
    for r in rows:
        m = marks.get(r["id"]) or {}
        build = m.get("build")
        out.append({**r, "build": build, "last_seen": m.get("last_seen") or None,
                    "out_of_date": bool(build is not None and offered is not None and build < offered)})
    return out
