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


# The owner's private values (home LAN addresses, the H2D serial, host, folder and account names) are NOT in this
# repository. They live in a local, untracked JSON file: the path in $FK_OWNER_BANS, else <repo root>/.owner-bans.local
# (git-ignored). Format: {"plain": [...] banned in docs and code, "code_plain": [...] banned in code only,
# "fingerprints": [...] salted SHA-256[:20] of banned words/addresses, "tree_wide": [...] the same, checked over every
# tracked file, "ota_plain": [...] for reader/tools/test_ota_publish.py, "salt": "..."}. Without the file the tests that
# need it skip (a contributor has nothing to ban); with FK_REQUIRE_OWNER_BANS=1 a missing file FAILS (the premerge check).
# What stays below is generic: private-network and local-domain shapes that no one should publish either.
OWNER_DATA = ("localdomain", "h2d_token", "sv08", "G:\\")   # any other private-looking address is caught below
_BANS_ENV = "FK_OWNER_BANS"
_REQUIRE_ENV = "FK_REQUIRE_OWNER_BANS"


def _load_bans(root=None):
    """The local ban file as a dict, or None when there is none."""
    import json
    import os
    path = Path(os.environ.get(_BANS_ENV) or (root or ROOT) / ".owner-bans.local")
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _need_bans():
    """The local bans, or a skip; a failure when FK_REQUIRE_OWNER_BANS=1."""
    import os
    bans = _load_bans()
    if bans is None:
        msg = f"no local owner-ban file ($FK_OWNER_BANS or <repo root>/.owner-bans.local); the owner-specific scan is not run"
        if os.environ.get(_REQUIRE_ENV) == "1":
            pytest.fail(msg + f" and {_REQUIRE_ENV}=1 requires it")
        pytest.skip(msg)
    return bans


_OWNER_TOKEN = re.compile(r"\d{1,3}(?:\.\d{1,3}){3}|[A-Za-z0-9][A-Za-z0-9-]*")
# Some names are ordinary words alone, so only their host or user form is banned: a second pass, on top of the parts above.
_OWNER_FORM = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*(?:\.local\b|@)", re.I)
_NO_BANS = {"plain": [], "code_plain": [], "fingerprints": [], "tree_wide": [], "salt": ""}


def _owner_tokens(text: str) -> set[str]:
    return set(_OWNER_TOKEN.findall(text)) | {m.lower() for m in _OWNER_FORM.findall(text)}


def _fingerprint(token: str, salt: str) -> str:
    return hashlib.sha256(salt.encode() + token.encode()).hexdigest()[:20]


def _owner_candidates(text: str) -> set[str]:
    """Each token as written and lower-cased, and each part of it split on - and _ (a hyphen stays inside a token, so
    `id-suffix` would never equal the banned `id`), with a leading or trailing separator trimmed."""
    out = set()
    for token in _owner_tokens(text):
        for form in {token, token.lower()}:
            out |= {form.strip("-_")} | {part for part in re.split(r"[-_]", form) if part}
    out.discard("")
    return out


def _owner_hits(text: str, fingerprints, salt: str) -> list[str]:
    fingerprints = set(fingerprints)
    return sorted(t for t in _owner_candidates(text) if _fingerprint(t, salt) in fingerprints)


# Every Markdown file under docs/ and release-notes/ is public (the owner's runbooks live outside the repository).
PUBLIC_DOCS = ["README.md", "THIRD-PARTY.md", "reader/README.md"] + sorted(
    p.relative_to(ROOT).as_posix() for p in [*(ROOT / "docs").rglob("*.md"), *(ROOT / "release-notes").glob("*.md")])
