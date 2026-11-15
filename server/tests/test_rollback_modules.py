"""A config written by this release still passes 0.3.0's `modules.validate` after `update --rollback`
(final review of release-v040, finding 1). 0.3.0 refuses any module name it does not know, even when it is false,
and its install.sh ends with `modules apply`, so one stray `"klipper": false` stopped a rollback half done."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from filament_kit import apply, cli, modules, updates
from test_updates import Runner, _cfg, _state, env, key, srv  # noqa: F401  (fixtures)

OLD_SRC = Path(__file__).parent / "data" / "v0.3.0" / "modules.py.txt"   # v0.3.0:server/filament_kit/modules.py


@pytest.fixture(scope="module")
def old():
    """0.3.0's modules.py, loaded as its own module (it imports nothing from the kit)."""
    loader = importlib.machinery.SourceFileLoader("modules_v030", str(OLD_SRC))
    spec = importlib.util.spec_from_loader("modules_v030", loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod            # dataclasses look the module up by name
    spec.loader.exec_module(mod)
    yield mod
    sys.modules.pop(spec.name, None)


def test_the_frozen_copy_is_v0_3_0s_file():
    git = shutil.which("git")
    root = Path(__file__).resolve().parents[2]
    if not git:
        pytest.skip("no git")
    got = subprocess.run([git, "-C", str(root), "show", "v0.3.0:server/filament_kit/modules.py"],
                         capture_output=True)
    if got.returncode:
        pytest.skip("tag v0.3.0 is not in this checkout (a shallow clone)")
    assert got.stdout.replace(b"\r\n", b"\n") == OLD_SRC.read_bytes().replace(b"\r\n", b"\n")


def test_the_only_module_0_3_0_lacks_is_listed_for_the_rollback(old):
    assert set(modules.MODULES) - set(old.MODULES) == set(modules.NEWER)


@pytest.mark.parametrize("mode", sorted(modules.MODES))
def test_every_mode_written_here_passes_0_3_0(old, mode):
    cfg = modules.set_mode({"station": {"allow": ["192.0.2.10"]}}, mode, say=None)   # station: the server's address
    assert "klipper" not in cfg["modules"]
    old.validate(cfg)


def test_switching_a_module_writes_no_name_0_3_0_lacks(old):
    cfg = modules.set_mode({}, "server", say=None)
    cfg = cli._with_modules(cfg, modules.enabled(cfg) | {"updates"})
    assert cfg["modules"]["updates"] is True and "klipper" not in cfg["modules"]
    old.validate(cfg)
    cfg = cli._with_modules(cfg, modules.enabled(cfg) - {"updates"})
    assert cfg["modules"]["updates"] is False          # modules 0.3.0 knows are still written true/false ...
    old.validate(cfg)


def test_an_opt_in_module_switched_off_still_has_its_units_disabled():
    """... so `apply` still disables an opt-in module's units (it does that only for a configured one)."""
    cfg = modules.set_mode({}, "server", say=None)
    on = cli._with_modules(cfg, modules.enabled(cfg) | {"updates"})
    off = cli._with_modules(on, modules.enabled(on) - {"updates"})
    units = {u for unit in modules.MODULES["updates"].units for u in apply._unit_files(unit)}
    assert units
    disabled = {a.arg for a in apply.plan(off, resolve=lambda h: ["192.0.2.1"]) if a.kind == "disable"}
    assert units <= disabled


def _write(env, cfg):
    (env / "etc" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")


def _read(env):
    return json.loads((env / "etc" / "config.json").read_text(encoding="utf-8"))


def test_klipper_switched_off_here_is_dropped_before_a_rollback_to_0_3_0(env, old, capsys):
    cfg = modules.set_mode({}, "server", say=None)
    cfg = cli._with_modules(cfg, modules.enabled(cfg) | {"klipper"})
    cfg = cli._with_modules(cfg, modules.enabled(cfg) - {"klipper"})
    assert cfg["modules"]["klipper"] is False
    with pytest.raises(old.ModuleError, match="unknown module 'klipper'"):
        old.validate(cfg)                               # the review's failure, without the guard
    _write(env, cfg)
    assert updates._modules_fit("0.3.0")
    after = _read(env)
    assert "klipper" not in after["modules"]
    old.validate(after)
    assert "Removed klipper" in capsys.readouterr().out


def test_klipper_on_refuses_a_rollback_to_0_3_0(env, capsys):
    cfg = modules.set_mode({}, "server", say=None)
    cfg = cli._with_modules(cfg, modules.enabled(cfg) | {"klipper"})
    _write(env, cfg)
    assert not updates._modules_fit("0.3.0")
    assert "`sudo filament-kit modules disable klipper` first" in capsys.readouterr().err
    assert _read(env) == cfg                            # nothing changed


def test_a_release_that_knows_klipper_keeps_the_entry(env):
    cfg = {"modules": {"server": True, "spoolman": True, "klipper": False}}
    _write(env, cfg)
    assert updates._modules_fit("0.4.0") and updates._modules_fit("0.5.1")
    assert _read(env) == cfg


def test_rollback_to_0_3_0_stops_before_installing_when_klipper_is_on(env, srv, key, monkeypatch, capsys):
    srv.add("0.3.0")
    srv.add("0.4.0")
    monkeypatch.setattr(updates, "current_version", lambda: "0.3.0")
    cfg = _cfg(env)
    assert updates.update(cfg, fetcher=srv.fetcher(), run=Runner()) == 0
    monkeypatch.setattr(updates, "current_version", lambda: "0.4.0")
    raw = _read(env)
    raw["modules"] = dict(raw.get("modules") or {}, klipper=True)
    _write(env, raw)
    run = Runner()
    assert updates.rollback(cfg, run=run) == 1 and run.cmds == []
    assert _state(env)["previous"] == "0.3.0"           # still kept, so it can be tried again
    raw["modules"]["klipper"] = False
    _write(env, raw)
    capsys.readouterr()
    assert updates.rollback(cfg, run=Runner()) == 0
    assert "klipper" not in _read(env)["modules"]
