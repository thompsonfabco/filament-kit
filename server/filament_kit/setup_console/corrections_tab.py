"""The corrections waiting to be shared (Share corrections), on the Hub page's Label Reader group: a thin pass-through
to the reader's queue (reader_corrections.py). Reads need no code; Remove and Send now take it.

    GET  label-reader/corrections               {opt_in, endpoint_configured, count, bytes, bundle_mb, capabilities, entries}
    GET  label-reader/corrections/package       the exact zip Send now would send (attachment, size-capped)
    POST label-reader/corrections/{id}/remove {code}   take one out of the list; nothing is sent
    POST label-reader/corrections/remove-all {code}    take all out; {removed}
    POST label-reader/corrections/send {code}   start the job `corrections_send` (the job strip follows it; the
                                                reader does the upload) after a look that something waits

A refusal is `{error: <the Hub's text>, reason: <code>}` (reader_corrections.CorrectionsError)."""
from __future__ import annotations

import anyio
from starlette.responses import Response

from .. import config, reader_corrections


def routes(page) -> list[tuple]:
    from ..setup_page import Refused

    def call(fn, *a):
        try:
            return fn(config.load(), *a)
        except reader_corrections.CorrectionsError as e:
            raise Refused(e.status, str(e), reason=e.code, **e.extra) from None

    async def listing(request, body):
        return await anyio.to_thread.run_sync(lambda: call(reader_corrections.waiting))

    async def package(request, body):
        data, name = await anyio.to_thread.run_sync(lambda: call(reader_corrections.package))
        return Response(data, media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    async def remove(request, body):
        eid = request.path_params["cid"]
        out = await anyio.to_thread.run_sync(lambda: call(reader_corrections.remove, eid))
        page.audit(request, "a correction waiting was removed")
        return out

    async def remove_all(request, body):
        out = await anyio.to_thread.run_sync(lambda: call(reader_corrections.remove_all))
        page.audit(request, f"{out['removed']} corrections waiting were removed")
        return out

    async def send(request, body):
        waiting = await anyio.to_thread.run_sync(lambda: call(reader_corrections.waiting))
        if not waiting["count"]:
            raise Refused(409, reader_corrections.EMPTY, reason="empty")
        await page._helper({"op": "job", "code": body["code"], "name": "corrections_send"})
        page.audit(request, "job corrections_send started")
        return {"ok": True, "name": "corrections_send", "count": waiting["count"]}

    return [("/label-reader/corrections", page.guard(listing), "GET"),
            ("/label-reader/corrections/package", page.guard(package), "GET"),
            ("/label-reader/corrections/remove-all", page.guard(remove_all, write=True), "POST"),
            ("/label-reader/corrections/send", page.guard(send, write="helper"), "POST"),
            ("/label-reader/corrections/{cid}/remove", page.guard(remove, write=True), "POST")]
