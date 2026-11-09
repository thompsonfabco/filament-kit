"""Reverse pairing of a station on another machine: it asks, the owner compares six digits and approves."""
from __future__ import annotations

import hashlib
import secrets
from pathlib import Path

import pytest
from starlette.testclient import TestClient
from test_setup_page import Helper, client, env, make, post  # noqa: F401

from filament_kit import cli, pairing, station_requests
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


def rid() -> str:
    return secrets.token_hex(32)


def test_the_comparison_code_is_six_digits_both_sides_derive_alike():
    fp = "AB:" * 31 + "CD"
    r = "0" * 64
    want = f"{int.from_bytes(hashlib.sha256(('filament-kit station pairing\n' + 'ab' * 31 + 'cd' + '\n' + r).encode()).digest()[:4], 'big') % 1000000:06d}"
    assert station_requests.comparison_code(fp, r) == want and len(want) == 6
    assert station_requests.comparison_code(fp.lower().replace(":", " "), r) == want
    assert station_requests.comparison_code(fp, "1" * 64) != want


def test_ask_then_approve_then_the_token_goes_out_once(env, kit):  # noqa: F811
    r = rid()
    assert kit.post("/api/station/pair-request", json={"request_id": r, "name": "Bench"}).status_code == 202
    assert kit.get(f"/api/station/pair-request/{r}").status_code == 202
    [q] = station_requests.pending()
    fp = pairing.fingerprint((pairing.config.paths().etc / "cert.pem").read_bytes())
    assert q["name"] == "Bench" and q["code"] == station_requests.comparison_code(fp, r)
    station_requests.decide(q["id"], True)
    got = kit.get(f"/api/station/pair-request/{r}")
    assert got.status_code == 200
    token = got.json()["token"]
    assert pairing.authorize(token)[1] == "station"          # the station's token reaches /api/station/* only
    assert kit.get(f"/api/station/pair-request/{r}").status_code == 410
    assert station_requests.pending() == []


def test_a_refused_request_answers_gone_and_pairs_nothing(env, kit):  # noqa: F811
    r = rid()
    kit.post("/api/station/pair-request", json={"request_id": r})
    before = pairing.devices()
    station_requests.decide(station_requests.pending()[0]["id"], False)
    assert kit.get(f"/api/station/pair-request/{r}").status_code == 410 and pairing.devices() == before


def test_requests_run_out(env, kit):  # noqa: F811
    r = rid()
    station_requests.ask(r, "x", "192.0.2.30", now=1000.0)
    assert station_requests.poll(r, now=1000.0 + station_requests.TTL + 1)[0] == 410
    assert station_requests.pending(now=1000.0 + station_requests.TTL + 1) == []


def test_at_most_three_wait(env, kit):  # noqa: F811
    for _ in range(station_requests.MAX_PENDING):
        assert kit.post("/api/station/pair-request", json={"request_id": rid()}).status_code == 202
    r = kit.post("/api/station/pair-request", json={"request_id": rid()})
    assert r.status_code == 429 and r.json()["error"] == "too_many"


def test_asking_again_with_the_same_id_is_one_request(env, kit):  # noqa: F811
    r = rid()
    for _ in range(5):
        assert kit.post("/api/station/pair-request", json={"request_id": r}).status_code == 202
    assert len(station_requests.pending()) == 1


@pytest.mark.parametrize("bad", ["", "x" * 64, "A" * 64, "0" * 63, None, 5])
def test_a_request_id_is_64_hex(env, kit, bad):  # noqa: F811
    assert kit.post("/api/station/pair-request", json={"request_id": bad}).status_code == 400
    assert station_requests.pending() == []


def test_a_name_is_cleaned(env):  # noqa: F811
    station_requests.ask(rid(), "<script>Bench</script>" + "x" * 80, "192.0.2.30")
    name = station_requests.pending()[0]["name"]
    assert "<" not in name and len(name) <= 40


def test_the_page_lists_and_answers_with_the_code_only(app, env):  # noqa: F811
    r = rid()
    station_requests.ask(r, "Bench", "192.0.2.30")
    c = client(app)
    assert post(c, "stations/requests", {}, code=None).status_code in (401, 403)
    assert post(c, "stations/requests", {}, code="0000-0000").status_code == 403
    [q] = post(c, "stations/requests", {}).json()["requests"]
    assert q["address"] == "192.0.2.30" and len(q["code"]) == 6
    assert post(c, f"stations/requests/{q['id']}/pair", {}, code="0000-0000").status_code == 403
    assert post(c, f"stations/requests/{q['id']}/pair", {}).json()["approved"] is True
    assert post(c, f"stations/requests/{q['id']}/pair", {}).status_code == 404       # answered already
    assert post(c, "stations/requests/nope/refuse", {}).status_code == 404
    assert station_requests.poll(r)[0] == 200


def test_the_devices_tab_has_the_card():
    src = (STATIC / "setup.js").read_text(encoding="utf-8")
    assert "stationAsksCard()" in src and "function stationAsksCard(" in src
    assert "Pair only if the station shows the same six digits" in src
