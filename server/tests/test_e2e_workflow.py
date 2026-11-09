"""The installer's end-to-end workflow: by hand, bounded, read-only token, and the cross-tag scenario is really in it."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FLOW = (ROOT / ".github/workflows/e2e.yml").read_text(encoding="utf-8")
RUN = (ROOT / "tools/e2e/run.sh").read_text(encoding="utf-8")
E2E = (ROOT / "tools/e2e/e2e.py").read_text(encoding="utf-8")


def test_it_runs_only_by_hand_with_a_limit_and_a_read_only_token():
    trigger = FLOW.split("\non:", 1)[1].split("\npermissions:", 1)[0]
    assert "workflow_dispatch" in trigger and "push" not in trigger and "schedule" not in trigger
    assert "permissions:\n  contents: read\n" in FLOW and re.search(r"timeout-minutes: \d+", FLOW)


def test_it_has_the_tags_and_gives_the_previous_one():
    assert "fetch-depth: 0" in FLOW and 'run.sh --previous "$PREVIOUS"' in FLOW


def test_a_typed_tag_reaches_the_shell_only_through_the_environment():
    for block in re.findall(r"run: \|?\n?((?:.*\n)*?)(?=\n      - |\Z)", FLOW):
        assert "${{" not in block, block


def test_the_run_passes_previous_on_and_the_scenario_is_there():
    assert '"${PREVIOUS[@]}"' in RUN and '"f": ("f)' in E2E and "def f_cross_tag" in E2E


def test_every_scenario_names_the_host_state_it_starts_from_and_the_run_prepares_it():
    """f leaves the previous release installed and e a station: a scenario after them (g after f failed, 2026-11-09)
    must not inherit that. Each scenario names its state and the loop prepares it before running it."""
    scenarios = set(re.findall(r'^    "([a-z])": \("', E2E, re.M))
    line = next(x for x in E2E.splitlines() if x.startswith("NEEDS = "))
    needs = dict(re.findall(r'"([a-z])": ("clean"|"release"|"server"|"seeded"|None)', line))
    assert scenarios == set(needs) and {"a", "f", "g"} <= scenarios
    assert needs["g"] == '"seeded"' and needs["c"] == '"seeded"' and needs["a"] == '"clean"'
    loop = E2E.split("for key in want:", 1)[1]
    assert loop.index("e2e.prepare(key)") < loop.index("getattr(e2e, meth)()")
    assert '"--version", self.v1' in E2E.split("def prepare", 1)[1].split("def _seed", 1)[0]   # b made v2 the latest


def test_the_previous_tree_is_not_what_clean_up_takes_uninstall_from():
    assert '"$WORK"/tree-*/install/uninstall.sh' in RUN and 'f"previous-{tag}"' in E2E
