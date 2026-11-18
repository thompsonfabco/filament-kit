"""A fake Hub for the command-line tests of the spool, catalog, device and printer slot commands (R83 10.5): answers
built from the contract's field lists (R83 section 10), no network. Example names only."""
from __future__ import annotations

import json

from filament_kit.web.slots import SlotError


class FakeApi:
    """`get/post/patch/delete(path, ...)` as the kit API client has them. `answers` maps "METHOD path" (the path
    with its query, exactly as called) to the answer: a dict, or a callable(body) -> dict, or a SlotError to raise.
    `calls` records (method, path, body)."""

    def __init__(self, answers: dict | None = None):
        self.answers = dict(answers or {})
        self.calls: list[tuple] = []

    def _call(self, method: str, path: str, body=None):
        self.calls.append((method, path, body))
        a = self.answers.get(f"{method} {path}")
        if a is None:
            raise SlotError(f"no answer for {method} {path}", code="not_found", http=404)
        if isinstance(a, Exception):
            raise a
        return a(body) if callable(a) else a

    def get(self, path):
        return self._call("GET", path)

    def post(self, path, body):
        return self._call("POST", path, body)

    def patch(self, path, body):
        return self._call("PATCH", path, body)

    def delete(self, path):
        return self._call("DELETE", path)

    def bodies(self, method: str, path: str) -> list:
        return [b for m, p, b in self.calls if (m, p) == (method, path)]


class FakePage:
    """`page(method, route, body=None)` as the Hub page's routes (R83 10.2) are called by the device commands."""

    def __init__(self, answers: dict):
        self.answers, self.calls = dict(answers), []

    def __call__(self, method, route, body=None):
        self.calls.append((method, route, body))
        a = self.answers.get(f"{method} {route}")
        if a is None:
            raise SlotError(f"no answer for {method} {route}", code="not_found", http=404)
        if isinstance(a, Exception):
            raise a
        return a(body) if callable(a) else a


def spool_view(n: int = 12, **kw) -> dict:
    """The spool view of R83 10 (`inventory.spool_view` plus `loaded` and `low`)."""
    view = {"id": n, "location": "Shelf A", "remaining_g": 640.0, "net_g": 1000.0, "tare_g": 180.0, "tag": None,
            "state": "opened", "filament_id": 3, "vendor": "Acme", "name": "PLA Red", "material": "PLA",
            "color_hex": "cc0000", "lot": None, "loaded": None, "low": False}
    return {**view, **kw}


def run_json(fn):
    """(exit code, the document) of `fn()` run as `--json` runs a command."""
    import io
    import sys
    from filament_kit import output
    output.configure(json=True)
    real, buf = sys.stdout, io.StringIO()
    sys.stdout = buf
    try:
        rc = output.run_json(fn)
    finally:
        sys.stdout = real
    return rc, json.loads(buf.getvalue())
