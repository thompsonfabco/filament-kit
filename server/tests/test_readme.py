"""F2: the README is for a normal user, and its module table follows the module registry (modules.py)."""
import re

import pytest
from pathlib import Path

from filament_kit import modules

ROOT = Path(__file__).resolve().parents[2]


def _readme() -> str:
    return (ROOT / "README.md").read_text(encoding="utf-8")


def test_first_line_is_the_one_command_install():
    first = _readme().splitlines()[0]
    assert "curl -fsSL https://github.com/thompsonfabco/filament-kit/releases/latest/download/get.sh | sudo bash" \
        in first


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


OWNER_DATA = ("192.0.2.10", "192.0.2.11", "192.0.2.109", "192.0.2.179", "localdomain", "example.com",
              "spoolman-vm", "mcp.example", "h2d_token", "sv08", "G:\\")


@pytest.mark.parametrize("rel", ["README.md", "docs/user-guide.md", "docs/testing-e2e.md", "docs/install-server.md",
                                 "docs/install-android-app.md", "docs/install-iphone-web-app.md",
                                 "docs/known-gaps.md"])
def test_public_docs_have_no_owner_specific_data(rel):
    text = (ROOT / rel).read_text(encoding="utf-8")
    for bad in OWNER_DATA:
        assert bad not in text, (rel, bad)
    # the GitHub repo path is the one allowed mention of the owner's account
    assert "thompsonfabco" not in text.replace("github.com/thompsonfabco/filament-kit", "").replace(
        "-R thompsonfabco/filament-kit", ""), rel


# Final review I4: the same ban over the public code and test files. `sv08` (a printer model the kit makes Orca
# presets for) and `h2d_token` (the filament-ops token file name that `migrate-ops` reads) are product names
# there, not the owner's data; the owner's H2D serial and scanner paths are added instead.
CODE_OWNER_DATA = tuple(b for b in OWNER_DATA if b not in ("sv08", "h2d_token")) + (
    "0948ZZ0A0000001", "h2d-scanner", "printer-host", "intake.home.arpa", "owner")
CODE_SCAN = ("server/tests", "get.sh", "install", "reader", "tools")
# ban lists themselves; the private runbook (docs/migrate-from-filament-ops.md) is not scanned here
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
    for h in ("## What it does", "## Modules", "## Supported printers", "## The phone app", "## The reader",
              "## Updates and rollback", "## The filament library", "## Where your data lives", "## Uninstall",
              "## Pair your PC"):        # the CLI says "see README: Pair your PC"
        assert h in text, h
    for path in re.findall(r"\]\(((?:docs|reader)/[^)#]+)", text):
        assert (ROOT / path).is_file(), path
