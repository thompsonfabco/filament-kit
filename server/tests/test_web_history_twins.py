"""The web twins of history and data (R84 9.4, HD8): the activity list, Undo, the health history, analytics and the three downloads of a
phone; the printers' usage by month. No network, no Hub: the kit API is a fake that records what it was asked."""
from __future__ import annotations

import io
import json
from urllib.parse import parse_qs, urlparse

import pytest

pytest.importorskip("mcp")

from filament_kit.web.slots import SlotError  # noqa: E402
from test_web_printers import AWAY, SERIAL, FakeKit, H, env, make_app, signed  # noqa: E402,F401

CSV = b"id,name\n1,PLA\n"


class HistoryKit(FakeKit):
    def __init__(self):
        super().__init__()
        self.undo_refusal: SlotError | None = None

    def get(self, path):
        if path.startswith("/api/events?activity=1"):
            self._check()
            self.calls.append(("GET", path))
            return {"events": [{"id": 9, "kind": "spool.moved", "text": "Moved", "undo": {"possible": True}, "undone": False}], "next": 9, "oldest": 1}
        if path.startswith(("/api/health", "/api/analytics")):
            self._check()
            self.calls.append(("GET", path))
            return {"checks": [], "changes": [], "months": []}
        return super().get(path)

    def post(self, path, body):
        if path.startswith("/api/events/") and path.endswith("/undo"):
            self._check()
            self.calls.append(("POST", path, body))
            if self.undo_refusal:
                raise self.undo_refusal
            return {"undone": True, "event": {"id": 10}}
        return super().post(path, body)

    def raw(self, path):
        self._check()
        self.calls.append(("RAW", path))
        return 200, "text/csv", io.BytesIO(CSV)


def called(kit):
    return [c[1] for c in kit.calls if c[0] in ("GET", "RAW")]


def test_activity_passes_the_hubs_parameters_only_and_caps_the_limit(env):
    kit = HistoryKit()
    c = signed(make_app(env, kit))
    r = c.get("/intake/api/activity?subject=spool:5&limit=10&junk=1&actor=device")
    assert r.status_code == 200 and r.json()["events"][0]["undo"]["possible"] is True
    q = {k: v[0] for k, v in parse_qs(urlparse(called(kit)[-1]).query).items()}
    assert q == {"activity": "1", "subject": "spool:5", "actor": "device", "limit": "10"}
    c.get("/intake/api/activity?limit=5000")
    assert parse_qs(urlparse(called(kit)[-1]).query)["limit"] == ["200"]
    assert c.get("/intake/api/activity?limit=ten").status_code == 400


def test_undo_passes_on_and_keeps_the_hubs_refusal_code(env):
    kit = HistoryKit()
    c = signed(make_app(env, kit))
    r = c.post("/intake/api/events/412/undo", headers=H)
    assert r.status_code == 200 and r.json()["undone"] is True and ("POST", "/api/events/412/undo", {}) in kit.calls
    kit.undo_refusal = SlotError("This changed again since, so it cannot be undone.", code="changed_since", http=409)
    r = c.post("/intake/api/events/412/undo", headers=H)
    assert r.status_code == 409 and r.json() == {"error": "This changed again since, so it cannot be undone.", "code": "changed_since"}
    assert c.post("/intake/api/events/a%20b/undo", headers=H).status_code == 400            # not an event id
    kit.undo_refusal = SlotError("kit unreachable", code="unreachable")
    assert c.post("/intake/api/events/412/undo", headers=H).status_code == 502
    kit.down = True
    assert c.post("/intake/api/events/412/undo", headers=H).status_code == 502


def test_health_and_analytics_check_their_values(env):
    kit = HistoryKit()
    c = signed(make_app(env, kit))
    assert c.get("/intake/api/health").status_code == 200 and called(kit)[-1] == "/api/health?days=7"
    assert c.get("/intake/api/health?days=30").status_code == 200 and called(kit)[-1] == "/api/health?days=30"
    assert c.get("/intake/api/health?days=14").status_code == 400
    assert c.get("/intake/api/analytics").status_code == 200 and called(kit)[-1] == "/api/analytics"
    assert c.get("/intake/api/analytics?months=13&printer=" + SERIAL).status_code == 200
    assert called(kit)[-1] == f"/api/analytics?months=13&printer={SERIAL}"
    assert c.get("/intake/api/analytics?months=14").status_code == 400 and c.get("/intake/api/analytics?months=0").status_code == 400
    assert c.get("/intake/api/analytics?printer=a%20b").status_code == 400


def test_the_three_downloads_pass_the_file_on_and_no_other_set_leaves(env):
    kit = HistoryKit()
    c = signed(make_app(env, kit))
    r = c.get("/intake/api/export/spoolman-spools.csv")
    assert r.status_code == 200 and r.content == CSV and r.headers["content-type"].startswith("text/csv")
    assert r.headers["content-disposition"] == 'attachment; filename="spoolman-spools.csv"' and called(kit)[-1] == "/api/export/spoolman-spools.csv"
    assert c.get("/intake/api/export/recent.csv").status_code == 200
    r = c.get(f"/intake/api/export/usage.csv?days=30&printer={SERIAL}&junk=1")
    assert r.status_code == 200 and called(kit)[-1] == f"/api/export/usage.csv?days=30&printer={SERIAL}"
    for other in ("locations.csv", "activity.csv", "printers.csv", "lines.csv", "spoolman-filaments.csv", "usage", "../x.csv"):
        assert c.get("/intake/api/export/" + other).status_code == 404, other
    assert c.get("/intake/api/export/usage.csv?days=x").status_code == 400
    kit.down = True
    assert c.get("/intake/api/export/recent.csv").status_code == 502


def test_the_twins_are_for_the_home_network_only(env):
    c = signed(make_app(env, HistoryKit()), AWAY)
    for path in ("activity", "health", "analytics", "export/recent.csv"):
        assert c.get("/intake/api/" + path).status_code == 403, path


def test_usage_by_month_is_passed_on_and_only_month(env):
    kit = HistoryKit()
    c = signed(make_app(env, kit))
    assert c.get(f"/intake/api/printers/{SERIAL}/usage?by=month").status_code == 200
    assert called(kit)[-1] == f"/api/printers/{SERIAL}/usage?by=month"
    assert c.get(f"/intake/api/printers/{SERIAL}/usage?days=7&by=month").status_code == 200
    assert called(kit)[-1] == f"/api/printers/{SERIAL}/usage?days=7&by=month"
    assert c.get(f"/intake/api/printers/{SERIAL}/usage?by=year").status_code == 400
    assert c.get(f"/intake/api/printers/{SERIAL}/usage?days=7").status_code == 200 and called(kit)[-1] == f"/api/printers/{SERIAL}/usage?days=7"
