"""The Updates tab.

    GET updates     updates.view: the installed version, what the last check found, what would be refused now

Check now, Update and Roll back are jobs (POST job, jobs.py). The kit server's unit does not reach GitHub, so the check
runs in the job unit too and leaves what it found where this route reads it.
"""
from __future__ import annotations

import anyio

from .. import config, updates
from . import jobs


def routes(page) -> list[tuple]:
    async def read(request, body):
        def run() -> dict:
            return page.updates_cache.get(jobs.stamp(), lambda: updates.view(config.load()))
        return await anyio.to_thread.run_sync(run)

    return [("/updates", page.guard(read), "GET")]
