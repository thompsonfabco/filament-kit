"""Tests 7 (words) and 8 (theme names agree) of docs/design/08-platform-mapping.md 3.4.

strings/en.json is the source; strings/strings.js and res/values/strings.xml are generated from it by
tokens/build_tokens.py. Test 7 reads both generated files back (undoing the escaping and the placeholder numbering) and
compares them with the source, keeps the product's and the command's name out of every entry but their own, and scans
the hand-written Kotlin under `ui/` and the page scripts for text that reaches the screen without the catalogue.
Today's literals are in strings_allowlist.txt, one line each: `<path> | <literal> | <reason>`. A literal outside the
list fails, and so does a line whose literal is gone (09 open point 4).
"""
import json
import re
import xml.etree.ElementTree as ET

from test_design_lints import _Scan, _rel, _script_sources, TESTS
from test_design_sources import ROOT, TOKENS, _kotlin_sources

SOURCE = ROOT / "strings" / "en.json"
STRINGS_JS = ROOT / "strings" / "strings.js"
STRINGS_XML = ROOT / "android" / "app" / "src" / "main" / "res" / "values" / "strings.xml"
ALLOWLIST = TESTS / "strings_allowlist.txt"

RESERVED = {"product": "app_name", "command": "command_name"}
PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*)\}")
LETTER = re.compile(r"[A-Za-z]")
PRINTF = re.compile(r"%(?:(\d+)\$([sd])|%)")


# ---- The source and the two generated files, read back to one form: {key: text or {"one", "other"}} ----

def source_texts(raw):
    """en.json with {product} and {command} filled in from app_name and command_name."""
    def fill(text):
        return PLACEHOLDER.sub(lambda m: raw[RESERVED[m.group(1)]] if m.group(1) in RESERVED else m.group(0), text)
    return {k: ({q: fill(t) for q, t in v.items()} if isinstance(v, dict) else fill(v)) for k, v in raw.items()}


def js_texts(text):
    m = re.search(r"window\.SW_TEXT = Object\.freeze\((\{.*\})\);\s*$", text, re.S)
    assert m, "strings.js is not window.SW_TEXT = Object.freeze({ ... });"
    return json.loads(re.sub(r",\s*\}$", "}", m.group(1)))


def _unescape(text, order):
    """Android text back to catalogue form, by Android's own rules: an unquoted text is trimmed and its whitespace runs
    collapsed, a text in double quotes keeps them; %n$s / %n$d become {name}; %% becomes % only in a string with
    placeholders (Android only undoes it when it formats); backslash escapes are undone."""
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"' and text[-2] != "\\":
        text = text[1:-1]
    else:
        text = re.sub(r"[ \t\n]+", " ", text).strip()

    def printf(m):
        if m.group(0) == "%%":
            return "%" if order else "%%"
        return "{" + order[int(m.group(1)) - 1] + "}"
    text = PRINTF.sub(printf, text)
    return re.sub(r"\\(.)", lambda m: "\n" if m.group(1) == "n" else m.group(1), text)


def xml_texts(text):
    root = ET.fromstring(text, ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))
    out, order = {}, []
    for el in root:
        if not isinstance(el.tag, str):                       # a comment: "<!-- 1=printer 2=count -->" names the order
            m = re.fullmatch(r"\s*(\d+=[a-z0-9_]+(?:\s+\d+=[a-z0-9_]+)*)\s*", el.text or "")
            order = [p.split("=")[1] for p in m.group(1).split()] if m else []
            continue
        name = el.get("name")
        if el.tag == "string":
            out[name] = _unescape(el.text or "", order)
        else:
            assert el.tag == "plurals", el.tag
            out[name] = {i.get("quantity"): _unescape(i.text or "", order) for i in el}
        order = []
    return out


def placeholders(value):
    return sorted({n for t in (value.values() if isinstance(value, dict) else [value]) for n in PLACEHOLDER.findall(t)})


def catalogue_problems(raw, js, xml):
    """Differences between the source and the generated files (test 7, first half)."""
    want = source_texts(raw)
    out = []
    for label, got in (("strings.js", js_texts(js)), ("strings.xml", xml_texts(xml))):
        if list(got) != list(want) and set(got) == set(want):
            out.append(f"{label}: keys are in another order than en.json")
        for key in sorted(set(want) ^ set(got)):
            out.append(f"{label}: key {key!r} is only in {'en.json' if key in want else label}")
        for key in sorted(set(want) & set(got)):
            if got[key] != want[key]:
                out.append(f"{label}: {key}: text differs from en.json ({got[key]!r} != {want[key]!r})")
            elif placeholders(got[key]) != placeholders(want[key]):
                out.append(f"{label}: {key}: placeholders differ")
    return out


