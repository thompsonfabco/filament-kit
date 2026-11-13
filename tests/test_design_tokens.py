"""The token folder's two checks (docs/design/08-platform-mapping.md 3.3) in the project's normal test run.

tokens.css must equal what tokens.json generates, and every required contrast pair must pass.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKENS = ROOT / "tokens"
THEME = Path("android/app/src/main/java/com/thompsonfabco/filamentkit/ui/theme")
KT = THEME / "SpoolwardenTokens.kt"
WINDOW = Path("android/app/src/main/res/values/sw_window.xml")
WINDOW_NIGHT = Path("android/app/src/main/res/values-night/sw_window.xml")
STRINGS_XML = Path("android/app/src/main/res/values/strings.xml")
STRINGS = (Path("strings/en.json"), Path("strings/strings.js"))
ANDROID_OUTPUTS = (KT, WINDOW, WINDOW_NIGHT)


def _run(*args):
    return subprocess.run([sys.executable, *args], capture_output=True, text=True, cwd=TOKENS, timeout=120)


def test_tokens_css_matches_tokens_json():
    r = _run(str(TOKENS / "build_tokens.py"), "--check")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "OK: tokens.css matches tokens.json" in r.stdout
    assert "OK: theme-init.js matches tokens.json" in r.stdout
    for name in ("SpoolwardenTokens.kt", "values/sw_window.xml", "values-night/sw_window.xml"):
        assert f"OK: {name} matches tokens.json" in r.stdout


def test_required_contrast_pairs_pass():
    r = _run(str(TOKENS / "check_contrast.py"))
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.rstrip().endswith("RESULT: PASS"), r.stdout[-400:]


GENERATED_LF = ("tokens/** text eol=lf", "icons/** text eol=lf", "strings/** text eol=lf")


def test_token_files_are_checked_out_with_lf():
    # --check compares bytes with "\n" endings; without these rules a Windows checkout (core.autocrlf) gets CRLF and fails
    attrs = (TOKENS.parent / ".gitattributes").read_text(encoding="utf-8").splitlines()
    for rule in GENERATED_LF:
        assert rule in attrs, rule


def _flat(tmp_path):
    """The token folder's files go in tmp_path/tokens, with strings/en.json beside it, which the generator also reads."""
    (tmp_path / "tokens").mkdir()
    (tmp_path / "strings").mkdir()
    (tmp_path / "strings" / "en.json").write_bytes((ROOT / "strings" / "en.json").read_bytes())
    return tmp_path / "tokens"


def test_check_fails_on_a_crlf_css(tmp_path):
    # what a checkout without the LF rule would hand the check: it must say so rather than pass
    d = _flat(tmp_path)
    for name in ("tokens.json", "build_tokens.py", "theme-init.js"):
        (d / name).write_bytes((TOKENS / name).read_bytes())
    (d / "tokens.css").write_bytes((TOKENS / "tokens.css").read_bytes().replace(b"\n", b"\r\n"))
    r = subprocess.run([sys.executable, str(d / "build_tokens.py"), "--check"], capture_output=True, text=True,
                       cwd=d, timeout=120)
    assert r.returncode == 1, r.stdout + r.stderr


def test_check_fails_on_a_hand_edited_css(tmp_path):
    # the equality check must catch a tokens.css edited by hand: run a copy of the folder with one value changed
    d = _flat(tmp_path)
    for name in ("tokens.json", "build_tokens.py", "tokens.css", "theme-init.js"):
        (d / name).write_bytes((TOKENS / name).read_bytes())
    css = d / "tokens.css"
    css.write_text(css.read_text(encoding="utf-8").replace("--s1: 4px", "--s1: 5px", 1), encoding="utf-8", newline="\n")
    r = subprocess.run([sys.executable, str(d / "build_tokens.py"), "--check"], capture_output=True, text=True,
                       cwd=d, timeout=120)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL: tokens.css differs" in r.stderr


def _copy_folder(tmp_path, *names):
    for name in names:
        (tmp_path / name).write_bytes((TOKENS / name).read_bytes())


def _check_copy(tmp_path):
    return subprocess.run([sys.executable, str(tmp_path / "build_tokens.py"), "--check"], capture_output=True, text=True,
                          cwd=tmp_path, timeout=120)


def test_check_fails_on_a_hand_edited_theme_init(tmp_path):
    d = _flat(tmp_path)
    _copy_folder(d, "tokens.json", "build_tokens.py", "tokens.css", "theme-init.js")
    js = d / "theme-init.js"
    js.write_text(js.read_text(encoding="utf-8").replace('"palette"', '"palettes"', 1), encoding="utf-8", newline="\n")
    r = _check_copy(d)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL: theme-init.js differs" in r.stderr
    assert "OK: tokens.css matches tokens.json" in r.stdout  # the other output is still reported on its own


