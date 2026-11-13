"""The token folder's two checks (docs/design/08-platform-mapping.md 3.3) in the project's normal test run.

tokens.css must equal what tokens.json generates, and every required contrast pair must pass.
"""
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


def test_required_contrast_pairs_pass():
    r = _run(str(TOKENS / "check_contrast.py"))
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.rstrip().endswith("RESULT: PASS"), r.stdout[-400:]


def test_check_fails_on_a_hand_edited_css(tmp_path):
    # the equality check must catch a tokens.css edited by hand: run a copy of the folder with one value changed
    for name in ("tokens.json", "build_tokens.py", "tokens.css"):
        (tmp_path / name).write_bytes((TOKENS / name).read_bytes())
    css = tmp_path / "tokens.css"
    css.write_text(css.read_text(encoding="utf-8").replace("--s1: 4px", "--s1: 5px", 1), encoding="utf-8", newline="\n")
    r = subprocess.run([sys.executable, str(tmp_path / "build_tokens.py"), "--check"], capture_output=True, text=True,
                       cwd=tmp_path, timeout=120)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL" in r.stdout + r.stderr
