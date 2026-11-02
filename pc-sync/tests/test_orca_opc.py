import os
from pathlib import Path

import pytest

import orca_fixture
from fksync import orca_opc

# read-only; the test is skipped on a PC without this Orca install
REAL_OPC = Path(os.environ.get("FKSYNC_REAL_OPC")
                or "G:/Program Files/OrcaSlicer 2.5.0/resources/profiles/OrcaFilamentLibrary.opc")


def test_library_presets_from_a_synthetic_blob():
    got = orca_opc.library_presets(orca_fixture.opc_blob(orca_fixture.LIBRARY))
    assert [p["name"] for p in got] == ["Acme PLA+ @System", "Eolas ABS @System", "Generic PLA @System"]
    by = {p["name"]: p for p in got}
    # filament_id and type come from the @base / fdm_filament_* records it inherits
    assert by["Acme PLA+ @System"] == {"name": "Acme PLA+ @System", "setting_id": "8EZyKHm5JquwOtfP",
                                       "filament_id": "OFAcme01", "filament_type": "PLA",
                                       "inherits": "Acme PLA+ @base"}
    assert by["Generic PLA @System"] == {"name": "Generic PLA @System", "setting_id": "RcBNzytWgwRrwXXz",
                                         "filament_id": "OFDSrzZ8", "filament_type": "PLA",
                                         "inherits": "fdm_filament_pla"}
    # a parent that is not in the blob: only what the record itself says
    assert by["Eolas ABS @System"] == {"name": "Eolas ABS @System", "setting_id": "R1lkPc60BdFq6i2Z",
                                       "filament_id": "OFXCBZTA", "filament_type": "ABS",
                                       "inherits": "fdm_filament_abs"}


def test_library_presets_missing_fields_are_none():
    blob = orca_fixture.opc_blob([{"name": "Generic PP @System", "setting_id": "yos4oScjK83JuXJV"}])
    assert orca_opc.library_presets(blob) == [{"name": "Generic PP @System", "setting_id": "yos4oScjK83JuXJV",
                                               "filament_id": None, "filament_type": None, "inherits": None}]


def test_library_presets_ops_fallback_and_garbage():
    # no recognisable tail: the first 16-character token after the record (ops gen.py orca_lib_ids)
    blob = (orca_fixture._s("Odd PLA @System") + orca_fixture._s("filament/Odd PLA @System.json")
            + b" xx cdEFGHijklMNOPqr yy")
    assert orca_opc.library_presets(blob) == [{"name": "Odd PLA @System", "setting_id": "cdEFGHijklMNOPqr",
                                               "filament_id": None, "filament_type": None, "inherits": None}]
    assert orca_opc.library_presets(b"") == []
    assert orca_opc.library_presets(b"not an opc file at all" * 50) == []


@pytest.mark.skipif(not REAL_OPC.is_file(), reason="no Orca 2.5.0 OrcaFilamentLibrary.opc on this PC")
def test_library_presets_real_opc():
    got = {p["name"]: p for p in orca_opc.library_presets(REAL_OPC.read_bytes())}
    assert len(got) > 200
    # the two ids ops gen.py asserts at import
    assert got["SUNLU PLA+ 2.0 @System"]["setting_id"] == "8EZyKHm5JquwOtfP"
    assert got["Overture PLA Pro @System"]["setting_id"] == "pynx7PjoLrNXAj6f"
    assert got["Generic PLA @System"]["inherits"] == "fdm_filament_pla"
    assert got["Generic PLA @System"]["filament_type"] == "PLA"
    assert all(p["setting_id"] for p in got.values())
