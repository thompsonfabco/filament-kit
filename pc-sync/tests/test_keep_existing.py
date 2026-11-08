"""The owner's rule (2026-11-06): an install never replaces a preset that is already in the slicer; it only adds new
ones. Updates to existing presets are written only once the owner accepted them on the server (`accept`).
Bambu Studio and Orca Slicer, in the Windows and the Linux folder layouts (all trees are fakes)."""
import json
from pathlib import Path

import pytest

import orca_fixture
import studio_fixture
from fksync import installer, studio
from fksync.store import AppDirs

A, B = "Acme PLA @BBL H2D", "Acme PLA @BBL H2D 0.6 nozzle"
OA, OB = "Acme PLA @SV08 MAX 0.4", "Acme PLA @SV08 MAX 0.6"


def _p(name, **kw):
    d = {"type": "filament", "name": name, "inherits": "", "from": "User", "filament_id": "P1a2b3c4",
         "filament_type": ["PLA"], "nozzle_temperature": ["215"]}
    d.update(kw)
    return d


def _op(name, **kw):
    d = {"name": name, "inherits": "Generic PLA @System", "from": "User", "filament_id": "Pabcdef1",
         "nozzle_temperature": ["215"]}
    d.update(kw)
    return d


def _tree(folder: Path, presets: dict) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for name, data in presets.items():
        (folder / f"{name}.json").write_text(json.dumps(data, indent=4), encoding="utf-8")
        (folder / f"{name}.info").write_text("sync_info = \nsetting_id = \n", encoding="utf-8")


def _folders(tmp_path, layout, base, orca_presets):
    """(StudioFolders, OrcaFolders) in the Windows (%APPDATA%) or the Linux (~/.config) layout."""
    info = {"sync_info": "", "user_id": "1", "setting_id": "PFUS1", "base_id": "GFSA04"}
    oinfo = {"sync_info": "", "user_id": orca_fixture.USER_ID, "setting_id": "", "base_id": "x"}
    bs = {n: (d, info) for n, d in base.items()}
    os_ = {n: (d, oinfo) for n, d in orca_presets.items()}
    if layout == "windows":
        return (studio_fixture.make(tmp_path / "appdata", base=bs),
                orca_fixture.make(tmp_path / "appdata", presets=os_))
    cfg = tmp_path / "home" / ".config"
    studio_fixture.make(cfg, variant="BambuStudio", user_id="111", base=bs)
    orca_fixture.make(cfg, presets=os_)
    lay = studio.LinuxLayout.from_env({"HOME": str(tmp_path / "home")}, system_flatpak=tmp_path / "fp",
                                      share_dirs=(), opt_dirs=())
    f, o = studio.locate(None, layout=lay), studio.locate_orca(None, None, layout=lay)
    assert str(f.user_filament).startswith(str(cfg)) and str(o.user_filament).startswith(str(cfg))
    return f, o


class Env:
    def __init__(self, tmp_path, layout, base=None, orca=None):
        self.tmp = tmp_path
        self.f, self.o = _folders(tmp_path, layout, base or {}, orca or {})
        self.dirs = AppDirs(tmp_path / "local" / "filament-kit-sync")
        self.dirs.ensure()
        self.n = 0

    def build(self, base, orca=None) -> Path:
        self.n += 1
        b = self.tmp / f"build{self.n}"
        b.mkdir()
        (b / "BUILD.json").write_text(json.dumps({"stamp": f"2026110201000{self.n}", "live_hash": "x"}))
        _tree(b / "base", base)
        if orca is not None:
            _tree(b / "orca", orca)
        return b

    def install(self, build, **kw):
        return installer.install(build, self.f, self.dirs, running=lambda: False, stamp_now=f"20261102-01000{self.n}",
                                 orca=self.o, orca_running=lambda: False, **kw)

    def bs(self, name) -> Path:
        return self.f.user_filament / "base" / f"{name}.json"

    def orca(self, name) -> Path:
        return self.o.user_filament / f"{name}.json"


LAYOUTS = ["windows", "linux"]