# the repository paths: filament-kit (README, get.sh), the filament-library repo that release.yml builds from, the app's
# package name, and the owner's support link: the one allowed mention of the owner's account
ALLOWED_REPO_PATHS = ("github.com/thompsonfabco/filament-kit", "-R thompsonfabco/filament-kit",
                      "thompsonfabco/filament-kit", "github.com/thompsonfabco/filament-library",
                      "thompsonfabco/filament-library", "com.thompsonfabco.filamentkit", "com/thompsonfabco/filamentkit",
                      "ko-fi.com/thompsonfabco")


@pytest.mark.parametrize("rel", PUBLIC_DOCS)
def test_public_docs_have_no_owner_specific_data(rel):
    text = (ROOT / rel).read_text(encoding="utf-8")
    for bad in OWNER_DATA:
        assert bad not in text, (rel, bad)
    rest = text
    for ok in ALLOWED_REPO_PATHS:
        rest = rest.replace(ok, "")
    assert "thompsonfabco" not in rest, rel


def test_public_docs_have_no_local_owner_bans():
    bans = _need_bans()
    found = []
    for rel in PUBLIC_DOCS:
        text = (ROOT / rel).read_text(encoding="utf-8")
        found += [f"{rel}: plain ban {i}" for i, bad in enumerate(bans["plain"]) if bad in text]
        if _owner_hits(text, bans["fingerprints"], bans["salt"]):
            found.append(f"{rel}: fingerprinted ban")
    assert not found, "\n".join(found)


# Final review I4: the same ban over every tracked text file. `sv08` (a printer model the kit makes Orca presets for) and
# `h2d_token` (the filament-ops token file name that `migrate-ops` reads) are product names there, not the owner's data;
# the owner's scanner paths come from the local ban file instead (its fingerprints apply as well).
CODE_OWNER_DATA = tuple(b for b in OWNER_DATA if b not in ("sv08", "h2d_token"))   # plus the local "code_plain"
GENERIC_SCOPE = ("server/tests/", "pc-sync/", "get.sh", "install/", "reader/", "tools/")
# the ban-loading code itself, which names the generic bans
CODE_SCAN_SKIP = {"server/tests/test_readme.py", "reader/tools/test_ota_publish.py"}
# binary by extension: images, archives, firmware
BINARY_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".zip", ".jar", ".bin", ".gz", ".pdf", ".ttf", ".otf",
              ".woff", ".woff2", ".keystore", ".jks", ".apk", ".stl", ".3mf", ".pyc"}


def _walk_files(root: Path) -> list[str]:
    """A copy with no .git (an archive a reviewer unpacked): every file. This is the leak guard, so it never skips; it may
    read a few more files than git would list, which can only make it stricter."""
    skip = {".git", "__pycache__"}
    return [f.relative_to(root).as_posix() for f in root.rglob("*")
            if f.is_file() and not skip & set(f.relative_to(root).parts) and f.name != ".owner-bans.local"]


def _tracked_files(root: Path = ROOT) -> list[str]:
    import subprocess
    try:
        out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=True).stdout.decode("utf-8")
        names = out.split("\0")
    except (subprocess.CalledProcessError, OSError):
        names = _walk_files(root)
    return [f for f in names if f and f not in CODE_SCAN_SKIP]


def _read_text_files(root: Path, names: list[str]):
    """([(rel, text)], [problems]): a file that is neither binary by extension nor UTF-8 is a problem, not a skip."""
    texts, problems = [], []
    for rel in names:
        if Path(rel).suffix.lower() in BINARY_EXT:
            continue
        try:
            data = (root / rel).read_bytes()
        except FileNotFoundError:
            continue                     # listed by git, deleted in this checkout
        except OSError:
            problems.append(f"{rel}: unreadable")
            continue
        try:
            texts.append((rel, data.decode("utf-8")))
        except UnicodeDecodeError:
            problems.append(f"{rel}: not UTF-8 and not a binary extension")
    return texts, problems


