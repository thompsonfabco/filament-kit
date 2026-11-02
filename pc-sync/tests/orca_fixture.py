"""Builds a fake Orca Slicer data tree (and a synthetic OrcaFilamentLibrary.opc) for tests (never the real one)."""
import json
import struct
from pathlib import Path

from fksync.studio import OrcaFolders

USER_ID = "0f0e0d0c-1111-2222-3333-444455556666"
BBL_SYSTEM = {
    "Bambu PLA Basic @BBL H2D.json": {"type": "filament", "name": "Bambu PLA Basic @BBL H2D",
                                      "inherits": "Bambu PLA Basic @base", "from": "system",
                                      "setting_id": "GFSA00_10", "instantiation": "true"},
    "Bambu PLA Basic @base.json": {"type": "filament", "name": "Bambu PLA Basic @base", "inherits": "fdm_filament_pla",
                                   "from": "system", "filament_id": "GFA00", "instantiation": "false"},
    "SUNLU/SUNLU PLA+ @BBL H2D.json": {"type": "filament", "name": "SUNLU PLA+ @BBL H2D",
                                       "inherits": "fdm_filament_pla", "from": "system"},
}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=4)
        f.write("\n")


def write_info(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("".join(f"{k} = {v}\n" for k, v in data.items()))


# --- synthetic .opc ------------------------------------------------------------------------------

def _s(text: str | bytes) -> bytes:
    raw = text.encode("ascii") if isinstance(text, str) else text
    return struct.pack("<Q", len(raw)) + raw


KEYS = ["chamber_temperature", "filament_flow_ratio", "filament_type", "filament_vendor"]


def opc_blob(records: list[dict]) -> bytes:
    """A small ZCRO blob in Orca 2.5.0's layout (as far as fksync.orca_opc reads it). Each record:
    {name, path?, inherits?, instantiation ("true"), setting_id?, filament_id?, filament_type?, vendor?}."""
    out = bytearray(b"ZCRO" + struct.pack("<IQII", 2, 0, 0x1234, 2))
    out += _s("OrcaFilamentLibrary") + _s("2.4.0.24")
    out += struct.pack("<Q", len(KEYS)) + b"".join(_s(k) for k in KEYS)
    out += struct.pack("<Q", len(KEYS)) + b"\x08@" * len(KEYS)          # the type table (not read)
    for r in records:
        out += _s(r["name"]) + _s(r.get("path") or f"filament/{r['name']}.json")
        values = bytearray()
        n = 1
        values += struct.pack("<HQ", KEYS.index("filament_flow_ratio"), 1) + struct.pack("<d", 0.98)
        if r.get("vendor"):
            values += struct.pack("<HQ", KEYS.index("filament_vendor"), 1) + _s(r["vendor"])
            n += 1
        if r.get("filament_type"):
            values += struct.pack("<HQ", KEYS.index("filament_type"), 1) + _s(r["filament_type"])
            n += 1
        out += struct.pack("<I", n) + values
        out += _s(r["inherits"]) if r.get("inherits") else b"\0" * 8
        out += b"\0" * 16 + _s(r.get("instantiation", "true"))
        out += _s(r["setting_id"]) if r.get("setting_id") else b"\0" * 8
        out += _s(r["filament_id"]) if r.get("filament_id") else b"\0" * 8
        out += b"\0" * 8
    return bytes(out)


LIBRARY = [
    {"name": "fdm_filament_pla", "path": "filament/base/fdm_filament_pla.json", "instantiation": "false",
     "filament_type": "PLA"},
    {"name": "Generic PLA @System", "inherits": "fdm_filament_pla", "setting_id": "RcBNzytWgwRrwXXz",
     "filament_id": "OFDSrzZ8"},
    {"name": "Acme PLA+ @base", "path": "filament/Acme/Acme PLA+ @base.json", "inherits": "fdm_filament_pla",
     "instantiation": "false", "filament_id": "OFAcme01", "vendor": "Acme"},
    {"name": "Acme PLA+ @System", "path": "filament/Acme/Acme PLA+ @System.json", "inherits": "Acme PLA+ @base",
     "setting_id": "8EZyKHm5JquwOtfP"},
    {"name": "Eolas ABS @System", "inherits": "fdm_filament_abs", "setting_id": "R1lkPc60BdFq6i2Z",
     "filament_id": "OFXCBZTA", "filament_type": "ABS", "vendor": "Eolas"},
]


# --- the Orca tree -------------------------------------------------------------------------------

def make(appdata: Path, *, user_id: str = USER_ID, presets: dict[str, tuple[dict, dict]] = {},
         conf_folder: str | None = None, system: dict[str, dict] | None = None,
         install: Path | None = None, opc: bytes | None = None) -> OrcaFolders:
    """Write appdata/OrcaSlicer/{OrcaSlicer.conf, user/<id>/filament, system/BBL/filament}.

    presets: name -> (json, info) written flat as filament/<name>.json + .info (Orca's layout)
    conf_folder: app.preset_folder in OrcaSlicer.conf (default user_id); the conf ends with Orca's MD5 line
    system: rel path -> json under system/BBL/filament (default BBL_SYSTEM)
    install: a fake install dir (orca-slicer.exe + resources/profiles/OrcaFilamentLibrary.opc from `opc`)
    """
    root = Path(appdata) / "OrcaSlicer"
    user_filament = root / "user" / user_id / "filament"
    user_filament.mkdir(parents=True, exist_ok=True)
    conf = root / "OrcaSlicer.conf"
    conf.write_text(json.dumps({"app": {"preset_folder": conf_folder or user_id, "version": "2.5.0"}}, indent=4)
                    + "\n# MD5 checksum 00000000000000000000000000000000\n", encoding="utf-8")
    for name, (data, info) in presets.items():
        _write_json(user_filament / f"{name}.json", data)
        write_info(user_filament / f"{name}.info", info)
    system_bbl = root / "system" / "BBL" / "filament"
    for rel, data in (BBL_SYSTEM if system is None else system).items():
        _write_json(system_bbl / rel, data)
    opc_path = None
    if install is not None:
        install.mkdir(parents=True, exist_ok=True)
        (install / "orca-slicer.exe").write_bytes(b"MZ")
        if opc is not None:
            opc_path = install / "resources" / "profiles" / "OrcaFilamentLibrary.opc"
            opc_path.parent.mkdir(parents=True, exist_ok=True)
            opc_path.write_bytes(opc)
    return OrcaFolders(root=root, user_id=user_id, user_filament=user_filament, system_bbl=system_bbl,
                       install=install, library_opc=opc_path)
