"""Copy the filament spec library into the server package as the test snapshot (the wheel bundles no entries).

    python -I tools/sync_library_snapshot.py --from <filament-library checkout> [--to server/tests/data/library_snapshot]

Copies index.json, schema/entry.schema.json and library/<vendor>/<product>.json byte for byte, after checking
that every entry validates (the server's own port of fl.py), sits at its own path, and matches its index sha256,
and that the index lists exactly the files present. Exit status 1, with the destination untouched, on any problem.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "server"))

from filament_kit import library  # noqa: E402


def check(src: Path) -> tuple[dict, list[str], list[str]]:
    """(index, entry paths, problems)."""
    problems = []
    try:
        idx = json.loads((src / "index.json").read_bytes().decode("utf-8"))
    except (OSError, ValueError) as e:
        return {}, [], [f"index.json: unreadable ({e})"]
    if idx.get("schema_version") != library.SCHEMA_VERSION:
        problems.append(f"index.json: schema_version must be {library.SCHEMA_VERSION}")
    if not isinstance(idx.get("library_version"), int):
        problems.append("index.json: library_version must be an integer")
    rows = idx.get("entries") if isinstance(idx.get("entries"), list) else []
    if idx.get("count") != len(rows):
        problems.append(f"index.json: count {idx.get('count')} but {len(rows)} entries")
    if not (src / "schema" / "entry.schema.json").is_file():
        problems.append("schema/entry.schema.json is missing")
    on_disk = {p.relative_to(src).as_posix() for p in (src / "library").rglob("*.json")}
    listed = []
    for r in rows:
        path = r.get("path", "") if isinstance(r, dict) else ""
        if not library.ROW_PATH.fullmatch(path):
            problems.append(f"index.json: invalid path {path!r}")
            continue
        listed.append(path)
        try:
            raw = (src / path).read_bytes()
        except OSError:
            problems.append(f"{path}: listed in index.json but missing")
            continue
        if hashlib.sha256(raw).hexdigest() != r.get("sha256"):
            problems.append(f"{path}: sha256 does not match index.json")
        try:
            entry = json.loads(raw.decode("utf-8"))
        except ValueError as e:
            problems.append(f"{path}: not valid JSON ({e})")
            continue
        problems += [f"{path}: {p}" for p in library.validate(entry)]
        if isinstance(entry, dict) and not library.validate(entry) and library.rel_path(entry) != path:
            problems.append(f"{path}: the entry belongs at {library.rel_path(entry)}")
    if len(set(listed)) != len(listed):
        problems.append("index.json: a path is listed twice")
    for extra in sorted(on_disk - set(listed)):
        problems.append(f"{extra}: present but not in index.json")
    return idx, listed, problems


def copy(src: Path, dest: Path, paths: list[str]) -> None:
    """Build the new snapshot next to `dest`, then swap it in."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(dir=dest.parent, prefix=dest.name + "."))
    try:
        for rel in ["index.json", "schema/entry.schema.json", *paths]:
            out = tmp / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes((src / rel).read_bytes())
        if dest.exists():
            shutil.rmtree(dest)
        tmp.rename(dest)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--from", dest="src", required=True, type=Path, help="filament-library checkout")
    ap.add_argument("--to", dest="dest", type=Path, default=REPO / "server" / "tests" / "data" / "library_snapshot")
    args = ap.parse_args(argv)
    idx, paths, problems = check(args.src)
    if problems:
        for p in problems:
            print(p, file=sys.stderr)
        print(f"{len(problems)} problem(s); nothing copied", file=sys.stderr)
        return 1
    copy(args.src, args.dest, paths)
    print(f"{len(paths)} entries copied, library_version {idx['library_version']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
