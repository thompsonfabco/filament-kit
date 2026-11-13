"""Accepting preset updates and restoring deleted presets from a paired device (the Android app) and from the phone web
app (FB-041): the same checks as the setup page's accept, never an update the owner was not shown."""
from __future__ import annotations

import logging

import pytest
from starlette.testclient import TestClient

from filament_kit import config, pairing
from filament_kit.api import create_app
from filament_kit.profiles import builds, updates

import test_builds as TB
import test_generate as TG
from test_presets_updates import _first_install, _rebuild, env  # noqa: F401  (env is a fixture)


@pytest.fixture
def app(env):  # noqa: F811
    pairing.make_cert("fkhost", [], config.paths().etc)
    c = TestClient(create_app(sm=env))
    tok = pairing.redeem_code(pairing.issue().code)
    return c, {"Authorization": f"Bearer {tok}"}, env


def _pending(sm):
    _first_install(sm)
    return _rebuild(sm, 1.31, TG.NOW + 1)


def test_a_paired_device_accepts_exactly_what_the_list_showed(app, caplog):
    c, h, sm = app
    b2 = _pending(sm)
    listed = c.get("/api/profiles/updates", headers=h).json()
    names = [u["name"] for u in listed["updates"]]
    with caplog.at_level(logging.INFO, logger="filament_kit.profiles_api"):
        r = c.post("/api/profiles/updates/accept", headers=h, json={"stamp": listed["stamp"], "names": names[:1]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["stamp"] == b2 and [a["name"] for a in body["accepted"]] == names[:1]
    assert set(body["accepted"][0]) == {"line_id", "target", "name", "file", "keys"}
    acc = builds.state_view("a")["accepted_updates"]
    assert acc["base"] == names[:1]                                  # the PC sync writes only this one
    assert any("preset updates accept device_id=" in m and "names=1" in m and "result=ok" in m
               for m in caplog.messages)


def test_an_accept_after_a_newer_build_accepts_nothing(app):
    c, h, sm = app
    b2 = _pending(sm)
    names = [u["name"] for u in c.get("/api/profiles/updates", headers=h).json()["updates"]]
    _rebuild(sm, 1.33, TG.NOW + 2)                                    # a build the owner has not seen
    r = c.post("/api/profiles/updates/accept", headers=h, json={"stamp": b2, "names": names})
    assert r.status_code == 409 and r.json()["error"] == "updates_changed"
    assert updates.accepted(TB.profiles_dir()) == {"base": {}, "orca": {}}


@pytest.mark.parametrize("body", [{}, {"stamp": "s"}, {"names": ["a"]}, {"stamp": "s", "names": []},
                                  {"stamp": "s", "names": "a"}, {"stamp": 1, "names": ["a"]},
                                  {"stamp": "s", "names": [1]}, {"stamp": "s", "names": ["x"] * 2001}])
def test_an_accept_must_name_the_list(app, body):
    c, h, sm = app
    r = c.post("/api/profiles/updates/accept", headers=h, json=body)
    assert r.status_code == 400 and r.json()["error"] == "bad_request"


def test_restore_deleted_from_a_paired_device(app):
    c, h, sm = app
    r = c.post("/api/profiles/restore-deleted", headers=h, json={})
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert builds._pending_request() is not None                     # a build is asked for


def test_the_routes_need_a_token_and_the_presets_module(app, env):  # noqa: F811
    c, h, sm = app
    assert c.post("/api/profiles/updates/accept", json={"stamp": "s", "names": ["a"]}).status_code == 401
    assert c.post("/api/profiles/restore-deleted", json={}).status_code == 401
    cfg = config.load()
    cfg["modules"] = {"spoolman": True, "server": True}
    config.save(cfg)
    c2 = TestClient(create_app(sm=sm))
    for path, body in (("/api/profiles/updates/accept", {"stamp": "s", "names": ["a"]}),
                       ("/api/profiles/restore-deleted", {})):
        r = c2.post(path, headers=h, json=body)
        assert r.status_code == 409 and r.json()["error"] == "module_off"


def test_the_web_unit_routes_are_in_its_token_scope():
    from filament_kit import api
    assert ("POST", "/api/profiles/web/updates_accept") in api.WEB_ROUTES
    assert ("POST", "/api/profiles/web/restore_deleted") in api.WEB_ROUTES


def test_the_phone_web_app_lists_accepts_and_restores(env, monkeypatch):  # noqa: F811
    """The kit's own /intake page: it reads the list in-process and sends the writes through the kit API with its
    web-role token (the web unit does the same), so the web token's scope is exercised too."""
    from test_setup_page import BASE, H, HOSTNAME, Helper, client
    from filament_kit import modules, web_access
    from filament_kit.web import slots
    cfg = config.load()
    cfg["web"] = {**cfg["web"], "lan": ["192.0.2.0/24"]}
    config.save(cfg)
    app = create_app(env, printers=object(), camera_hub=object(), mapper=object(),
                     enabled_modules=modules.enabled(config.load()) - {"printers", "klipper"},
                     setup={"helper": Helper(), "hosts": lambda: {HOSTNAME}})
    kit = TestClient(app)
    pairing.make_cert("fkhost", [], config.paths().etc)
    web_tok = pairing.redeem_code(pairing.issue(slots.INTAKE_DEVICE, role=web_access.WEB_ROLE).code)

    def call(self, method, path, body=None):          # KitApi._call over the test client instead of the loopback
        r = kit.request(method, path, json=body, headers={"Authorization": f"Bearer {web_tok}"})
        if r.status_code >= 400:
            err = r.json()
            raise slots.SlotError(err.get("message") or str(r.status_code), code=err.get("error"), http=r.status_code)
        return r.json()
    monkeypatch.setattr(slots.KitApi, "_call", call)
    c = client(app)
    b2 = _pending(env)
    u = c.get("/intake/api/updates").json()
    assert u["stamp"] == b2 and u["count"] > 0
    names = [x["name"] for x in u["updates"]]
    r = c.post("/intake/api/updates_accept", json={"stamp": b2, "names": names}, headers=H)
    assert r.status_code == 200, r.text
    assert sorted(a["name"] for a in r.json()["accepted"]) == sorted(names)
    stale = c.post("/intake/api/updates_accept", json={"stamp": "old", "names": names}, headers=H)
    assert stale.status_code == 400 and "changed since this list" in stale.text        # the page shows the kit's words
    assert c.post("/intake/api/updates_accept", json={"stamp": b2, "names": names}).status_code == 403    # no Origin
    assert c.post("/intake/api/restore_deleted", json={}, headers=H).json() == {"ok": True}
    assert BASE
