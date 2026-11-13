"""Inno Setup's preprocessor reads any line whose first non-blank character is '#' as a directive.

A [Code] string continuation that starts with #13#10 therefore aborts the compile ("Unknown preprocessor
directive"), which only release.yml ever runs. Keep such characters at the end of the previous line.
"""
import re
from pathlib import Path

ISS = Path(__file__).resolve().parents[1] / "installer" / "filament-kit-sync.iss"
DIRECTIVES = {"define", "undef", "ifdef", "ifndef", "if", "else", "elif", "endif", "error", "include",
              "pragma", "emit", "insert", "sub", "endsub", "for", "endfor", "preproc", "expr"}


def test_no_line_starts_with_a_hash_that_is_not_a_preprocessor_directive():
    bad = []
    for n, line in enumerate(ISS.read_text(encoding="utf-8").splitlines(), 1):
        m = re.match(r"\s*#\s*(\w*)", line)
        if m and m.group(1).lower() not in DIRECTIVES:
            bad.append((n, line.strip()[:60]))
    assert not bad, f"lines starting with '#' that are not Inno preprocessor directives: {bad}"
