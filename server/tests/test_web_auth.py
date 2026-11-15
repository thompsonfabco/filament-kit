"""web.auth: OAuth provider + store, passphrase, LAN-only wrapper, /login page, lockout.

Behaviour is a port of filament-ops vm/server.py (Provider, Store, LanOnly, /login); these tests pin it down.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import secrets
import shutil
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

pytest.importorskip("mcp")

from mcp.server.auth.provider import AuthorizeError, RegistrationError, TokenError  # noqa: E402
from mcp.server.auth.routes import create_auth_routes  # noqa: E402
from mcp.shared.auth import OAuthClientInformationFull  # noqa: E402
from starlette.applications import Starlette  # noqa: E402
from starlette.responses import PlainTextResponse  # noqa: E402
from starlette.routing import Route  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from filament_kit.web import auth  # noqa: E402

PUBLIC = "https://mcp.example.test/filament"
ORIGIN = "https://mcp.example.test"
CB = "https://claude.ai/api/mcp/auth_callback"
CB2 = "https://claude.com/api/mcp/auth_callback"
LAN = ["192.168.1.0/24"]
HOME = ("192.168.1.20", 50000)
AWAY = ("203.0.113.9", 50000)
PASS = "correct horse battery"
DATA = Path(__file__).parent / "data"


def run(coro):
    return asyncio.run(coro)


class Clock:
    """Stands in for the time module inside auth only (the SDK keeps the real clock)."""

    def __init__(self):
        self.now = time.time()

    def time(self):
        return self.now


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(auth, "time", c)
    return c


@pytest.fixture
def store(tmp_path):
    return auth.Store(tmp_path / "web" / "oauth.json")


@pytest.fixture
def provider(store):
    return auth.Provider(store, PUBLIC)


@pytest.fixture
def passfile(tmp_path):
    p = tmp_path / "web_passphrase"
    p.write_text(auth.hash_passphrase(PASS) + "\n", encoding="utf-8")
    return p


def _client_info(redirects=(CB,), name="Claude", issued_at=None):
    return OAuthClientInformationFull(
        client_id=secrets.token_hex(8), client_name=name, redirect_uris=list(redirects),
        token_endpoint_auth_method="none", grant_types=["authorization_code", "refresh_token"],
        response_types=["code"], scope="filament", client_id_issued_at=int(issued_at or time.time()))


def _app(store, passfile, lockout=None):
    lockout = lockout if lockout is not None else auth.Lockout()
    s = auth.auth_settings(PUBLIC)
    routes = create_auth_routes(auth.Provider(store, PUBLIC), issuer_url=s.issuer_url,
                                client_registration_options=s.client_registration_options,
                                revocation_options=s.revocation_options)
    routes += auth.login_routes(store, PUBLIC, passfile, lan_cidrs=LAN, lockout=lockout)
    routes.append(Route("/mcp", lambda r: PlainTextResponse("mcp"), methods=["GET"]))
    routes.append(Route("/intake/api/find", lambda r: PlainTextResponse("intake"), methods=["GET"]))
    return auth.lan_only(Starlette(routes=routes), LAN)


def _pkce():
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def _register(c, redirects=(CB,)):
    r = c.post("/register", json={"redirect_uris": list(redirects), "client_name": "Claude",
                                  "token_endpoint_auth_method": "none",
                                  "grant_types": ["authorization_code", "refresh_token"],
                                  "response_types": ["code"]})
    return r


def _sign_in(c, client_id, challenge, passphrase=PASS, state="st8"):
    r = c.get("/authorize", params={"response_type": "code", "client_id": client_id, "redirect_uri": CB,
                                    "code_challenge": challenge, "code_challenge_method": "S256",
                                    "state": state, "scope": "filament"}, follow_redirects=False)
    assert r.status_code == 302, r.text
    loc = urlparse(r.headers["location"])
    assert f"{loc.scheme}://{loc.netloc}{loc.path}" == f"{PUBLIC}/login"
    rid = parse_qs(loc.query)["req"][0]
    return c.post("/login", data={"req": rid, "passphrase": passphrase}, headers={"Origin": ORIGIN},
                  follow_redirects=False), rid


def _full_flow(c):
    cid = _register(c).json()["client_id"]
    verifier, challenge = _pkce()
    r, _ = _sign_in(c, cid, challenge)
    assert r.status_code == 302
    q = parse_qs(urlparse(r.headers["location"]).query)
    t = c.post("/token", data={"grant_type": "authorization_code", "code": q["code"][0], "redirect_uri": CB,
                               "client_id": cid, "code_verifier": verifier})
    assert t.status_code == 200, t.text
    return cid, t.json()


# ---------- dynamic client registration ----------

@pytest.mark.parametrize("uris", [[CB], [CB2], [CB, CB2]])
def test_dcr_accepts_only_claude_callbacks(store, provider, uris):
    info = _client_info(uris)
    run(provider.register_client(info))
    assert info.client_id in store.d["clients"]


@pytest.mark.parametrize("uris", [["https://evil.example/cb"], [CB, "https://evil.example/cb"],
                                  ["http://claude.ai/api/mcp/auth_callback"], []])
def test_dcr_rejects_other_redirects(store, provider, uris):
    with pytest.raises(RegistrationError) as e:
        run(provider.register_client(_client_info(uris)))
    assert e.value.error == "invalid_redirect_uri"
    assert store.d["clients"] == {}


def test_dcr_over_http_rejects_foreign_callback(store, passfile):
    with TestClient(_app(store, passfile), client=AWAY) as c:  # /register answers everyone, like the VM
        assert _register(c, ["https://evil.example/cb"]).status_code == 400
        assert _register(c).status_code == 201
    assert len(store.d["clients"]) == 1


def test_idle_client_dropped_after_an_hour(store, provider, clock):
    old = _client_info(issued_at=clock.now - 3601)
    young = _client_info(issued_at=clock.now - 3500)
    used = _client_info(issued_at=clock.now - 99999)
    for c in (old, young, used):
        store.d["clients"][c.client_id] = c.model_dump(mode="json")
    store.d["refresh"]["h"] = {"client_id": used.client_id, "scopes": ["filament"], "expires_at": clock.now + 99}
    run(provider.register_client(_client_info()))
    assert old.client_id not in store.d["clients"]
    assert young.client_id in store.d["clients"] and used.client_id in store.d["clients"]


def test_full_client_table_drops_oldest_idle(store, provider, clock):
    infos = [_client_info(issued_at=clock.now - 100 + i) for i in range(auth.MAX_CLIENTS)]
    for c in infos:
        store.d["clients"][c.client_id] = c.model_dump(mode="json")
    new = _client_info()
    run(provider.register_client(new))
    assert len(store.d["clients"]) == auth.MAX_CLIENTS == 50
    assert infos[0].client_id not in store.d["clients"] and new.client_id in store.d["clients"]


def test_client_table_full_of_connected_clients_refuses(store, provider, clock):
    for i in range(50):
        c = _client_info(issued_at=clock.now - 99999)
        store.d["clients"][c.client_id] = c.model_dump(mode="json")
        store.d["refresh"][f"h{i}"] = {"client_id": c.client_id, "scopes": ["filament"],
                                       "expires_at": clock.now + 99}
    with pytest.raises(RegistrationError) as e:
        run(provider.register_client(_client_info()))
    assert e.value.error == "invalid_client_metadata"
    assert len(store.d["clients"]) == 50


# ---------- authorize / login / code / tokens ----------

def test_full_flow_issues_tokens_with_ttls(store, passfile):
    with TestClient(_app(store, passfile), client=HOME) as c:
        cid, tok = _full_flow(c)
        assert tok["expires_in"] == 3600 and tok["token_type"].lower() == "bearer" and tok["scope"] == "filament"
    a = store.d["access"][auth._h(tok["access_token"])]
    r = store.d["refresh"][auth._h(tok["refresh_token"])]
    assert a["client_id"] == cid and abs(a["expires_at"] - time.time() - 3600) < 5
    assert abs(r["expires_at"] - time.time() - 60 * 86400) < 5 and r["access"] == auth._h(tok["access_token"])
    raw = store.path.read_text(encoding="utf-8")
    assert tok["access_token"] not in raw and tok["refresh_token"] not in raw  # stored hashed only


def test_login_redirect_carries_state_and_code_is_hashed(store, passfile):
    with TestClient(_app(store, passfile), client=HOME) as c:
        cid = _register(c).json()["client_id"]
        r, _ = _sign_in(c, cid, _pkce()[1], state="xyz")
    loc = urlparse(r.headers["location"])
    assert f"{loc.scheme}://{loc.netloc}{loc.path}" == CB
    q = parse_qs(loc.query)
    assert q["state"] == ["xyz"]
    entry = store.d["codes"][auth._h(q["code"][0])]
    assert entry["client_id"] == cid and abs(entry["expires_at"] - time.time() - 300) < 5
    assert q["code"][0] not in store.path.read_text(encoding="utf-8")


def test_code_is_single_use_and_needs_pkce(store, passfile):
    with TestClient(_app(store, passfile), client=HOME) as c:
        cid = _register(c).json()["client_id"]
        verifier, challenge = _pkce()
        r, _ = _sign_in(c, cid, challenge)
        code = parse_qs(urlparse(r.headers["location"]).query)["code"][0]
        body = {"grant_type": "authorization_code", "code": code, "redirect_uri": CB, "client_id": cid}
        bad = c.post("/token", data={**body, "code_verifier": secrets.token_urlsafe(48)})
        assert bad.status_code == 400 and bad.json()["error"] == "invalid_grant"
        assert c.post("/token", data={**body, "code_verifier": verifier}).status_code == 200
        again = c.post("/token", data={**body, "code_verifier": verifier})
        assert again.status_code == 400 and again.json()["error"] == "invalid_grant"


def test_exchange_code_twice_raises(store, provider):
    info = _client_info()
    run(provider.register_client(info))
    store.d["codes"][auth._h("c0de")] = {"scopes": ["filament"], "expires_at": time.time() + 300,
                                         "client_id": info.client_id, "code_challenge": "x" * 43,
                                         "redirect_uri": CB, "redirect_uri_provided_explicitly": True,
                                         "resource": None}
    code = run(provider.load_authorization_code(info, "c0de"))
    run(provider.exchange_authorization_code(info, code))
    with pytest.raises(TokenError):
        run(provider.exchange_authorization_code(info, code))


def test_code_of_another_client_or_expired_is_not_loaded(store, provider, clock):
    info, other = _client_info(), _client_info()
    store.d["codes"][auth._h("c0de")] = {"scopes": ["filament"], "expires_at": clock.now + 300,
                                         "client_id": info.client_id, "code_challenge": "x" * 43,
                                         "redirect_uri": CB, "redirect_uri_provided_explicitly": True}
    assert run(provider.load_authorization_code(other, "c0de")) is None
    clock.now += 301
    assert run(provider.load_authorization_code(info, "c0de")) is None


def test_access_token_expires_after_an_hour(store, provider, clock):
    info = _client_info()
    tok = provider._issue(info.client_id, ["filament"], None)
    assert run(provider.load_access_token(tok.access_token)).client_id == info.client_id
    clock.now += 3601
    assert run(provider.load_access_token(tok.access_token)) is None


def test_refresh_rotates(store, provider, clock):
    info = _client_info()
    first = provider._issue(info.client_id, ["filament"], None)
    rt = run(provider.load_refresh_token(info, first.refresh_token))
    second = run(provider.exchange_refresh_token(info, rt, []))
    assert second.refresh_token != first.refresh_token
    assert run(provider.load_access_token(first.access_token)) is None  # the old access token ends with it
    assert run(provider.load_access_token(second.access_token)) is not None
    assert auth._h(first.refresh_token) in store.d["used"]
    with pytest.raises(TokenError):
        run(provider.exchange_refresh_token(info, rt, []))


def test_refresh_token_expires_after_60_days(store, provider, clock):
    info = _client_info()
    tok = provider._issue(info.client_id, ["filament"], None)
    clock.now += 60 * 86400 - 10
    assert run(provider.load_refresh_token(info, tok.refresh_token)) is not None
    clock.now += 20
    assert run(provider.load_refresh_token(info, tok.refresh_token)) is None


def test_refresh_token_of_another_client_is_refused(store, provider):
    info, other = _client_info(), _client_info()
    tok = provider._issue(info.client_id, ["filament"], None)
    assert run(provider.load_refresh_token(other, tok.refresh_token)) is None


def test_refresh_replay_within_grace_is_harmless(store, provider, clock):
    info = _client_info()
    first = provider._issue(info.client_id, ["filament"], None)
    second = run(provider.exchange_refresh_token(info, run(provider.load_refresh_token(info, first.refresh_token)), []))
    clock.now += 29  # e.g. Claude retried a request whose answer got lost
    assert run(provider.load_refresh_token(info, first.refresh_token)) is None
    assert run(provider.load_access_token(second.access_token)) is not None
    assert run(provider.load_refresh_token(info, second.refresh_token)) is not None


def test_refresh_replay_after_30s_revokes_all_client_tokens(store, provider, clock):
    info, other = _client_info(), _client_info()
    first = provider._issue(info.client_id, ["filament"], None)
    extra = provider._issue(info.client_id, ["filament"], None)
    bystander = provider._issue(other.client_id, ["filament"], None)
    second = run(provider.exchange_refresh_token(info, run(provider.load_refresh_token(info, first.refresh_token)), []))
    clock.now += 31
    assert run(provider.load_refresh_token(info, first.refresh_token)) is None
    for t in (second, extra):
        assert run(provider.load_access_token(t.access_token)) is None
        assert run(provider.load_refresh_token(info, t.refresh_token)) is None
    assert run(provider.load_access_token(bystander.access_token)) is not None
    on_disk = json.loads(store.path.read_text(encoding="utf-8"))
    assert all(v["client_id"] != info.client_id for k in ("access", "refresh") for v in on_disk[k].values())


def test_refresh_replay_over_http_revokes(store, passfile, clock):
    with TestClient(_app(store, passfile), client=HOME) as c:
        cid, tok = _full_flow(c)
        body = {"grant_type": "refresh_token", "client_id": cid, "refresh_token": tok["refresh_token"]}
        new = c.post("/token", data=body)
        assert new.status_code == 200, new.text
        clock.now += 31
        assert c.post("/token", data=body).status_code == 400
        newer = {**body, "refresh_token": new.json()["refresh_token"]}
        assert c.post("/token", data=newer).status_code == 400  # the legitimate copy was revoked too
    assert store.d["access"] == {} and store.d["refresh"] == {}


def test_revoking_access_token_ends_its_refresh_token(store, provider):
    info = _client_info()
    tok = provider._issue(info.client_id, ["filament"], None)
    run(provider.revoke_token(run(provider.load_access_token(tok.access_token))))
    assert run(provider.load_access_token(tok.access_token)) is None
    assert run(provider.load_refresh_token(info, tok.refresh_token)) is None


def test_revoking_refresh_token_ends_its_access_token(store, provider):
    info = _client_info()
    tok = provider._issue(info.client_id, ["filament"], None)
    run(provider.revoke_token(run(provider.load_refresh_token(info, tok.refresh_token))))
    assert run(provider.load_access_token(tok.access_token)) is None


def test_authorize_returns_login_url_and_caps_pending(store, provider, clock):
    info = _client_info()
    params = auth.AuthorizationParams(state="s", scopes=["filament"], code_challenge="x" * 43, redirect_uri=CB,
                                      redirect_uri_provided_explicitly=True)
    url = run(provider.authorize(info, params))
    assert url.startswith(f"{PUBLIC}/login?req=")
    for _ in range(auth.MAX_PENDING - 1):
        run(provider.authorize(info, params))
    with pytest.raises(AuthorizeError) as e:
        run(provider.authorize(info, params))
    assert e.value.error == "temporarily_unavailable"
    clock.now += 601  # pending requests expire after 10 minutes
    run(provider.authorize(info, params))
    assert len(store.pending) == 1
    assert not store.path.exists() or "pending" not in json.loads(store.path.read_text())  # memory only


def test_auth_settings():
    s = auth.auth_settings(PUBLIC + "/")
    assert str(s.issuer_url).rstrip("/") == PUBLIC
    assert str(s.resource_server_url) == PUBLIC + "/mcp"
    assert s.validate_token_resource is False
    assert s.client_registration_options.enabled and s.client_registration_options.valid_scopes == ["filament"]
    assert s.client_registration_options.default_scopes == ["filament"]
    assert s.revocation_options.enabled and s.required_scopes == ["filament"]


# ---------- /login page ----------

def test_login_only_answers_lan(store, passfile):
    with TestClient(_app(store, passfile), client=AWAY) as c:
        assert c.get("/login", params={"req": "x"}).status_code == 403
        r = c.post("/login", data={"req": "x", "passphrase": PASS}, headers={"Origin": ORIGIN})
        assert r.status_code == 403
    routes = auth.login_routes(store, PUBLIC, passfile, lan_cidrs=LAN,
                               lockout=auth.Lockout())  # its own check, without the wrapper
    with TestClient(Starlette(routes=routes), client=AWAY) as c:
        assert c.get("/login", params={"req": "x"}).status_code == 403
    with TestClient(Starlette(routes=routes), client=("127.0.0.1", 1)) as c:
        assert c.get("/login", params={"req": "x"}).status_code == 400  # loopback counts as home


def test_login_post_needs_own_origin(store, passfile):
    with TestClient(_app(store, passfile), client=HOME) as c:
        cid = _register(c).json()["client_id"]
        r, rid = _sign_in(c, cid, _pkce()[1], passphrase="wrong one at first")
        for hdrs in ({}, {"Origin": "https://evil.example"}, {"Origin": "null"}):
            r = c.post("/login", data={"req": rid, "passphrase": PASS}, headers=hdrs, follow_redirects=False)
            assert r.status_code == 403
        assert c.post("/login", data={"req": rid, "passphrase": PASS}, headers={"Origin": ORIGIN},
                      follow_redirects=False).status_code == 302


def test_login_page_headers_and_escaping(store, passfile):
    with TestClient(_app(store, passfile), client=HOME) as c:
        cid = c.post("/register", json={"redirect_uris": [CB], "client_name": "<script>x</script>",
                                        "token_endpoint_auth_method": "none"}).json()["client_id"]
        _, ch = _pkce()
        r = c.get("/authorize", params={"response_type": "code", "client_id": cid, "redirect_uri": CB,
                                        "code_challenge": ch, "code_challenge_method": "S256"},
                  follow_redirects=False)
        rid = parse_qs(urlparse(r.headers["location"]).query)["req"][0]
        page = c.get("/login", params={"req": rid})
    assert page.status_code == 200
    assert "<script>x" not in page.text and "&lt;script&gt;" in page.text
    h = page.headers
    assert h["content-security-policy"] == (
        "default-src 'none'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
        "form-action 'self' " + " ".join(sorted(auth.CALLBACKS)))
    # 04 11.2: the web app's stylesheet and the Show button's script, no style inside the page (AUT-2, N24)
    assert "<style" not in page.text and " style=" not in page.text
    for f in ("intake/shared/theme-init.js", "intake/shared/tokens.css", "intake/shared/components.css",
              "intake/app.css", "intake/signin.js"):
        assert f"'{f}'" in page.text, f
    assert "<h1>Allow &lt;script&gt;x&lt;/script&gt;?</h1>" in page.text and "<title>filament-kit sign-in</title>" in page.text
    assert "class=field__label for=pass>Passphrase</label>" in page.text and "autofocus" in page.text
    assert "aria-controls=pass" in page.text and ">Allow</button>" in page.text
    assert h["x-frame-options"] == "DENY" and h["cache-control"] == "no-store"
    assert h["referrer-policy"] == "same-origin" and h["x-content-type-options"] == "nosniff"


def test_login_unknown_or_expired_request(store, passfile, clock):
    with TestClient(_app(store, passfile), client=HOME) as c:
        assert c.get("/login", params={"req": "nope"}).status_code == 400
        cid = _register(c).json()["client_id"]
        _, ch = _pkce()
        r = c.get("/authorize", params={"response_type": "code", "client_id": cid, "redirect_uri": CB,
                                        "code_challenge": ch, "code_challenge_method": "S256"},
                  follow_redirects=False)
        rid = parse_qs(urlparse(r.headers["location"]).query)["req"][0]
        clock.now += 601
        assert c.get("/login", params={"req": rid}).status_code == 400


def test_login_wrong_passphrase_then_lockout(store, passfile, clock):
    lock = auth.Lockout()
    with TestClient(_app(store, passfile, lockout=lock), client=HOME) as c:
        cid = _register(c).json()["client_id"]
        r, rid = _sign_in(c, cid, _pkce()[1], passphrase="nope")
        assert r.status_code == 401
        # 04 11.2: the form again, the error under the field, the field empty and focused
        assert "<p class=field__error id=pass-error>Wrong passphrase.</p>" in r.text
        assert "aria-describedby=pass-error aria-invalid=true" in r.text and "autofocus" in r.text
        assert "nope" not in r.text and "name=passphrase" in r.text
        for _ in range(4):
            r = c.post("/login", data={"req": rid, "passphrase": "nope"}, headers={"Origin": ORIGIN})
            assert r.status_code == 401
        r = c.post("/login", data={"req": rid, "passphrase": PASS}, headers={"Origin": ORIGIN},
                   follow_redirects=False)
        assert r.status_code == 429  # even the right passphrase waits out the lockout
        assert store.d["codes"] == {}
        clock.now += 601  # lockout over (the old request expired with it: start again)
        r, _ = _sign_in(c, cid, _pkce()[1])
        assert r.status_code == 302


def test_lockout_is_shared(store, passfile, clock):
    lock = auth.Lockout()
    for _ in range(5):
        lock.attempt()  # another wrong passphrase at /login
    with TestClient(_app(store, passfile, lockout=lock), client=HOME) as c:
        cid = _register(c).json()["client_id"]
        r, _ = _sign_in(c, cid, _pkce()[1])
        assert r.status_code == 429


def test_login_without_passphrase_file(store, tmp_path):
    missing = tmp_path / "none"
    lock = auth.Lockout()
    with TestClient(_app(store, missing, lockout=lock), client=HOME) as c:
        cid = _register(c).json()["client_id"]
        r, _ = _sign_in(c, cid, _pkce()[1])
        assert r.status_code == 503
        assert "Settings &gt; Web passphrase, or run `sudo filament-kit web passphrase` on the Hub." in r.text
    assert lock.fails == []  # a server problem is not a wrong guess


def test_login_success_consumes_request(store, passfile):
    with TestClient(_app(store, passfile), client=HOME) as c:
        cid = _register(c).json()["client_id"]
        r, rid = _sign_in(c, cid, _pkce()[1])
        assert r.status_code == 302
        again = c.post("/login", data={"req": rid, "passphrase": PASS}, headers={"Origin": ORIGIN})
        assert again.status_code == 400


# ---------- LAN-only wrapper ----------

@pytest.mark.parametrize("path", ["/authorize", "/authorize/", "/intake", "/intake/", "/intake/api/find", "/login"])
def test_lan_only_blocks_outsiders(store, passfile, path):
    with TestClient(_app(store, passfile), client=AWAY) as c:
        r = c.get(path)
    assert r.status_code == 403 and "home network" in r.text
    assert r.headers["content-security-policy"].startswith("default-src 'none'")
    assert "<style" not in r.text and " style=" not in r.text


def test_outsiders_get_the_refusal_page_and_its_files(store, passfile):
    """04 11.1: /intake outside the home network is the refusal page; the files it links answer anyone, the rest does
    not."""
    with TestClient(_app(store, passfile), client=AWAY) as c:
        page = c.get("/intake")
        assert page.status_code == 403 and "<h1>Only on the home network</h1>" in page.text
        assert "filament-kit only works on the home network. Connect this phone" in page.text
        assert "<title>filament-kit</title>" in page.text and ">Try again</a>" in page.text
        assert "intake/shared/tokens.css" in page.text and "<form" not in page.text
        for path in ("/intake/shared/theme-init.js", "/intake/shared/tokens.css", "/intake/shared/components.css",
                     "/intake/app.css"):
            assert c.get(path).status_code != 403, path
        for path in ("/intake/app.js", "/intake/signin.js", "/intake/shared/strings.js"):
            assert c.get(path).status_code == 403, path
    with TestClient(_app(store, passfile), client=("2001:db8::7", 1)) as c:
        assert "IPv6" in c.get("/intake").text                     # the Hub's IPv6 hint as a second paragraph


def test_lan_only_lets_lan_and_loopback_through(store, passfile):
    for who in (HOME, ("127.0.0.1", 1), ("::1", 1), ("::ffff:192.168.1.77", 1)):
        with TestClient(_app(store, passfile), client=who) as c:
            assert c.get("/intake/api/find").text == "intake"


def test_lan_only_leaves_other_routes_public(store, passfile):
    with TestClient(_app(store, passfile), client=AWAY) as c:
        assert c.get("/mcp").text == "mcp"
        assert c.get("/.well-known/oauth-authorization-server").status_code == 200


def test_is_lan():
    nets = auth.parse_lan(["192.168.1.0/24", "10.0.0.0/8"])
    assert auth.is_lan("192.168.1.5", nets) and auth.is_lan("10.2.3.4", nets) and auth.is_lan("127.0.0.1", nets)
    assert not auth.is_lan("192.168.2.5", nets) and not auth.is_lan("8.8.8.8", nets)
    assert not auth.is_lan("", nets) and not auth.is_lan("testclient", nets)


# ---------- store ----------

def test_store_creates_parent_and_writes_0600_atomically(store, monkeypatch):
    opened = []
    real_open = os.open

    def spy(path, flags, mode=0o777, *a, **kw):
        opened.append((str(path), mode))
        return real_open(path, flags, mode, *a, **kw)

    monkeypatch.setattr(auth.os, "open", spy)
    store.d["clients"]["c"] = {"client_id": "c"}
    store.save()
    assert store.path.exists() and not store.path.with_name(store.path.name + ".tmp").exists()
    assert opened and opened[0][1] == 0o600 and opened[0][0].endswith(".tmp")
    if os.name != "nt":
        assert (store.path.stat().st_mode & 0o777) == 0o600


def test_store_save_failure_leaves_old_file(store, monkeypatch):
    store.d["clients"]["a"] = {"client_id": "a"}
    store.save()
    before = store.path.read_bytes()

    def boom(*a, **kw):
        raise OSError("disk full")

    monkeypatch.setattr(auth.os, "replace", boom)
    store.d["clients"]["b"] = {"client_id": "b"}
    with pytest.raises(OSError):
        store.save()
    assert store.path.read_bytes() == before


def test_store_prunes_expired_on_save(store, clock):
    for k in ("codes", "access", "refresh", "used"):
        store.d[k] = {"old": {"client_id": "c", "expires_at": clock.now - 1},
                      "new": {"client_id": "c", "expires_at": clock.now + 60}}
    store.save()
    d = json.loads(store.path.read_text(encoding="utf-8"))
    for k in ("codes", "access", "refresh", "used"):
        assert list(d[k]) == ["new"]


def test_store_loads_ops_oauth_json_unchanged(tmp_path):
    src = DATA / "ops_oauth.json"
    path = tmp_path / "oauth.json"
    shutil.copy(src, path)
    original = json.loads(src.read_text(encoding="utf-8"))
    st = auth.Store(path)
    assert st.d == {k: v for k, v in original.items() if k != "sessions"}  # the gone "sessions" key is dropped
    p = auth.Provider(st, PUBLIC)
    cid = "8d3c2f0e-ops-client"
    client = run(p.get_client(cid))
    assert client is not None and [str(u) for u in client.redirect_uris] == [CB]
    assert run(p.load_access_token("ops-access-token")).client_id == cid
    assert run(p.load_refresh_token(client, "ops-refresh-token")).scopes == ["filament"]
    st.save()  # and writes it back in the same shape
    again = json.loads(path.read_text(encoding="utf-8"))
    assert set(again) == {"clients", "codes", "access", "refresh", "used"}
    assert again["clients"] == original["clients"] and again["refresh"] == original["refresh"]


def test_store_starts_empty(store):
    assert set(store.d) == {"clients", "codes", "access", "refresh", "used"}
    assert all(v == {} for v in store.d.values()) and store.pending == {}


# ---------- passphrase ----------

def test_hash_passphrase_format_and_check(tmp_path):
    h = auth.hash_passphrase(PASS)
    salt, digest = h.split()
    assert len(bytes.fromhex(salt)) == 16 and len(bytes.fromhex(digest)) == 64
    assert auth.hash_passphrase(PASS) != h  # fresh salt each time
    f = tmp_path / "p"
    f.write_text(h + "\n", encoding="utf-8")
    assert auth.check_passphrase(PASS, f) is True
    assert auth.check_passphrase(PASS + "x", f) is False
    assert auth.check_passphrase("", f) is False


def test_hash_passphrase_refuses_short_ones():
    for short in ("", "elevenchars", " " * 11, "x" * (auth.MIN_PASSPHRASE - 1)):
        with pytest.raises(ValueError, match="at least 12"):
            auth.hash_passphrase(short)
    assert auth.MIN_PASSPHRASE == 12
    auth.hash_passphrase("x" * auth.MIN_PASSPHRASE)  # exactly 12 is fine


def test_login_routes_need_a_lockout(store, passfile):
    with pytest.raises(TypeError):
        auth.login_routes(store, PUBLIC, passfile, lan_cidrs=LAN)  # the shared Lockout is required


def test_check_passphrase_reads_ops_file(tmp_path):
    # exactly what ops set_passphrase.py writes
    salt = bytes(range(16))
    digest = hashlib.scrypt(b"ops passphrase!", salt=salt, n=2 ** 15, r=8, p=1, maxmem=2 ** 26).hex()
    f = tmp_path / "passphrase"
    f.write_text(f"{salt.hex()} {digest}\n", encoding="utf-8")
    assert auth.check_passphrase("ops passphrase!", f) is True


def test_check_passphrase_unset(tmp_path):
    assert auth.check_passphrase(PASS, tmp_path / "missing") is None
    bad = tmp_path / "bad"
    bad.write_text("not a hash", encoding="utf-8")
    assert auth.check_passphrase(PASS, bad) is None


# ---------- lockout ----------

def test_lockout_window(clock):
    lock = auth.Lockout()
    for _ in range(4):
        assert lock.attempt() is not None
        clock.now += 100
    assert lock.attempt() is not None
    assert lock.attempt() is None  # five counted in the window
    clock.now += 201  # the first failure is now older than 600 s
    assert lock.attempt() is not None


# ---------- A-M1: the lockout counts an attempt before the (slow) check ----------

def test_lockout_attempts_are_counted_before_the_check():
    import threading
    lock = auth.Lockout()
    gate = threading.Barrier(20)
    got = []

    def go():
        gate.wait()
        got.append(lock.attempt())

    ts = [threading.Thread(target=go) for _ in range(20)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    granted = [g for g in got if g is not None]
    assert len(granted) == auth.LOCK_MAX and lock.attempt() is None
    lock.release(granted[0])                  # a right passphrase does not count
    assert lock.attempt() is not None and lock.attempt() is None


def test_parallel_wrong_passphrases_get_at_most_lock_max_checks(store, passfile, monkeypatch):
    """Many sign-ins at once: each is counted before scrypt runs, so at most LOCK_MAX are ever checked."""
    import threading
    checks = []

    def slow_wrong(text, path):
        checks.append(text)
        time.sleep(0.3)
        return False

    monkeypatch.setattr(auth, "check_passphrase", slow_wrong)
    app = _app(store, passfile)
    with TestClient(app, client=HOME) as c:
        cid = _register(c).json()["client_id"]
        r = c.get("/authorize", params={"response_type": "code", "client_id": cid, "redirect_uri": CB,
                                        "code_challenge": _pkce()[1], "code_challenge_method": "S256",
                                        "state": "s", "scope": "filament"}, follow_redirects=False)
        rid = parse_qs(urlparse(r.headers["location"]).query)["req"][0]
        codes = []

        def post():
            codes.append(c.post("/login", data={"req": rid, "passphrase": "guess"}, headers={"Origin": ORIGIN},
                                follow_redirects=False).status_code)

        ts = [threading.Thread(target=post) for _ in range(12)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
    assert len(checks) == auth.LOCK_MAX
    assert sorted(codes) == [401] * len(checks) + [429] * (12 - len(checks))


def test_right_passphrase_does_not_count_towards_the_lockout(store, passfile):
    lock = auth.Lockout()
    with TestClient(_app(store, passfile, lockout=lock), client=HOME) as c:
        cid = _register(c).json()["client_id"]
        for _ in range(auth.LOCK_MAX + 1):
            r, _ = _sign_in(c, cid, _pkce()[1])
            assert r.status_code == 302
    assert lock.fails == []