def test_check_fails_on_a_missing_theme_init(tmp_path):
    d = _flat(tmp_path)
    _copy_folder(d, "tokens.json", "build_tokens.py", "tokens.css")
    r = _check_copy(d)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "theme-init.js does not exist" in r.stderr


def _tile_part(css):
    start = css.index("/* Preview tiles")
    return css[start:css.index("/* Phone:", start)]


def test_preview_tile_blocks_hold_colour_type_and_radius_only():
    # 08 section 3.4: a tile block must not carry a size, elevation or motion token, or it could undo a phone block
    themes = json.loads((TOKENS / "tokens.json").read_text(encoding="utf-8"))["themes"]
    tiles = _tile_part((TOKENS / "tokens.css").read_text(encoding="utf-8"))
    for name in themes:
        sel = f'[data-look="{name}"]'
        assert f"\n{sel} {{" in tiles, name
        assert f'  :root:not([data-theme="light"]) {sel} {{' in tiles, name
        assert f':root[data-theme="dark"] {sel} {{' in tiles, name
    assert "\n:root {" not in tiles and "  color-scheme:" not in tiles
    for name, t in themes.items():  # no size, elevation or motion key of any theme appears
        extra = t.get("extra", {})
        keys = [*t["size"], *t["motion"], *t["elevation"]["light"], *t["elevation"]["dark"],
                *extra.get("size", {}), *extra.get("elevation", {}).get("light", {})]
        for key in keys:
            assert f"--{key.removesuffix('-phone')}:" not in tiles, (name, key)


def test_theme_init_lists_exactly_the_theme_keys():
    themes = json.loads((TOKENS / "tokens.json").read_text(encoding="utf-8"))["themes"]
    js = (TOKENS / "theme-init.js").read_text(encoding="utf-8")
    listed = json.loads(re.search(r"if \((\[[^\]]*\])\.indexOf\(l\)", js).group(1))
    assert listed == list(themes)
    assert js.startswith("// Spoolwarden design tokens. GENERATED by build_tokens.py from tokens.json.")
    assert "\r" not in js and js.endswith("\n")


def _mirror(tmp_path):
    """A copy of the token folder, the Android and strings outputs and strings/en.json, laid out as in the repository;
    --check passes on it."""
    for name in ("tokens.json", "build_tokens.py", "tokens.css", "theme-init.js"):
        (tmp_path / "tokens").mkdir(exist_ok=True)
        (tmp_path / "tokens" / name).write_bytes((TOKENS / name).read_bytes())
    for rel in ANDROID_OUTPUTS:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes((ROOT / rel).read_bytes())
    for rel in (*STRINGS, STRINGS_XML):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes((ROOT / rel).read_bytes())
    return tmp_path / "tokens" / "build_tokens.py"


def _check(script):
    return subprocess.run([sys.executable, str(script), "--check"], capture_output=True, text=True, cwd=script.parent, timeout=120)


