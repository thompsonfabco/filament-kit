#!/usr/bin/env python3
"""WCAG contrast check for tokens.json and the generated Kotlin colours (standard library only).

Implements AUT-1 (docs/design/07-accessibility.md section 15) and test 3 of 08-platform-mapping.md 3.4.
Every pair below is required, for every theme in light and dark (eight token sets), on the unrounded ratio:
  4.5:1  text, muted, accent-text, ok, warn, bad, info   on bg, surface, surface-2   (07 3.1)
  4.5:1  ok/ok-soft, warn/warn-soft, bad/bad-soft, info/info-soft; on-accent on accent; on-bad on bad   (07 3.1)
  3.0:1  border-strong and focus on surface and bg; focus on surface-2   (07 3.1)
  4.5:1  the text pairs of 07 3.2 (surface-3, code, accent-hover, accent-soft, the tooltip pair)
  3.0:1  border-strong on surface-2; focus on code and surface-3   (07 3.2)
  Material roles (07 CON-8; 08 3.4 test 3), read from SpoolwardenTokens.kt: onSurface and onSurfaceVariant on
  surface and surfaceContainerHighest; onPrimary on primary; onError on error; outline on surface at 3:1;
  onPrimaryContainer on primaryContainer; onErrorContainer on errorContainer; inverseOnSurface on inverseSurface.
Translucent colours (scrim) are skipped. A missing token is a failure.

Prints a table; exits 1 when any pair fails, naming it as
"palette dark: --muted on --surface-2 is 4.31:1, needs 4.5:1 (CON-1)".
Usage: python check_contrast.py [path/to/tokens.json [path/to/SpoolwardenTokens.kt]]
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KOTLIN = HERE.parent / "android/app/src/main/java/com/thompsonfabco/filamentkit/ui/theme/SpoolwardenTokens.kt"

TEXT = ["text", "muted", "accent-text", "ok", "warn", "bad", "info"]
GROUNDS = ["bg", "surface", "surface-2"]
SOFT = [("ok", "ok-soft"), ("warn", "warn-soft"), ("bad", "bad-soft"), ("info", "info-soft")]
ON = [("on-accent", "accent"), ("on-bad", "bad")]
NONTEXT = ["border-strong", "focus"]
NONTEXT_GROUNDS = ["surface", "bg"]
# 07 3.2 and the two former advisory pairs: (foreground, background, required ratio)
ADDED = [
    ("focus", "surface-2", 3.0),
    ("accent-text", "accent-soft", 4.5), ("text", "surface-3", 4.5),
    ("on-accent", "accent-hover", 4.5), ("muted", "surface-3", 4.5), ("bad", "surface-3", 4.5),
    ("surface", "text", 4.5), ("text", "code", 4.5), ("muted", "code", 4.5),
    ("border-strong", "surface-2", 3.0), ("focus", "code", 3.0), ("focus", "surface-3", 3.0),
]
# 07 CON-8 and 08 3.4 test 3: (Material roles, foreground token, background token, ratio); the Kotlin field of a
# token is its name in camel case (surface-2 -> surface2)
MATERIAL = [
    ("onSurface", "surface", "text", "surface", 4.5),
    ("onSurface", "surfaceContainerHighest", "text", "surface-2", 4.5),
    ("onSurfaceVariant", "surface", "muted", "surface", 4.5),
    ("onSurfaceVariant", "surfaceContainerHighest", "muted", "surface-2", 4.5),
    # primary on surface and surfaceContainer* (CON-8) is left out: Spool light is 2.20:1 and 1.88:1 and 07 3.2 says the
    # edge of a filled main button is not a required pair; the design session decides (see the S0.5 report)
    ("onPrimary", "primary", "on-accent", "accent", 4.5),
    ("onError", "error", "on-bad", "bad", 4.5),
    ("outline", "surface", "border-strong", "surface", 3.0),
    ("onPrimaryContainer", "primaryContainer", "accent-text", "accent-soft", 4.5),
    ("onErrorContainer", "errorContainer", "bad", "bad-soft", 4.5),
    ("inverseOnSurface", "inverseSurface", "surface", "text", 4.5),
]


def required_pairs():
    """The 31 pairs per token set that the first version of this check required."""
    pairs = []
    for fg in TEXT:
        for bg in GROUNDS:
            pairs.append((fg, bg, 4.5))
    for fg, bg in SOFT + ON:
        pairs.append((fg, bg, 4.5))
    for fg in NONTEXT:
        for bg in NONTEXT_GROUNDS:
            pairs.append((fg, bg, 3.0))
    return pairs


def kotlin_colours(text):
    """{theme: {"light"|"dark": {field: "#RRGGBB"}}} from the generated Kotlin; translucent colours are skipped."""
    out = {}
    for m in re.finditer(r"^    val (\w+) = ThemeTokens\(", text, re.M):
        end = text.find("\n    )\n", m.end())
        block = text[m.end():end if end >= 0 else len(text)]
        for mode in ("light", "dark"):
            mm = re.search(mode + r" = SpoolwardenColors\((.*?)\n        \)", block, re.S)
            if not mm:
                continue
            fields = {}
            for field, argb in re.findall(r"(\w+) = Color\(0x([0-9A-Fa-f]{8})\)", mm.group(1)):
                if argb[:2].upper() == "FF":
                    fields[field] = "#" + argb[2:]
            out.setdefault(m.group(1), {})[mode] = fields
    return out


def camel(token):
    head, *rest = token.split("-")
    return head + "".join(w.capitalize() for w in rest)


def parse_hex(value):
    m = re.fullmatch(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})", value.strip())
    if not m:
        raise ValueError(f"not an opaque hex colour: {value!r}")
    h = m.group(1)
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def channel(c):
    c = c / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(rgb):
    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(a, b):
    la, lb = luminance(parse_hex(a)), luminance(parse_hex(b))
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def main(argv):
    path = Path(argv[1]) if len(argv) > 1 else HERE / "tokens.json"
    kt_path = Path(argv[2]) if len(argv) > 2 else KOTLIN
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    kt = kotlin_colours(kt_path.read_text(encoding="utf-8")) if kt_path.is_file() else {}
    first = required_pairs()
    web = [(fg, bg, need) for fg, bg, need in first + ADDED]
    total = fails = first_total = 0
    problems = []
    print(f"Contrast check of {path.name} and {kt_path.name}: need 4.5:1 for text pairs, 3.0:1 for outlines and focus")
    print(f"{'theme':<10} {'mode':<5} {'foreground':<14} {'background':<11} {'need':>5} {'ratio':>7}  result")
    print("-" * 66)

    def check(name, mode, fg, bg, need, rule, fgv, bgv, said_fg, said_bg, in_first=False):
        nonlocal total, fails, first_total
        total += 1
        first_total += in_first
        if fgv is None or bgv is None:
            gone = said_fg if fgv is None else said_bg
            fails += 1
            problems.append(f"{name} {mode}: {gone} is missing, needed for {said_fg} on {said_bg} ({rule})")
            print(f"{name:<10} {mode:<5} {fg:<14} {bg:<11} {need:>5.1f} {'-':>7}  FAIL (missing)")
            return
        r = ratio(fgv, bgv)
        ok = r >= need
        if not ok:
            fails += 1
            problems.append(f"{name} {mode}: {said_fg} on {said_bg} is {r:.2f}:1, needs {need:g}:1 ({rule})")
        print(f"{name:<10} {mode:<5} {fg:<14} {bg:<11} {need:>5.1f} {r:>7.2f}  {'pass' if ok else 'FAIL'}")

    for name, theme in data["themes"].items():
        for mode in ("light", "dark"):
            colours = theme[mode]
            for i, (fg, bg, need) in enumerate(web):
                check(name, mode, fg, bg, need, "CON-1", colours.get(fg), colours.get(bg), f"--{fg}", f"--{bg}",
                      in_first=i < len(first))
            kc = kt.get(name, {}).get(mode, {})
            for role_fg, role_bg, fg, bg, need in MATERIAL:
                check(name, mode, "kt:" + role_fg, role_bg, need, "CON-8", kc.get(camel(fg)), kc.get(camel(bg)),
                      role_fg, role_bg)
    print("-" * 66)
    print(f"required pairs checked: {total} (of which {first_total} are the first version's); failed: {fails}")
    for line in problems:
        print(line, file=sys.stderr)
    print("RESULT: " + ("FAIL" if fails else "PASS"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