def _bytes(folder: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(folder.iterdir()) if p.is_file()}


@pytest.mark.parametrize("layout", LAYOUTS)
def test_existing_presets_left_byte_identical_new_ones_written(tmp_path, layout):
    e = Env(tmp_path, layout, base={A: _p(A)}, orca={OA: _op(OA)})
    before_bs, before_o = _bytes(e.f.user_filament / "base"), _bytes(e.o.user_filament)
    b = e.build({A: _p(A, nozzle_temperature=["230"]), B: _p(B)},
                {OA: _op(OA, nozzle_temperature=["230"]), OB: _op(OB)})
    res = e.install(b)
    # the existing presets (.json and .info) are exactly as they were
    for name, data in before_bs.items():
        assert (e.f.user_filament / "base" / name).read_bytes() == data
    for name, data in before_o.items():
        assert (e.o.user_filament / name).read_bytes() == data
    # the new ones are written
    assert json.loads(e.bs(B).read_text()) == _p(B)
    assert json.loads(e.orca(OB).read_text()) == _op(OB)
    assert (res.installed, res.kept) == ([B], [A])
    assert (res.installed_orca, res.kept_orca) == ([OB], [OA])
    # the backup step stays
    assert (res.backup / "base" / f"{A}.json").is_file() and (res.backup_orca / f"{OA}.json").is_file()
    # the snapshot is what the slicers hold: the kept presets' own copies, the build's for the new ones
    assert (e.dirs.installed / "base" / f"{A}.json").read_bytes() == before_bs[f"{A}.json"]
    assert (e.dirs.installed / "base" / f"{B}.json").read_bytes() == (b / "base" / f"{B}.json").read_bytes()
    assert (e.dirs.installed / "orca" / f"{OA}.json").read_bytes() == before_o[f"{OA}.json"]


@pytest.mark.parametrize("layout", LAYOUTS)
def test_same_preset_name_in_another_file_is_not_overwritten_nor_duplicated(tmp_path, layout):
    e = Env(tmp_path, layout)
    (e.f.user_filament / "base" / "my own.json").write_text(json.dumps(_p(A)), encoding="utf-8")
    (e.o.user_filament / "mine.json").write_text(json.dumps(_op(OA)), encoding="utf-8")
    res = e.install(e.build({A: _p(A, nozzle_temperature=["230"])}, {OA: _op(OA, nozzle_temperature=["230"])}))
    assert not e.bs(A).exists() and not e.orca(OA).exists()
    assert json.loads((e.f.user_filament / "base" / "my own.json").read_text()) == _p(A)
    assert res.kept == [A] and res.kept_orca == [OA] and res.installed == [] and res.installed_orca == []
    assert not (e.dirs.installed / "base" / f"{A}.json").exists()       # not ours: never diffed as an edit
    assert not (e.dirs.installed / "orca" / f"{OA}.json").exists()


@pytest.mark.parametrize("layout", LAYOUTS)
def test_accepted_updates_are_the_only_overwrites(tmp_path, layout):
    e = Env(tmp_path, layout, base={A: _p(A), B: _p(B)}, orca={OA: _op(OA), OB: _op(OB)})
    keep_b, keep_ob = e.bs(B).read_bytes(), e.orca(OB).read_bytes()
    b = e.build({A: _p(A, nozzle_temperature=["230"]), B: _p(B, nozzle_temperature=["230"])},
                {OA: _op(OA, nozzle_temperature=["230"]), OB: _op(OB, nozzle_temperature=["230"])})
    res = e.install(b, accept={"base": [A], "orca": [OA]})
    assert json.loads(e.bs(A).read_text())["nozzle_temperature"] == ["230"]
    assert json.loads(e.orca(OA).read_text())["nozzle_temperature"] == ["230"]
    assert e.bs(B).read_bytes() == keep_b and e.orca(OB).read_bytes() == keep_ob
    assert installer.read_info(e.f.user_filament / "base" / f"{A}.info")["setting_id"] == "PFUS1"   # cloud id kept
    assert (res.installed, res.kept, res.installed_orca, res.kept_orca) == ([A], [B], [OA], [OB])
    assert (e.dirs.installed / "base" / f"{A}.json").read_bytes() == (b / "base" / f"{A}.json").read_bytes()
    assert (e.dirs.installed / "base" / f"{B}.json").read_bytes() == keep_b
    # the backup holds the overwritten preset as it was
    assert json.loads((res.backup / "base" / f"{A}.json").read_text())["nozzle_temperature"] == ["215"]