def test_mirror_passes_the_check(tmp_path):
    r = _check(_mirror(tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr


def test_check_fails_on_a_hand_edited_android_file(tmp_path):
    for rel, old, new in ((KT, "s1 = 4.dp", "s1 = 5.dp"), (WINDOW, "#F3F5F6", "#000000"), (WINDOW_NIGHT, "#0B0F12", "#000000")):
        script = _mirror(tmp_path)
        f = tmp_path / rel
        text = f.read_text(encoding="utf-8")
        assert old in text, rel
        f.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")
        r = _check(script)
        assert r.returncode == 1 and "FAIL" in r.stderr, (rel, r.stdout + r.stderr)


def test_check_fails_on_a_hand_edited_strings_file(tmp_path):
    for rel, old, new in ((STRINGS[1], '"Back"', '"Go back"'), (STRINGS_XML, ">Back<", ">Go back<")):
        script = _mirror(tmp_path)
        f = tmp_path / rel
        text = f.read_text(encoding="utf-8")
        assert old in text, rel
        f.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")
        r = _check(script)
        assert r.returncode == 1 and "FAIL" in r.stderr, (rel, r.stdout + r.stderr)


def test_check_fails_on_a_missing_android_file(tmp_path):
    for rel in ANDROID_OUTPUTS:
        script = _mirror(tmp_path)
        (tmp_path / rel).unlink()
        r = _check(script)
        assert r.returncode == 1 and "does not exist" in r.stderr, (rel, r.stdout + r.stderr)


def test_kotlin_holds_one_theme_tokens_per_theme():
    themes = json.loads((TOKENS / "tokens.json").read_text(encoding="utf-8"))["themes"]
    kt = (ROOT / KT).read_text(encoding="utf-8")
    assert re.findall(r"^    val (\w+) = ThemeTokens\(", kt, re.M) == list(themes)
    for name in themes:
        assert f"Look.{name.capitalize()} -> {name}" in kt


def test_colour_conversion_per_form():
    sys.path.insert(0, str(TOKENS))
    try:
        import build_tokens as bt
    finally:
        sys.path.remove(str(TOKENS))
    assert bt.kt_color("#f3f5f6") == "Color(0xFFF3F5F6)"
    assert bt.kt_color("rgb(12 18 22 / .5)") == "Color(0x800C1216)"  # 127.5 rounds up to 128
    assert bt.kt_color("rgba(16,18,32,.45)") == "Color(0x73101220)"  # 114.75 -> 115
    assert bt.kt_color("rgba(0,0,0,.62)") == "Color(0x9E000000)"  # 158.1 -> 158
    assert bt.kt_sp("0.6875rem") == "11.sp" and bt.kt_dp("4px") == "4.dp"


def _contrast(*args):
    return subprocess.run([sys.executable, str(TOKENS / "check_contrast.py"), *map(str, args)], capture_output=True, text=True,
                          cwd=TOKENS, timeout=120)


def test_contrast_counts_the_old_pairs_and_the_new_ones():
    r = _contrast()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "required pairs checked: 424 (of which 248 are the first version's); failed: 0" in r.stdout
    assert "advisory" not in r.stdout  # accent-text on accent-soft and text on surface-3 are required now
    rows = [line.split() for line in r.stdout.splitlines()]
    assert ["palette", "dark", "focus", "surface-2", "3.0"] == next(x for x in rows if x[:4] == ["palette", "dark", "focus", "surface-2"])[:5]
    assert any(x[:4] == ["panes", "light", "accent-text", "accent-soft"] for x in rows)


def test_lowered_token_value_fails_in_the_message_form_of_aut_1(tmp_path):
    data = json.loads((TOKENS / "tokens.json").read_text(encoding="utf-8"))
    data["themes"]["palette"]["dark"]["muted"] = "#6B5E52"
    bad = tmp_path / "tokens.json"
    bad.write_text(json.dumps(data), encoding="utf-8")
    r = _contrast(bad)
    assert r.returncode == 1, r.stdout + r.stderr
    assert re.search(r"palette dark: --muted on --surface-2 is \d\.\d\d:1, needs 4\.5:1 \(CON-1\)", r.stderr), r.stderr
    assert r.stdout.rstrip().endswith("RESULT: FAIL")


def test_lowered_added_pair_value_fails(tmp_path):
    # a 07 3.2 pair that the first version did not check: the focus ring on a log block
    data = json.loads((TOKENS / "tokens.json").read_text(encoding="utf-8"))
    data["themes"]["console"]["light"]["focus"] = data["themes"]["console"]["light"]["code"]
    bad = tmp_path / "tokens.json"
    bad.write_text(json.dumps(data), encoding="utf-8")
    r = _contrast(bad)
    assert r.returncode == 1
    assert "console light: --focus on --code is 1.00:1, needs 3:1 (CON-1)" in r.stderr


def test_missing_token_fails(tmp_path):
    data = json.loads((TOKENS / "tokens.json").read_text(encoding="utf-8"))
    del data["themes"]["panes"]["dark"]["surface-3"]
    bad = tmp_path / "tokens.json"
    bad.write_text(json.dumps(data), encoding="utf-8")
    r = _contrast(bad)
    assert r.returncode == 1
    assert "panes dark: --surface-3 is missing" in r.stderr


def test_material_pairs_are_read_from_the_kotlin_values(tmp_path):
    # tokens.json stays as it is; one Kotlin colour is lowered, so only the CON-8 rows can catch it
    kt = (ROOT / KT).read_text(encoding="utf-8")
    old = "onBad = Color(0xFF2A0B07)"  # palette dark
    assert old in kt
    low = tmp_path / "SpoolwardenTokens.kt"
    low.write_text(kt.replace(old, "onBad = Color(0xFF8F5A55)", 1), encoding="utf-8", newline="\n")
    r = _contrast(TOKENS / "tokens.json", low)
    assert r.returncode == 1, r.stdout + r.stderr
    assert re.search(r"palette dark: onError on error is \d\.\d\d:1, needs 4\.5:1 \(CON-8\)", r.stderr), r.stderr
    assert r.stderr.count("\n") == 1  # the web pairs are untouched
    assert _contrast(TOKENS / "tokens.json", tmp_path / "missing.kt").returncode == 1  # no Kotlin file, no Material values
