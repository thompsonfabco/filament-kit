"""The web unit's token reaches exactly api.WEB_ROUTES, and those are exactly what filament_kit/web calls."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from starlette.routing import Route
from starlette.testclient import TestClient

from filament_kit import api, config, pairing
from filament_kit.api import create_app
from filament_kit.spoolman import Spoolman

WEB = Path(api.__file__).parent / "web"
PUBLIC = {("GET", "/api/info"), ("POST", "/api/pair"), ("POST", "/api/station/pair-request"),
          ("GET", "/api/station/pair-request/{request_id}"),
          ("POST", "/api/station/pair-request/{request_id}/reveal")}      # a station with no token yet


@pytest.fixture(autouse=True)
def certificate(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_ETC", str(tmp_path))
    pairing.make_cert("fkhost", [], tmp_path)


@pytest.fixture
def sm(spoolman_url):
    s = Spoolman(spoolman_url)
    s.ensure_fields()
    return s


@pytest.fixture
def app(sm):
    return create_app(sm=sm)


def _api_routes(app) -> set[tuple[str, str]]:
    out = set()
    for r in app.routes:
        if isinstance(r, Route) and r.path.startswith("/api/"):
            out |= {(m, r.path) for m in r.methods if m != "HEAD"}
    return out


def _example(template: str) -> str:
    return re.sub(r"\{\w+(:\w+)?\}", "1", template)


def _web_token() -> dict:
    return {"Authorization": "Bearer " + pairing.redeem_code(pairing.issue("web (MCP)", role=pairing.WEB_ROLE).code)}


def _phone_token() -> dict:
    return {"Authorization": "Bearer " + pairing.redeem_code(pairing.issue().code)}


def test_every_listed_route_is_a_route_of_the_app(app):
    assert set(api.WEB_ROUTES) <= _api_routes(app), set(api.WEB_ROUTES) - _api_routes(app)


def test_every_other_route_refuses_the_web_token(app):
    """Fail closed: a route added to the app is refused until it is listed."""
    h = _web_token()
    c = TestClient(app, raise_server_exceptions=False)
    for method, template in sorted(_api_routes(app) - set(api.WEB_ROUTES) - PUBLIC):
        r = c.request(method, _example(template), headers=h)
        assert r.status_code == 403 and "web unit" in r.json()["message"], (method, template, r.status_code)


def test_every_listed_route_lets_the_web_token_through(app):
    """Through means the handler answered: not 401, and not a 403 either (the printer-change switch is on here, so
    the three registry writes are not refused for it)."""
    config.save({**config.load(), "web": {"printer_changes": True}})
    h = _web_token()
    c = TestClient(app, raise_server_exceptions=False)
    for method, template in api.WEB_ROUTES:
        r = c.request(method, _example(template), headers=h)
        assert r.status_code not in (401, 403), (method, template, r.status_code, r.text[:100])


def _calls_in_web() -> set[str]:
    """Every /api/ path written in filament_kit/web, with what a format string fills in as 1."""
    out = set()
    for f in WEB.glob("*.py"):
        for literal in re.findall(r"""f?["'](/api/[^"'?]*)""", f.read_text(encoding="utf-8")):
            out.add(re.sub(r"\{[^}]*\}", "1", literal))
    return out


def test_every_path_the_web_unit_writes_is_listed():
    calls = _calls_in_web()
    assert "/api/intake/orders" in calls and "/api/printers/1/map" in calls       # the scan does find them
    for path in calls:
        if path.endswith("/"):      # slots.printer_path's start: its routes are named below
            continue
        if path == UNDO_CALL:       # the scan stops at the quote in f"/api/events/{quote(event, safe='')}/undo"
            path = "/api/events/1/undo"
        if any(rx.fullmatch(path) for rx in _CALLED_BEFORE_THE_HUB_MOUNTS_THEM_RX):
            continue                # refused until the Hub mounts the route: the tests below hold that
        assert (api._web_may("GET", path) or api._web_may("POST", path) or api._web_may("DELETE", path)), path


def test_the_slot_paths_are_listed():
    from filament_kit.web import slots
    assert api._web_may("GET", slots.printer_path("SERIAL"))
    assert api._web_may("POST", slots.load_path("SERIAL", "A1"))


def test_every_listed_route_is_one_the_web_unit_writes():
    """The other way: nothing stays listed once the web unit stops calling it."""
    from filament_kit.web import slots
    calls = _calls_in_web() | {slots.printer_path("1"), slots.load_path("1", "1"), "/api/printers/1/slots/1/unload",
                               "/api/printers/1/camera/1"}
    for method, template in api.WEB_ROUTES:
        if (method, template) in LISTED_BEFORE_THE_WEB_UNIT_CALLS_THEM:
            continue
        rx = re.compile(re.sub(r"\{\w+\}", "[^/]+", re.sub(r"\{\w+:path\}", ".+", template)))
        assert any(rx.fullmatch(c) for c in calls), (method, template)


# The events and alerts routes (R80 E1, EA3) are listed for the web unit before it calls them: its side (EA4: the
# hand-over, the push sender, the web twins) comes after. The next test makes EA4 delete each line here once its code
# calls the route, so this list cannot outlive the gap. The events and alert reads (EA4, EA7) now call all of them but
# the alerts test, which only the push twin of the web app sends.
LISTED_BEFORE_THE_WEB_UNIT_CALLS_THEM = {("POST", "/api/alerts/test")}


def test_a_route_listed_ahead_of_the_web_unit_is_not_yet_called_by_it():
    calls = _calls_in_web()
    for method, template in LISTED_BEFORE_THE_WEB_UNIT_CALLS_THEM:
        assert (method, template) in api.WEB_ROUTES
        rx = re.compile(re.sub(r"\{\w+\}", "[^/]+", template))
        assert not any(rx.fullmatch(c) for c in calls), f"{template} is called now: drop it from the list above"


# The kit routes the web unit's twins call (EV6a, EV6b, HD8) that the Hub has not mounted yet (their api.py mounts are
# EV1's, HD1's and RC9's steps). Each is ruled for a web token; none can be in WEB_ROUTES while the app has no such
# route (test_every_listed_route_is_a_route_of_the_app), so until then the token is refused and the twin gets the
# refusal. The mount step lists the route in WEB_ROUTES and deletes its line here; the tests below make that so.
UNDO_CALL = "/api/events/{quote(event, safe="
CALLED_BEFORE_THE_HUB_MOUNTS_THEM = {
    ("GET", "/api/hub"),                                    # R83 10.1 (what a web token may call gains exactly ...)
    ("POST", "/api/printers/{id}/slots/{label}/clear"),     # R83 10.1
    ("GET", "/api/library/local"),                          # R83 10.1
    ("POST", "/api/library/local/form"),                    # R83 10.1
    ("DELETE", "/api/library/local/{id}"),                  # R83 10.1
    ("POST", "/api/events/{id}/undo"),                      # R84 9.1: a web token may call it
    ("GET", "/api/export/{set}.csv"),                       # R84 9.2: the GET /api/export/... routes, not the imports
    ("GET", "/api/health"),                                 # R84 9.2
    ("GET", "/api/analytics"),                              # R84 9.2
}
_CALLED_BEFORE_THE_HUB_MOUNTS_THEM_RX = [
    re.compile(re.sub(r"\{\w+\}", "[^/]+", t).replace("[^/]+.csv", "[^/]+")) for _, t in CALLED_BEFORE_THE_HUB_MOUNTS_THEM]


def test_a_route_the_hub_has_not_mounted_is_refused_to_the_web_token_until_it_is_listed(app):
    """Not listed while the app has no such route; the moment the app has it, it must be listed (or leave this set)."""
    shape = lambda t: re.sub(r"\{[^}]*\}", "{}", t)       # noqa: E731 - {id} and {entry_id} are the same route
    mounted = {(m, shape(t)) for m, t in _api_routes(app)}
    for method, template in sorted(CALLED_BEFORE_THE_HUB_MOUNTS_THEM):
        if (method, shape(template)) in mounted:
            assert (method, template) in api.WEB_ROUTES, f"{method} {template} is mounted now: list it in api.WEB_ROUTES"
        else:
            assert (method, template) not in api.WEB_ROUTES, f"{method} {template} is listed but the app has no such route"


def test_the_ruled_routes_stay_off_the_web_token_for_every_other_method():
    """The ruling names a method for each: the others stay refused (R84 9.2: not the imports)."""
    for method, path in (("POST", "/api/hub"), ("GET", "/api/printers/1/slots/1/clear"), ("PUT", "/api/library/local/1"),
                         ("POST", "/api/import/spools"), ("POST", "/api/import/locations"), ("POST", "/api/export/usage.csv")):
        assert not api._web_may(method, path), (method, path)


def test_a_slash_in_a_path_cannot_reach_a_listed_route_by_another_shape():
    for method, path in (("GET", "/api/printers/1/2"), ("POST", "/api/printers/1/slots/1/2/load"),
                         ("DELETE", "/api/printers/1/2"), ("PATCH", "/api/printers/1/2"), ("POST", "/api/printers/1")):
        assert not api._web_may(method, path), (method, path)


def test_the_web_unit_may_add_edit_and_forget_printers():
    """Interface parity gap 3 (2026-11-10): the phone web app's Manage printers adds, edits and forgets printers, as
    the setup page and the Android app do; before, the web token was kept off registry writes."""
    for method, path in (("POST", "/api/printers"), ("PATCH", "/api/printers/1"), ("DELETE", "/api/printers/1")):
        assert api._web_may(method, path), (method, path)


def test_a_pairing_made_before_the_scope_has_it_from_its_role(app):
    tok = pairing.redeem_code(pairing.issue("web (MCP)").code)
    h = {"Authorization": f"Bearer {tok}"}
    c = TestClient(app, raise_server_exceptions=False)
    assert c.get("/api/spools", headers=h).status_code == 200       # no role yet: a device like any other
    assert pairing.set_role_by_name("web (MCP)", pairing.WEB_ROLE) == 1
    assert c.get("/api/spools", headers=h).status_code == 403       # no new pairing needed


def test_a_phone_keeps_its_routes_and_cannot_call_the_web_units_writes(app):
    h = _phone_token()
    c = TestClient(app, raise_server_exceptions=False)
    assert c.get("/api/spools", headers=h).status_code == 200
    for path in ("line_add", "line_new", "generate"):
        r = c.post(f"/api/profiles/web/{path}", headers=h, json={})
        assert r.status_code == 403 and "web unit" in r.json()["message"], path


def test_the_station_token_is_unchanged(app):
    h = {"Authorization": "Bearer " + pairing.redeem_code(pairing.issue("station").code)}
    c = TestClient(app, raise_server_exceptions=False)
    assert c.get("/api/spools", headers=h).status_code == 403
    assert c.get("/api/printers", headers=h).status_code == 403
