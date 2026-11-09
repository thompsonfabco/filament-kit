"""Nightly prereleases (unsigned), for `filament-kit update --channel nightly` (updates.py).

.github/workflows/nightly.yml publishes a PRERELEASE tagged nightly-YYYYMMDD with
filament-kit-<version>-nightly.YYYYMMDD.tar.gz and a plain SHA256SUMS: no signature (the orchestrator's ruling on R42).
The hash only shows the download is the file the release lists, not who built it. Kept out of release.py, which get.sh
carries verbatim: the installer never takes a nightly.
"""
from __future__ import annotations

import hmac
import json
import re
import urllib.parse
from pathlib import Path

from .release import (LIMIT_JSON, LIMIT_SUMS, LIMIT_TARBALL, REPO, SUMS, Fetcher, ReleaseError, file_sha256,
                      parse_sums, parse_version)

NIGHTLY_TAG = re.compile(r"nightly-(\d{8})")
NIGHTLY_VERSION = re.compile(r"(\d+\.\d+\.\d+)-nightly\.(\d{8})")
NIGHTLY_UNSIGNED = ("Nightly builds are untested and unsigned: the download is checked only against the SHA256SUMS of "
                    "the same prerelease, which proves nothing about who built it. sudo filament-kit update --channel "
                    "stable goes back to signed releases.")


def nightly_key(version: str) -> tuple[int, int, int, int]:
    """Order of an installed or offered version: X.Y.Z then its nightly date (a release counts as date 0)."""
    m = NIGHTLY_VERSION.fullmatch(str(version))
    if m:
        return (*parse_version(m[1]), int(m[2]))
    return (*parse_version(version), 0)


def latest_nightly(fetcher: Fetcher, repo: str = REPO) -> dict:
    """{"version": X.Y.Z-nightly.YYYYMMDD, "assets", "notes"} of the newest nightly prerelease of `repo`."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ReleaseError(f"bad repo name {repo!r} (owner/name)")
    raw = fetcher.get(f"{fetcher.api}/repos/{repo}/releases?per_page=30", LIMIT_JSON, "application/vnd.github+json")
    try:
        docs = json.loads(raw)
        assert isinstance(docs, list)
    except (ValueError, AssertionError):
        raise ReleaseError("the release list answer is not a GitHub release list") from None
    best = None
    for doc in docs:
        if not isinstance(doc, dict) or doc.get("prerelease") is not True:
            continue
        tag = doc.get("tag_name")
        m = NIGHTLY_TAG.fullmatch(tag) if isinstance(tag, str) else None
        if m is None:
            continue
        try:
            assets = {a["name"]: a["url"] for a in doc.get("assets") or []}
        except (KeyError, TypeError):
            continue
        names = [n for n in assets if isinstance(n, str) and re.fullmatch(
            r"filament-kit-(\d+\.\d+\.\d+)-nightly\." + m[1] + r"\.tar\.gz", n)]
        if len(names) != 1 or SUMS not in assets:
            continue
        version = names[0][len("filament-kit-"):-len(".tar.gz")]
        if best is None or nightly_key(version) > nightly_key(best["version"]):
            body = doc.get("body")
            best = {"version": version, "assets": assets, "notes": body if isinstance(body, str) else ""}
    if best is None:
        raise ReleaseError(f"{repo} has no nightly prerelease with a tarball and SHA256SUMS")
    for name, url in best["assets"].items():
        if not isinstance(url, str) or urllib.parse.urlsplit(url).scheme not in ("https", "http"):
            raise ReleaseError(f"asset {name!r} has a bad address")
    return best


def fetch_nightly(dest: Path, rel: dict, *, fetcher: Fetcher) -> Path:
    """Download the nightly `rel` (latest_nightly) into `dest`: SHA256SUMS and the tarball, the tarball checked
    against it (integrity only: nothing is signed). On any failure the tarball is deleted."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    name = f"filament-kit-{rel['version']}.tar.gz"
    sums = fetcher.get(rel["assets"][SUMS], LIMIT_SUMS)
    table = parse_sums(sums)
    if name not in table:
        raise ReleaseError(f"the nightly's {SUMS} does not list {name}")
    tarball = dest / name
    try:
        fetcher.save(rel["assets"][name], tarball, LIMIT_TARBALL)
        check_nightly(tarball, table)
    except BaseException:
        tarball.unlink(missing_ok=True)
        raise
    (dest / SUMS).write_bytes(sums)
    return tarball


def check_nightly(tarball: Path, table: dict[str, str]) -> None:
    want = table.get(tarball.name)
    if want is None or not hmac.compare_digest(file_sha256(tarball), want):
        raise ReleaseError(f"{tarball.name} does not match its hash in the nightly's (unsigned) {SUMS} "
                           "(a damaged or changed download); nothing was installed")