def name_problems(raw):
    """Entries other than app_name and command_name that hold either name as a word (test 7, second half)."""
    out = []
    for placeholder, entry in RESERVED.items():
        name = raw[entry]
        rx = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])", re.I)
        for key, value in raw.items():
            if key in RESERVED.values():
                continue
            if any(rx.search(t) for t in (value.values() if isinstance(value, dict) else [value])):
                out.append(f"{key}: holds {name!r} (the value of {entry}); write {{{placeholder}}} instead")
    return out


def theme_name_problems(tokens, raw):
    """themes.<key>.label against theme_<key>_name (test 8)."""
    out = []
    for key, theme in tokens["themes"].items():
        if f"theme_{key}_name" not in raw:
            out.append(f"theme_{key}_name is missing")
        elif raw[f"theme_{key}_name"] != theme["label"]:
            out.append(f"theme_{key}_name is {raw[f'theme_{key}_name']!r}, themes.{key}.label is {theme['label']!r}")
    return out


# ---- Text reaching the screen without the catalogue ----

SCREEN_ASSIGN = re.compile(r"(?<![\w$])(?:textContent|ariaLabel|title|placeholder)\s*(?:=(?!=)|:)\s*([\"'`])")
SCREEN_CALL = re.compile(r"(?<![\w$])(?:announce|toast)\s*\(\s*([\"'`])")


def kotlin_literals(text):
    """[(literal, line)] of every string literal with a letter in it (a template's ${...} parts do not count)."""
    return [(c, ln) for c, ln in _Scan(text, js=False).literals if LETTER.search(c.replace("${}", ""))]


def script_literals(text):
    """[(literal, line)] of letters-bearing literals given to textContent, ariaLabel, title, placeholder, announce( or toast(."""
    scan = _Scan(text, js=True)
    code = scan.code_text
    out = []
    for rx in (SCREEN_ASSIGN, SCREEN_CALL):
        for m in rx.finditer(code):
            quote, start = m.group(1), m.end()
            end = start
            while end < len(text) and text[end] != quote:
                end += 2 if text[end] == "\\" else 1
            content = text[start:end]
            if LETTER.search(content.replace("${}", "")):
                out.append((content, text.count("\n", 0, start) + 1))
    return out


def _key(literal):
    return literal.replace("\\", "\\\\").replace("\n", "\\n")


def _screen_sources():
    kt = [f for f in _kotlin_sources() if "/ui/" in f.as_posix()]
    return [(f, kotlin_literals) for f in kt] + [(f, script_literals) for f in _script_sources()]


def _entries():
    entries = {}
    for line in ALLOWLIST.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            path, sep, rest = line.partition(" | ")
            literal, sep2, reason = rest.rpartition(" | ")
            assert sep and sep2 and path.strip() and literal.strip() and reason.strip(), \
                f"{ALLOWLIST.name}: a line needs a file, a literal and a reason: {line!r}"
            key = (path.strip(), literal)
            assert key not in entries, f"{ALLOWLIST.name}: listed twice: {line!r}"
            entries[key] = reason
    return entries


def literal_verdict(found, allowed):
    new = sorted(f"{f}:{ln}: {lit}" for (f, lit), ln in found.items() if (f, lit) not in allowed)
    stale = sorted(f"{f} | {lit}" for f, lit in allowed if (f, lit) not in found)
    return new, stale


def collect_literals():
    found = {}
    for f, finder in _screen_sources():
        for lit, ln in finder(f.read_text(encoding="utf-8")):
            found.setdefault((_rel(f), _key(lit)), ln)
    return found


# ---- Test 7 ----

def test_generated_strings_equal_the_catalogue():
    raw = json.loads(SOURCE.read_text(encoding="utf-8"))
    problems = catalogue_problems(raw, STRINGS_JS.read_text(encoding="utf-8"), STRINGS_XML.read_text(encoding="utf-8"))
    assert not problems, "\n".join(problems)


def test_the_names_are_held_once():
    raw = json.loads(SOURCE.read_text(encoding="utf-8"))
    assert all(isinstance(raw[e], str) and raw[e] for e in RESERVED.values())
    problems = name_problems(raw)
    assert not problems, "\n".join(problems)


def test_no_text_reaches_the_screen_without_the_catalogue():
    new, stale = literal_verdict(collect_literals(), _entries())
    assert not new, "not in strings_allowlist.txt:\n" + "\n".join(new)
    assert not stale, "in strings_allowlist.txt but no longer found, drop the line:\n" + "\n".join(stale)


# ---- Test 8 ----

