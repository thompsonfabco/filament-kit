import pytest

from filament_kit.bridge import models


@pytest.mark.parametrize("model,name", [
    ("O1D", "Bambu Lab H2D"), ("BL-P001", "Bambu Lab X1 Carbon"), ("X1C", "Bambu Lab X1 Carbon"),
    ("C12", "Bambu Lab P1S"), ("N1", "Bambu Lab A1 mini"), ("zz", None), (None, None), ("", None),
    ("3DPrinter-X1-Carbon", "Bambu Lab X1 Carbon"), ("Bambu Lab H2D", "Bambu Lab H2D"), ("h2d pro", "Bambu Lab H2D Pro"),
    ("H2DPRO", "Bambu Lab H2D Pro"), ("A1MINI", "Bambu Lab A1 mini"), ("o1e", "Bambu Lab H2D Pro"),
    ("X1E", "Bambu Lab X1E"), ("N2S", "Bambu Lab A1"),
])
def test_printer_preset_name(model, name):
    assert models.printer_preset_name(model) == name


@pytest.mark.parametrize("model,cmax", [
    ("O1D", 65), ("N6", 65), ("C13", 60), ("C12", None), ("O1E", 65), ("O1S", 65), ("O1C", 65), ("O1C2", 65),
    ("H2D", 65), ("X1E", 60), ("X1C", None), ("zz", None), (None, None),
])
def test_chamber_max(model, cmax):
    assert models.chamber_max(model) == cmax


@pytest.mark.parametrize("model,kind", [
    ("O1D", "hls"), ("C12", "mjpeg"), ("N9", "mjpeg"), ("X1C", "hls"), ("zz", None), (None, None),
])
def test_camera_kind(model, kind):
    assert models.camera_kind(model) == kind


def test_model_record():
    assert models.model("O1D").name == "H2D" and models.model("O1D").known
    assert models.model("zz").known is False
