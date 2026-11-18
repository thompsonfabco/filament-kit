"""Logs > Activity, checks that need no browser: the kind list of the Spool changes filter and the Who label are read from
the script's source (R84 sections 1 and 2.1)."""
import re
from pathlib import Path

from filament_kit import cli

SRC = (Path(cli.__file__).parent / "setup_static" / "setup_logs.js").read_text(encoding="utf-8")


def test_spool_changes_holds_every_spool_kind_of_activity():
    kinds = re.search(r'spools: \["activity_kind_spools", "([^"]+)"\]', SRC).group(1).split(",")
    assert {"spool.added", "spool.weighed", "spool.moved", "spool.emptied", "spool.opened", "spool.loaded", "spool.unloaded",
            "slot.cleared"} <= set(kinds)
    assert "spool.low" not in kinds and "spool.ok" not in kinds and len(kinds) == len(set(kinds))


def test_the_who_cell_is_never_empty_for_any_actor_type():
    assert 'cell("who", "activity_col_who", actWho(ev.actor))' in SRC
    body = re.search(r"const actWho = .*?\n};", SRC, re.S).group(0)
    assert "actor.name" in body and "activity_who_unknown" in body and "ACT_WHO.find" in body
    types = re.findall(r'\["(\w+)", "activity_who_\w+"\]', SRC.split("const ACT_WHO")[1].split("];")[0])
    assert set(types) == {"page", "cli", "hub", "device", "connector"}      # each type has its plain word
    assert "activity_who_unknown" in SRC.split("const ACT_TEXT")[1].split("};")[0]
