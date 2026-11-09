"""The Overview tab: `filament-kit status` as rows.

    GET  overview           the rows with addresses and serials taken out
    POST overview {code}    the rows whole, and the station's pairing from the root helper (the service user can't read it)
    POST fields {code}      make the Spoolman fields (`ensure-fields`), the one fix on this tab so far
"""
from __future__ import annotations

from dataclasses import asdict

import anyio

from .. import __version__, config, redact, status, updates
from . import jobs


def _rows(page, station_pairing: str | None) -> list[dict]:
    def run() -> list[dict]:
        return [asdict(r) for r in status.collect(config.load(), page.client_factory, station_pairing)]
    return page.overview_cache.get(station_pairing, run)


def answer(page, whole: bool, station_pairing: str | None = None) -> dict:
    rows = _rows(page, station_pairing)
    if not whole:
        known = redact.known_values()
        rows = [{**r, "text": redact.text(r["text"], known), "fix": redact.text(r["fix"], known)} for r in rows]
    return {"rows": rows, "redacted": not whole, "version": __version__, "version_text": updates.version_text(),
            "update": updates.summary(),
            "job": jobs.view(0, with_text=False)}


def routes(page) -> list[tuple]:
    from ..setup_page import Refused

    async def read(request, body):
        return await anyio.to_thread.run_sync(answer, page, False)

    async def read_whole(request, body):
        r = await page._helper({"op": "station_pairing", "code": body["code"]})
        return await anyio.to_thread.run_sync(answer, page, True, r.get("state"))

    async def fields(request, body):
        from .. import cli

        def run() -> list[str]:
            try:
                return cli.Spoolman(config.load()["spoolman_url"]).ensure_fields()
            except cli.SpoolmanError as e:
                raise Refused(502, f"Spoolman: {e}") from None
        made = await anyio.to_thread.run_sync(run)
        page.overview_cache.clear()
        page.audit(request, "Spoolman fields made" if made else "Spoolman fields checked")
        return {"ok": True, "made": made}

    return [("/overview", page.guard(read), "GET"), ("/overview", page.guard(read_whole, write="helper"), "POST"),
            ("/fields", page.guard(fields, write=True), "POST")]
