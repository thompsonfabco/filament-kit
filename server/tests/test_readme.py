"""F2: the README is for a normal user, and its module table follows the module registry (modules.py)."""
import hashlib
import re

import pytest
from pathlib import Path

from filament_kit import modules

ROOT = Path(__file__).resolve().parents[2]


def _readme() -> str:
    return (ROOT / "README.md").read_text(encoding="utf-8")


def test_readme_opens_with_the_goal_then_the_one_command_install():
    # The owner's order: what the kit is and what it is for first, then how to install it.
    text = _readme()
    assert text.startswith("# filament-kit\n")
    install = text.index("\n## Install\n")
    assert "## What you need" in text[:install]
    # download-then-run, not `curl | sudo bash`: piped into sudo, the installer hangs at apt (no controlling tty)
    section = text[install:text.index("\n## ", install + 1)]
    assert "curl -fsSLO https://github.com/thompsonfabco/filament-kit/releases/latest/download/get.sh && sudo bash get.sh" \
        in section
    assert "| sudo bash" not in section


def test_module_table_matches_the_registry():
    text = _readme()
    table = text[text.index("| Module | What it is | Needs |"):]
    rows = [line for line in table.splitlines()[2:] if line.startswith("| `")]
    rows = rows[:len(modules.MODULES)]
    names = [re.match(r"\| `([a-z_]+)` \|", r)[1] for r in rows]
    assert names == list(modules.MODULES)            # every module, in the registry's order
    for row in rows:
        name, what, needs = (c.strip() for c in row.strip("|").split("|"))
        m = modules.MODULES[name.strip("`")]
        assert ("Optional AI" in what) == m.optional_ai, row
        for dep in m.depends:
            assert f"`{dep}`" in needs, (row, dep)
        if m.needs_text:
            assert m.needs_text in needs, (row, m.needs_text)


OWNER_DATA = ("localdomain", "spoolman-vm", "h2d_token", "sv08", "G:\\")   # any other "thompsonfabco" is caught below

# The owner's private values (home LAN addresses, the H2D serial, host and account names) are banned by salted
# SHA-256 fingerprint, so this file does not publish them itself. A text is cut into IPv4 addresses and word runs.
_OWNER_SALT = b"filament-kit owner-data v1:"
OWNER_FINGERPRINTS = frozenset({
    "d760cbea97a1228524ab", "92ce0773c1c5a2e0ca4a", "95fb2cac257df2546230", "87bf20b4038304003845",
    "17b7f0c3556139cbbfd1", "107b22d060e0f4dce62d", "dbf1988c2971e2f59646", "4cff4dd88d4eba517032",
    "c9f6ef41de056225a7cf", "e44aa6a688481d0bf3fb"})
_OWNER_TOKEN = re.compile(r"\d{1,3}(?:\.\d{1,3}){3}|[A-Za-z0-9][A-Za-z0-9-]*")


def _owner_hits(text: str) -> list[str]:
    return sorted({t for t in _OWNER_TOKEN.findall(text)
                   if hashlib.sha256(_OWNER_SALT + t.encode()).hexdigest()[:20] in OWNER_FINGERPRINTS})


# Every Markdown file under docs/ is public (the owner's runbooks live outside the repository).
PUBLIC_DOCS = ["README.md", "THIRD-PARTY.md", "reader/README.md"] + sorted(
    p.relative_to(ROOT).as_posix() for p in (ROOT / "docs").rglob("*.md"))


@pytest.mark.parametrize("rel", PUBLIC_DOCS)
def test_public_docs_have_no_owner_specific_data(rel):
    text = (ROOT / rel).read_text(encoding="utf-8")
    for bad in OWNER_DATA:
        assert bad not in text, (rel, bad)
    assert not _owner_hits(text), rel
    # the GitHub repo paths are the one allowed mention of the owner's account
    rest = text
    for ok in ("github.com/thompsonfabco/filament-kit", "-R thompsonfabco/filament-kit",
               "github.com/thompsonfabco/filament-library", "thompsonfabco/filament-library",
               "com.thompsonfabco.filamentkit", "com/thompsonfabco/filamentkit"):  # the app's package name
        rest = rest.replace(ok, "")
    assert "thompsonfabco" not in rest, rel


# Final review I4: the same ban over the public code and test files. `sv08` (a printer model the kit makes Orca
# presets for) and `h2d_token` (the filament-ops token file name that `migrate-ops` reads) are product names
# there, not the owner's data; the owner's scanner paths are added instead (the fingerprints apply as well).
CODE_OWNER_DATA = tuple(b for b in OWNER_DATA if b not in ("sv08", "h2d_token")) + ("h2d-scanner",)
CODE_SCAN = ("server/tests", "get.sh", "install", "reader", "tools")
# ban lists themselves
CODE_SCAN_SKIP = {"server/tests/test_readme.py", "reader/tools/test_ota_publish.py"}
# the repository paths: filament-kit (README, get.sh), and the filament-library repo that release.yml builds from
ALLOWED_REPO_PATHS = ("github.com/thompsonfabco/filament-kit", "thompsonfabco/filament-kit",
                      "github.com/thompsonfabco/filament-library", "thompsonfabco/filament-library")


def _public_code_files() -> list[str]:
    import subprocess
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z", "--", *CODE_SCAN], capture_output=True,
                         check=True).stdout.decode("utf-8")
    return [f for f in out.split("\0") if f and f not in CODE_SCAN_SKIP]


def test_public_code_and_tests_have_no_owner_specific_data():
    files = _public_code_files()
    assert "get.sh" in files and any(f.startswith("server/tests/") for f in files)
    found = []
    for rel in files:
        try:
            text = (ROOT / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue                     # binaries (firmware images, fixtures)
        for n, line in enumerate(text.splitlines(), 1):
            found += [f"{rel}:{n}: owner value" for _ in _owner_hits(line)]
            for bad in CODE_OWNER_DATA:
                if re.search(re.escape(bad) + (r"(?!\d)" if bad[-1].isdigit() else ""), line):
                    found.append(f"{rel}:{n}: {bad}")
            rest = line
            for ok in ALLOWED_REPO_PATHS:
                rest = rest.replace(ok, "")
            if "thompsonfabco" in rest:
                found.append(f"{rel}:{n}: thompsonfabco")
    assert not found, "\n".join(found)


def test_readme_sections_a_user_needs():
    text = _readme()
    for h in ("## What you need", "## Install", "## What it does", "## Modules", "## Supported printers",
              "## The phone app", "## The reader",
              "## Updates and rollback", "## The filament library", "## Where your data lives", "## Uninstall",
              "## Pair your PC"):        # the CLI says "see README: Pair your PC"
        assert h in text, h
    for path in re.findall(r"\]\(((?:docs|reader)/[^)#]+)", text):
        assert (ROOT / path).exists(), path      # a file, or a folder
