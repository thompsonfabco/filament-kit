"""Build the library release asset (library-<date>.tar.gz) from a filament-library checkout.

    python -I tools/build_library_asset.py --from <filament-library checkout> --out dist/library-2026-11-02.tar.gz

The tarball holds index.json, schema/entry.schema.json and library/<vendor>/<product>.json at its root, which is
what `filament-kit library update` reads. The checkout gets the same checks `sync_library_snapshot.py` applies
(every entry validates, sits at its own path and matches its index sha256; the index lists exactly the files
present). The archive is reproducible: sorted names, zero timestamps and owners. Nothing is uploaded.
"""
from __future__ import annotations

import argparse
import gzip
import io
import sys
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import sync_library_snapshot as snap  # noqa: E402


def build(src: Path, out: Path) -> int:
    """Write the archive; returns the entry count. SystemExit(1) with the problems printed if `src` is unusable."""
    idx, paths, problems = snap.check(src)
    if problems:
        for p in problems:
            print(p, file=sys.stderr)
        print(f"{len(problems)} problem(s); no archive built", file=sys.stderr)
        raise SystemExit(1)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".part")
    try:
        with open(tmp, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="") as gz, \
                tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tar:
            for rel in ["index.json", "schema/entry.schema.json", *sorted(paths)]:
                data = (src / rel).read_bytes()
                info = tarfile.TarInfo(rel)
                info.size, info.mtime, info.mode = len(data), 0, 0o644
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                tar.addfile(info, io.BytesIO(data))
        tmp.replace(out)
    finally:
        tmp.unlink(missing_ok=True)
    print(f"{out}: {len(paths)} entries, library_version {idx['library_version']}")
    return len(paths)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--from", dest="src", required=True, type=Path, help="filament-library checkout")
    ap.add_argument("--out", required=True, type=Path, help="the .tar.gz to write")
    args = ap.parse_args(argv)
    build(args.src, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
