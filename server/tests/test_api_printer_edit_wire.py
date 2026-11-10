"""Review R103 on the wire: after any PATCH a paired device may send alone, a host at the new address never receives
the stored Access Code. A real Manager (paho, TLS pinning) against the e2e's fake printer on 127.0.0.1."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
from starlette.testclient import TestClient

pytest.importorskip("paho.mqtt")
pytest.importorskip("cryptography")

from filament_kit import config, pairing  # noqa: E402
from filament_kit.api import create_app  # noqa: E402
from filament_kit.bridge import family, registry  # noqa: E402
from filament_kit.bridge.connection import Manager  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "e2e"))
import fake_printer  # noqa: E402

SERIAL = "01P00A444444444"
STORED = "11112222"


class Listening(fake_printer.Broker):
    """The fake printer at the address a device names; it records every password it is sent."""

    def __init__(self, *a, **k):
        self.passwords = []
        super().__init__(*a, **k)

    def _parse_connect(self, body):
        user, password = super()._parse_connect(body)
        self.passwords.append(password)
        return user, password


@pytest.fixture
def rig(tmp_path, monkeypatch):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    pairing.make_cert("fkhost", [], tmp_path / "etc")
    config.save({})
    host = Listening(SERIAL, "99998888", tmp_path / "certs", host="127.0.0.1", port=0)
    port = host.srv.getsockname()[1]
    # the real printer, elsewhere, pinned long ago
    registry.upsert(registry.Printer(SERIAL, "Shop P1S", "C12", "192.0.2.50", STORED, True, cert_fp="cd" * 32))
    m = Manager(port=port)
    app = create_app(object(), printers=family.Printers(bambu=m, klipper=None), camera_hub=object(), mapper=object(),
                     enabled_modules=frozenset({"server", "printers"}))
    c = TestClient(app)
    c.headers["Authorization"] = "Bearer " + pairing.redeem_code(pairing.issue().code)
    yield c, m, host
    m.stop()
    host.close()


def _settle(m, host, seconds=4.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end and m.state(SERIAL) not in ("connected", "cert_changed", "wrong_code"):
        time.sleep(0.1)
    time.sleep(0.3)


def test_a_new_address_alone_keeps_the_pin_and_the_code(rig):
    c, m, host = rig
    assert c.patch(f"/api/printers/{SERIAL}", json={"address": "127.0.0.1"}).status_code == 200
    _settle(m, host)
    assert m.state(SERIAL) == "cert_changed" and STORED not in host.passwords


def test_unpin_without_a_code_is_refused_and_sends_nothing(rig):
    c, m, host = rig
    r = c.patch(f"/api/printers/{SERIAL}", json={"address": "127.0.0.1", "unpin": True})
    assert r.status_code == 400
    m.sync()
    _settle(m, host, 1.5)
    assert host.passwords == []


def test_unpin_with_a_code_sends_only_that_code(rig):
    c, m, host = rig
    r = c.patch(f"/api/printers/{SERIAL}", json={"address": "127.0.0.1", "unpin": True, "access_code": "55556666"})
    assert r.status_code == 200
    _settle(m, host)
    assert host.passwords and set(host.passwords) == {"55556666"}
