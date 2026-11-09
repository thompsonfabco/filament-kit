"""The Logs tab. The journal is root's, so the helper reads it; logs hold addresses and serials, so it takes the code.

    GET  logs/units                   the services of the modules that are on (names only)
    POST logs {code, unit, lines}     the last lines of one of them
"""
from __future__ import annotations

import anyio

from .. import config, setup_helper


def routes(page) -> list[tuple]:
    async def units(request, body):
        return {"units": await anyio.to_thread.run_sync(lambda: setup_helper.journal_units(config.load()))}

    async def read(request, body):
        r = await page._helper({"op": "journal", "code": body["code"], "unit": body.get("unit"),
                                "lines": body.get("lines", 100)})
        page.audit(request, f"log of {r['unit']} read")
        return {"unit": r["unit"], "text": r["text"], "truncated": r["truncated"]}

    return [("/logs/units", page.guard(units), "GET"), ("/logs", page.guard(read, write="helper"), "POST")]