def test_theme_names_agree():
    problems = theme_name_problems(TOKENS, json.loads(SOURCE.read_text(encoding="utf-8")))
    assert not problems, "\n".join(problems)


# ---- The checks fail on plants ----

def _generated():
    return json.loads(SOURCE.read_text(encoding="utf-8")), STRINGS_JS.read_text(encoding="utf-8"), \
        STRINGS_XML.read_text(encoding="utf-8")


def test_plants_are_found():
    raw, js, xml = _generated()
    assert catalogue_problems(raw, js, xml) == []
    # a key missing on one side
    assert catalogue_problems(raw, js.replace('  "common_back": "Back",\n', ""), xml) == \
        ["strings.js: key 'common_back' is only in en.json"]
    assert catalogue_problems(raw, js, xml.replace('    <string name="common_back">Back</string>\n', "")) == \
        ["strings.xml: key 'common_back' is only in en.json"]
    assert catalogue_problems(raw, js, xml.replace("</resources>", '<string name="extra">x</string></resources>')) == \
        ["strings.xml: key 'extra' is only in strings.xml"]
    # a text that differs
    assert len(catalogue_problems(raw, js.replace('"Back"', '"Go back"'), xml)) == 1
    assert len(catalogue_problems(raw, js, xml.replace(">Cancel<", ">Stop<"))) == 1
    # a placeholder renamed in one file
    assert catalogue_problems(raw, js.replace("{hub}", "{box}", 1), xml)
    assert catalogue_problems(raw, js, xml.replace("1=hub", "1=box", 1))
    # the apostrophe escape and the number format are read back
    assert xml_texts("<resources><!-- 1=count --><string name=\"a\">It\\'s %1$d%%</string></resources>") == {"a": "It's {count}%"}
    # Android's whitespace and percent rules: an unquoted trailing space or double space is lost, a lone %% stays %%
    assert xml_texts('<resources><string name="a">State: </string><string name="b">s  q</string></resources>') == \
        {"a": "State:", "b": "s q"}
    assert xml_texts('<resources><string name="a">"State: "</string><string name="b">"s  q"</string></resources>') == \
        {"a": "State: ", "b": "s  q"}
    assert xml_texts('<resources><string name="a">%%</string><string name="b" formatted="false">%</string></resources>') \
        == {"a": "%%", "b": "%"}
    # so a generator that left them unquoted, or wrote a lone % as %%, fails the comparison
    planted = {"zz_trailing": "State: ", "zz_double": "s  save", "zz_percent": "%"}
    for k, v in planted.items():
        bad = xml.replace("</resources>", f'<string name="{k}">{v.replace("%", "%%")}</string></resources>')
        head, _, tail = js.rpartition("});")
        assert catalogue_problems({**raw, k: v}, head + f"  {json.dumps(k)}: {json.dumps(v)},\n}});" + tail, bad), k
    # a theme name that differs, a theme name that is missing
    tokens = json.loads(json.dumps(TOKENS))
    assert theme_name_problems(tokens, raw) == []
    tokens["themes"]["panes"]["label"] = "Lists"
    assert len(theme_name_problems(tokens, raw)) == 1
    assert theme_name_problems(TOKENS, {k: v for k, v in raw.items() if k != "theme_palette_name"}) == \
        ["theme_palette_name is missing"]
    # the product's name written inside another entry, the command's name too
    assert name_problems(raw) == []
    planted = dict(raw, home_title="Home of filament-kit")
    assert len(name_problems(planted)) == 2          # both names are today's name
    planted = dict(raw, app_name="Spoolwarden", home_title="Welcome to Spoolwarden", command_name="spoolwarden",
                   pair_start_intro="run sudo spoolwarden pair")
    assert sorted({p.split(":")[0] for p in name_problems(planted)}) == ["home_title", "pair_start_intro"]
    # text given to the screen without the catalogue
    assert kotlin_literals('Text("Save"); val r = "home/{id}"; val k = "${x}"; val n = "123"') == [("Save", 1), ("home/{id}", 1)]
    assert script_literals('el.textContent = "Hello"; a.title = `T ${x}`; announce("Done"); toast(\'Oops\')') == \
        [("Hello", 1), ("T ${x}", 1), ("Done", 1), ("Oops", 1)]
    assert script_literals('el.textContent = t("home_title"); el.textContent = ""; x.title == "a"; announce(msg)') == []
    found = {("a.kt", "Save"): 3}
    assert literal_verdict(found, {}) == (["a.kt:3: Save"], [])
    assert literal_verdict(found, {("a.kt", "Save"): "r", ("a.kt", "Gone"): "r"}) == ([], ["a.kt | Gone"])
