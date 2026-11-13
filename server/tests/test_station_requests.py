"""Reverse pairing of a station on another machine (protocol version 2): it commits, the kit adds a nonce, it reveals,
the owner compares six digits and approves."""
from __future__ import annotations

import hashlib
import secrets
from pathlib import Path

import pytest
from starlette.testclient import TestClient
from test_setup_page import Helper, client, env, make, post  # noqa: F401

from filament_kit import cli, pairing, station_requests as sr
from filament_kit.api import create_app
from filament_kit.spoolman import Spoolman

STATIC = Path(cli.__file__).parent / "setup_static"


class Mgr:
    def sync(self):
        pass

    def state(self, serial):
        return None


@pytest.fixture(autouse=True)
def cert(env):  # noqa: F811
    """The server certificate the comparison code is made from."""
    pairing.make_cert("kit", [], pairing.config.paths().etc)


@pytest.fixture
def app(env):  # noqa: F811
    return make(env, Helper(), Mgr())


@pytest.fixture
def kit(env):  # noqa: F811
    return TestClient(create_app(Spoolman("http://127.0.0.1:9")))


def hx() -> str:
    return secrets.token_hex(32)


def fp() -> str:
    return pairing.fingerprint((pairing.config.paths().etc / "cert.pem").read_bytes())


def station(kit, name="Bench"):
    """What a station does up to the reveal: (request_id, secret, nonce)."""
    r, s = hx(), hx()
    a = kit.post("/api/station/pair-request", json={"request_id": r, "commit": sr.commitment(s), "name": name})
    assert a.status_code == 202, a.text
    nonce = a.json()["nonce"]
    assert kit.post(f"/api/station/pair-request/{r}/reveal", json={"secret": s}).status_code == 200
    return r, s, nonce


def test_the_code_is_six_digits_from_the_fingerprint_the_secret_and_the_nonce():
    f, s, n = "AB:" * 31 + "CD", "1" * 64, "2" * 64
    want = hashlib.sha256(("filament-kit station pairing v2\n" + "ab" * 31 + "cd" + "\n" + s + "\n" + n).encode()).digest()
    assert sr.comparison_code(f, s, n) == f"{int.from_bytes(want[:4], 'big') % 1000000:06d}"
    assert sr.comparison_code(f.lower().replace(":", " "), s, n) == sr.comparison_code(f, s, n)
    assert sr.comparison_code(f, s, "3" * 64) != sr.comparison_code(f, s, n)
    assert sr.commitment(s) == hashlib.sha256(("filament-kit station pairing commit\n" + s).encode()).hexdigest()


def test_commit_reveal_approve_and_the_token_goes_out_once(env, kit):  # noqa: F811
    r, s, nonce = station(kit)
    assert kit.get(f"/api/station/pair-request/{r}").status_code == 202
    [q] = sr.pending()
    assert q["name"] == "Bench" and q["code"] == sr.comparison_code(fp(), s, nonce)
    sr.decide(q["id"], True)
    got = kit.get(f"/api/station/pair-request/{r}")
    assert got.status_code == 200
    assert pairing.authorize(got.json()["token"])[1] == "station"
    assert kit.get(f"/api/station/pair-request/{r}").status_code == 410
    assert sr.pending() == []


def test_a_request_is_shown_only_after_the_reveal(env, kit):  # noqa: F811
    r, s = hx(), hx()
    kit.post("/api/station/pair-request", json={"request_id": r, "commit": sr.commitment(s)})
    assert sr.pending() == [] and kit.get(f"/api/station/pair-request/{r}").json()["state"] == "committed"


def test_a_secret_that_does_not_match_the_commitment_is_refused(env, kit):  # noqa: F811
    r, s = hx(), hx()
    kit.post("/api/station/pair-request", json={"request_id": r, "commit": sr.commitment(s)})
    assert kit.post(f"/api/station/pair-request/{r}/reveal", json={"secret": hx()}).status_code == 400
    assert sr.pending() == []


def test_the_kit_picks_its_nonce_after_the_commitment_and_keeps_it(env, kit):  # noqa: F811
    """The man in the middle's grind: a new commitment for the same id is refused, so the nonce cannot be re-rolled."""
    r, s = hx(), hx()
    n1 = kit.post("/api/station/pair-request", json={"request_id": r, "commit": sr.commitment(s)}).json()["nonce"]
    n2 = kit.post("/api/station/pair-request", json={"request_id": r, "commit": sr.commitment(s)}).json()["nonce"]
    assert n1 == n2
    assert kit.post("/api/station/pair-request", json={"request_id": r, "commit": sr.commitment(hx())}).status_code == 409


def test_version_1_requests_without_a_commitment_are_refused(env, kit):  # noqa: F811
    r = kit.post("/api/station/pair-request", json={"request_id": hx()})
    assert r.status_code == 400 and "commit" in r.json()["message"]


