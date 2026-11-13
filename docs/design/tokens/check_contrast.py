#!/usr/bin/env python3
"""WCAG contrast check for tokens.json (standard library only), per foundations section 4.1.

Required pairs, for every theme in light and dark:
  4.5:1  text, muted, accent-text, ok, warn, bad, info   on bg, surface, surface-2
  4.5:1  ok/ok-soft, warn/warn-soft, bad/bad-soft, info/info-soft
  4.5:1  on-accent on accent; on-bad on bad
  3.0:1  border-strong and focus against surface and bg
Advisory pairs (printed as WARN, never fail the run): accent-text on accent-soft, text on surface-3.

Prints a table; exits 1 when any required pair fails.
Usage: python check_contrast.py [path/to/tokens.json]
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

TEXT = ["text", "muted", "accent-text", "ok", "warn", "bad", "info"]
GROUNDS = ["bg", "surface", "surface-2"]
SOFT = [("ok", "ok-soft"), ("warn", "warn-soft"), ("bad", "bad-soft"), ("info", "info-soft")]
ON = [("on-accent", "accent"), ("on-bad", "bad")]
NONTEXT = ["border-strong", "focus"]
NONTEXT_GROUNDS = ["surface", "bg"]
ADVISORY = [("accent-text", "accent-soft"), ("text", "surface-3")]


def required_pairs():
    pairs = []
    for fg in TEXT:
        for bg in GROUNDS:
            pairs.append((fg, bg, 4.5, True))
    for fg, bg in SOFT + ON:
        pairs.append((fg, bg, 4.5, True))
    for fg in NONTEXT:
        for bg in NONTEXT_GROUNDS:
            pairs.append((fg, bg, 3.0, True))
    for fg, bg in ADVISORY:
        pairs.append((fg, bg, 4.5, False))
    return pairs


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
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    pairs = required_pairs()
    total = fails = warns = 0
    print(f"Contrast check of {path.name}: need 4.5:1 for text pairs, 3.0:1 for border-strong and focus")
    print(f"{'theme':<10} {'mode':<5} {'foreground':<14} {'background':<11} {'need':>5} {'ratio':>7}  result")
    print("-" * 66)
    for name, theme in data["themes"].items():
        for mode in ("light", "dark"):
            colours = theme[mode]
            for fg, bg, need, required in pairs:
                r = ratio(colours[fg], colours[bg])
                ok = r >= need
                if required:
                    total += 1
                    fails += 0 if ok else 1
                    result = "pass" if ok else "FAIL"
                else:
                    warns += 0 if ok else 1
                    result = "pass (advisory)" if ok else "WARN (advisory)"
                print(f"{name:<10} {mode:<5} {fg:<14} {bg:<11} {need:>5.1f} {r:>7.2f}  {result}")
    print("-" * 66)
    print(f"required pairs checked: {total}; failed: {fails}; advisory warnings: {warns}")
    print("RESULT: " + ("FAIL" if fails else "PASS"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
