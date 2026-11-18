"""The Analytics section (R84 section 5): filament used over the last months, from the printers' filament-used logs.

    GET  analytics?months=12&printer=<id>    as the kit route GET /api/analytics (R84 9.2): {months: [{month, grams, prints,
                                         unfinished_prints, unfinished_grams, logged_only_grams, no_weight_prints,
                                         by_printer: [{id, name, grams, prints}], by_material: [{material, grams}],
                                         top_material?}], insights: [{key, text}], notes: [text]}. `months` is 1 to 13
                                         (12 when left out), `printer` is one printer's id (all printers when left out).
                                         Looking needs no code: the answer holds no address, serial or secret
"""
from __future__ import annotations

import anyio

try:
    from .. import analytics as _analytics          # HD3's module; not in every build yet (see read())
except ImportError:
    _analytics = None

EMPTY = {"months": [], "insights": [], "notes": []}


def read(months: int, printer: str | None) -> dict:
    """The kit's analytics for `months` months (one printer when `printer`), in the shape of R84 9.2. Until the kit has
    its analytics module (HD3) the answer is the shape with nothing in it, which the page shows as "No usage yet"."""
    view = getattr(_analytics, "view", None)
    return view(months=months, printer=printer) if callable(view) else dict(EMPTY)


def routes(page) -> list[tuple]:
    from ..setup_page import Refused

    async def get(request, body):
        q = request.query_params
        try:
            months = int(q.get("months") or 12)
        except ValueError:
            months = 0
        if not 1 <= months <= 13:
            raise Refused(400, "months must be 1 to 13")
        printer = (q.get("printer") or "").strip() or None
        return await anyio.to_thread.run_sync(read, months, printer)

    return [("/analytics", page.guard(get), "GET")]
