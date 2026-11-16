"""The Weigh Station in the paired devices list: its type (also for a pairing made before scopes existed), and whether it
answers, so an idle station is not shown as dead. Example names and ports only."""
from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from filament_kit import cli, config, pairing, station_client


@pytest.fixture(autouse=True)
def hub(tmp_path, monkeypatch):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    monkeypatch.setenv("FK_NO_SYSTEMD", "1")
    pairing.make_cert("fkhost", ["192.0.2.5"], tmp_path / "etc")
    monkeypatch.setattr(cli, "_is_root", lambda: True)
    station_client._reach.clear()


@pytest.fixture
def station():
    """A station's read-only view: GET /state answers 200."""
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"tag": {}, "scale": null, "last_weight": null}')

        def log_message(self, *a):
            pass
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def closed_port_url():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{port}"


def old_station_pairing():
    """A station paired before scopes existed: named "station", no `scope` key in devices.json."""
    p = pairing.issue(device_hint="station")
    pairing.redeem_code(p.code)
    path = config.paths().state / "devices.json"
    devs = json.loads(path.read_text())
    for d in devs:
        d.pop("scope", None)
    path.write_text(json.dumps(devs))


def set_station_url(url):
    c = config.load()
    c["station"] = {**c["station"], "url": url}
    config.save(c)


def test_a_pairing_without_a_scope_is_listed_as_a_weigh_station():
    old_station_pairing()
    p = pairing.issue(device_hint="Bench", scope="station")
    pairing.redeem_code(p.code)
    q = pairing.issue(device_hint="Shop phone")
    pairing.redeem_code(q.code)
    assert {d["name"]: d["type"] for d in pairing.devices()} == {"station": "station", "Bench": "station", "Shop phone": None}


def test_the_cli_lists_the_type_and_that_an_idle_station_answers(capsys, station):
    old_station_pairing()
    set_station_url(station)
    assert cli.main(["devices"]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0].split() == ["NAME", "TYPE", "PAIRED", "LAST", "SEEN", "STATUS", "ID"]
    row = out.splitlines()[1]
    assert "Weigh Station" in row and "(last intake)" in row and "answering" in row and "not answering" not in row
    assert cli.main(["devices", "--json"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got[0]["type"] == "station" and got[0]["reachable"] is True


def test_the_cli_says_when_the_station_does_not_answer(capsys):
    old_station_pairing()
    set_station_url(closed_port_url())
    assert cli.main(["devices", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["reachable"] is False
    station_client._reach.clear()
    assert cli.main(["devices"]) == 0
    assert "not answering" in capsys.readouterr().out


def test_nothing_is_claimed_without_a_station_address(capsys):
    old_station_pairing()
    assert cli.main(["devices", "--json"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got[0]["type"] == "station" and got[0]["reachable"] is None


def test_two_station_pairings_are_not_guessed_at(station):
    old_station_pairing()
    p = pairing.issue(device_hint="Bench", scope="station")
    pairing.redeem_code(p.code)
    assert station_client.station_reach(pairing.devices(), station) == {}


def test_the_answer_is_reused_for_a_short_while(station, monkeypatch):
    old_station_pairing()
    devs = pairing.devices()
    assert station_client.station_reach(devs, station) == {devs[0]["id"]: True}
    monkeypatch.setattr(station_client, "StationClient", lambda *a, **k: pytest.fail("asked again"))
    assert station_client.station_reach(devs, station) == {devs[0]["id"]: True}
