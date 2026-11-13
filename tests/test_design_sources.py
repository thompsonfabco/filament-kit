"""Design source tests of docs/design/08-platform-mapping.md 3.4 ("Proposed tests"), one test function per check.

Test 2 here: tokens.json is complete and well-formed. Test 4: every token a component uses is a token. Later steps add
the others to this file.
"""
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOKENS = json.loads((ROOT / "tokens" / "tokens.json").read_text(encoding="utf-8"))
KNOWN_VERSIONS = (2,)

THEME_KEYS = {"label", "profile", "light", "dark", "type", "space", "radius", "size", "elevation", "motion", "derived",
              "extra"}
COLOURS = ["bg", "surface", "surface-2", "surface-3", "text", "muted", "border", "border-strong", "accent", "accent-hover",
           "on-accent", "accent-soft", "accent-text", "ok", "ok-soft", "warn", "warn-soft", "bad", "bad-soft", "on-bad",
           "info", "info-soft", "focus", "scrim", "code"]
TYPE = ["sans", "mono", "fs-xs", "fs-s", "fs-m", "fs-b", "fs-l", "fs-xl", "fs-2xl", "lh-body", "lh-title", "fw-text",
        "fw-label", "fw-title"]
SIZES = ["ctl", "ctl-phone", "top", "rail", "tab", "row", "gap", "drawer", "hairline", "nav-mark", "thumb", "qr", "side-w",
         "list-w", "content-max", "label-col", "thumb-s", "swatch-row-w", "swatch-row-h", "swatch-head", "empty-mark",
         "chip", "slot-label", "port-field", "column-max", "preview-max", "list-pane"]
MOTION = ["t-fast", "t", "t-slow", "ease"]
PROFILE = {"nav": {"rail", "sidebar", "pills", "list"}, "collection": {"table", "cards", "tiles", "rows"},
           "detail": {"inline", "card", "sheet", "pane"}}
ANDROID_FAMILIES = {"default", "monospace", "serif", "sans-serif"}

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
RGB_SLASH = re.compile(r"^rgb\((\d{1,3}) (\d{1,3}) (\d{1,3}) / (\.\d+|0|1|0\.\d+)\)$")
RGBA = re.compile(r"^rgba\((\d{1,3}),\s*(\d{1,3}),\s*(\d{1,3}),\s*(\.\d+|0|1|0\.\d+)\)$")
REM = re.compile(r"^(\d+(\.\d+)?)rem$")
PX = re.compile(r"^(\d+(\.\d+)?)px$")
MS = re.compile(r"^\d+ms$")
EASE = re.compile(r"^cubic-bezier\((-?[\d.]+),\s*(-?[\d.]+),\s*(-?[\d.]+),\s*(-?[\d.]+)\)$")
VAR = re.compile(r"var\(--([a-z0-9-]+)\)")

THEMES = list(TOKENS["themes"].items())
IDS = [name for name, _ in THEMES]


def _colour_ok(v):
    if HEX.match(v):
        return True
    m = RGB_SLASH.match(v) or RGBA.match(v)
    return bool(m) and all(0 <= int(m.group(i)) <= 255 for i in (1, 2, 3)) and 0 <= float(m.group(4)) <= 1


def test_version_is_known():
    assert TOKENS["version"] in KNOWN_VERSIONS


@pytest.mark.parametrize("name,t", THEMES, ids=IDS)
def test_theme_has_every_group(name, t):
    assert set(t) == THEME_KEYS, sorted(set(t) ^ THEME_KEYS)
    assert isinstance(t["label"], str) and t["label"]
    assert isinstance(t["derived"], list) and all(isinstance(x, str) for x in t["derived"])   # notes, may be empty
    assert isinstance(t["extra"], dict)


@pytest.mark.parametrize("name,t", THEMES, ids=IDS)
def test_colours_complete_and_parse(name, t):
    for mode in ("light", "dark"):
        assert list(t[mode]) == COLOURS or set(t[mode]) == set(COLOURS), (mode, sorted(set(t[mode]) ^ set(COLOURS)))
        bad = {k: v for k, v in t[mode].items() if not _colour_ok(v)}
        assert not bad, (mode, bad)


@pytest.mark.parametrize("name,t", THEMES, ids=IDS)
def test_type(name, t):
    ty = t["type"]
    missing = [k for k in TYPE if k not in ty]
    assert not missing, missing
    for k in TYPE:
        if k.startswith("fs-"):
            m = REM.match(ty[k])
            assert m and float(m.group(1)) > 0, (k, ty[k])
        elif k.startswith(("lh-", "fw-")):
            float(ty[k])
        else:
            assert isinstance(ty[k], str) and ty[k], k
    assert set(ty.get("android", {})) == {"sans", "mono"}, ty.get("android")
    assert set(ty["android"].values()) <= ANDROID_FAMILIES, ty["android"]