def _code_findings(root: Path, bans: dict, names: list[str] | None = None) -> list[str]:
    """Where a banned value is: `path:line: what`, never the value. The generic bans always apply, `bans` adds the local ones."""
    names = _tracked_files(root) if names is None else names
    assert names, "the scan listed no files"
    texts, _ = _read_text_files(root, names)
    assert texts, "the scan read no file"
    tree_wide = set(bans["tree_wide"])
    found = []
    for rel, text in texts:
        # the generic suffixes are product knowledge in the app's own code (it redacts them), so they are banned only
        # where code and tests never had a reason to name them; the local code-only bans are not for the docs
        plain = ([*CODE_OWNER_DATA] if rel.startswith(GENERIC_SCOPE) else []) + bans["plain"] + (
            [] if rel in PUBLIC_DOCS else bans["code_plain"])
        if tree_wide & {_fingerprint(t, bans["salt"]) for t in _owner_candidates(text)}:
            found.append(f"{rel}: fingerprinted host name")
        for n, line in enumerate(text.splitlines(), 1):
            found += [f"{rel}:{n}: fingerprinted ban" for _ in _owner_hits(line, bans["fingerprints"], bans["salt"])]
            for i, bad in enumerate(plain):
                if re.search(re.escape(bad) + (r"(?!\d)" if bad[-1].isdigit() else ""), line):
                    found.append(f"{rel}:{n}: plain ban {i}")
            rest = line
            for ok in ALLOWED_REPO_PATHS:
                rest = rest.replace(ok, "")
            if "thompsonfabco" in rest:
                found.append(f"{rel}:{n}: thompsonfabco")
    return found


def test_the_leak_guard_finds_the_files_without_git(monkeypatch):
    """Not a skip: the same files, from a walk."""
    import subprocess

    def no_git(*a, **k):
        raise subprocess.CalledProcessError(128, "git")
    monkeypatch.setattr(subprocess, "run", no_git)
    files = _tracked_files()
    assert "get.sh" in files and "server/tests/test_release_files.py" in files and "pc-sync/pyproject.toml" in files
    assert "server/tests/test_readme.py" not in files and not any("__pycache__" in f for f in files)
    assert ".owner-bans.local" not in files


def test_every_tracked_text_file_is_utf8():
    names = _tracked_files()
    assert "get.sh" in names
    texts, problems = _read_text_files(ROOT, names)
    assert len(texts) > 100 and not problems, "\n".join(problems)


def test_no_generic_ban_is_in_any_tracked_file():
    """Every tracked text file, the app, the stations and the workflows too (not the ban-loading code itself)."""
    assert "get.sh" in _tracked_files()
    found = _code_findings(ROOT, _NO_BANS)
    assert not found, "\n".join(found)


def test_no_local_owner_ban_is_in_any_tracked_file():
    bans = {**_NO_BANS, **_need_bans()}
    assert "get.sh" in _tracked_files()
    found = _code_findings(ROOT, bans)
    assert not found, "\n".join(found)


def test_the_scan_catches_a_planted_value_and_an_unreadable_file(tmp_path):
    salt = "test salt"
    bans = {**_NO_BANS, "salt": salt, "fingerprints": [_fingerprint("plantedhost9", salt)],
            "tree_wide": [_fingerprint("plantedhost9", salt)], "plain": ["planted-folder"], "code_plain": ["planted-id"]}
    (tmp_path / "get.sh").write_text("echo clean\n", encoding="utf-8")
    assert _code_findings(tmp_path, bans, _walk_files(tmp_path)) == []
    for text in ("ssh plantedhost9.localdomain", "see planted-folder", "x = 'planted-id'", "ssh me@plantedhost9.local"):
        (tmp_path / "a.txt").write_text(text + "\n", encoding="utf-8")
        found = _code_findings(tmp_path, bans, _walk_files(tmp_path))
        assert found and all(f.startswith("a.txt") for f in found) and not any("planted" in f for f in found), text
    (tmp_path / "a.txt").write_bytes(b"\xff\xfe not text")
    assert _read_text_files(tmp_path, _walk_files(tmp_path))[1] == ["a.txt: not UTF-8 and not a binary extension"]
    (tmp_path / "a.txt").unlink()
    (tmp_path / "a.png").write_bytes(b"\xff\xfe not text")
    assert _read_text_files(tmp_path, _walk_files(tmp_path))[1] == []
    with pytest.raises(AssertionError):
        _code_findings(tmp_path, bans, [])           # a scan that listed nothing is a failure, not a pass