@pytest.mark.parametrize("layout", LAYOUTS)
def test_accepted_update_of_a_preset_in_another_file_goes_over_that_file(tmp_path, layout):
    e = Env(tmp_path, layout)
    own = e.f.user_filament / "base" / "my own.json"
    own.write_text(json.dumps(_p(A)), encoding="utf-8")
    res = e.install(e.build({A: _p(A, nozzle_temperature=["230"])}), accept={"base": [A]})
    assert json.loads(own.read_text())["nozzle_temperature"] == ["230"] and not e.bs(A).exists()
    assert res.installed == [A]
    assert not (e.dirs.installed / "base" / f"{A}.json").exists()       # as the server: not diffed by name


def test_kept_presets_g_code_is_the_owners(tmp_path):
    """A kept preset's snapshot copy is the owner's own file: its G-code counts like an accepted one (it is carried
    after an app reset, say); G-code from nowhere is still refused."""
    e = Env(tmp_path, "windows", base={A: _p(A, filament_start_gcode=["; mine"])})
    e.install(e.build({A: _p(A)}))
    assert e.install(e.build({A: _p(A), B: _p(B, filament_start_gcode=["; mine"])})).installed == [B]
    with pytest.raises(installer.Refused) as r:
        e.install(e.build({A: _p(A), "C": _p("C", filament_start_gcode=["; from nowhere"])}))
    assert r.value.code == "untrusted_gcode"


def test_stale_presets_are_never_removed(tmp_path):
    e = Env(tmp_path, "windows")
    e.install(e.build({A: _p(A), B: _p(B)}))
    res = e.install(e.build({A: _p(A)}))
    assert res.stale == [B] and e.bs(B).is_file()


# --- the sync run: nothing over an existing preset until the owner accepts its update --------------------------

from fksync import store, sync, treehash  # noqa: E402
from test_sync import INFO, PRESET, STAMP, T0, FakeClient, _build_zip, _synced_state  # noqa: E402
from test_orca_sync import N as ON, OPRESET, OINFO, OrcaClient, _state as _ostate, _zip as _ozip  # noqa: E402

LIVE_NAME = PRESET["name"]


@pytest.fixture
def senv(tmp_path):
    folders = studio_fixture.make(tmp_path / "appdata", base={LIVE_NAME: (PRESET, INFO)})
    dirs = store.AppDirs(tmp_path / "local" / "filament-kit-sync")
    dirs.ensure()
    return folders, dirs


def _live_file(folders):
    return folders.user_filament / "base" / f"{LIVE_NAME}.json"


def _two(live_hash):
    return _build_zip(live_hash=live_hash, presets={LIVE_NAME: dict(PRESET, nozzle_temperature=["220"]),
                                                   "New PLA @BBL H2D": dict(PRESET, name="New PLA @BBL H2D")})


def test_sync_install_keeps_the_existing_preset_and_reports_what_was_written(senv):
    folders, dirs = senv
    before = _live_file(folders).read_bytes()
    live = treehash.tree_hash(folders.user_filament)
    c = FakeClient(_synced_state(folders, build={"stamp": STAMP, "live_hash": live}), _two(live))
    assert sync.run_once(c, folders, dirs, running=lambda: False, now=T0) == "installed"
    assert _live_file(folders).read_bytes() == before
    assert (folders.user_filament / "base" / "New PLA @BBL H2D.json").is_file()
    assert c.written == [{"base": ["New PLA @BBL H2D"]}]
    assert "1 presets are already in the slicer and were left as they are" in dirs.log_file.read_text()
    # the kept preset is no in-app change: the next run is up to date (no rebuild asked for)
    c.st.update(live_hash=treehash.tree_hash(folders.user_filament), installed={"stamp": STAMP})
    c.calls.clear()
    assert sync.run_once(c, folders, dirs, running=lambda: False, now=T0 + 60) == "up_to_date"
    assert _live_file(folders).read_bytes() == before


