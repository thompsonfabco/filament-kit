"""The station's intake flow end to end against the REAL kit API: uvicorn with the kit's TLS certificate, the fake
Spoolman and FakeClaude, the station paired the way `filament-kit station pair` pairs it, and flow.api() building
its ServerApi from those pairing files. Only the hardware is fake: the camera, the scale reading and the panel's
serial port. tag -> camera -> recognise -> weigh -> long press -> spool created and tag linked."""
from __future__ import annotations

import threading
import time

import pytest
import uvicorn
from fakes.claude_fake import FakeClaude

from conftest import free_port
from filament_kit import config, inventory, pairing, tags
from filament_kit.api import create_app
from filament_kit.spoolman import Spoolman
from filament_kit.station import camera, flow, nfc, panel, server_api, speech
from filament_kit.station import state as st

UID = "4:77:90:e:9:22:89"
JPEG = b"\xff\xd8\xff\xe0" + b"x" * 100
ITEM = {"photos": [0], "existing_filament_id": None, "vendor": "OVERTURE", "name": "PETG Black",
        "material": "PETG", "color_hex": "111111", "net": 1000, "tare": 155, "density": 1.27, "count": 1,
        "nozzle": 240, "bed": 75, "nozzle_range": "230-250", "bed_range": "70-80", "lot": None, "note": "",
        "estimates": [], "sealed": False, "sealed_reason": "bare spool", "line": "PETG"}


class Ser:
    port = "/dev/ttyFAKE"

    def __init__(self):
        self.lines: list[str] = []

    def write(self, data):
        self.lines += [ln for ln in data.decode().split("\n") if ln]


@pytest.fixture(autouse=True)
def fk_env(tmp_path, monkeypatch):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    pairing.make_cert("fkhost", ["127.0.0.1"], tmp_path / "etc")
    config.save({"placement": {"box_count": 2}})  # a legacy config: ai_intake on
    monkeypatch.setattr(inventory, "_record_lines", lambda items: None)
    monkeypatch.setattr(inventory, "_check_parents", lambda items: None)


@pytest.fixture
def kit(spoolman_url, tmp_path):
    sm = Spoolman(spoolman_url)
    sm.ensure_fields()
    port = free_port()
    etc = tmp_path / "etc"
    srv = uvicorn.Server(uvicorn.Config(create_app(sm=sm, claude=FakeClaude({"questions": [], "items": [ITEM]})),
                                        host="127.0.0.1", port=port, log_level="warning",
                                        ssl_certfile=str(etc / "cert.pem"), ssl_keyfile=str(etc / "key.pem")))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    fp = pairing.fingerprint((etc / "cert.pem").read_bytes())
    tok = pairing.redeem_code(pairing.issue("station").code)
    server_api.save_pairing(server_api.Link("kit.example.com", port, tok, fp, ["127.0.0.1"]), owner=None)
    yield sm
    srv.should_exit = True
    t.join(5)


@pytest.fixture
def station(monkeypatch):
    with st.lock:
        saved_state, saved_flow = dict(st.state), dict(st.flow)
        st.state.update(tag=None, tag_at=None, scale=None, held=None, held_at=None, photo=None, photo_at=None,
                        blink_until=0)
        st.flow.update(step="idle", seq=0, spool=None, filament=None, display=[], message="", at=0.0)
    ser = Ser()
    monkeypatch.setitem(st.panel, "ser", ser)
    monkeypatch.setitem(st.settings, "recognise_timeout", 20)
    monkeypatch.setattr(flow, "_api", {"key": None, "api": None})
    monkeypatch.setattr(camera, "grab_photo", lambda: (JPEG, None))
    monkeypatch.setattr(speech, "say", lambda text: None)
    yield ser
    with st.lock:
        st.state.clear()
        st.state.update(saved_state)
        st.flow.clear()
        st.flow.update(saved_flow)


def wait_step(want, secs=20):
    end = time.time() + secs
    while flow.flow["step"] != want and time.time() < end:
        time.sleep(0.05)
    return flow.flow["step"]


def test_new_spool_from_tag_to_spoolman(kit, station):
    sm = kit
    seen = panel.Shown()

    def rows():
        st.panel_dirty.set()
        panel.refresh(seen, time.time())
        return seen.rows

    nfc.on_tag(UID)  # the real threads: lookup runs off the reader thread
    assert wait_step("camera") == "camera", flow.flow
    assert rows()[0] == "New Tag Scanned"
    panel.on_line(b"P H")
    assert wait_step("weigh") == "weigh", flow.flow
    assert rows()[0] == "PETG Black" and flow.flow["filament"]["vendor"] == "OVERTURE"
    with st.lock:
        st.state.update(scale={"grams": 900.0, "status": "stable", "unit": 2}, scale_at=time.time())
    panel.on_line(b"P H")
    assert flow.flow["step"] == "ready" and rows()[0] == "900 g"
    panel.on_line(b"L H")
    assert wait_step("done") == "done", flow.flow
    assert rows()[0] == "Saved"
    s = inventory.by_tag(sm, tags.normalize_uid(UID))
    assert s is not None and s["remaining_weight"] == 745  # 900 g gross - 155 g tare: an opened spool
    assert (s["filament"]["vendor"]["name"], s["filament"]["name"]) == ("OVERTURE", "PETG Black")

    # the same tag again: linked now, so straight to weighing, and the save only updates the weight
    nfc.on_tag(UID)
    assert wait_step("weigh") == "weigh" and flow.flow["spool"]["id"] == s["id"]
    with st.lock:
        st.state.update(scale={"grams": 800.0, "status": "stable", "unit": 2}, scale_at=time.time())
    panel.on_line(b"P H")
    panel.on_line(b"L H")
    assert wait_step("done") == "done", flow.flow
    assert inventory.by_tag(sm, tags.normalize_uid(UID))["remaining_weight"] == 645
