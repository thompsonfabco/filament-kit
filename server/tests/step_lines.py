"""Reading the `==> step K of N <sentence>` lines a counted job writes (steps.py), for the tests of each job."""
from __future__ import annotations

import re

from filament_kit import redact

_STEP = re.compile(r"^==> step ([0-9]+) of ([0-9]+) (.+)$", re.M)


def sentences(text: str, count: int | None = None, *, whole: bool = True) -> list[str]:
    """The step sentences in `text`, after checking the rules of docs/design 02 8.4: K goes 1, 2, 3 ... in order, N is the
    same on every line (and `count` when given), a job that reached its last step has written all N (`whole`), and no
    sentence holds anything the log redaction would hide (an address, a serial, a name)."""
    found = _STEP.findall(text)
    assert found, "no step lines"
    counts = {int(n) for _k, n, _s in found}
    assert len(counts) == 1, f"N changed: {sorted(counts)}"
    n = counts.pop()
    assert [int(k) for k, _n, _s in found] == list(range(1, len(found) + 1)), "K is not 1, 2, 3 ... in order"
    if count is not None:
        assert n == count
    if whole:
        assert len(found) == n, f"{len(found)} step lines for N = {n}"
    for _k, _n, sentence in found:
        assert redact.text(sentence) == sentence, f"redaction changes the sentence {sentence!r}"
    return [s for _k, _n, s in found]
