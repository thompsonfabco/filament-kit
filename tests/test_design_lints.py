"""Lint checks of docs/design/07-accessibility.md section 15 (AUT-2, AUT-3, AUT-4, AUT-6, AUT-7) and of
docs/design/08-platform-mapping.md 3.4 test 5, one test function per lint.

They read the web sources (`setup_static/*`, `web/static/*`) and the app's Kotlin (see test_design_sources.py). Today's
findings are in the allow-lists next to this file, one line each: `<path> | <finding> | <reason>`. A finding outside
its allow-list fails, and so does an allow-list line that no longer matches anything (09 open point 4), so a step that
rewrites a file removes that file's lines.
"""
import re
from pathlib import Path

from test_design_sources import ROOT, _kotlin_sources, _web_sources

TESTS = ROOT / "tests"
LITERAL_ALLOWLIST = TESTS / "literal_allowlist.txt"
DIALOG_ALLOWLIST = TESTS / "dialog_allowlist.txt"
FIELD_ALLOWLIST = TESTS / "field_allowlist.txt"
PRESS_ALLOWLIST = TESTS / "press_allowlist.txt"
WORDS_ALLOWLIST = TESTS / "words_allowlist.txt"
ACCENT_ALLOWLIST = TESTS / "accent_allowlist.txt"

# The field component (07 AUT-4) does not exist yet; the file that holds it goes here when S0.10/S0.11 add it.
FIELD_COMPONENT_FILES = frozenset()
TOKEN_CSS = frozenset({"tokens.css"})       # the generated token block: literals belong there (foundations 12.5)

# ---- Reading the sources ----

# Strings whose content stays visible in the "code view" of a script, so the lints can match them
KEPT_STRINGS = {"alert", "confirm", "prompt", "input", "select", "textarea", "pointerdown", "mousedown", "touchstart"}


class _Scan:
    """Walks a script or Kotlin file once. `code` is the text with comments, regular expressions and string contents
    blanked (newlines kept, so offsets and line numbers stay); `literals` is [(content, line)] of every string."""

    def __init__(self, text, js):
        self.t, self.js, self.n = text, js, len(text)
        self.code = list(text)
        self.literals = []
        self._code(0, False)

    def _blank(self, a, b):
        for k in range(a, min(b, self.n)):
            if self.code[k] != "\n":
                self.code[k] = " "

    def _line(self, i):
        return self.t.count("\n", 0, i) + 1

    def _regex_ok(self, i):
        j = i - 1
        while j >= 0 and self.t[j] in " \t":
            j -= 1
        if j < 0 or self.t[j] in "(,=:[!&|?{};\n":
            return True
        m = re.search(r"(return|typeof|case)$", self.t[max(0, j - 6):j + 1])
        return bool(m)

    def _regex(self, i):
        j, in_class = i + 1, False
        while j < self.n and self.t[j] != "\n":
            c = self.t[j]
            if c == "\\":
                j += 1
            elif c == "[":
                in_class = True
            elif c == "]":
                in_class = False
            elif c == "/" and not in_class:
                j += 1
                while j < self.n and self.t[j].isalpha():
                    j += 1
                return j
            j += 1
        return i + 1

    def _code(self, i, nested):
        depth, t, n = 0, self.t, self.n
        while i < n:
            c = t[i]
            if t.startswith("//", i):
                j = t.find("\n", i)
                j = n if j < 0 else j
                self._blank(i, j)
                i = j
                continue
            if t.startswith("/*", i):
                j = t.find("*/", i + 2)
                j = n if j < 0 else j + 2
                self._blank(i, j)
                i = j
                continue
            if self.js and c == "/" and self._regex_ok(i):
                j = self._regex(i)
                self._blank(i, j)
                i = j
                continue
            if c in "'\"" or (self.js and c == "`"):
                i = self._string(i)
                continue
            if nested:
                if c == "{":
                    depth += 1
                elif c == "}":
                    if depth == 0:
                        return i + 1
                    depth -= 1
            i += 1
        return i

    def _string(self, i):
        t, n = self.t, self.n
        q = t[i]
        triple = not self.js and t.startswith('"""', i)
        start = i
        i += 3 if triple else 1
        begin, parts = i, []
        while i < n:
            c = t[i]
            if triple and t.startswith('"""', i):
                break
            if not triple and c == q:
                break
            if c == "\n" and q != "`" and not triple:
                break
            if c == "\\" and not triple:
                i += 2
                continue
            if c == "$" and t.startswith("${", i) and (q == "`" or not self.js):
                parts.append(t[begin:i])
                i = self._code(i + 2, True)
                begin = i
                parts.append("${}")
                continue
            i += 1
        parts.append(t[begin:i])
        content = "".join(parts)
        self.literals.append((content, self._line(start)))
        if content not in KEPT_STRINGS:
            self._blank(begin, i)
        return i + (3 if triple else 1)

    @property
    def code_text(self):
        return "".join(self.code)


