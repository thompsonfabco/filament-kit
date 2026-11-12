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
    # the owner's support line (one paragraph with a ko-fi link) may sit above the title
    first, _, rest = text.partition("\n\n")
    if "ko-fi.com/thompsonfabco" in first and "\n" not in first.strip() and not first.startswith("#"):
        text = rest
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
    "c9f6ef41de056225a7cf", "e44aa6a688481d0bf3fb", "c65d6e88416e61346130", "e61de7055a6e495661f4"})
_OWNER_TOKEN = re.compile(r"\d{1,3}(?:\.\d{1,3}){3}|[A-Za-z0-9][A-Za-z0-9-]*")
# Some names are ordinary words alone, so only their host or user form is banned: a second pass, on top of the parts above.
_OWNER_FORM = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*(?:\.local\b|@)", re.I)
TREE_WIDE_FINGERPRINTS = frozenset({"c65d6e88416e61346130", "e61de7055a6e495661f4"})


def _owner_tokens(text: str) -> set[str]:
    return set(_OWNER_TOKEN.findall(text)) | {m.lower() for m in _OWNER_FORM.findall(text)}


def _fingerprint(token: str) -> str:
    return hashlib.sha256(_OWNER_SALT + token.encode()).hexdigest()[:20]


def _owner_hits(text: str) -> list[str]:
    return sorted(t for t in _owner_tokens(text) if _fingerprint(t) in OWNER_FINGERPRINTS)


# Every Markdown file under docs/ and release-notes/ is public (the owner's runbooks live outside the repository).
PUBLIC_DOCS = ["README.md", "THIRD-PARTY.md", "reader/README.md"] + sorted(
    p.relative_to(ROOT).as_posix() for p in [*(ROOT / "docs").rglob("*.md"), *(ROOT / "release-notes").glob("*.md")])


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
               "com.thompsonfabco.filamentkit", "com/thompsonfabco/filamentkit",  # the app's package name
               "ko-fi.com/thompsonfabco"):  # the owner's support link
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
                      "github.com/thompsonfabco/filament-library", "thompsonfabco/filament-library",
                      "ko-fi.com/thompsonfabco")


def _walk_code_scan() -> list[str]:
    """A copy with no .git (an archive a reviewer unpacked): every file under CODE_SCAN. This is the leak guard, so it
    never skips; it may read a few more files than git would list, which can only make it stricter."""
    out = []
    for item in CODE_SCAN:
        p = ROOT / item
        files = [p] if p.is_file() else [f for f in p.rglob("*") if f.is_file()]
        out += [f.relative_to(ROOT).as_posix() for f in files if "__pycache__" not in f.parts and f.suffix != ".pyc"]
    return out


def _public_code_files() -> list[str]:
    import subprocess
    try:
        out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z", "--", *CODE_SCAN], capture_output=True,
                             check=True).stdout.decode("utf-8")
        names = out.split("\0")
    except (subprocess.CalledProcessError, OSError):
        names = _walk_code_scan()
    return [f for f in names if f and f not in CODE_SCAN_SKIP]


def test_the_leak_guard_finds_the_files_without_git(monkeypatch):
    """Not a skip: the same files, from a walk."""
    import subprocess

    def no_git(*a, **k):
        raise subprocess.CalledProcessError(128, "git")
    monkeypatch.setattr(subprocess, "run", no_git)
    files = _public_code_files()
    assert "get.sh" in files and "server/tests/test_release_files.py" in files
    assert "server/tests/test_readme.py" not in files and not any("__pycache__" in f for f in files)