@pytest.mark.parametrize("name,t", THEMES, ids=IDS)
def test_space_strictly_increases(name, t):
    values = []
    for k, v in t["space"].items():
        m = PX.match(v)
        assert m and float(m.group(1)) > 0, (k, v)
        values.append(float(m.group(1)))
    assert values == sorted(values) and len(set(values)) == len(values), t["space"]


@pytest.mark.parametrize("name,t", THEMES, ids=IDS)
def test_radius_lengths(name, t):
    for k, v in t["radius"].items():
        m = PX.match(v)
        assert m and float(m.group(1)) > 0, (k, v)


@pytest.mark.parametrize("name,t", THEMES, ids=IDS)
def test_sizes_complete_and_positive(name, t):
    size = t["size"]
    missing = [k for k in SIZES if k not in size]
    assert not missing, missing
    for k, v in size.items():
        m = PX.match(v)
        assert m, (k, v)
        assert float(m.group(1)) > 0 or k == "rail", (k, v)
        if k.endswith("-phone"):
            assert k[: -len("-phone")] in size, k


@pytest.mark.parametrize("name,t", THEMES, ids=IDS)
def test_elevation(name, t):
    el = t["elevation"]
    assert set(el) == {"light", "dark", "android"}, sorted(el)
    for mode in ("light", "dark"):
        assert set(el[mode]) == {"e0", "e2"}, (mode, el[mode])
        for k, v in el[mode].items():
            for ring in VAR.findall(v):
                assert ring in COLOURS, (mode, k, ring)          # a ring names a colour token
    assert set(el["android"]) == {"e0", "e2"}
    for k, v in el["android"].items():
        assert PX.match(v), (k, v)


@pytest.mark.parametrize("name,t", THEMES, ids=IDS)
def test_motion(name, t):
    mo = t["motion"]
    assert set(mo) == set(MOTION), sorted(mo)
    for k in ("t-fast", "t", "t-slow"):
        assert MS.match(mo[k]), (k, mo[k])
    assert EASE.match(mo["ease"]), mo["ease"]


@pytest.mark.parametrize("name,t", THEMES, ids=IDS)
def test_profile_choices(name, t):
    assert set(t["profile"]) == set(PROFILE)
    for k, v in t["profile"].items():
        assert v in PROFILE[k], (k, v)

# ---- Test 4: every token a component uses is a token ----

SERVER = ROOT / "server" / "filament_kit"
KOTLIN_DIR = ROOT / "android" / "app" / "src" / "main" / "java"
ALLOWLIST = ROOT / "tests" / "design_source_allowlist.txt"
BREAKPOINTS = {600, 601, 1024, 1025}
DEFAULT_LOOK = "console"

USED_VAR = re.compile(r"var\(\s*--([a-zA-Z0-9-]+)")
KOTLIN_USE = re.compile(r"\bSpoolwardenTheme\.(\w+)\.(\w+)")
MEDIA = re.compile(r"@media([^{]*)\{")
MEDIA_WIDTH = re.compile(r"width\s*(?::|[<>]=?)\s*([\d.]+)\s*([a-z]*)")
PROFILE_COMMENT = re.compile(r"/\*\s*profile:\s*([a-z-]+)=([a-z-]+)\s*\*/")
RULE_HEAD = re.compile(r"([^{}]+)\{")
DATA_LOOK = re.compile(r'^:root\[data-look="([a-z]+)"\]')

# Kotlin groups whose fields are styles, not tokens: only the group is checked (08 3.4)
KOTLIN_STYLE_GROUPS = {"type": None}


def _camel(name):
    head, *rest = name.split("-")
    return head + "".join(p[:1].upper() + p[1:] for p in rest)


def _token_names():
    """Custom property names that are tokens: every group of every theme except `extra` and `derived`."""
    names = set()
    for t in TOKENS["themes"].values():
        for group in ("light", "dark", "type", "space", "radius", "size", "motion"):
            names.update(k for k in t[group] if k != "android")
        for mode in ("light", "dark"):
            names.update(t["elevation"][mode])
    return {n[: -len("-phone")] if n.endswith("-phone") else n for n in names}


TOKEN_NAMES = _token_names()


def _kotlin_fields():
    sizes = {"control" if k == "ctl" else "controlPhone" if k == "ctl-phone" else _camel(k)
             for t in TOKENS["themes"].values() for k in t["size"]}
    return {
        "colors": {_camel(c) for c in COLOURS},
        "space": {f"s{i}" for i in range(1, 8)},
        "sizes": sizes,
        "density": {"control", "row", "gap"},
        "shapes": {"rS", "r", "rL"},
        "elevation": {"e0", "e2"},
        "motion": {"fast", "base", "slow", "easing"},
        **KOTLIN_STYLE_GROUPS,
    }


def _web_sources():
    files = [p for d in ("setup_static", "web/static") for p in sorted((SERVER / d).iterdir())
             if p.suffix in (".css", ".js") and "bundle" not in p.name]
    assert files
    return files


def _kotlin_sources():
    return [p for p in sorted(KOTLIN_DIR.rglob("*.kt")) if p.name != "SpoolwardenTokens.kt"]