def test_accepted_update_of_the_installed_build_is_written_then_cleared(senv):
    folders, dirs = senv
    before = _live_file(folders).read_bytes()
    live = treehash.tree_hash(folders.user_filament)
    c = FakeClient(_synced_state(folders, build={"stamp": STAMP, "live_hash": live}), _two(live))
    sync.run_once(c, folders, dirs, running=lambda: False, now=T0)
    c.st.update(live_hash=treehash.tree_hash(folders.user_filament), installed={"stamp": STAMP})
    # an accepted update for another build changes nothing
    c.st["accepted_updates"] = {"stamp": "20261101-000000", "base": [LIVE_NAME]}
    assert sync.run_once(c, folders, dirs, running=lambda: False, now=T0 + 60) == "up_to_date"
    assert _live_file(folders).read_bytes() == before
    c.st["accepted_updates"] = {"stamp": STAMP, "base": [LIVE_NAME], "orca": []}
    assert sync.run_once(c, folders, dirs, running=lambda: False, now=T0 + 120) == "installed"
    assert json.loads(_live_file(folders).read_text())["nozzle_temperature"] == ["220"]
    assert c.written[-1] == {"base": [LIVE_NAME]}                  # exactly the accepted one
    assert len(list(dirs.backups.iterdir())) == 2                  # backed up before the overwrite
    assert json.loads((dirs.installed / "base" / f"{LIVE_NAME}.json").read_text())["nozzle_temperature"] == ["220"]
    # the server cleared it: nothing more is written
    c.st.pop("accepted_updates")
    c.st.update(live_hash=treehash.tree_hash(folders.user_filament))
    assert sync.run_once(c, folders, dirs, running=lambda: False, now=T0 + 180) == "up_to_date"


def test_accepted_update_goes_in_with_a_new_build(senv):
    folders, dirs = senv
    live = treehash.tree_hash(folders.user_filament)
    c = FakeClient(_synced_state(folders, build={"stamp": STAMP, "live_hash": live}), _two(live))
    c.st["accepted_updates"] = {"stamp": STAMP, "base": [LIVE_NAME]}
    assert sync.run_once(c, folders, dirs, running=lambda: False, now=T0) == "installed"
    assert json.loads(_live_file(folders).read_text())["nozzle_temperature"] == ["220"]
    assert c.written == [{"base": [LIVE_NAME, "New PLA @BBL H2D"]}]


def test_owed_report_keeps_what_was_written(senv):
    folders, dirs = senv
    live = treehash.tree_hash(folders.user_filament)
    c = FakeClient(_synced_state(folders, build={"stamp": STAMP, "live_hash": live}), _two(live))
    c.fail["installed"] = sync.ApiError(500, "boom", "down")
    with pytest.raises(sync.ApiError):
        sync.run_once(c, folders, dirs, running=lambda: False, now=T0)
    assert sync.load_state(dirs)["report_written"] == {"base": ["New PLA @BBL H2D"]}
    c.fail.clear()
    sync.run_once(c, folders, dirs, running=lambda: False, now=T0 + 60)
    assert c.written[-1] == {"base": ["New PLA @BBL H2D"]}