def _line_of(text, pos):
    return text.count("\n", 0, pos) + 1


def _script_sources():
    return [f for f in _web_sources() if f.suffix == ".js" and f.name != "sw.js"] + \
           [f for f in _web_sources() if f.name == "sw.js"]


def _rel(f):
    return f.relative_to(ROOT).as_posix()


def _entries(path):
    """Allow-list lines as {(file, finding): reason}."""
    entries = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            parts = [x.strip() for x in line.split("|", 2)]
            assert len(parts) == 3 and all(parts), f"{path.name}: a line needs a file, a finding and a reason: {line!r}"
            key = (parts[0], parts[1])
            assert key not in entries, f"{path.name}: listed twice: {line!r}"
            entries[key] = parts[2]
    return entries


def _verdict(found, allowlist):
    """found: {(file, finding): first line}. Returns (not listed, listed but gone)."""
    allowed = set(_entries(allowlist))
    new = sorted(f"{f}:{ln}: {what}" for (f, what), ln in found.items() if (f, what) not in allowed)
    stale = sorted(f"{f} | {what}" for f, what in allowed if (f, what) not in found)
    return new, stale


def _collect(files, finder):
    found = {}
    for f in files:
        for what, ln in finder(f.read_text(encoding="utf-8")):
            found.setdefault((_rel(f), what), ln)
    return found


def _assert_lint(found, allowlist):
    new, stale = _verdict(found, allowlist)
    assert not new, "not in the allow-list:\n" + "\n".join(new)
    assert not stale, f"in {allowlist.name} but no longer found, drop the line:\n" + "\n".join(stale)


# ---- AUT-2 / test 5: literal colours and values ----