@pytest.mark.parametrize("text", ["fabricatedid7", "FabricatedID7", "FABRICATEDID7", "fabricatedid7-suffix", "prefix-fabricatedid7",
                                  "a-fabricatedid7-b", "fabricatedid7_suffix", "prefix_fabricatedid7", "FABRICATEDID7_X-y",
                                  "fabricatedid7-", "x = 'fabricatedid7'"])
def test_a_fabricated_ban_is_caught_bare_joined_and_in_any_case(text, tmp_path):
    salt = "test salt"
    bans = {**_NO_BANS, "salt": salt, "fingerprints": [_fingerprint("fabricatedid7", salt)],
            "tree_wide": [_fingerprint("fabricatedid7", salt)]}
    assert _owner_hits(text, bans["fingerprints"], salt) == ["fabricatedid7"]
    (tmp_path / "get.sh").write_text("ok\n", encoding="utf-8")
    (tmp_path / "a.txt").write_text(text + "\n", encoding="utf-8")
    found = _code_findings(tmp_path, bans, _walk_files(tmp_path))
    assert found and all(f.startswith("a.txt") for f in found) and not any("fabricated" in f.lower() for f in found)
    assert not _owner_hits("fabricatedid70 or fabricated", bans["fingerprints"], salt)


def test_the_ban_file_is_optional_but_can_be_required(tmp_path, monkeypatch):
    monkeypatch.setenv(_BANS_ENV, str(tmp_path / "absent.json"))
    monkeypatch.delenv(_REQUIRE_ENV, raising=False)
    with pytest.raises(pytest.skip.Exception) as skipped:
        _need_bans()
    assert "owner-ban" in str(skipped.value)
    monkeypatch.setenv(_REQUIRE_ENV, "1")
    with pytest.raises(pytest.fail.Exception):
        _need_bans()
    (tmp_path / "present.json").write_text('{"plain": ["x"]}', encoding="utf-8")
    monkeypatch.setenv(_BANS_ENV, str(tmp_path / "present.json"))
    assert _need_bans() == {"plain": ["x"]}


def test_a_host_or_user_form_is_read_whole_and_its_parts_too():
    assert _owner_tokens("open Kit.local:8710 or me@host now") == {"open", "Kit", "local", "kit.local", "8710", "or", "me",
                                                                   "me@", "host", "now"}
    assert not _owner_hits("kit.local", [_fingerprint("secrethost9", "s")], "s")


@pytest.mark.parametrize("text", ["secrethost9", "http://secrethost9:7912", "secrethost9.local", "http://secrethost9.local:7912",
                                  "secrethost9.localdomain", "user@secrethost9.local"])
def test_a_banned_bare_name_is_caught_in_every_form(text):
    assert _owner_hits(text, [_fingerprint("secrethost9", "s")], "s") == ["secrethost9"]


@pytest.mark.parametrize("text,token", [("secrethost9.local", "secrethost9.local"), ("SecretHost9.LOCAL:1", "secrethost9.local"),
                                        ("ssh secrethost9@server", "secrethost9@"), ("SecretHost9@example.org", "secrethost9@")])
def test_a_banned_form_is_caught_in_any_case_and_the_bare_word_is_not(text, token):
    assert _owner_hits(text, [_fingerprint(token, "s")], "s") == [token]
    assert not _owner_hits("the secrethost9 variable", [_fingerprint(token, "s")], "s")


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
