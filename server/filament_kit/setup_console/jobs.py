"""The background jobs (setup_helper.JOBS) as the page sees them.

    GET  job?from=N             the log from byte N with addresses and serials taken out, and whether it finished
    POST job/log {code, from}   the same log whole
    POST job {code, name}       start a job (the root helper checks the code and the guards)

The server restarts during apply, update and rollback; the log lives in /run, so the page comes back and reads on.
`version` tells it when the server it reloaded under is another release.
"""
from __future__ import annotations

import re
import time

import anyio

from .. import __version__, redact, setup_helper

MAX_LOG = 64 * 1024
STALE_AFTER = 65 * 60       # past the unit's TimeoutStartSec: a job with no last line is not running any more
_FINISHED = re.compile(rb"^==> finished \(exit (-?[0-9]+)\)\s*$", re.M)


def stamp():
    """Changes when a job has written (see Cached)."""
    try:
        return setup_helper.job_log().stat().st_mtime
    except OSError:
        return None


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
    lost = not done and age > STALE_AFTER
    start = max(0, min(start, len(data)))
    chunk = data[start:start + MAX_LOG] if with_text else b""
    # whole lines only, unless the job has ended: an address cut in two would pass the redaction
    if chunk and not done and not chunk.endswith(b"\n"):
        last = chunk.rfind(b"\n")
        if last >= 0:
            chunk = chunk[:last + 1]
        elif len(chunk) < MAX_LOG:
            chunk = b""
    text = chunk.decode("utf-8", "replace")
    return {"seen": True, "name": setup_helper.job_name_of(data.split(b"\n", 1)[0].decode("utf-8", "replace")),
            "running": not done and not lost, "exit": int(ends[-1].group(1)) if done else None, "lost": lost,
            "text": text if whole else redact.text(text), "next": start + len(chunk),
            "version": __version__, "redacted": not whole}


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
        await page._helper({"op": "job", "code": body["code"], "name": name})
        page.audit(request, f"job {name} started")
        return {"ok": True, "name": name}

    return [("/job", page.guard(lambda request, body: read(page, request, body)), "GET"),
            ("/job", page.guard(start, write="helper"), "POST"),
            ("/job/log", page.guard(read_whole, write=True), "POST")]
