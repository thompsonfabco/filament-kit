"""S4.13 (N25): the Slicer presets line and build actions for a paired phone (the Android app), `/api/profiles/uncovered`,
`/api/profiles/lines`, `/api/profiles/lines/{id}/filaments` and `/api/profiles/build`: the web unit's `presets.*`
functions with the same checks; the `web/*` routes stay the web unit's."""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from filament_kit import config, pairing, web_access
from filament_kit.api import create_app
from filament_kit.profiles import builds, lines as lines_mod
from filament_kit.web import slots

import test_builds as TB
import test_generate as TG
from test_presets_updates import env  # noqa: F401  (env is a fixture)


class PatchSm(TB.FakeSm):
    def __init__(self, filaments):
        super().__init__(filaments)
        self.patched = []

    def patch(self, path, body):
        self.patched.append((path, body))
        return {}


@pytest.fixture
def app(env):  # noqa: F811
    sm = PatchSm([TG.fil(17, "PLA+ 2.0 Grey"), TG.fil(3, "PLA+ 2.0 Red"), TG.fil(5, "Silk Gold"),
                  TG.fil(9, "Other", vendor="Acme")])
    pairing.make_cert("fkhost", [], config.paths().etc)
    c = TestClient(create_app(sm=sm), raise_server_exceptions=False)
    tok = pairing.redeem_code(pairing.issue().code)
    return c, {"Authorization": f"Bearer {tok}"}, sm


def test_a_paired_device_lists_creates_adds_and_builds(app):
    c, h, sm = app
    r = c.get("/api/profiles/uncovered", headers=h)
    assert r.status_code == 200, r.text
    got = r.json()["uncovered_filaments"]
    assert [f["id"] for f in got] == [17, 3, 5, 9]
    assert set(got[0]) == {"id", "vendor", "name", "material", "lines_for_vendor"} and got[0]["lines_for_vendor"] == []

    r = c.post("/api/profiles/lines", headers=h, json={"name": "SUNLU Silk", "vendor": "SUNLU", "ids": [5],
                                                       "bs_template": "Generic PLA"})
    assert r.status_code == 200, r.text
    lid = r.json()["line_id"]
    assert r.json()["filament_ids"] == [5] and "a build is requested" in r.json()["output"]
    assert lines_mod.load()[lid].filaments == [5]
    got = c.get("/api/profiles/uncovered", headers=h).json()["uncovered_filaments"]
    assert [f["id"] for f in got] == [17, 3, 9]
    assert got[0]["lines_for_vendor"] == ["SUNLU Silk"] and got[2]["lines_for_vendor"] == []

    r = c.post(f"/api/profiles/lines/{lid}/filaments", headers=h, json={"ids": [3]})
    assert r.status_code == 200, r.text
    assert r.json()["filament_ids"] == [3, 5]
    assert ("filament/3", {"extra": {"line": '"Silk"'}}) in sm.patched       # pinned as the web route pins it
    assert [f["id"] for f in c.get("/api/profiles/uncovered", headers=h).json()["uncovered_filaments"]] == [17, 9]

    r = c.post("/api/profiles/build", headers=h, json={})
    assert r.status_code == 200 and r.json()["requested"] is True and "output" in r.json()
    assert builds._pending_request() is not None


def test_the_same_checks_as_the_web_routes(app):
    c, h, sm = app
    assert c.post("/api/profiles/lines", headers=h, json={"name": "SUNLU Silk", "vendor": "SUNLU", "ids": [5],
                                                          "bs_template": "Generic PLA"}).status_code == 200
    lid = lines_mod.line_id_for("SUNLU", "Silk")
    bad = [("/api/profiles/lines", {"name": "SUNLU Silk", "vendor": "SUNLU", "ids": [3], "bs_template": "Generic PLA"}),  # exists
           ("/api/profiles/lines", {"name": "X", "vendor": "SUNLU", "ids": ["x"], "bs_template": "Generic PLA"}),
           ("/api/profiles/lines", {"name": "X", "vendor": "SUNLU", "ids": [3]}),                  # no bs_template
           (f"/api/profiles/lines/{lid}/filaments", {"ids": [5]}),                                  # already in it
           (f"/api/profiles/lines/{lid}/filaments", {"ids": []}),
           (f"/api/profiles/lines/{lid}/filaments", {"ids": [9]}),                                  # another brand
           (f"/api/profiles/lines/{lid}/filaments", {"ids": [404]}),                                # not in Spoolman
           ("/api/profiles/lines/nope/filaments", {"ids": [3]})]
    for path, body in bad:
        r = c.post(path, headers=h, json=body)
        assert r.status_code == 400 and r.json()["error"] == "bad_request", (path, body, r.text)
    assert lines_mod.load()[lid].filaments == [5]


def test_an_unpaired_caller_is_refused(app):
    c, h, sm = app
    for method, path, body in (("GET", "/api/profiles/uncovered", None),
                               ("POST", "/api/profiles/lines", {"name": "A B", "vendor": "A", "ids": [1],
                                                                "bs_template": "Generic PLA"}),
                               ("POST", "/api/profiles/lines/x/filaments", {"ids": [1]}),
                               ("POST", "/api/profiles/build", {})):
        assert c.request(method, path, json=body).status_code == 401, path
        bogus = {"Authorization": "Bearer nope"}
        assert c.request(method, path, json=body, headers=bogus).status_code == 401, path
    assert lines_mod.load() == {}