def test_orca_accepted_update_of_the_installed_build(tmp_path):
    folders = studio_fixture.make(tmp_path / "appdata", base={LIVE_NAME: (PRESET, INFO)})
    orca = orca_fixture.make(tmp_path / "appdata", presets={ON: (OPRESET, OINFO)},
                             install=tmp_path / "pf" / "OrcaSlicer 2.5.0",
                             opc=orca_fixture.opc_blob(orca_fixture.LIBRARY))
    dirs = store.AppDirs(tmp_path / "local" / "filament-kit-sync")
    dirs.ensure()
    ofile = orca.user_filament / f"{ON}.json"
    before = ofile.read_bytes()
    st = _ostate(folders, orca)
    st["build"] = {"stamp": STAMP, "live_hash": st["live_hash"], "orca_live_hash": st["orca_live_hash"]}
    c = OrcaClient(st, _ozip(live_hash=st["live_hash"], orca_live_hash=st["orca_live_hash"]))
    run = lambda now: sync.run_once(c, folders, dirs, running=lambda: False, now=now, orca=orca,  # noqa: E731
                                    orca_running=lambda: False)
    assert run(T0) == "installed"
    assert ofile.read_bytes() == before                             # kept
    assert c.written == [{"base": [], "orca": []}]
    c.st.update(_ostate(folders, orca, build=c.st["build"], installed={"stamp": STAMP}))
    assert run(T0 + 60) == "up_to_date"
    c.st["accepted_updates"] = {"stamp": STAMP, "base": [], "orca": [ON]}
    assert run(T0 + 120) == "installed"
    assert json.loads(ofile.read_text())["nozzle_temperature"] == ["225"]
    assert c.written[-1] == {"base": [], "orca": [ON]}
    assert (folders.user_filament / "base" / f"{LIVE_NAME}.json").read_bytes() == \
        studio_fixture.json.dumps(PRESET, indent=4).encode() + b"\n"      # Bambu Studio's still untouched


def test_accepted_orca_update_that_cannot_go_in_does_not_reinstall_every_run(tmp_path):
    folders = studio_fixture.make(tmp_path / "appdata", base={LIVE_NAME: (PRESET, INFO)})
    orca = orca_fixture.make(tmp_path / "appdata", presets={ON: (OPRESET, OINFO)},
                             install=tmp_path / "pf" / "OrcaSlicer 2.5.0",
                             opc=orca_fixture.opc_blob(orca_fixture.LIBRARY))
    dirs = store.AppDirs(tmp_path / "local" / "filament-kit-sync")
    dirs.ensure()
    st = _ostate(folders, orca)
    st["build"] = {"stamp": STAMP, "live_hash": st["live_hash"], "orca_live_hash": "older"}
    c = OrcaClient(st, _ozip(live_hash=st["live_hash"], orca_live_hash="older"))
    run = lambda now: sync.run_once(c, folders, dirs, running=lambda: False, now=now, orca=orca,  # noqa: E731
                                    orca_running=lambda: False)
    assert run(T0) == "installed"                                   # base only (Orca presets are newer)
    c.st.update(_ostate(folders, orca, build=c.st["build"], installed={"stamp": STAMP}))
    c.st["accepted_updates"] = {"stamp": STAMP, "base": [], "orca": [ON]}
    n = len(list(dirs.backups.iterdir()))
    assert run(T0 + 60) == "rebuild_requested"                        # its Orca presets are newer: a rebuild
    assert len(list(dirs.backups.iterdir())) == n                   # no install, no backup churn


# --- fix round 1 ---------------------------------------------------------------------------------------------

import unicodedata  # noqa: E402


@pytest.mark.parametrize("layout", LAYOUTS)
def test_case_only_file_name_match_is_kept_and_never_blocks_later_installs(tmp_path, layout):
    """I1: `acme pla @bbl h2d.json` holds the generated preset: kept, not in the snapshot (not ours to diff), and the
    next installs go through (on Linux the build-cased snapshot copy read as "deleted in Bambu Studio")."""
    e = Env(tmp_path, layout)
    own = e.f.user_filament / "base" / f"{A.lower()}.json"
    own.write_text(json.dumps(_p(A)), encoding="utf-8")
    before = own.read_bytes()
    r1 = e.install(e.build({A: _p(A, nozzle_temperature=["230"]), B: _p(B)}))
    assert r1.kept == [A] and r1.installed == [B]
    assert sorted(p.name for p in (e.dirs.installed / "base").glob("*.json")) == [f"{B}.json"]
    r2 = e.install(e.build({A: _p(A, nozzle_temperature=["235"]), B: _p(B)}))
    assert r2.kept == [A, B] and own.read_bytes() == before
    e.install(e.build({A: _p(A, nozzle_temperature=["240"]), B: _p(B)}), accept={"base": [A]})
    assert json.loads(own.read_text())["nozzle_temperature"] == ["240"]
    assert sorted(p.name for p in (e.dirs.installed / "base").glob("*.json")) == [f"{B}.json"]