def test_the_owners_host_name_is_nowhere_in_the_tree():
    """Every tracked text file, the app and the workflows too, not only what the other scans cover."""
    import subprocess
    try:
        names = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"], capture_output=True, check=True,
                               ).stdout.decode("utf-8").split("\0")
    except (subprocess.CalledProcessError, OSError):       # a copy with no .git: never a skip, this is the leak guard
        names = [f.relative_to(ROOT).as_posix() for f in ROOT.rglob("*") if f.is_file()]
    found = []
    for rel in filter(None, names):
        try:
            text = (ROOT / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if TREE_WIDE_FINGERPRINTS & {_fingerprint(t) for t in _owner_tokens(text)}:
            found.append(rel)
    assert not found, found


def test_a_host_or_user_form_is_read_whole_and_its_parts_too():
    assert _owner_tokens("open Kit.local:8710 or me@host now") == {"open", "Kit", "local", "kit.local", "8710", "or", "me",
                                                                   "me@", "host", "now"}
    assert not _owner_hits("kit.local")


@pytest.mark.parametrize("text", ["secrethost9", "http://secrethost9:7912", "secrethost9.local", "http://secrethost9.local:7912",
                                  "secrethost9.localdomain", "user@secrethost9.local"])
def test_a_banned_bare_name_is_caught_in_every_form(monkeypatch, text):
    monkeypatch.setitem(globals(), "OWNER_FINGERPRINTS", frozenset({_fingerprint("secrethost9")}))
    assert _owner_hits(text) == ["secrethost9"]


@pytest.mark.parametrize("text,token", [("secrethost9.local", "secrethost9.local"), ("SecretHost9.LOCAL:1", "secrethost9.local"),
                                        ("ssh secrethost9@server", "secrethost9@"), ("SecretHost9@example.org", "secrethost9@")])
def test_a_banned_form_is_caught_in_any_case_and_the_bare_word_is_not(monkeypatch, text, token):
    monkeypatch.setitem(globals(), "OWNER_FINGERPRINTS", frozenset({_fingerprint(token)}))
    assert _owner_hits(text) == [token]
    assert not _owner_hits("the secrethost9 variable")


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


# What someone bought, and when: the same patterns as filament-library's tools/scan_owner_data.py. A bare listing id is a
# real source; an id or a date next to purchase wording, or wording that attributes something to a person, is not.
_ATTRIBUTION = re.compile(r"\b(?!(?:the\s+)?user(?:['\u2019]s)?\s+(?:manual|guide)\b)(?:the\s+user|user['\u2019]s)\b"
                          r"|\buser\s+(?:asin|spool|note|record|order|upc)s?\b|\bthe\s+caller\b", re.I)
_PURCHASE = re.compile(r"\b(?:ordered|purchased|bought|order\s*(?:date|number|no\b|#)|(?:my|our)\s+(?:order|spool)|owner'?s?)\b", re.I)
_IDENTIFIER = re.compile(r"\bB0[A-Z0-9]{8}\b|\b(?:UPC|EAN|GTIN)\D{0,5}\d{8,14}\b|\b20\d\d-\d\d-\d\d\b|\b\d{1,2}/\d{1,2}/20\d\d\b|"
                         r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2},?\s+20\d\d\b", re.I)


def _purchase_record(line: str) -> str | None:
    if m := _ATTRIBUTION.search(line):
        return m[0]
    for m in _IDENTIFIER.finditer(line):
        if word := _PURCHASE.search(line[max(0, m.start() - 80):m.end() + 80]):
            return f"{m[0]} next to {word[0]}"
    return None


@pytest.mark.parametrize("line", ["The user's ASIN B0AAAAAAAA now redirects", "Amazon B0AAAAAAAA (user ASIN, search snippet)",
                                  "User's single-spool UPC 012345678905 was not found",
                                  "The yellow listing the caller gave", "the user gave this listing","ordered 2026-01-02 from the listing",
                                  "order date: Mar 3, 2026", "B0AAAAAAAA bought in a pack", "UPC 012345678905, purchased 1/2/2026"])
def test_a_purchase_record_is_caught(line):
    assert _purchase_record(line)


@pytest.mark.parametrize("line", ["Listing B0AAAAAAAA states 220 C", "UPC 012345678905 on the listing", "updated 2026-01-02",
                                  "see the user manual", "the user's guide says 220 C", "a forum user reports 220 C"])
def test_a_listing_id_or_a_manual_is_a_source(line):
    assert _purchase_record(line) is None


def test_the_library_snapshot_holds_no_purchase_record():
    found = {f"{p.relative_to(ROOT).as_posix()}: {why}" for p in sorted((ROOT / "server/tests/data/library_snapshot").rglob("*.json"))
             for line in p.read_text(encoding="utf-8").splitlines() if (why := _purchase_record(line))}
    assert not found, found
