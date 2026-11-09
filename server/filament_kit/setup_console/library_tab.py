"""The filament library on the Settings tab. Update and rollback are the jobs `library_update` and `library_rollback`.

    GET  library                   version, source, local additions, last check (redacted: no code was given)
    POST library/add {code, entry}  a local addition: the JSON text of one entry, checked as `library add` checks it
"""
from __future__ import annotations

import time

import anyio

from .. import library, redact
from ..profiles import builds


def _view() -> dict:
    st = library.status()
    known = redact.known_values()
    lc = st.get("last_check")
    if isinstance(lc, dict):
        at = lc.get("at")
        lc = {"at": time.strftime("%Y-%m-%d %H:%M", time.localtime(at)) if isinstance(at, (int, float)) else None,
              "ok": bool(lc.get("ok")),
              "error": redact.text(str(lc["error"]), known) if lc.get("error") else None}
    skipped = st.get("skipped")
    return {"version": st.get("version"), "source": st.get("source"), "local": st.get("local"),
            "url": redact.text(str(st.get("url") or ""), known), "last_check": lc,
            "skipped": redact.text(str(skipped), known) if skipped else None}


def routes(page) -> list[tuple]:
    from ..setup_page import Refused

    async def read(request, body):
        return await anyio.to_thread.run_sync(_view)

    async def add(request, body):
        text = body.get("entry")
        if not isinstance(text, str) or not text.strip():
            raise Refused(400, "paste the entry's JSON")
        data = text.encode("utf-8")
        if len(data) > library.LOCAL_LIMIT:
            raise Refused(400, f"entry not added: larger than {library.LOCAL_LIMIT // 1024} KiB")

        def run() -> tuple[dict, str]:
            try:
                entry, line = library.add_local(data)
            except ValueError as e:
                raise Refused(400, f"entry not added: {e}") from None
            builds.request_rebuild(f"local library addition {line}")
            return entry, line
        entry, line = await anyio.to_thread.run_sync(run)
        page.audit(request, f"library entry added (line {line})")
        return {"ok": True, "vendor": entry["vendor"], "product": entry["product"], "line": line}

    return [("/library", page.guard(read), "GET"), ("/library/add", page.guard(add, write=True), "POST")]
