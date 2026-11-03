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


@pytest.mark.parametrize("rel", ["README.md", "docs/user-guide.md", "docs/testing-e2e.md"])
def test_public_docs_have_no_owner_specific_data(rel):
    text = (ROOT / rel).read_text(encoding="utf-8")
    for bad in OWNER_DATA:
        assert bad not in text, (rel, bad)
    # the GitHub repo path is the one allowed mention of the owner's account
    assert "thompsonfabco" not in text.replace("github.com/thompsonfabco/filament-kit", "").replace(
        "-R thompsonfabco/filament-kit", ""), rel


def test_readme_sections_a_user_needs():
    text = _readme()
    for h in ("## What it does", "## Modules", "## Supported printers", "## The phone app", "## The reader",
              "## Updates and rollback", "## The filament library", "## Where your data lives", "## Uninstall",
              "## Pair your PC"):        # the CLI says "see README: Pair your PC"
        assert h in text, h
    for path in re.findall(r"\]\(((?:docs|reader)/[^)#]+)", text):
        assert (ROOT / path).is_file(), path
