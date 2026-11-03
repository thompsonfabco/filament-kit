"""Install the test library snapshot as a downloaded copy in a state directory (the production path)."""
import json
import os
import shutil
from pathlib import Path

SNAPSHOT = Path(__file__).parent / "data" / "library_snapshot"
DIR_NAME = "2-20261101T000000Z"


def install_snapshot(state: Path) -> None:
    """state/library/current.json -> versions/<dir>, which links to the shared snapshot (a copy where a link
    cannot be made); `library.load()` then reads it exactly as it reads a real download."""
    lib = Path(state) / "library"
    versions = lib / "versions"
    versions.mkdir(parents=True, exist_ok=True)
    dest = versions / DIR_NAME
    if not dest.exists():
        try:
            os.symlink(SNAPSHOT, dest, target_is_directory=True)
        except (OSError, NotImplementedError):
            shutil.copytree(SNAPSHOT, dest)
    version = json.loads((SNAPSHOT / "index.json").read_text(encoding="utf-8"))["library_version"]
    (lib / "current.json").write_text(json.dumps({"dir": DIR_NAME, "version": version, "at": 1.0}), encoding="utf-8")
