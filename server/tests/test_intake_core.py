"""The phone web app served by the kit server itself (api._intake_web_app), the user's decision 2026-11-09: at
https://<server>:8710/intake on the home network, no module needed; the same rules as the web unit's copy."""
from __future__ import annotations

import pytest

from filament_kit import api, config
from test_setup_page import BASE, HOME, Helper, client, env, make  # noqa: F401  (env is a fixture)

ORIGIN = BASE           # https://kit.local:8710: the page's own origin in the kit server


@pytest.fixture
def app(env):  # noqa: F811
    return make(env, Helper())


def test_the_page_is_served_with_no_module_on(app):
    assert "web" not in config.load().get("modules", {}) or not config.load()["modules"].get("web")
    r = client(app).get("/intake")
    assert r.status_code == 200 and "data-base='/intake'" in r.text and "/intake/app.js" in r.text
    assert client(app).get("/intake/app.js").status_code == 200
    m = client(app).get("/intake/manifest-light.webmanifest").json()
    assert m["start_url"] == "/intake" and m["scope"] == "/intake"


def test_only_the_home_network_and_the_servers_own_names(app):
    for path in ("/intake", "/intake/app.js", "/intake/manifest-light.webmanifest", "/intake/api/vendors"):
        assert client(app, who=("203.0.113.9", 4000)).get(path).status_code == 403, path
        assert client(app, base="https://rebind.example.com:8710").get(path).status_code == 403, path


def test_a_post_needs_the_pages_own_origin(app):
    c = client(app)
    for origin in (None, "https://evil.example", "https://rebind.example.com:8710", "http://kit.local:8710"):
        r = c.post("/intake/api/add", json={"items": [], "dry_run": True}, headers={"Origin": origin} if origin else {})
        assert r.status_code == 403 and r.json()["error"] == "bad origin", origin
    r = c.post("/intake/api/add", json={"items": [], "dry_run": True}, headers={"Origin": ORIGIN})
    assert r.status_code != 403                     # past the gate (the empty list is the app's own refusal)


def test_it_pairs_as_its_own_device_and_sends_no_push(monkeypatch, env):  # noqa: F811
    made = {}
    from filament_kit.web import intake_app, slots

    real = intake_app.IntakeApp.__init__

    def spy(self, tools, **kw):
        made.update(kw)
        real(self, tools, **kw)
    monkeypatch.setattr(intake_app.IntakeApp, "__init__", spy)
    make(env, Helper())
    assert made["public_url"] is None and made["push"] is False and callable(made["host_ok"])
    kit = made["kit_api"]
    assert isinstance(kit, slots.KitApi) and kit._token_file() == config.paths().state / api.INTAKE_TOKEN
    assert kit._device == api.INTAKE_DEVICE


# ---------------------------------------------------------------- R91 review notes

def test_the_kits_own_pairing_is_built_in_and_not_revoked_from_the_page(app):
    from test_setup_page import post
    from filament_kit import pairing
    pairing.make_cert("kit", ["192.0.2.5"], config.paths().etc)
    own = pairing.issue(api.INTAKE_DEVICE).token
    pairing.check(own)
    phone = pairing.issue("Pixel").token
    pairing.check(phone)
    devs = client(app).get("/setup/api/state").json()["devices"]
    by = {d["name"]: d for d in devs}
    assert by[api.INTAKE_DEVICE]["built_in"] is True and by["Pixel"]["built_in"] is False
    r = post(client(app), f"devices/{by[api.INTAKE_DEVICE]['id']}/revoke", {})
    assert r.status_code == 409 and "pairs again when next needed" in r.json()["error"]
    assert post(client(app), f"devices/{by['Pixel']['id']}/revoke", {}).status_code == 200


def test_its_refused_token_says_a_restart_fixes_it(env, caplog):  # noqa: F811
    from filament_kit.web import slots
    kit = slots.KitApi(token_file=config.paths().state / api.INTAKE_TOKEN, device=api.INTAKE_DEVICE)
    with caplog.at_level("ERROR"):
        kit._refuse()
    text = caplog.text
    assert "its own phone web app" in text and "restarts" in text and "web unit" not in text


def test_a_wrong_host_on_intake_says_how_to_add_a_name(app):
    c = client(app, base="https://rebind.example.com:8710")
    r = c.get("/intake/api/vendors")                        # the API keeps its JSON answer
    assert r.status_code == 403 and "Names for this page" in r.json()["error"]
    assert r.json()["error"].startswith("Open the setup page") and "kit.local" not in r.json()["error"]   # F2
    page = c.get("/intake")                                 # the page: the refusal page, "Not at this address" (04 11.1)
    assert page.status_code == 403 and page.headers["content-type"].startswith("text/html")
    assert "<h1>Not at this address</h1>" in page.text and "Names for this page" in page.text
    assert "kit.local" not in page.text and "data-base" not in page.text      # no Hub data on the refusal page
    assert c.get("/intake/shared/tokens.css").status_code == 200 and c.get("/intake/app.css").status_code == 200
    assert c.get("/intake/app.js").status_code == 403       # only the refusal page's own files answer a refused name
