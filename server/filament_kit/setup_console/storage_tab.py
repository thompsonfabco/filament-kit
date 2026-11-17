"""The Storage locations group of the Settings tab (R79 section 3 and 4): one list, saved whole.

    GET  settings/storage                the saved list as GET api/storage gives it (locations with how full, the order a
                                         new spool goes by material, notices), no code
    POST settings/storage/preview {locations}   the same for a list not saved yet, plus `errors` (a list of
                                         {row, id, name, field, error, fix}; empty = it could be saved) and `renames`:
                                         the panel "Where a new spool goes" is built from it. Writes nothing, no code
    POST settings/storage {code, locations[, dry_run]}   save the whole list (ids kept for existing rows, none for new
                                         ones). Answers {ok, saved: true, text, updated, locations, ...} or, when more
                                         than 20 spools are renamed, {ok, saved: false, job: {steps}}. A refusal is 400
                                         with `error` (the first line) and `errors` per row and field; 409 while a rename
                                         job runs. `dry_run: true` answers as the preview, with the code checked
    GET  settings/storage/job            the rename job: {state: none|running|done|failed, step: {index, count, text},
                                         progress, text, error}
"""
from __future__ import annotations

import anyio

from .. import config, storage, storage_api
from ..spoolman import Spoolman, SpoolmanError


def routes(page) -> list[tuple]:
    from ..setup_page import Refused

    def sm() -> Spoolman:
        return Spoolman(config.load()["spoolman_url"])

    def run(fn, *a):
        try:
            return fn(*a)
        except storage_api.StorageRefused as e:
            raise Refused(e.status, str(e), errors=e.errors) from None
        except storage.StorageError as e:
            raise Refused(500, str(e).replace("\n", " ")) from None
        except SpoolmanError as e:
            raise Refused(502, "Spoolman is not reachable" if e.status is None else str(e)) from None

    def read() -> dict:
        return storage_api.current_view(sm())

    async def get(request, body):
        return await anyio.to_thread.run_sync(run, read)

    async def preview(request, body):
        return await anyio.to_thread.run_sync(run, lambda b: storage_api.preview(sm(), b), body)

    async def write(request, body):
        if body.get("dry_run") is True:
            return await anyio.to_thread.run_sync(run, lambda b: storage_api.preview(sm(), b), body)
        r = await anyio.to_thread.run_sync(run, lambda b: storage_api.save(sm(), b), body)
        page.audit(request, "storage locations saved" if r["saved"] else "storage locations saving (rename job)")
        return r

    async def job(request, body):
        return storage_api.job_state()

    return [("/settings/storage", page.guard(get), "GET"),
            ("/settings/storage/preview", page.guard(preview, write=False), "POST"),
            ("/settings/storage/job", page.guard(job), "GET"),
            ("/settings/storage", page.guard(write, write=True), "POST")]
