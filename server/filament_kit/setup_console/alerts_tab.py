"""The Hub page's alerts (03 2.8, 4.2, 10.13, 15): the same answers as the kit routes of api.py, from the same code
(alerts_api), under /setup/api/. Nothing here decides what an alert says.

    GET  events [since|since_at, wait, kinds, limit, alert, client]   alerts_api.events_answer; `client` is the browser's id
    GET  alerts                      the eight alert types, last_spool_only and the numbers
    GET  spools/low                  {threshold_g, spools}, least filament first
    GET  storage-use                 {filesystems, items}
    POST settings/alerts {code, types, last_spool_only, running_low_g, storage_warn_percent}   saves; a refusal is 400
                                     with `error` and `errors` {field: text}
    POST alerts/test {client}        one test alert for that browser (no code: it stores nothing)
"""
from __future__ import annotations

import anyio

from .. import alerts_api, config, events
from ..spoolman import Spoolman, SpoolmanError


def routes(page) -> list[tuple]:
    from ..setup_page import Refused

    def number(q, name, kind=int):
        raw = q.get(name)
        if raw in (None, ""):
            return None
        try:
            return kind(raw)
        except ValueError:
            raise Refused(400, f"{name} must be a number", field=name) from None

    async def events_get(request, body):
        q = request.query_params
        since, since_at = number(q, "since"), q.get("since_at") or None
        if since is not None and since_at:
            raise Refused(400, "give since or since_at, not both")
        if since is not None and since < 0:
            raise Refused(400, "since must be 0 or more", field="since")
        if since_at:
            try:
                since_at = alerts_api.parse_time(since_at)
            except ValueError as e:
                raise Refused(400, str(e), field="since_at") from None
        client = (q.get("client") or "").strip()[:80]

        def run() -> dict:
            return alerts_api.events_answer(since=since, since_at=since_at, wait=min(number(q, "wait", float) or 0, 5),
                                            kinds=q.get("kinds") or None, limit=number(q, "limit") or events.LIMIT_DEFAULT,
                                            alert=q.get("alert", "").lower() in ("1", "true", "yes"),
                                            callers=[f"client:{client}"] if client else [])
        return await anyio.to_thread.run_sync(run)

    async def alerts_get(request, body):
        return await anyio.to_thread.run_sync(alerts_api.alerts_view)

    async def low(request, body):
        def run() -> dict:
            try:
                return alerts_api.low_view(Spoolman(config.load()["spoolman_url"]))
            except SpoolmanError as e:
                raise Refused(502, str(e)) from None
        return await anyio.to_thread.run_sync(run)

    async def storage_use(request, body):
        return await anyio.to_thread.run_sync(alerts_api.storage_view)

    async def save(request, body):
        change = {k: v for k, v in body.items() if k != "code"}
        try:
            view = await anyio.to_thread.run_sync(alerts_api.save, change)
        except alerts_api.AlertsRefused as e:
            raise Refused(400, str(e), **({"field": e.field, "errors": {e.field: str(e)}} if e.field else {})) from None
        page.overview_cache.clear()                    # the Storage and Alerts rows of the Checks read the settings
        page.audit(request, "alerts settings saved")
        return view

    async def test(request, body):
        client = str(body.get("client") or "").strip()[:80]
        if not client:
            raise Refused(400, "a test alert needs the browser id (client)", field="client")
        return {"ok": True, "test": await anyio.to_thread.run_sync(alerts_api.queue_test, f"client:{client}")}

    return [("/events", page.guard(events_get), "GET"), ("/alerts", page.guard(alerts_get), "GET"),
            ("/spools/low", page.guard(low), "GET"), ("/storage-use", page.guard(storage_use), "GET"),
            ("/settings/alerts", page.guard(save, write=True), "POST"), ("/alerts/test", page.guard(test), "POST")]