def test_a_refused_request_answers_gone_and_its_address_waits_out_the_window(env, kit):  # noqa: F811
    r, _, _ = station(kit)
    before = pairing.devices()
    sr.decide(sr.pending()[0]["id"], False)
    assert kit.get(f"/api/station/pair-request/{r}").status_code == 410 and pairing.devices() == before
    again = kit.post("/api/station/pair-request", json={"request_id": hx(), "commit": sr.commitment(hx())})
    assert again.status_code == 429 and again.json()["error"] == "refused"


def test_a_refused_address_is_let_in_again_only_after_the_window(env):  # noqa: F811
    r, s = hx(), hx()
    sr.ask(r, sr.commitment(s), "x", "192.0.2.31", now=1000.0)
    sr.reveal(r, s, now=1000.0)
    sr.decide(sr.pending(now=1000.0)[0]["id"], False, now=1000.0)
    with pytest.raises(sr.RequestError) as e:
        sr.ask(hx(), sr.commitment(hx()), "x", "192.0.2.31", now=1000.0 + sr.TTL - 1)
    assert (e.value.status, e.value.code) == (429, "refused")
    assert sr.ask(hx(), sr.commitment(hx()), "x", "192.0.2.31", now=1000.0 + sr.TTL + 1)["nonce"]


def test_revealing_an_unknown_request_is_404(env):  # noqa: F811
    with pytest.raises(sr.RequestError) as e:
        sr.reveal(hx(), hx())
    assert (e.value.status, e.value.code) == (404, "not_found")


def test_requests_run_out(env):  # noqa: F811
    r, s = hx(), hx()
    sr.ask(r, sr.commitment(s), "x", "192.0.2.30", now=1000.0)
    sr.reveal(r, s, now=1000.0)
    later = 1000.0 + sr.TTL + 1
    assert sr.poll(r, now=later)[0] == 410 and sr.pending(now=later) == []


def test_an_approval_nobody_fetches_is_revoked_when_it_runs_out(env):  # noqa: F811
    r, s = hx(), hx()
    sr.ask(r, sr.commitment(s), "x", "192.0.2.30", now=1000.0)
    sr.reveal(r, s, now=1000.0)
    n = len(pairing.devices())
    sr.decide(sr.pending(now=1000.0)[0]["id"], True, now=1000.0)
    assert len(pairing.devices()) == n + 1
    sr.pending(now=1000.0 + sr.TTL + 1)
    assert len(pairing.devices()) == n


def test_at_most_three_wait(env, kit):  # noqa: F811
    for _ in range(sr.MAX_PENDING):
        assert kit.post("/api/station/pair-request", json={"request_id": hx(), "commit": sr.commitment(hx())}).status_code == 202
    r = kit.post("/api/station/pair-request", json={"request_id": hx(), "commit": sr.commitment(hx())})
    assert r.status_code == 429 and r.json()["error"] == "too_many"


@pytest.mark.parametrize("bad", ["", "x" * 64, "A" * 64, "0" * 63, None, 5])
def test_ids_and_commitments_are_64_hex(env, kit, bad):  # noqa: F811
    assert kit.post("/api/station/pair-request", json={"request_id": bad, "commit": hx()}).status_code == 400
    assert kit.post("/api/station/pair-request", json={"request_id": hx(), "commit": bad}).status_code == 400


def test_a_name_is_cleaned(env, kit):  # noqa: F811
    station(kit, "<script>Bench</script>" + "x" * 80)
    name = sr.pending()[0]["name"]
    assert "<" not in name and len(name) <= 40


def test_the_page_lists_and_answers_with_the_code_only(app, env, kit):  # noqa: F811
    r, s, nonce = station(kit)
    c = client(app)
    assert post(c, "stations/requests", {}, code=None).status_code in (401, 403)
    assert post(c, "stations/requests", {}, code="0000-0000").status_code == 403
    [q] = post(c, "stations/requests", {}).json()["requests"]
    assert q["code"] == sr.comparison_code(fp(), s, nonce)
    assert post(c, f"stations/requests/{q['id']}/pair", {}, code="0000-0000").status_code == 403
    assert post(c, f"stations/requests/{q['id']}/pair", {}).json()["approved"] is True
    assert post(c, f"stations/requests/{q['id']}/pair", {}).status_code == 404       # answered already
    assert post(c, "stations/requests/nope/refuse", {}).status_code == 404
    assert sr.poll(r)[0] == 200


def test_the_devices_tab_has_the_card():
    src = (STATIC / "setup.js").read_text(encoding="utf-8")
    assert "stationAsksCard()" in src and "Pair only if the station shows the same six digits" in src
