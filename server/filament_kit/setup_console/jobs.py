"""The background jobs (setup_helper.JOBS) as the page sees them.

    GET  job?from=N             the log with addresses and serials taken out, from character N of that redacted text, and
                                whether it finished
    POST job/log {code, from}   the log whole, from byte N
    POST job {code, name}       start a job (the root helper checks the code and the guards)

The redaction runs on whole lines of the whole log, and `from` indexes its result. It must never run on a slice: its patterns
need the start of what they hide, so a caller choosing where a slice begins could read past them. A running job's unfinished last
line waits until it has ended.

The server restarts during apply, update and rollback; the log lives in /run, so the page comes back and reads on.
`version` tells it when the server it reloaded under is another release.
"""
from __future__ import annotations

import re
import subprocess
import threading
import time

import anyio

from .. import __version__, redact, setup_helper

MAX_LOG = 64 * 1024
STALE_AFTER = 65 * 60       # past the unit's TimeoutStartSec: a job with no last line is not running any more
GONE_AFTER = 15.0           # seconds a log may stand with no unit behind it (the unit writes it, then ends)
GONE_MEMO = 2.0
_FINISHED = re.compile(rb"^==> finished \(exit (-?[0-9]+)\)\s*$", re.M)
_memo_lock = threading.Lock()
_memo: tuple | None = None  # (the bytes it was made from, the redacted text): a page polls once a second
_gone_memo: tuple | None = None  # (when it was asked, the answer)


def stamp():
    """Changes when a job has written (see Cached)."""
    try:
        return setup_helper.job_log().stat().st_mtime
    except OSError:
        return None


def _redacted(data: bytes) -> str:
    """The whole of `data`, whole lines only, redacted."""
    global _memo
    with _memo_lock:
        if _memo is not None and _memo[0] == data:
            return _memo[1]
    text = redact.text(data.decode("utf-8", "replace"))
    with _memo_lock:
        _memo = (data, text)
    return text


def _unit_gone(age: float) -> bool:
    """A job with no last line whose unit has gone (killed hard, out of memory): nothing more will come. The check runs
    only while a log looks unfinished. Where it can't be told, the answer is no, and STALE_AFTER decides. Asking takes
    four systemctl runs and several places ask per poll, so an answer stands for GONE_MEMO seconds."""
    global _gone_memo
    if setup_helper._no_systemd() or age < GONE_AFTER:
        return False
    now = time.monotonic()
    if _gone_memo is not None and now - _gone_memo[0] < GONE_MEMO:
        return _gone_memo[1]
    try:
        gone = not setup_helper._applying()
    except (OSError, subprocess.SubprocessError):
        gone = False
    _gone_memo = (now, gone)
    return gone


def view(start: int, *, with_text: bool = True, whole: bool = False) -> dict:
    empty = {"seen": False, "name": None, "running": False, "exit": None, "lost": False, "text": "", "next": 0,
             "version": __version__, "redacted": not whole}
    path = setup_helper.job_log()
    try:
        data, age = path.read_bytes(), time.time() - path.stat().st_mtime
    except OSError:
        return empty
    ends = list(_FINISHED.finditer(data))
    done = bool(ends)
    lost = not done and (age > STALE_AFTER or _unit_gone(age))
    out = {"seen": True, "name": setup_helper.job_name_of(data.split(b"\n", 1)[0].decode("utf-8", "replace")),
           "running": not done and not lost, "exit": int(ends[-1].group(1)) if done else None, "lost": lost,
           "version": __version__, "redacted": not whole, "text": "", "next": 0}
    if not with_text:
        return out
    if whole:
        start = max(0, min(start, len(data)))
        chunk = data[start:start + MAX_LOG]
        return {**out, "text": chunk.decode("utf-8", "replace"), "next": start + len(chunk)}
    # an unfinished last line stays back until it has its end; a job that has ended has no more coming
    complete = data if done or lost else data[:data.rfind(b"\n") + 1]
    text = _redacted(complete)
    start = max(0, min(start, len(text)))
    chunk = text[start:start + MAX_LOG]
    return {**out, "text": chunk, "next": start + len(chunk)}


def _from(value) -> int:
    from ..setup_page import Refused
    try:
        return int(value)
    except (TypeError, ValueError):
        raise Refused(400, "from must be a number") from None


async def read(page, request, body):
    return await anyio.to_thread.run_sync(view, _from(request.query_params.get("from", "0")))


def routes(page) -> list[tuple]:
    from ..setup_page import Refused

    async def read_whole(request, body):
        start = _from(body.get("from", 0))
        return await anyio.to_thread.run_sync(lambda: view(start, whole=True))

    async def start(request, body):
        name = body.get("name")
        if not isinstance(name, str) or name not in setup_helper.JOBS:
            raise Refused(400, "job must be one of: " + ", ".join(setup_helper.JOBS))
        req = {"op": "job", "code": body["code"], "name": name}
        if name == "restore":           # the typed word, checked by the helper
            req["confirm"] = body.get("confirm")
        await page._helper(req)
        page.audit(request, f"job {name} started")
        return {"ok": True, "name": name}

    return [("/job", page.guard(lambda request, body: read(page, request, body)), "GET"),
            ("/job", page.guard(start, write="helper"), "POST"),
            ("/job/log", page.guard(read_whole, write=True), "POST")]
