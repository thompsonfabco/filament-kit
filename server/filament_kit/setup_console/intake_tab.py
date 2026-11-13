"""The Intake tab: the intake history (intake_history.py) on the page, the same functions as the API and the CLI.

    GET  intake/history                     the records, newest first (keep, photo bytes, whether AI is on)
    GET  intake/history/{hid}               one record with its revisions
    GET  intake/history/{hid}/photos/{n}    a photo (image/jpeg)
    POST intake/history/{hid}/revise {code, note[, item]}            ask the AI again; writes nothing but the proposal
    POST intake/history/{hid}/apply {code, proposal | item + values[, spool_ids]}   write a change to Spoolman
    POST intake/history/{hid}/undo {code[, revision]}                undo the newest revision

Reads need no code (the home network, as the intake page); a change takes the code like every write on the page. A
revision is a label read: it counts against the daily read cap."""
from __future__ import annotations

import anyio
from starlette.responses import Response

from .. import config, intake, intake_history
from ..spoolman import Spoolman


def routes(page) -> list[tuple]:
    from ..setup_page import Refused

    w = lambda fn: page.guard(fn, write=True)  # noqa: E731
    g = page.guard

    def sm() -> Spoolman:
        return Spoolman(config.load()["spoolman_url"])

    def ai_on() -> bool:
        return intake.reading_on(config.load())

    def call(fn, *a, **k):
        try:
            return fn(*a, **k)
        except intake_history.HistoryError as e:
            raise Refused(e.status, str(e)) from None
        except intake.ReadError as e:
            raise Refused(502, str(e)) from None
        except intake.CapReached as e:
            raise Refused(429, str(e)) from None

    async def history(request, body):
        return await anyio.to_thread.run_sync(lambda: call(intake_history.list_records, ai_on()))

    async def one(request, body):
        return await anyio.to_thread.run_sync(lambda: call(intake_history.get, request.path_params["hid"]))

    async def photo(request, body):
        data = await anyio.to_thread.run_sync(lambda: call(intake_history.photo, request.path_params["hid"],
                                                           request.path_params["n"]))
        return Response(data, media_type="image/jpeg")

    async def revise(request, body):
        def run() -> dict:
            cfg = config.load()
            cap = intake.ReadCap(config.paths().state / "reads.json", cfg["reads_per_day"])

            def charge():                   # only a revision by Claude counts against the daily cap
                ticket = cap.take("setup page")
                return lambda: intake.refund_quietly(cap, ticket, "setup page")
            return call(intake_history.revise, sm(), request.path_params["hid"], body.get("note"),
                        body.get("item"), ai_on=ai_on(), charge=charge)
        out = await anyio.to_thread.run_sync(run)
        page.audit(request, f"intake record {request.path_params['hid']} revision asked of the AI")
        return out

    async def apply(request, body):
        out = await anyio.to_thread.run_sync(lambda: call(
            intake_history.apply, sm(), request.path_params["hid"], proposal=body.get("proposal"),
            item=body.get("item"), values=body.get("values") if body.get("proposal") is None else None,
            spool_ids=body.get("spool_ids"), device="setup page"))
        page.audit(request, f"intake record {request.path_params['hid']} revised")
        return out

    async def undo(request, body):
        out = await anyio.to_thread.run_sync(lambda: call(intake_history.undo, sm(), request.path_params["hid"],
                                                          body.get("revision")))
        page.audit(request, f"intake record {request.path_params['hid']} revision undone")
        return out

    return [("/intake/history", g(history), "GET"), ("/intake/history/{hid}", g(one), "GET"),
            ("/intake/history/{hid}/photos/{n:int}", g(photo), "GET"),
            ("/intake/history/{hid}/revise", w(revise), "POST"), ("/intake/history/{hid}/apply", w(apply), "POST"),
            ("/intake/history/{hid}/undo", w(undo), "POST")]
