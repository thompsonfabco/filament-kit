"""Checks of the shared component files of design step S0.11 (docs/design/09-implementation-order.md):
web-shared/components.css and web-shared/components.js, and the additions components-jobs.css, components-media.css,
components-media.js and components-lock.js (the Hub page's lock chip and unlock dialog).

The size limits of foundations 12 rule 7, every class the script uses is drawn by the stylesheet, every catalogue key
the script names is in strings/en.json, and the page audit (AUT-5, tests/page_audit.js) is a script that parses. The
lints of test_design_lints.py and test 4 of test_design_sources.py read the two files with the page sources. The audit
itself runs on the sample page through tests/aut5_run.mjs (the one AUT-5 runner) in a Chrome, Edge or Chromium already
on the machine.
"""
import http.server
import json
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from test_design_lints import _Scan
from test_design_sources import ROOT

SHARED = ROOT / "web-shared"
CSS = SHARED / "components.css"
JS = SHARED / "components.js"
ADDITIONS = [SHARED / "components-jobs.css", SHARED / "components-media.css"]
MEDIA_JS = SHARED / "components-media.js"
LOCK_JS = SHARED / "components-lock.js"
AUDIT = ROOT / "tests" / "page_audit.js"
RUNNER = ROOT / "tests" / "aut5_run.mjs"
SAMPLE = ROOT / "tests" / "components-sample.html"
CATALOGUE = json.loads((ROOT / "strings" / "en.json").read_text(encoding="utf-8"))

# foundations 12 rule 7: "under 40 KB" and "under 60 KB", uncompressed, and each addition "at most 30 KB"; read as
# thousands of bytes (the stricter reading)
LIMITS = {CSS: 40_000, JS: 60_000, **{a: 30_000 for a in ADDITIONS + [MEDIA_JS, LOCK_JS]}}

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
    used = set().union(*(script_classes(p.read_text(encoding="utf-8")) for p in (JS, MEDIA_JS, LOCK_JS)))
    assert {"btn", "result", "dialog__title", "field__control", "coll__sort"} <= used
    missing = sorted(c for c in used if not css_has(c, css))
    assert not missing, "classes the script uses that the shared stylesheets do not draw: " + ", ".join(missing)


def test_every_key_of_the_script_is_in_the_catalogue():
    keys = set().union(*(script_keys(p.read_text(encoding="utf-8")) for p in (JS, MEDIA_JS, LOCK_JS)))
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
                "../web-shared/components.js", "../web-shared/components-media.js", "../web-shared/components-lock.js",
                "components-sample.js"):
        assert src in sample, src


@pytest.mark.skipif(not shutil.which("node"), reason="no JavaScript parser (node) on this machine")
@pytest.mark.parametrize("path", [AUDIT, RUNNER, JS, MEDIA_JS, LOCK_JS, ROOT / "tests" / "components-sample.js"], ids=lambda p: p.name)
def test_scripts_parse(path):
    r = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def _node():
    """Node 22 or later (the runner talks to the browser with Node's own WebSocket), or None."""
    node = shutil.which("node")
    if not node:
        return None
    major = subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip().lstrip("v").split(".")[0]
    return node if major.isdigit() and int(major) >= 22 else None


def _missing(why):
    """No Node 22 or no browser: a skip, or a failure where the run is required (AUT5_REQUIRED=1, e.g. in CI)."""
    if os.environ.get("AUT5_REQUIRED") == "1":
        pytest.fail(f"AUT5_REQUIRED=1 but {why}")
    pytest.skip(why)


class _Quiet(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, ".js": "text/javascript", ".mjs": "text/javascript",
                      ".css": "text/css", ".svg": "image/svg+xml", ".json": "application/json", "": "application/octet-stream"}

    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(ROOT), **k)

    def log_message(self, *a):
        pass


# 09 S0.11 "Check": AUT-5 on the sample page at 1280 px and 320 px (touch), light and dark; every view has no finding.
# One runner for every page (09 S1.11): tests/aut5_run.mjs, with no allow-list here.
def test_page_audit_on_the_sample():
    node = _node()
    if not node:
        _missing("AUT-5 needs Node 22 or later")
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Quiet)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        r = subprocess.run([node, str(RUNNER), "--url", f"http://127.0.0.1:{server.server_address[1]}/tests/components-sample.html",
                            "--views", "#printers"], capture_output=True, text=True, encoding="utf-8", timeout=300)
    finally:
        server.shutdown()
        server.server_close()
    if r.returncode == 2 and "no Chrome, Edge or Chromium" in r.stderr:
        _missing("AUT-5 needs a Chrome, Edge or Chromium (set AUT5_BROWSER)")
    if r.returncode == 3:          # a browser was found but cannot run headless on this machine (its error is shown)
        _missing("AUT-5: " + r.stderr.strip().replace("AUT-5: ", "", 1))
    assert r.returncode == 0, r.stdout + r.stderr
    out = json.loads(r.stdout)
    assert out["views"] == 4 and out["failing"] == 0 and not out.get("allowed")      # 1280 / 320 px, light / dark
    for p in out["passes"]:      # each view really ran at its width, appearance and (at 320 px) as a touch device
        assert (p["innerWidth"], p["dark"], p["coarse"]) == (p["width"], p["scheme"] == "dark", p["width"] == 320), p
    assert {(p["width"], p["scheme"]) for p in out["passes"]} == {(1280, "light"), (1280, "dark"), (320, "light"), (320, "dark")}
