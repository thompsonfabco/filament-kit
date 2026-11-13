"""Design source tests of docs/design/08-platform-mapping.md 3.4 ("Proposed tests"), one test function per check.

Test 2 here: tokens.json is complete and well-formed. Later steps add the others to this file.
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