def test_the_web_token_and_the_web_routes_are_unchanged(app):
    c, h, sm = app
    web = {"Authorization": "Bearer " + pairing.redeem_code(
        pairing.issue(slots.INTAKE_DEVICE, role=web_access.WEB_ROLE).code)}
    for method, path in (("GET", "/api/profiles/uncovered"), ("POST", "/api/profiles/lines"),
                         ("POST", "/api/profiles/lines/x/filaments"), ("POST", "/api/profiles/build")):
        assert c.request(method, path, headers=web, json={}).status_code == 403, path
    assert c.post("/api/profiles/web/generate", headers=web, json={}).status_code == 200      # still the web unit's
    assert c.post("/api/profiles/web/generate", headers=h, json={}).status_code == 403        # and not a phone's
    assert c.get("/api/profiles/lines", headers=h).status_code == 200                         # the list route kept


def _new(**kw):
    return {"name": "SUNLU Silk", "vendor": "SUNLU", "ids": [5], "bs_template": "Generic PLA", **kw}


def test_a_refused_new_line_names_its_field(app):
    c, h, sm = app
    assert c.post("/api/profiles/lines", headers=h, json=_new()).status_code == 200
    cases = [(_new(ids=[3]), "name"),                              # the line exists already
             (_new(name="Bad@Name"), "name"),
             (_new(name=" "), "name"),
             (_new(vendor=""), "vendor"),
             (_new(bs_template=""), "parent"),
             (_new(ids=["x"]), "ids"),
             (_new(name="SUNLU Other", ids=[404]), "ids")]
    for body, field in cases:
        r = c.post("/api/profiles/lines", headers=h, json=body)
        assert r.status_code == 400 and r.json()["error"] == "bad_request", (body, r.text)
        assert r.json()["field"] == field and r.json()["message"], (body, r.text)


def test_both_parent_inputs_refuse_with_the_one_parent_field(app):
    c, h, sm = app
    for body in (_new(orca_parent="Bad@Parent"), _new(bs_template="Bad@Parent"), _new(bs_template="")):
        r = c.post("/api/profiles/lines", headers=h, json=body)
        assert r.status_code == 400 and r.json()["field"] == "parent", (body, r.text)


def test_an_unknown_parent_names_the_parent_field(app):
    c, h, sm = app
    TB.synced(sm)                                                   # a system store: the parent is checked
    r = c.post("/api/profiles/lines", headers=h, json=_new(bs_template="No such preset"))
    assert r.status_code == 400 and r.json()["error"] == "unknown_parent" and r.json()["field"] == "parent"
    assert lines_mod.load() == {}


def test_the_web_routes_still_send_no_field(app):
    c, h, sm = app
    web = {"Authorization": "Bearer " + pairing.redeem_code(
        pairing.issue(slots.INTAKE_DEVICE, role=web_access.WEB_ROLE).code)}
    body = {"name": "SUNLU Silk", "vendor": "SUNLU", "ids": [5], "bs_template": "Generic PLA"}
    assert c.post("/api/profiles/web/line_new", headers=web, json=body).status_code == 200
    r = c.post("/api/profiles/web/line_new", headers=web, json={**body, "ids": [3]})     # exists already
    assert r.status_code == 400 and "field" not in r.json(), r.text
    r = c.post("/api/profiles/web/line_new", headers=web, json={**body, "name": "SUNLU Z", "bs_template": ""})
    assert r.status_code == 400 and "field" not in r.json(), r.text


def test_orca_parents_for_a_paired_device(app):
    import io
    c, h, sm = app
    assert c.get("/api/profiles/orca-parents", headers=h).json() == {"orca_parents": []}      # no Orca library yet
    builds.store_upload("orca_system", io.BytesIO(TB.orca_system_zip()), device_id="a")
    every = c.get("/api/profiles/orca-parents", headers=h).json()["orca_parents"]
    assert "Generic PLA" in every and every == sorted(every)
    r = c.get("/api/profiles/orca-parents", headers=h, params={"material": "  pla  "})
    assert r.status_code == 200 and r.json()["orca_parents"] == [n for n in every if "pla" in n.casefold()]
    assert c.get("/api/profiles/orca-parents", headers=h, params={"material": "GENERIC pla"}).json() == {
        "orca_parents": ["Generic PLA", "Generic PLA Silk"]}
    assert c.get("/api/profiles/orca-parents", headers=h, params={"material": "zzz"}).json() == {"orca_parents": []}
    r = c.get("/api/profiles/orca-parents", headers=h, params={"material": "x" * 101})
    assert r.status_code == 400 and r.json()["error"] == "bad_request"


def test_the_route_and_find_parents_share_the_public_orca_parents_helper(app, monkeypatch):
    from filament_kit.web import presets
    c, h, sm = app
    monkeypatch.setattr(presets, "orca_parents", lambda words: ["seen " + " ".join(words)])
    assert c.get("/api/profiles/orca-parents", headers=h, params={"material": "A b"}).json() == {
        "orca_parents": ["seen a b"]}
    assert presets.find_parents("C")["orca_parents"] == ["seen c"]


def test_orca_parents_tokens(app):
    c, h, sm = app
    assert c.get("/api/profiles/orca-parents").status_code == 401
    web = {"Authorization": "Bearer " + pairing.redeem_code(
        pairing.issue(slots.INTAKE_DEVICE, role=web_access.WEB_ROLE).code)}
    assert c.get("/api/profiles/orca-parents", headers=web).status_code == 403
    station = {"Authorization": "Bearer " + pairing.redeem_code(pairing.issue("station").code)}
    assert c.get("/api/profiles/orca-parents", headers=station).status_code == 403