NAMED_COLOURS = set("""aliceblue antiquewhite aqua aquamarine azure beige bisque black blanchedalmond blue blueviolet brown
burlywood cadetblue chartreuse chocolate coral cornflowerblue cornsilk crimson cyan darkblue darkcyan darkgoldenrod darkgray
darkgreen darkgrey darkkhaki darkmagenta darkolivegreen darkorange darkorchid darkred darksalmon darkseagreen darkslateblue
darkslategray darkslategrey darkturquoise darkviolet deeppink deepskyblue dimgray dimgrey dodgerblue firebrick floralwhite
forestgreen fuchsia gainsboro ghostwhite gold goldenrod gray green greenyellow grey honeydew hotpink indianred indigo ivory
khaki lavender lavenderblush lawngreen lemonchiffon lightblue lightcoral lightcyan lightgoldenrodyellow lightgray lightgreen
lightgrey lightpink lightsalmon lightseagreen lightskyblue lightslategray lightslategrey lightsteelblue lightyellow lime
limegreen linen magenta maroon mediumaquamarine mediumblue mediumorchid mediumpurple mediumseagreen mediumslateblue
mediumspringgreen mediumturquoise mediumvioletred midnightblue mintcream mistyrose moccasin navajowhite navy oldlace olive
olivedrab orange orangered orchid palegoldenrod palegreen paleturquoise palevioletred papayawhip peachpuff peru pink plum
powderblue purple rebeccapurple red rosybrown royalblue saddlebrown salmon sandybrown seagreen seashell sienna silver skyblue
slateblue slategray slategrey snow springgreen steelblue tan teal thistle tomato turquoise violet wheat white whitesmoke
yellow yellowgreen""".split())
HEX_LITERAL = re.compile(r"#[0-9a-fA-F]{3,8}\b")
COLOUR_FN = re.compile(r"\b(rgba?|hsla?|hwb|lab|lch|oklab|oklch)\(")
WORD = re.compile(r"[a-zA-Z]+")
LENGTH = re.compile(r"(?<![\w.#-])-?(?:\d+\.?\d*|\.\d+)(?:px|rem|em|vh|vw|dvh|dvw|svh|lvh|ch|pt|cm|mm|in)\b")
TIME = re.compile(r"(?<![\w.#-])(?:\d+\.?\d*|\.\d+)(?:ms|s)\b")
FUNC_LENGTH = re.compile(r"\b(?:calc|min|max|clamp)\(")
LENGTH_OK = {"0", "1px", "2px", "3px"}                  # hairline, focus ring and its offset, active mark (02 1.2)
LINE_HEIGHT_OK = {"1.45", "1.25"}                       # foundations 4.2
DURATION_PROPS = ("transition", "animation")
CSS_RULE = re.compile(r"([^{}]*)\{([^{}]*)\}")
CSS_COMMENT = re.compile(r"/\*.*?\*/", re.S)
CSS_STRING = re.compile(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'")
CSS_URL = re.compile(r"url\([^)]*\)")
CUSTOM_NAME = re.compile(r"--[\w-]+")
KOTLIN_COLOR_CONST = re.compile(r"\bColor\.(?!Transparent\b|Unspecified\b)\w+")
KOTLIN_COLOR_FN = re.compile(r"\bColor\(\s*0x[0-9a-fA-F_]+")
KOTLIN_SP = re.compile(r"(?<![\w.])\d+(?:\.\d+)?\.sp\b")
KOTLIN_DP = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\.dp\b")
KOTLIN_EM = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\.em\b")


def _blank_keep_lines(m):
    return re.sub(r"[^\n]", " ", m.group(0))


def css_findings(text):
    """[(finding, line)] for component rules; tokens.css (the token block) is not read."""
    text = CSS_COMMENT.sub(_blank_keep_lines, text)
    out = []
    for rule in CSS_RULE.finditer(text):
        body, pos = rule.group(2), rule.start(2)
        decls = []
        for part in body.split(";"):
            prop, colon, value = part.partition(":")
            if colon:
                decls.append((prop.strip().lower(), value.strip(), pos + len(part) - len(part.lstrip()), pos))
            pos += len(part) + 1
        props = {d[0] for d in decls}
        for prop, value, at, _ in decls:
            ln = _line_of(text, at)
            plain = CUSTOM_NAME.sub(" ", CSS_URL.sub(" ", CSS_STRING.sub(" ", value)))
            for lit in HEX_LITERAL.findall(plain):
                out.append((lit.lower(), ln))
            for fn in COLOUR_FN.findall(plain):
                out.append((fn + "(", ln))
            for word in WORD.findall(plain):
                if word.lower() in NAMED_COLOURS:
                    out.append((word.lower(), ln))
            if prop == "font-size":
                if not re.fullmatch(r"var\(--fs-[a-z0-9]+\)|inherit", value):
                    out.append((f"font-size: {value}", ln))
            elif prop == "line-height":
                if not (re.fullmatch(r"var\(--lh-[a-z]+\)|inherit", value) or value in LINE_HEIGHT_OK):
                    out.append((f"line-height: {value}", ln))
            elif prop.startswith(DURATION_PROPS) or prop.endswith(("-duration", "-delay")):
                for lit in TIME.findall(plain):
                    if float(lit.rstrip("ms")) != 0:
                        out.append((f"duration {lit}", ln))
            elif prop == "opacity":
                try:
                    if 0 < float(value) < 1:
                        out.append((f"opacity: {value}", ln))
                except ValueError:
                    out.append((f"opacity: {value}", ln))
            elif prop == "outline" and re.fullmatch(r"none|0", value) and "box-shadow" not in props:
                out.append((f"outline: {value}", ln))
            if prop not in ("font-size", "line-height") and not prop.startswith(DURATION_PROPS):
                if not (FUNC_LENGTH.search(plain) and "var(" in value):
                    for lit in LENGTH.findall(plain):
                        if lit not in LENGTH_OK and not re.fullmatch(r"-?0(\.0+)?[a-z]+", lit):
                            out.append((lit, ln))
    return out


def kotlin_findings(text):
    code = _Scan(text, js=False).code_text
    code = "\n".join("" if ln.lstrip().startswith(("import ", "package ")) else ln for ln in code.split("\n"))
    out = []
    for rx in (KOTLIN_COLOR_FN, KOTLIN_COLOR_CONST, KOTLIN_SP):
        out += [(re.sub(r"\s+", "", m.group(0)), _line_of(code, m.start())) for m in rx.finditer(code)]
    for rx, ok in ((KOTLIN_DP, {0, 1, 2, 3}), (KOTLIN_EM, {0.05})):
        out += [(m.group(0), _line_of(code, m.start())) for m in rx.finditer(code) if float(m.group(1)) not in ok]
    return out


def _literal_sources():
    css = [f for f in _web_sources() if f.suffix == ".css" and f.name not in TOKEN_CSS]
    return css, _kotlin_sources()


def test_no_literal_values_in_components():
    css, kt = _literal_sources()
    found = _collect(css, css_findings)
    found.update(_collect(kt, kotlin_findings))
    _assert_lint(found, LITERAL_ALLOWLIST)


# ---- AUT-2 / CON-9: --accent only as the fill of a labelled part ----

ACCENT_USE = re.compile(r"var\(\s*--accent\s*[,)]")
# the labelled fills of 07 CON-9, by their class in 02-components.md: the main button, the chosen part of a segmented
# choice, the skip link, the icon tile of the current section in the list navigation
LABELLED_FILLS = ("btn--primary", "segmented__option", "segmented__input", "skip", "nav__icon")
LABELLED_FILL = re.compile(r"\.(?:" + "|".join(re.escape(c) for c in LABELLED_FILLS) + r")(?![\w-])")


def accent_findings(text):
    """[(finding, line)]: a rule using var(--accent) with a selector that is not a labelled fill."""
    text = CSS_COMMENT.sub(_blank_keep_lines, text)
    out = []
    for rule in CSS_RULE.finditer(text):
        selector, body = rule.group(1), rule.group(2)
        if not ACCENT_USE.search(body):
            continue
        for sel in selector.split(","):
            sel = " ".join(sel.split())
            if sel and not LABELLED_FILL.search(sel):
                out.append((f"var(--accent) in {sel}", _line_of(text, rule.start(2))))
    return out


def test_accent_only_on_labelled_fills():
    css, _ = _literal_sources()
    _assert_lint(_collect(css, accent_findings), ACCENT_ALLOWLIST)


# ---- AUT-3: native dialogs; AUT-4: fields outside the field component; AUT-6: press-down handlers ----

DIALOG_CALL = re.compile(r"(?<![\w$.])(?:(?:window|self|globalThis)\s*\.\s*)?(alert|confirm|prompt)\s*\(")
DIALOG_BRACKET = re.compile(r"\b(?:window|self|globalThis)\s*\[\s*['\"`](alert|confirm|prompt)['\"`]\s*\]")
FIELD_CREATE = re.compile(r"\(\s*['\"`](input|select|textarea)['\"`]")
FIELD_MARKUP = re.compile(r"<(input|select|textarea)\b", re.I)
PRESS = re.compile(r"(?<![\w-])(?:on)?(pointerdown|mousedown|touchstart)\b")


def dialog_findings(text):
    code = _Scan(text, js=True).code_text
    return [(m.group(1), _line_of(code, m.start())) for rx in (DIALOG_CALL, DIALOG_BRACKET) for m in rx.finditer(code)]


def field_findings(text):
    scan = _Scan(text, js=True)
    code = scan.code_text
    out = [(m.group(1), _line_of(code, m.start())) for m in FIELD_CREATE.finditer(code)]
    out += [(m.group(1).lower(), ln) for content, ln in scan.literals for m in FIELD_MARKUP.finditer(content)]
    return out


def press_findings(text):
    code = _Scan(text, js=True).code_text
    return [(m.group(1), _line_of(code, m.start())) for m in PRESS.finditer(code)]


def test_no_native_dialogs():
    _assert_lint(_collect(_script_sources(), dialog_findings), DIALOG_ALLOWLIST)


def test_fields_only_through_the_field_component():
    files = [f for f in _script_sources() if _rel(f) not in FIELD_COMPONENT_FILES]
    _assert_lint(_collect(files, field_findings), FIELD_ALLOWLIST)


def test_no_press_down_handlers():
    _assert_lint(_collect(_script_sources(), press_findings), PRESS_ALLOWLIST)


# ---- AUT-7: the words lint ----

# Internal words (LNG-1), the old names of the "Was" column of foundations 2, "color" (LNG-7) and the "Never" column of
# the shared wording table (08 section 12). (finding, pattern); matched on whole words inside a string literal.
BANNED = [
    ("ai_intake", r"ai_intake"), ("gcode_state", r"gcode_state"), ("module", r"modules?"), ("endpoint", r"endpoints?"),
    ("job id", r"job[ _-]?ids?"), ("dry run", r"dry[ _-]?runs?"),
    ("filament-kit", r"filament-kit"), ("the server", r"the server"), ("the kit", r"the kit"),
    ("setup page", r"setup page"), ("setup console", r"setup console"), ("phone web app", r"phone web app"),
    ("android app", r"android app"), ("intake station", r"intake station"), ("intake panel", r"intake panel"),
    ("printer station", r"printer station"), ("bench reader", r"bench reader"), ("nfc reader", r"nfc reader"),
    ("ai intake", r"(?:local )?ai intake"), ("intake history", r"intake history"), ("printer pack", r"printer pack"),
    ("filament library", r"filament library"), ("pc sync", r"pc sync"), ("all-in-one", r"all-in-one"),
    ("color", r"colors?"),
    ("gross weight", r"gross weight"), ("weight on the scale", r"weight on the scale"),
    ("scale weight", r"scale weight"), ("retry", r"retry"), ("blank =", r"blank ="),
    ("empty = chosen automatically", r"empty = chosen automatically"), ("profile", r"profiles?"),
    ("unfinished add", r"unfinished adds?"),
]
BANNED_RX = [(name, re.compile(r"(?<![A-Za-z0-9])(?:%s)(?![A-Za-z0-9])" % pat, re.I)) for name, pat in BANNED]
HMS = re.compile(r"(?<![A-Za-z0-9])HMS(?![A-Za-z0-9])")
WHOLE_TEXTS = {"OK", "here", "Here", "click here", "Click here"}      # a whole button or link text (LNG-2)


def word_findings_in(content):
    out = [name for name, rx in BANNED_RX if rx.search(content)]
    if HMS.search(content):
        out.append("HMS")
    if content.strip() in WHOLE_TEXTS:
        out.append(f'"{content.strip()}"')
    return out


def word_findings(text, js):
    return [(w, ln) for content, ln in _Scan(text, js).literals for w in word_findings_in(content)]


def test_ui_words():
    found = _collect(_script_sources(), lambda t: word_findings(t, True))
    found.update(_collect(_kotlin_sources(), lambda t: word_findings(t, False)))
    _assert_lint(found, WORDS_ALLOWLIST)


# ---- The lints fail on plants ----

def test_plants_are_found():
    assert [w for w, _ in accent_findings(".toggle:checked { background: var(--accent) }")] == \
        ["var(--accent) in .toggle:checked"]
    assert accent_findings(".btn--primary, .skip:focus { background: var(--accent); color: var(--on-accent) }") == []
    assert accent_findings("a { color: var(--accent-text); border-color: var(--accent-hover) }") == []
    assert [w for w, _ in accent_findings("@media (max-width: 600px) { .bar, .btn--primary { fill: var(--accent) } }")] \
        == ["var(--accent) in .bar"]
    assert dialog_findings("if (confirm('x')) y();") == [("confirm", 1)]
    assert [w for w, _ in dialog_findings("window.prompt('a'); self.alert(1); globalThis.confirm(2)")] == \
        ["prompt", "alert", "confirm"]
    assert dialog_findings('window["confirm"](x)') == [("confirm", 1)]
    assert dialog_findings("// confirm(x)\nconst s = 'confirm(';\nuser.confirm(1); myconfirm(2)") == []
    assert [w for w, _ in field_findings("h('input', {})")] == ["input"]
    assert [w for w, _ in field_findings("document.createElement(\"select\")")] == ["select"]
    assert [w for w, _ in field_findings("el.innerHTML = `<div><textarea></textarea></div>`")] == ["textarea"]
    assert field_findings("h('inputs', {}); const s = 'input';") == []
    assert [w for w, _ in press_findings("el.addEventListener('pointerdown', f); b.onmousedown = f;")] == \
        ["pointerdown", "mousedown"]
    assert [w for w, _ in press_findings("h('b', { on: { touchstart: f } })")] == ["touchstart"]
    assert press_findings("el.addEventListener('click', f); // pointerdown")  == []
    assert [w for w, _ in css_findings("a { color: #FFF; background: rgba(0, 0, 0, .5) }")] == ["#fff", "rgba("]
    assert [w for w, _ in css_findings("a { border: 1px solid white; color: transparent }")] == ["white"]
    assert [w for w, _ in css_findings("a { font-size: 14px; line-height: 20px; transition: opacity .2s }")] == \
        ["font-size: 14px", "line-height: 20px", "duration .2s"]
    assert css_findings("a { font-size: var(--fs-m); line-height: 1.45; transition: color var(--t); margin: 0 }") == []
    assert [w for w, _ in css_findings("a { padding: 12px; margin: calc(var(--s2) + 1px); gap: 3px }")] == ["12px"]
    assert [w for w, _ in css_findings("a { opacity: .6 } b { outline: none }")] == ["opacity: .6", "outline: none"]
    assert css_findings("a:focus-visible { outline: none; box-shadow: inset 0 0 0 2px var(--focus) }") == []
    assert [w for w, _ in kotlin_findings("val c = Color(0xFF112233); val d = Color.White; val e = Color.Transparent")] \
        == ["Color(0xFF112233", "Color.White"]
    assert [w for w, _ in kotlin_findings("Modifier.padding(12.dp, 0.dp, 2.dp); fontSize = 14.sp; x = 0.05.em")] == \
        ["14.sp", "12.dp"] or sorted(w for w, _ in kotlin_findings("p(12.dp, 0.dp); fontSize = 14.sp")) == ["12.dp", "14.sp"]
    assert word_findings_in("Modules") == ["module"]
    assert word_findings_in("Set the color of the dry run") == ["dry run", "color"] or \
        sorted(word_findings_in("Set the color of the dry run")) == ["color", "dry run"]
    assert word_findings_in("OK") == ['"OK"'] and word_findings_in("HMS error") == ["HMS"]
    assert word_findings_in("Click here") == ['"Click here"']
    assert word_findings_in("Features, Colour, okay, hereby, Retrying") == []
    assert [w for w, _ in word_findings('h("button", { textContent: "Modules" })', True)] == ["module"]
    assert [w for w, _ in word_findings('Text("OK")', False)] == ['"OK"']