def _allowlist():
    entries = {}
    for line in ALLOWLIST.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            path, _, reason = (x.strip() for x in line.partition("|"))
            assert path and reason, f"allow-list line needs a file and a reason: {line!r}"
            entries[path] = reason
    return entries


def unknown_vars(text):
    return sorted({n for n in USED_VAR.findall(text) if n not in TOKEN_NAMES})


def bad_breakpoints(text):
    bad = []
    for prelude in MEDIA.findall(text):
        for value, unit in MEDIA_WIDTH.findall(prelude):
            if unit != "px" or float(value) not in BREAKPOINTS:
                bad.append(f"{value}{unit}")
    return bad


def unknown_kotlin(text):
    fields = _kotlin_fields()
    return sorted({f"{g}.{f}" for g, f in KOTLIN_USE.findall(text)
                   if g not in fields or (fields[g] is not None and f not in fields[g])})


def profile_group_errors(css):
    """Each `/* profile: key=choice */` group is keyed on exactly the themes whose profile has that choice (08 9)."""
    errors = []
    marks = list(PROFILE_COMMENT.finditer(css))
    for i, m in enumerate(marks):
        key, choice = m.groups()
        end = marks[i + 1].start() if i + 1 < len(marks) else len(css)
        body = re.sub(r"/\*.*?\*/", "", css[m.end():end], flags=re.S)
        found = set()
        for head in RULE_HEAD.findall(body):
            for sel in head.split(","):
                sel = sel.strip()
                if sel and not sel.startswith("@"):
                    d = DATA_LOOK.match(sel)
                    found.add(d.group(1) if d else DEFAULT_LOOK)    # no qualifier: the default theme (08 9)
        expected = {n for n, t in THEMES if t["profile"].get(key) == choice}
        if choice not in PROFILE.get(key, ()):
            errors.append(f"{key}={choice}: not a profile choice")
        elif found != expected:
            errors.append(f"{key}={choice}: keyed on {sorted(found)}, tokens.json says {sorted(expected)}")
    return errors


def test_allowlist_entries_are_needed():
    for path in _allowlist():
        f = ROOT / path
        assert f.is_file(), f"allow-listed file is gone, drop its line: {path}"
        assert unknown_vars(f.read_text(encoding="utf-8")), f"{path} uses only tokens now, drop its allow-list line"


def test_web_vars_are_tokens():
    allowed = _allowlist()
    for f in _web_sources():
        rel = f.relative_to(ROOT).as_posix()
        if rel not in allowed:
            assert not unknown_vars(f.read_text(encoding="utf-8")), (rel, "uses a name that is not a token")


def test_web_media_queries_use_the_edges():
    for f in _web_sources():
        assert not bad_breakpoints(f.read_text(encoding="utf-8")), f.name


def test_web_profile_groups():
    for f in _web_sources():
        if f.suffix == ".css":
            assert not profile_group_errors(f.read_text(encoding="utf-8")), f.name


def test_kotlin_theme_reads_are_tokens():
    for f in _kotlin_sources():
        assert not unknown_kotlin(f.read_text(encoding="utf-8")), f.name


def test_the_scan_sees_files():
    assert _web_sources() and _kotlin_sources()


def test_token_names_leave_out_extra():
    assert {"accent", "surface-2", "s1", "r-s", "ctl", "content-max", "e0", "fs-2xl", "ease"} <= TOKEN_NAMES
    assert not ({"accent-2", "lh-tight", "e1", "tap", "ctl-phone"} & TOKEN_NAMES)


def test_checks_fail_on_plants():
    assert unknown_vars("a { color: var(--not-a-token); b: var(--accent, red) }") == ["not-a-token"]
    assert unknown_vars("a { color: var(--accent-2) }") == ["accent-2"]                   # only `extra` defines it
    assert bad_breakpoints("@media (max-width: 700px) { a { b: c } }") == ["700px"]
    assert bad_breakpoints("@media (min-width: 40em) { a { b: c } }") == ["40em"]
    assert bad_breakpoints("@media (min-width: 601px) and (max-width: 1024px) { a { b: c } }") == []
    assert unknown_kotlin("SpoolwardenTheme.colors.accent SpoolwardenTheme.colors.nope") == ["colors.nope"]
    assert unknown_kotlin("SpoolwardenTheme.looks.x SpoolwardenTheme.type.data") == ["looks.x"]
    assert unknown_kotlin("SpoolwardenTheme.sizes.sideW SpoolwardenTheme.shapes.rL") == []
    nav_rail = sorted(n for n, t in THEMES if t["profile"]["nav"] == "rail")
    sel = ", ".join(f':root[data-look="{n}"] .nav' for n in nav_rail)
    assert profile_group_errors(f"/* profile: nav=rail */\n{sel} {{ a: b }}") == []
    assert profile_group_errors('/* profile: nav=rail */\n:root[data-look="nonesuch"] .nav { a: b }')
    assert profile_group_errors("/* profile: nav=bogus */\n.nav { a: b }")
