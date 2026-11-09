"""The setup console's routes, by tab; setup_page.py keeps the page, its access rules and the routes it had before.

Each module gives `routes(page)`: `(path, handler, method)` entries under /setup/api, wrapped in the page's own guard.
What is viewable without the setup code here never shows the owner's addresses or serials (`redact`): with the code,
given in a POST body because the page never puts it in a URL, the same answer comes whole.
"""
from __future__ import annotations

import time

from . import jobs, logs_tab, modes, overview, presets_tab, printers_tab, trust_tab, updates_tab, webapp_tab


class Cached:
    """A short memory for an answer that runs commands or reads big files: anyone on the home network may ask for it.
    `stamp` (the job log's time) drops it at once when a job has changed what it says."""

    def __init__(self, ttl: float = 5.0):
        self.ttl, self.at, self.stamp, self.value = ttl, 0.0, None, None

    def get(self, stamp, fn):
        now = time.monotonic()
        if self.value is None or stamp != self.stamp or now - self.at >= self.ttl:
            self.value, self.at, self.stamp = fn(), now, stamp
        return self.value

    def clear(self) -> None:
        self.value = None


def routes(page) -> list[tuple]:
    page.overview_cache, page.updates_cache = Cached(), Cached()
    return (jobs.routes(page) + modes.routes(page) + overview.routes(page) + updates_tab.routes(page)
            + printers_tab.routes(page) + trust_tab.routes(page) + presets_tab.routes(page) + webapp_tab.routes(page) + logs_tab.routes(page))
