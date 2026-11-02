import json
from pathlib import Path

import pytest

import studio_fixture
from fksync import inapp, installer
from fksync.store import AppDirs
from fksync.treehash import tree_hash

SYS_GCODE = ["M106 P3 S0\n; system start"]


def _preset(name: str, **extra) -> dict:
    d = {"type": "filament", "name": name, "inherits": "", "from": "User", "filament_id": "P1a2b3c4",
         "filament_type": ["PLA"], "filament_flow_ratio": ["0.98"], "nozzle_temperature": ["220", "220"]}
    d.update(extra)
    return d


def _write_build(path: Path, presets: dict[str, dict], infos: dict[str, dict] | None = None,
                 stamp: str = "20261102-010000") -> Path:
    base = path / "base"
    base.mkdir(parents=True)
    (path / "BUILD.json").write_text(json.dumps({"stamp": stamp, "live_hash": "x"}), encoding="utf-8")
    for name, data in presets.items():
        with open(base / f"{name}.json", "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, indent=4)
        info = (infos or {}).get(name, {"sync_info": "", "user_id": "", "setting_id": "", "base_id": "GFSA04"})
        with open(base / f"{name}.info", "w", encoding="utf-8", newline="\n") as f:
            f.write("".join(f"{k} = {v}\n" for k, v in info.items()))
    return path


def _read_info(path: Path) -> dict:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


class Env:
    def __init__(self, tmp_path: Path, live: dict[str, tuple[dict, dict]] | None = None):
        self.tmp = tmp_path
        self.folders = studio_fixture.make(tmp_path / "appdata", base=live or {})
        self.live = self.folders.user_filament / "base"
        self.dirs = AppDirs(tmp_path / "local" / "filament-kit-sync")
        self.dirs.ensure()
        self.n = 0

    def build(self, presets, infos=None) -> Path:
        self.n += 1
        return _write_build(self.tmp / f"build{self.n}", presets, infos, stamp=f"2026110201000{self.n}")

    def snapshot(self, presets) -> None:
        """Pretend a previous install put these presets in dirs.installed."""
        _write_build(self.dirs.installed, presets)

    def install(self, build_dir, stamp="20261102-010000", running=lambda: False):
        return installer.install(build_dir, self.folders, self.dirs, running=running, stamp_now=stamp)


def _info(setting_id="", **kw):
    d = {"sync_info": "", "user_id": "1725623066", "setting_id": setting_id, "base_id": "GFSA04"}
    d.update(kw)
    return d


# --- inapp port ----------------------------------------------------------------------------------

def test_inapp_diff_ignores_bookkeeping_and_compatible_printers():
    old = {"name": "a", "filament_flow_ratio": ["0.98"], "compatible_printers": ["x"], "updated_time": "1"}
    new = {"name": "b", "filament_flow_ratio": ["0.95"], "compatible_printers": ["y"], "updated_time": "2",
           "pressure_advance": ["0.02"]}
    assert inapp.diff(old, new) == {"filament_flow_ratio": ["0.95"], "pressure_advance": ["0.02"]}
    assert inapp.norm([1, "2"]) == ["1", "2"] and inapp.norm(3) == "3"


def test_inapp_is_reset_more_than_a_quarter():
    snap = {f"p{i}" for i in range(8)}
    assert inapp.is_reset(snap, snap - {"p0", "p1", "p2"})
    assert not inapp.is_reset(snap, snap - {"p0", "p1"})
    assert not inapp.is_reset(set(), set())


# --- happy path ----------------------------------------------------------------------------------

def test_happy_path_writes_files_and_keeps_setting_id(tmp_path):
    old_a = _preset("A", nozzle_temperature=["210", "210"])
    env = Env(tmp_path, live={"A": (old_a, _info("PFUS123abc", sync_info="", base_id="GFSA04"))})
    new_a, new_b = _preset("A"), _preset("B", filament_id="P0000001")
    build = env.build({"A": new_a, "B": new_b})

    res = env.install(build, stamp="20261102-011500")

    assert res.installed == ["A", "B"]
    assert res.stale == []
    assert res.backup == env.dirs.backups / "20261102-011500"
    assert json.loads((env.live / "A.json").read_text(encoding="utf-8")) == new_a
    assert json.loads((env.live / "B.json").read_text(encoding="utf-8")) == new_b
    info_a = _read_info(env.live / "A.info")
    assert info_a["setting_id"] == "PFUS123abc"  # live cloud id kept
    assert info_a["sync_info"] == "update"
    assert _read_info(env.live / "B.info")["setting_id"] == ""
    # the backup holds the live folder as it was before the install
    backed = res.backup / "base" / "A.json"
    assert json.loads(backed.read_text(encoding="utf-8")) == old_a
    assert b"\r\n" not in (env.live / "A.info").read_bytes()


def test_sixth_install_leaves_five_backups(tmp_path):
    env = Env(tmp_path)
    for i in range(6):
        build = env.build({"A": _preset("A", nozzle_temperature=[str(200 + i)] * 2)})
        env.install(build, stamp=f"20261102-01000{i}")
    left = sorted(p.name for p in env.dirs.backups.iterdir())
    assert left == [f"20261102-01000{i}" for i in range(1, 6)]
    assert json.loads((env.live / "A.json").read_text(encoding="utf-8"))["nozzle_temperature"] == ["205", "205"]


def test_same_stamp_twice_does_not_overwrite_backup(tmp_path):
    env = Env(tmp_path)
    r1 = env.install(env.build({"A": _preset("A")}), stamp="20261102-010000")
    r2 = env.install(env.build({"A": _preset("A", filament_flow_ratio=["0.9"])}), stamp="20261102-010000")
    assert r1.backup != r2.backup and r1.backup.is_dir() and r2.backup.is_dir()


def test_installed_equals_build_after_success(tmp_path):
    env = Env(tmp_path)
    env.snapshot({"OLD": _preset("OLD")})
    build = env.build({"A": _preset("A"), "B": _preset("B")})
    env.install(build)
    assert tree_hash(env.dirs.installed) == tree_hash(build)
    assert sorted(p.name for p in (env.dirs.installed / "base").iterdir()) == ["A.info", "A.json", "B.info", "B.json"]
    assert (env.dirs.installed / "BUILD.json").read_bytes() == (build / "BUILD.json").read_bytes()
    # no temp or old dirs left next to it
    assert sorted(p.name for p in env.dirs.base.iterdir() if p.is_dir()) == ["backups", "installed"]
    assert build.is_dir()  # the build dir itself is left alone


# --- G-code check --------------------------------------------------------------------------------

def _all_files(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_untrusted_gcode_refused_nothing_written(tmp_path):
    env = Env(tmp_path, live={"A": (_preset("A"), _info())})
    before = _all_files(env.folders.user_filament)
    build = env.build({"A": _preset("A"), "B": _preset("B", filament_start_gcode=["M104 S300 ; evil"])})
    with pytest.raises(installer.Refused) as e:
        env.install(build)
    assert "G-code" in e.value.reason
    assert "B" in e.value.reason and "filament_start_gcode" in e.value.reason
    assert _all_files(env.folders.user_filament) == before
    assert not env.dirs.backups.exists()
    assert not env.dirs.installed.exists()


def test_gcode_from_system_or_live_is_trusted(tmp_path):
    env = Env(tmp_path, live={"A": (_preset("A", filament_end_gcode=["; my own end"]), _info())})
    sysp = {"name": "Generic PLA @BBL H2D", "filament_start_gcode": SYS_GCODE}
    (env.folders.system_filament / "Generic PLA with gcode.json").write_text(json.dumps(sysp), encoding="utf-8")
    (env.folders.system_filament / "broken.json").write_text("{not json", encoding="utf-8")
    build = env.build({
        "A": _preset("A", filament_start_gcode=SYS_GCODE, filament_end_gcode=["; my own end"]),
        "B": _preset("B", filament_start_gcode=SYS_GCODE),
    })
    assert env.install(build).installed == ["A", "B"]


def test_gcode_not_equal_to_live_value_refused(tmp_path):
    env = Env(tmp_path, live={"A": (_preset("A", filament_end_gcode=["; my own end"]), _info())})
    build = env.build({"A": _preset("A", filament_end_gcode=["; changed by someone"])})
    with pytest.raises(installer.Refused) as e:
        env.install(build)
    assert "G-code" in e.value.reason and "filament_end_gcode" in e.value.reason


# --- edited / deleted after the build -------------------------------------------------------------

def test_edited_in_app_after_build_refused_naming_key(tmp_path):
    snap_a = _preset("A")
    env = Env(tmp_path, live={"A": (_preset("A", filament_flow_ratio=["0.95"]), _info())})
    env.snapshot({"A": snap_a})
    before = _all_files(env.folders.user_filament)
    build = env.build({"A": _preset("A")})  # does not carry the 0.95 edit
    with pytest.raises(installer.Refused) as e:
        env.install(build)
    assert "filament_flow_ratio" in e.value.reason
    assert "edited" in e.value.reason
    assert _all_files(env.folders.user_filament) == before
    assert not env.dirs.backups.exists()


def test_edit_carried_by_build_is_fine(tmp_path):
    env = Env(tmp_path, live={"A": (_preset("A", filament_flow_ratio=["0.95"]), _info())})
    env.snapshot({"A": _preset("A")})
    build = env.build({"A": _preset("A", filament_flow_ratio=["0.95"], nozzle_temperature=["225", "225"])})
    assert env.install(build).installed == ["A"]


def test_deleted_in_app_after_build_refused(tmp_path):
    names = ["A", "B", "C", "D", "E"]
    env = Env(tmp_path, live={n: (_preset(n), _info()) for n in names if n != "A"})
    env.snapshot({n: _preset(n) for n in names})
    build = env.build({n: _preset(n) for n in names})
    with pytest.raises(installer.Refused) as e:
        env.install(build)
    assert "A" in e.value.reason and "deleted" in e.value.reason
    assert not (env.live / "A.json").exists()


def test_app_reset_is_not_a_deletion(tmp_path):
    names = ["A", "B", "C", "D"]
    env = Env(tmp_path, live={"D": (_preset("D"), _info())})  # 3 of 4 vanished: app reset
    env.snapshot({n: _preset(n) for n in names})
    build = env.build({n: _preset(n) for n in names})
    assert env.install(build).installed == names
    assert all((env.live / f"{n}.json").exists() for n in names)


# --- Bambu Studio starts during the install --------------------------------------------------------

def test_studio_starts_right_before_first_write(tmp_path):
    env = Env(tmp_path, live={"A": (_preset("A"), _info())})
    before = _all_files(env.folders.user_filament)
    answers = iter([False, True])
    calls = []

    def running():
        calls.append(1)
        return next(answers)

    build = env.build({"A": _preset("A", nozzle_temperature=["230", "230"]), "B": _preset("B")})
    with pytest.raises(installer.Refused) as e:
        env.install(build, running=running)
    assert e.value.reason == "Bambu Studio is running"
    assert e.value.code == "studio_running"
    assert len(calls) == 2
    assert not env.dirs.backups.exists()
    assert not env.dirs.installed.exists()
    assert _all_files(env.folders.user_filament) == before


def test_studio_running_at_start_refused(tmp_path):
    env = Env(tmp_path)
    with pytest.raises(installer.Refused) as e:
        env.install(env.build({"A": _preset("A")}), running=lambda: True)
    assert e.value.code == "studio_running"
    assert not env.dirs.backups.exists()


# --- never delete ---------------------------------------------------------------------------------

def test_stale_preset_kept_on_disk_and_listed(tmp_path):
    env = Env(tmp_path, live={"A": (_preset("A"), _info()), "OLD": (_preset("OLD"), _info("PFUSold"))})
    env.snapshot({"A": _preset("A"), "OLD": _preset("OLD"), "GONE": _preset("GONE")})
    build = env.build({"A": _preset("A")})
    res = env.install(build)
    assert res.stale == ["OLD"]  # GONE is no longer live, so it is not listed
    assert (env.live / "OLD.json").exists() and (env.live / "OLD.info").exists()


def test_bad_build_json_refused(tmp_path):
    env = Env(tmp_path)
    build = env.build({"A": _preset("A")})
    (build / "base" / "A.json").write_text("{nope", encoding="utf-8")
    with pytest.raises(installer.Refused):
        env.install(build)
    assert not env.dirs.backups.exists()
