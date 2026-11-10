"""The panel's own PN532 (firmware 11): `TAG <hex>` lines reach the intake flow like the USB reader's tags, the same tag
from either reader within 2 s is one tap, and `NFC ok` / `NFC none` is recorded."""
from __future__ import annotations

import time
import types

import pytest

from filament_kit.station import flow
from filament_kit.station import nfc as station_nfc
from filament_kit.station import panel as station_panel
from filament_kit.station import state as st

UID = bytes([4, 0x77, 0x90, 0x0E, 9, 0x22, 0x89])
FORMATTED = "4:77:90:e:9:22:89"


@pytest.fixture
def taps(monkeypatch):
    seen = []
    clock = [100.0]
    monkeypatch.setattr(flow, "on_tag", seen.append)
    monkeypatch.setattr(station_nfc, "time", types.SimpleNamespace(monotonic=lambda: clock[0], sleep=time.sleep))
    station_nfc._recent.clear()
    monkeypatch.setitem(st.ports, "panel_nfc", None)
    yield seen, clock
    station_nfc._recent.clear()


def test_tag_line_reaches_the_flow_with_the_usb_readers_id(taps):
    seen, _ = taps
    station_panel.on_line(b"TAG 0477900e092289")
    station_nfc.on_identifier(UID)  # what the USB reader does, a moment later: the same tap
    assert seen == [FORMATTED]


def test_tag_line_formats_like_format_uid(taps):
    seen, _ = taps
    station_panel.on_line(b"TAG " + UID.hex().encode())
    assert seen == [FORMATTED]


def test_same_tag_from_panel_then_usb_within_2s_is_one_tap(taps):
    seen, clock = taps
    station_panel.on_line(b"TAG " + UID.hex().encode())
    clock[0] += 1.9
    station_nfc.on_identifier(UID)
    assert seen == [FORMATTED]


def test_same_tag_from_usb_then_panel_within_2s_is_one_tap(taps):
    seen, clock = taps
    station_nfc.on_identifier(UID)
    clock[0] += 0.5
    station_panel.on_line(b"TAG " + UID.hex().encode())
    assert seen == [FORMATTED]


def test_a_different_tag_passes(taps):
    seen, clock = taps
    station_panel.on_line(b"TAG " + UID.hex().encode())
    clock[0] += 0.1
    station_nfc.on_identifier(bytes([1, 2, 3, 4]))
    clock[0] += 0.1
    station_panel.on_line(b"TAG " + UID.hex().encode())  # the first again, within 2 s of its own tap: still one
    assert seen == [FORMATTED, "1:2:3:4"]


def test_the_same_tag_after_2s_passes(taps):
    seen, clock = taps
    station_panel.on_line(b"TAG " + UID.hex().encode())
    clock[0] += 2.0
    station_nfc.on_identifier(UID)
    assert seen == [FORMATTED, FORMATTED]


def test_bad_tag_lines_are_ignored(taps):
    seen, _ = taps
    for line in (b"TAG ", b"TAG zz", b"TAG 0", b"TAG \xff\xfe"):
        station_panel.on_line(line)
    assert seen == []


def test_nfc_status_lines(taps):
    station_panel.on_line(b"NFC ok")
    assert st.ports["panel_nfc"] is True
    station_panel.on_line(b"NFC none")
    assert st.ports["panel_nfc"] is False
    assert st.view()["panel_nfc"] is False