@pytest.mark.parametrize("layout", LAYOUTS)
def test_upper_case_suffix_of_a_kept_preset(tmp_path, layout):
    """M5 + round 2: a kept `<name>.JSON` is "another file" (only an exact `<name>.json` is the preset's own): kept,
    no snapshot copy, and the next installs go through (on Linux a `<name>.json` snapshot copy read as "deleted in
    Bambu Studio")."""
    e = Env(tmp_path, layout)
    own = e.f.user_filament / "base" / f"{A}.JSON"
    own.write_text(json.dumps(_p(A)), encoding="utf-8")
    before = own.read_bytes()
    res = e.install(e.build({A: _p(A, nozzle_temperature=["230"]), B: _p(B)}))
    assert res.kept == [A] and own.read_bytes() == before
    assert sorted(p.name for p in (e.dirs.installed / "base").iterdir()) == [f"{B}.info", f"{B}.json"]
    res = e.install(e.build({A: _p(A, nozzle_temperature=["235"]), B: _p(B)}))
    assert res.kept == [A, B] and own.read_bytes() == before
    e.install(e.build({A: _p(A, nozzle_temperature=["240"]), B: _p(B)}), accept={"base": [A]})
    assert json.loads(own.read_text())["nozzle_temperature"] == ["240"]
    assert not (e.dirs.installed / "base" / f"{A}.json").exists()


def test_names_match_after_unicode_normalization(tmp_path):
    """M4: a live file (and `name`) in NFD is the same preset as the build's NFC name."""
    nfc = unicodedata.normalize("NFC", "Acme Café PLA @BBL H2D")
    nfd = unicodedata.normalize("NFD", nfc)
    assert nfc != nfd
    e = Env(tmp_path, "windows")
    (e.f.user_filament / "base" / f"{nfd}.json").write_text(json.dumps(_p(nfd)), encoding="utf-8")
    res = e.install(e.build({nfc: _p(nfc, nozzle_temperature=["230"])}))
    assert res.kept == [nfc] and res.installed == []
    assert sorted(p.name for p in (e.f.user_filament / "base").glob("*.json")) == [f"{nfd}.json"]


@pytest.mark.parametrize("layout", LAYOUTS)
def test_same_name_preset_in_the_filament_root_is_never_written_over(tmp_path, layout):
    """Bambu Studio keeps the user presets that inherit a system preset in filament/ itself (only the flattened,
    `inherits: ""` ones in filament/base/). One of the same name there is the owner's: kept, also when accepted
    (writing base/<name>.json would make two presets of one name)."""
    e = Env(tmp_path, layout)
    root = e.f.user_filament / f"{A}.json"
    root.write_text(json.dumps(_p(A, inherits="Generic PLA @BBL H2D")), encoding="utf-8")
    before = root.read_bytes()
    for accept in (None, {"base": [A]}):
        res = e.install(e.build({A: _p(A, nozzle_temperature=["230"])}), accept=accept)
        assert res.kept == [A] and res.installed == []
        assert root.read_bytes() == before and not e.bs(A).exists()
        assert not (e.dirs.installed / "base" / f"{A}.json").exists()


def test_report_owed_from_before_the_upgrade_sends_no_written(senv):
    """M3: an owed report without `report_written` (saved by the older PC sync) sends written=None: the server
    keeps its old behaviour (that install wrote every preset)."""
    folders, dirs = senv
    live = treehash.tree_hash(folders.user_filament)
    c = FakeClient(_synced_state(folders, build={"stamp": STAMP, "live_hash": live}, installed={"stamp": STAMP}))
    sync._save_state(dirs, {"report": STAMP, "report_trees": ["base"]})
    sync.run_once(c, folders, dirs, running=lambda: False, now=T0)
    assert c.written == [None]
