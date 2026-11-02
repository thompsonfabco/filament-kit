"""Builds a fake Bambu Studio data tree for tests (never the real one)."""
import json
import shutil
from pathlib import Path

from fksync.studio import StudioFolders

MINIMAL_SYSTEM = {
    "Generic PLA @BBL H2D.json": {
        "type": "filament",
        "name": "Generic PLA @BBL H2D",
        "inherits": "fdm_filament_pla",
        "from": "system",
        "setting_id": "GFSA04_09",
        "filament_id": "GFL99",
        "instantiation": "true",
        "filament_type": ["PLA"],
        "filament_vendor": ["Generic"],
        "nozzle_temperature_range_low": ["190"],
        "nozzle_temperature_range_high": ["240"],
        "compatible_printers": ["Bambu Lab H2D 0.4 nozzle"],
    }
}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=4)
        f.write("\n")


def _write_info(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("".join(f"{k} = {v}\n" for k, v in data.items()))


def make(appdata: Path, *, variant="BambuStudioBeta", user_id="1234567890",
         presets: dict[str, dict] = {}, base: dict[str, tuple[dict, dict]] = {},
         system_src: Path | None = None) -> StudioFolders:
    """Write appdata/<variant>/{BambuStudio.conf, user/<id>/filament, system/BBL/filament}.

    presets: name -> json written as filament/<name>.json
    base: name -> (json, info) written as filament/base/<name>.json + .info
    system_src: a folder copied as system/BBL/filament; otherwise one minimal Generic PLA preset.
    """
    root = Path(appdata) / variant
    root.mkdir(parents=True, exist_ok=True)
    conf = root / "BambuStudio.conf"
    if not conf.exists():
        _write_json(conf, {"app": {"version": "fixture"}})
    user_filament = root / "user" / user_id / "filament"
    (user_filament / "base").mkdir(parents=True, exist_ok=True)
    for name, data in presets.items():
        _write_json(user_filament / f"{name}.json", data)
    for name, (data, info) in base.items():
        _write_json(user_filament / "base" / f"{name}.json", data)
        _write_info(user_filament / "base" / f"{name}.info", info)
    system_filament = root / "system" / "BBL" / "filament"
    if system_src is not None:
        shutil.copytree(system_src, system_filament, dirs_exist_ok=True)
    else:
        for fname, data in MINIMAL_SYSTEM.items():
            if not (system_filament / fname).exists():
                _write_json(system_filament / fname, data)
    return StudioFolders(root=root, variant=variant, user_id=user_id,
                         user_filament=user_filament, system_filament=system_filament)
