"""Checks of the shared component files of design step S0.11 (docs/design/09-implementation-order.md):
web-shared/components.css and web-shared/components.js, and the additions components-jobs.css, components-media.css and
components-media.js.

The size limits of foundations 12 rule 7, every class the script uses is drawn by the stylesheet, every catalogue key
the script names is in strings/en.json, and the page audit (AUT-5, tests/page_audit.js) is a script that parses. The
lints of test_design_lints.py and test 4 of test_design_sources.py read the two files with the page sources. The audit
itself runs on the sample page in headless Microsoft Edge (tests/run_page_audit.js) where Edge is installed.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from test_design_lints import _Scan
from test_design_sources import ROOT

SHARED = ROOT / "web-shared"
CSS = SHARED / "components.css"
JS = SHARED / "components.js"
ADDITIONS = [SHARED / "components-jobs.css", SHARED / "components-media.css"]
MEDIA_JS = SHARED / "components-media.js"
AUDIT = ROOT / "tests" / "page_audit.js"
RUNNER = ROOT / "tests" / "run_page_audit.js"
SAMPLE = ROOT / "tests" / "components-sample.html"
CATALOGUE = json.loads((ROOT / "strings" / "en.json").read_text(encoding="utf-8"))

# foundations 12 rule 7: "under 40 KB" and "under 60 KB", uncompressed, and each addition "at most 30 KB"; read as
# thousands of bytes (the stricter reading)
LIMITS = {CSS: 40_000, JS: 60_000, **{a: 30_000 for a in ADDITIONS + [MEDIA_JS]}}

CLASS = r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*(?:__[a-z0-9]+(?:-[a-z0-9]+)*)?(?:--[a-z0-9]+(?:-[a-z0-9]+)*)?"
CLASS_TOKEN = re.compile(rf"^{CLASS}$")
# where the script names classes: class: "…", E(tag, "…"), cls: "…", classList.x("…"), icon(name, "…"), and " block--variant"
CLASS_CONTEXT = re.compile(r"""(?:\bclass(?:Name)?:\s*|\bE\(\s*"[a-z0-9]+",\s*|\bcls:\s*|classList\.(?:add|remove|toggle)\(\s*|\bicon\([^,()]+,\s*)$""")
SELECTOR_CLASS = re.compile(rf"(?:^|[\s,>(+~:])\.({CLASS})(?![\w-])")
KEY = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$")


def css_has(cls, css):
    return re.search(r"\." + re.escape(cls) + r"(?![\w-])", css) is not None


def script_classes(text):
    """Class names the script writes (in a class context or a ' block--variant' string) or selects ('.block__part')."""
    scan = _Scan(text, js=True)
    out = set()
    for m in re.finditer(r"""(["'`])((?:\\.|(?!\1).)*?)\1""", text):
        content = re.sub(r"\$\{[^}]*\}", " ", m.group(2))
        before = text[max(0, m.start() - 40):m.start()]
        if CLASS_CONTEXT.search(before) or re.match(r"^ [a-z][\w-]*--", content):
            out.update(tok for tok in content.split() if CLASS_TOKEN.match(tok) and not tok.endswith(("-", "_")))
        out.update(SELECTOR_CLASS.findall(content))
    assert scan.literals                                   # the scanner read the file
    return out


def script_keys(text):
    """String literals that look like catalogue keys, for the prefixes the catalogue uses."""
    prefixes = {k.split("_")[0] for k in CATALOGUE}
    return {c for c, _ in _Scan(text, js=True).literals if KEY.match(c) and c.split("_")[0] in prefixes}


@pytest.mark.parametrize("path", list(LIMITS), ids=lambda p: p.name)
def test_size_limits(path):
    size = path.stat().st_size
    assert size < LIMITS[path], f"{path.name} is {size} bytes; the limit is {LIMITS[path]}"


# 01 4.3, 02 1.2: hairlines and marks use --hairline and --nav-mark, never a bare 1px or 3px
BARE_MARK = re.compile(r"(?<![\w.-])[13]px\b")


def bare_marks(css):
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group().count("\n"), css, flags=re.S)   # comments keep their lines
    return [text[:m.start()].count("\n") + 1 for m in BARE_MARK.finditer(text)]


@pytest.mark.parametrize("path", [CSS] + ADDITIONS, ids=lambda p: p.name)
def test_no_bare_hairline_or_mark(path):
    lines = bare_marks(path.read_text(encoding="utf-8"))
    assert not lines, f"{path.name}: bare 1px or 3px on line(s) {lines}; use var(--hairline) or var(--nav-mark)"


def test_bare_marks_are_found():
    assert bare_marks(".a{border:1px solid}\n.b{width:3px;outline:2px solid;inset:min(0px,1)}\n.c{top:11px;x:1.1px}") == [1, 2]
    assert bare_marks(".a{border:var(--hairline) solid} /* 1px */") == []


def test_every_class_of_the_script_is_drawn():
    css = "\n".join(p.read_text(encoding="utf-8") for p in [CSS] + ADDITIONS)
    used = script_classes(JS.read_text(encoding="utf-8")) | script_classes(MEDIA_JS.read_text(encoding="utf-8"))
    assert {"btn", "result", "dialog__title", "field__control", "coll__sort"} <= used
    missing = sorted(c for c in used if not css_has(c, css))
    assert not missing, "classes the script uses that the shared stylesheets do not draw: " + ", ".join(missing)


def test_every_key_of_the_script_is_in_the_catalogue():
    keys = script_keys(JS.read_text(encoding="utf-8"))
    assert {"common_close", "unlock_title", "status_needs_look", "form_saved_fields"} <= keys
    missing = sorted(k for k in keys if k not in CATALOGUE)
    assert not missing, "keys the script names that strings/en.json does not hold: " + ", ".join(missing)


def test_the_checks_fail_on_plants():
    assert script_classes('h("span", { class: "btn nope__part" }); x.closest(".gone"); const m = " field--odd";') >= \
        {"btn", "nope__part", "gone", "field--odd"}
    assert script_classes('E("span", `status status--${kind}`); const k = "plain words"; h("div", { class: `a ${b}` })') == {"status", "a"}
    assert not css_has("nope__part", ".btn{} .nope__part-x{}") and css_has("btn", "a .btn:hover{}")
    assert script_keys('t("common_close"); const w = ["s-filled", "ok", "status_ok"]; t("nope_key"); x.dataset.nav__item') == \
        {"common_close", "status_ok"}


def test_page_audit_and_sample_exist():
    text = AUDIT.read_text(encoding="utf-8")
    for check in ("without a name", "h1", "landmark", "lang", "title", "tabindex", "img", "svg", "aria-expanded",
                  "aria-busy", "role=status", "cell", "07 9.1", "44 x 44", "horizontal page scroll", "zoom"):
        assert check in text, check
    sample = SAMPLE.read_text(encoding="utf-8")
    assert "<script>" not in sample and " style=" not in sample        # no inline script or style (strict CSP)
    for src in ("../tokens/theme-init.js", "../tokens/tokens.css", "../web-shared/components.css", "../web-shared/components-jobs.css",
                "../web-shared/components-media.css", "../strings/strings.js",
                "../web-shared/components.js", "../web-shared/components-media.js", "components-sample.js"):
        assert src in sample, src


@pytest.mark.skipif(not shutil.which("node"), reason="no JavaScript parser (node) on this machine")
@pytest.mark.parametrize("path", [AUDIT, RUNNER, JS, MEDIA_JS, ROOT / "tests" / "components-sample.js"], ids=lambda p: p.name)
def test_scripts_parse(path):
    r = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def edge():
    """The Microsoft Edge executable: $SW_EDGE, Edge on the PATH, or (Windows) the one the registry names; else None."""
    if os.environ.get("SW_EDGE"):
        return os.environ["SW_EDGE"] if Path(os.environ["SW_EDGE"]).is_file() else None
    for name in ("msedge", "microsoft-edge", "microsoft-edge-stable"):
        if shutil.which(name):
            return shutil.which(name)
    if sys.platform == "win32":
        import winreg
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe") as key:
                    path = winreg.QueryValue(key, None)
            except OSError:
                continue
            if Path(path).is_file():
                return path
    mac = Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge")
    return str(mac) if mac.is_file() else None


EDGE = edge()


def _node_has_websocket():
    """The runner talks to the browser with Node's own WebSocket (Node 22 and later); older Node has none."""
    if not shutil.which("node"):
        return False
    r = subprocess.run(["node", "-e", "process.exit(typeof WebSocket === 'function' ? 0 : 1)"], capture_output=True)
    return r.returncode == 0


NODE_WS = _node_has_websocket()


# 09 S0.11 "Check": AUT-5 on the sample page at 1280 px and 320 px (touch), light and dark; every view has no finding
@pytest.mark.skipif(not NODE_WS, reason="node 22 or later (with WebSocket) is not installed, so the page audit (AUT-5) did not run")
@pytest.mark.skipif(EDGE is None, reason="Microsoft Edge is not installed (or set SW_EDGE to its path), so the page "
                                         "audit (AUT-5) on the sample page did not run")
def test_page_audit_on_the_sample():
    r = subprocess.run(["node", str(RUNNER), EDGE], capture_output=True, text=True, encoding="utf-8", timeout=300)
    assert r.returncode == 0, r.stderr
    views = json.loads(r.stdout)
    assert sorted(views) == ["1280 dark", "1280 light", "320 dark", "320 light"]
    for name, view in views.items():
        width, scheme = name.split()
        assert (view["innerWidth"], view["dark"], view["coarse"]) == (int(width), scheme == "dark", width == "320"), name
    found = {name: view["findings"] for name, view in views.items() if view["findings"]}
    assert not found, "page audit findings on tests/components-sample.html: " + json.dumps(found, indent=1)
