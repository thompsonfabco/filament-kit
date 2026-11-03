"""P3, review focus 1: a printer with 16 AMS units, 8 AMS HT units and two external holders: every slot's number
under the model's schemes decodes back to that slot's label in usage, and a calibration over all of them proves
the printer's scheme with one job."""
import pytest

from filament_kit.bridge import ams, calib3mf, hardware, layout, registry, usage
from filament_kit.bridge.registry import Printer

SERIAL = "S16"


def tray(i, n):
    return {"id": str(i), "tray_type": "PLA", "tray_color": f"{n:02X}{i:02X}10FF", "tray_info_idx": f"GF{n:03d}{i}"}


def big_report():
    units = [{"id": str(u), "tray": [tray(i, u) for i in range(4)]} for u in range(16)]
    units += [{"id": str(128 + h), "tray": [tray(0, 128 + h)]} for h in range(8)]
    return {"gcode_state": "IDLE", "ams": {"ams": units, "tray_now": "255"},
            "vir_slot": [dict(tray(0, 254), id="254"), dict(tray(0, 255), id="255")]}


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FK_STATE", str(tmp_path / "state"))
    monkeypatch.setenv("FK_ETC", str(tmp_path / "etc"))
    hardware._reset_cache()


@pytest.mark.parametrize("model,scheme", [("O1D", "shift8"), ("O1D", "legacy"), ("C12", "legacy")])
def test_every_slot_of_a_16_unit_printer_decodes_back(model, scheme):
    registry.upsert(Printer(SERIAL, "Big", model, "10.0.0.9", "13572468", True))
    rep = big_report()
    start = usage.start_slots(SERIAL, rep)
    lay = layout.build(rep, model)
    labels = [(u.ams_id, s.tray_id, s.label) for u in lay.units for s in u.slots]
    assert len(labels) == 16 * 4 + 8 + 2 and len({l for *_, l in labels}) == len(labels)
    hw = hardware.load()
    numbers = set()
    for a, t, label in labels:
        n = ams.scheme_global(a, t, scheme, model, hw)
        numbers.add(n)
        # calibrated with only the scheme: decoded through it, checked against the slots at the print's start
        assert usage.decode(n, ams.SlotMap(calibrated=True, scheme=scheme), model, start, hw) == (label, "scheme")
        # the calibration's own reported numbers: decoded from the map
        smap = ams.SlotMap(slots={label: {"ams_id": a, "tray_id": t, "global_id": n}}, calibrated=True)
        assert usage.decode(n, smap, model, start, hw) == (label, "map")
        assert calib3mf.fits(hw, hw.model(model), scheme, n, a, t)
    assert len(numbers) == len(labels)                        # no two slots share a number


def test_uncalibrated_16_unit_h2d_guesses_with_shift8():
    registry.upsert(Printer(SERIAL, "Big", "O1D", "10.0.0.9", "13572468", True))
    assert usage.decode((15 << 8) | 3, ams.SlotMap(), "O1D") == ("P4", "model")
    assert usage.decode(135 << 8, ams.SlotMap(), "O1D") == ("HT-H", "model")
