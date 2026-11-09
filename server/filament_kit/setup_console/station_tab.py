"""Stations asking to pair, on the Devices tab (station_requests.py has the protocol). Listing shows addresses, so it
takes the code or a trusted computer, as does each answer.

    POST stations/requests {code}                 the waiting requests, each with its comparison code
    POST stations/requests/{id}/pair {code}       pair it: the station picks its token up at its next poll
    POST stations/requests/{id}/refuse {code}
"""
from __future__ import annotations

import anyio

from .. import station_requests


def routes(page) -> list[tuple]:
    from ..setup_page import Refused

    w = lambda fn: page.guard(fn, write=True)  # noqa: E731

    async def listing(request, body):
        try:
            return {"requests": await anyio.to_thread.run_sync(station_requests.pending)}
        except OSError as e:
            raise Refused(503, f"cannot read the server certificate ({type(e).__name__})") from None

    def answer(approve: bool):
        async def route(request, body):
            rid = request.path_params["id"]
            try:
                r = await anyio.to_thread.run_sync(station_requests.decide, rid, approve)
            except station_requests.RequestError as e:
                raise Refused(e.status, str(e)) from None
            page.audit(request, f"station pairing request {rid} {'approved' if approve else 'refused'}")
            return {"ok": True, **r}
        return route

    return [("/stations/requests", w(listing), "POST"),
            ("/stations/requests/{id}/pair", w(answer(True)), "POST"),
            ("/stations/requests/{id}/refuse", w(answer(False)), "POST")]
