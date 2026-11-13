"""The token folder's two checks (docs/design/08-platform-mapping.md 3.3) in the project's normal test run.

tokens.css must equal what tokens.json generates, and every required contrast pair must pass.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

TOKENS = Path(__file__).resolve().parent.parent / "tokens"


def _run(*args):
    return subprocess.run([sys.executable, *args], capture_output=True, text=True, cwd=TOKENS, timeout=120)


def test_tokens_css_matches_tokens_json():
    r = _run(str(TOKENS / "build_tokens.py"), "--check")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "OK: tokens.css matches tokens.json" in r.stdout
    assert "OK: theme-init.js matches tokens.json" in r.stdout


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


def test_check_fails_on_a_crlf_css(tmp_path):
    # what a checkout without the LF rule would hand the check: it must say so rather than pass
    for name in ("tokens.json", "build_tokens.py", "theme-init.js"):
        (tmp_path / name).write_bytes((TOKENS / name).read_bytes())
    (tmp_path / "tokens.css").write_bytes((TOKENS / "tokens.css").read_bytes().replace(b"\n", b"\r\n"))
    r = subprocess.run([sys.executable, str(tmp_path / "build_tokens.py"), "--check"], capture_output=True, text=True,
                       cwd=tmp_path, timeout=120)
    assert r.returncode == 1, r.stdout + r.stderr


def test_check_fails_on_a_hand_edited_css(tmp_path):
    # the equality check must catch a tokens.css edited by hand: run a copy of the folder with one value changed
    for name in ("tokens.json", "build_tokens.py", "tokens.css", "theme-init.js"):
        (tmp_path / name).write_bytes((TOKENS / name).read_bytes())
    css = tmp_path / "tokens.css"
    css.write_text(css.read_text(encoding="utf-8").replace("--s1: 4px", "--s1: 5px", 1), encoding="utf-8", newline="\n")
    r = subprocess.run([sys.executable, str(tmp_path / "build_tokens.py"), "--check"], capture_output=True, text=True,
                       cwd=tmp_path, timeout=120)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL" in r.stdout + r.stderr


def _copy_folder(tmp_path, *names):
    for name in names:
        (tmp_path / name).write_bytes((TOKENS / name).read_bytes())


def _check_copy(tmp_path):
    return subprocess.run([sys.executable, str(tmp_path / "build_tokens.py"), "--check"], capture_output=True, text=True,
                          cwd=tmp_path, timeout=120)


def test_check_fails_on_a_hand_edited_theme_init(tmp_path):
    _copy_folder(tmp_path, "tokens.json", "build_tokens.py", "tokens.css", "theme-init.js")
    js = tmp_path / "theme-init.js"
    js.write_text(js.read_text(encoding="utf-8").replace('"spool"', '"spools"', 1), encoding="utf-8", newline="\n")
    r = _check_copy(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL: theme-init.js differs" in r.stderr
    assert "OK: tokens.css matches tokens.json" in r.stdout  # the other output is still reported on its own


def test_check_fails_on_a_missing_theme_init(tmp_path):
    _copy_folder(tmp_path, "tokens.json", "build_tokens.py", "tokens.css")
    r = _check_copy(tmp_path)
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
