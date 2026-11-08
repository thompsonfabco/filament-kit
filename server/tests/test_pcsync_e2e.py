"""End to end: the real server app under uvicorn over TLS on 127.0.0.1 + the real PC sync client and installer.

A fixture Bambu Studio folder lives under tmp_path (APPDATA / LOCALAPPDATA point there, as in pc-sync's conftest);
Spoolman is the in-memory FakeSm of test_builds; the system presets are server/tests/data/bbl/filament. Builds run
in-process (`builds.run_build`), as filament-kit-build.service would run them.
"""
import importlib.util
import io
import json
import re
import shutil
import sys
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from conftest import free_port
from filament_kit import config, library, pairing
from filament_kit.api import create_app
from filament_kit.bridge import registry
from filament_kit.bridge.registry import Printer
from filament_kit.profiles import builds, preset_for

import test_generate as TG
from test_builds import FakeSm, SUNLU

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "pc-sync"))

from fksync import __main__ as fkmain, client as fkclient, installer, store, studio, sync  # noqa: E402

_spec = importlib.util.spec_from_file_location("pcsync_studio_fixture", REPO / "pc-sync" / "tests" / "studio_fixture.py")
studio_fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(studio_fixture)

BBL = Path(__file__).parent / "data" / "bbl" / "filament"
H2D = "Bambu Lab H2D"
P_ID = re.compile(r"^P[0-9a-f]{7}$")
IDS_LINE = "Spoolman filament ids: 3, 17"
LID = "sunlu--pla-plus-2-0"


@pytest.fixture(autouse=True)
def _fake_appdata(tmp_path, monkeypatch):
    """As pc-sync's conftest: nothing here may reach the real %APPDATA% / %LOCALAPPDATA%."""
    for name in ("APPDATA", "LOCALAPPDATA"):
        (tmp_path / name.lower()).mkdir()
        monkeypatch.setenv(name, str(tmp_path / name.lower()))


# ---------- the server ----------

@pytest.fixture
def server(tmp_path, monkeypatch):
    """(port, FakeSm) of a real create_app under uvicorn with the server's own TLS certificate."""
    srv = tmp_path / "srv"
    for name in ("etc", "state", "opt"):
        (srv / name).mkdir(parents=True)
        monkeypatch.setenv(f"FK_{name.upper()}", str(srv / name))
    pairing.make_cert("fkhost", [], srv / "etc")
    config.save({"placement": {"box_count": 2}})
    monkeypatch.setattr(library, "load", lambda: TG.make_lib())
    registry.upsert(Printer("S1", "H2D", "O1D", "10.0.0.5", "", True))
    sm = FakeSm([json.loads(json.dumps(f)) for f in SUNLU])
    port = free_port()
    etc = config.paths().etc
    uv = uvicorn.Server(uvicorn.Config(create_app(sm=sm), host="127.0.0.1", port=port, log_level="warning",
                                       ssl_certfile=str(etc / "cert.pem"), ssl_keyfile=str(etc / "key.pem"),
                                       lifespan="off"))
    t = threading.Thread(target=uv.run, daemon=True)
    t.start()
    for _ in range(200):
        if uv.started:
            break
        time.sleep(0.05)
    else:
        raise RuntimeError("the server did not start")
    yield port, sm
    uv.should_exit = True
    t.join(timeout=10)
    assert not t.is_alive(), "the uvicorn thread did not stop"


# ---------- the PC ----------

class Pc:
    """One Windows PC: its fixture Bambu Studio folder, the sync's own files and a paired client."""

    def __init__(self, root: Path, port: int, system_src: Path):
        self.appdata, self.dirs = root / "appdata", store.AppDirs(root / "local" / "filament-kit-sync")
        self.folders = studio_fixture.make(self.appdata, system_src=system_src)
        self.port = port
        self.now = time.time()
        self.client = None

    def pair(self, monkeypatch, code: str) -> int:
        """The real `filament-kit-sync pair` dialogue: address, confirm the fingerprint, 6-digit code."""
        self.dirs.ensure()
        monkeypatch.setattr(sys, "stdin", io.StringIO(f"127.0.0.1:{self.port}\ny\n{code}\n"))
        rc = fkmain.cmd_pair(self.dirs)
        if rc == 0:
            cfg = store.load_config(self.dirs)
            self.folders = studio.locate(self.appdata, cfg)
            self.client = fkclient.Client(cfg, store.load_token(self.dirs))
        return rc

    def run(self) -> str:
        self.now += 3600          # past REQUEST_RETRY, so every run may ask for a rebuild again
        return sync.run_once(self.client, self.folders, self.dirs, running=lambda: False, now=self.now)

    @property
    def base(self) -> Path:
        return self.folders.user_filament / "base"

    def preset(self, name: str) -> dict:
        return json.loads((self.base / f"{name}.json").read_text(encoding="utf-8"))

    def write(self, name: str, cfg: dict) -> None:
        with open(self.base / f"{name}.json", "w", encoding="utf-8", newline="\n") as f:
            json.dump(cfg, f, indent=4)

    def names(self) -> set[str]:
        return {p.stem for p in self.base.glob("*.json")}


def system_copy(tmp_path) -> Path:
    """The fixture system presets without broken.json (an unparsable system preset is only a store problem, see
    test_unparsable_system_preset_is_a_problem_not_a_refusal; the flows here need no problem line for it)."""
    dest = tmp_path / "bbl-src"
    shutil.copytree(BBL, dest)
    (dest / "broken.json").unlink()
    return dest


def sunlu(nozzle: str) -> str:
    return TG.sunlu(H2D, nozzle)


def build(sm) -> dict:
    r = builds.run_build(sm)
    assert r["ok"], r
    return r


def manifest(stamp: str) -> dict:
    return builds.manifest(stamp)


def accept_all() -> list[dict]:
    """The owner accepts every listed update (`profiles apply-updates --all`): the only way the PC writes over a
    preset that is already in Bambu Studio."""
    return builds.apply_updates(all_=True)["chosen"]


def choose_parent(port: int, fp: str, parent: str) -> None:
    """The phone app (its own paired device) sets the line's Bambu parent: PATCH /api/profiles/lines/<id>."""
    phone = fkclient.Client({"host": "127.0.0.1", "port": port, "fp": fp},
                            pairing.redeem_code(pairing.issue("phone").code))
    res = phone._request("PATCH", f"/api/profiles/lines/{LID}", json.dumps({"bambu_parent": parent}).encode(),
                         "application/json")
    assert res["line"]["bambu_parent"] == parent, res


def uploaded_then_rebuild(pc: Pc) -> None:
    """The in-app change goes up and, although the installed build is current, the PC asks for a rebuild itself
    (ruling S29b: its live hash differs from the one the install left)."""
    assert pc.run() == "rebuild_requested"
    st = pc.client.state()
    assert st["live_hash"] == builds.tree_hash(pc.folders.user_filament)
    assert st["rebuild_requested"]["live_hash"] == st["live_hash"]


def paired_pc(tmp_path, server, monkeypatch, name="pc1") -> Pc:
    port, _ = server
    pc = Pc(tmp_path / name, port, system_copy(tmp_path / name))
    assert pc.pair(monkeypatch, pairing.issue("pc").code) == 0
    return pc


def installed_first_build(tmp_path, server, monkeypatch) -> tuple[Pc, str]:
    """Pair, upload, build, install; returns (pc, stamp)."""
    _, sm = server
    pc = paired_pc(tmp_path, server, monkeypatch)
    assert pc.run() == "uploaded"
    build(sm)                                   # creates the line (no usable parent for the H2D yet)
    choose_parent(pc.port, store.load_config(pc.dirs)["fp"], "Generic PLA")
    stamp = build(sm)["stamp"]
    assert pc.run() == "installed"
    return pc, stamp


# ---------- the brief's flow ----------

def test_full_cycle(tmp_path, server, monkeypatch):
    port, sm = server

    # a build before any sync waits cleanly (S15)
    r = builds.run_build(sm)
    assert r["ok"] is False and r.get("waiting") is True and r["stamp"] is None
    assert builds.current() is None

    # 1. pair with a code (the PC checks the fingerprint, then sends the code; the token is stored by DPAPI)
    pc = Pc(tmp_path / "pc1", port, system_copy(tmp_path / "pc1"))
    assert pc.pair(monkeypatch, pairing.issue("pc").code) == 0
    cfg = store.load_config(pc.dirs)
    assert cfg["fp"] == pairing.fingerprint((config.paths().etc / "cert.pem").read_bytes())
    me = cfg["device"]
    assert me in {d["id"] for d in pairing.devices()}
    st = pc.client.state()
    assert st["owner"] is None and st["you"] == me and st["build"] is None

    # 2. run_once -> uploaded (live + system), then no_build; the system upload asked for a build
    assert pc.run() == "uploaded"
    st = pc.client.state()
    assert st["owner"] == me and st["user_id"] == pc.folders.user_id
    assert st["live_hash"] == builds.tree_hash(pc.folders.user_filament)
    assert st["system_hash"] == builds.tree_hash(pc.folders.system_filament)
    assert st["rebuild_requested"] is not None
    assert builds.tree_hash(config.paths().state / "profiles" / "live" / "system") == st["system_hash"]
    assert pc.run() == "no_build"

    # 3. the build. The library's parent (Bambu PLA Tough+) is not in this system folder and the one SUNLU brand
    # preset lists only the X1C: a good build with a problem line; the owner picks Generic PLA in the app
    b0 = build(sm)
    assert manifest(b0["stamp"])["presets"] == []
    assert any(LID in p and "H2D" in p for p in b0["problems"]), b0["problems"]
    choose_parent(port, cfg["fp"], "Generic PLA")
    assert pc.client.state()["rebuild_requested"] is not None
    b1 = build(sm)
    st = pc.client.state()
    assert st["build"]["stamp"] == b1["stamp"] and st["build"]["live_hash"] == st["live_hash"]
    assert st["rebuild_requested"] is None and st["installed"] is None
    m1 = manifest(b1["stamp"])
    built = {p["name"] for p in m1["presets"]}
    h2d = {n for n in built if f"@{H2D} " in n}
    assert h2d and len(h2d) >= 3, (built, m1["problems"])

    # 4. run_once -> installed; base/ has the H2D presets with the Spoolman ids line last; the server knows
    assert pc.run() == "installed"
    assert h2d <= pc.names()
    for name in h2d:
        cfg_ = pc.preset(name)
        notes = cfg_["filament_notes"]
        notes = "\n".join(notes) if isinstance(notes, list) else notes
        assert notes.splitlines()[-1] == IDS_LINE, name
        assert cfg_["inherits"] == "" and P_ID.match(cfg_["filament_id"]), name
        assert (pc.base / f"{name}.info").is_file()
    st = pc.client.state()
    assert st["installed"]["stamp"] == b1["stamp"]
    assert st["live_hash"] == builds.tree_hash(pc.folders.user_filament)     # re-uploaded after the install
    assert json.loads((pc.dirs.installed / "BUILD.json").read_text(encoding="utf-8"))["stamp"] == b1["stamp"]
    assert pc.run() == "up_to_date"

    # 5. preset_for: the line's generated P id with int temps, never a Generic or system id
    ref = preset_for(SUNLU[0], "O1D", 0.4)
    assert ref is not None and ref.name == sunlu("0.4")
    assert P_ID.match(ref.filament_id) and not ref.filament_id.startswith("G")
    system_ids = {json.loads(p.read_text(encoding="utf-8")).get("filament_id")
                  for p in pc.folders.system_filament.glob("*.json")}
    assert ref.filament_id not in system_ids
    assert ref.filament_id == pc.preset(ref.name)["filament_id"]
    assert type(ref.nozzle_temp_min) is int and type(ref.nozzle_temp_max) is int
    assert (ref.nozzle_temp_min, ref.nozzle_temp_max) == (190, 230)       # the Spoolman nozzle_range
    assert ref.filament_type == "PLA"
    ref_red = preset_for(SUNLU[1], "O1D", 0.4)
    assert ref_red is not None and ref_red.filament_id == ref.filament_id       # one id per line

    # 6. an in-app edit of filament_flow_ratio is kept through upload, rebuild and reinstall
    edited = sunlu("0.4")
    cfg_ = pc.preset(edited)
    flow = ["0.91"] * len(cfg_["filament_flow_ratio"])
    assert cfg_["filament_flow_ratio"] != flow
    cfg_["filament_flow_ratio"] = flow
    pc.write(edited, cfg_)
    uploaded_then_rebuild(pc)
    b2 = build(sm)
    assert any(edited in e and "filament_flow_ratio" in e for e in manifest(b2["stamp"])["edits"])
    assert pc.run() == "installed"
    assert pc.client.state()["installed"]["stamp"] == b2["stamp"]
    assert pc.preset(edited)["filament_flow_ratio"] == flow
    assert pc.preset(sunlu("0.6"))["filament_flow_ratio"] != flow          # only the edited one

    # 7. a preset deleted in the app is not reinstalled
    gone = sunlu("0.6")
    (pc.base / f"{gone}.json").unlink()
    (pc.base / f"{gone}.info").unlink()
    uploaded_then_rebuild(pc)
    b3 = build(sm)
    m3 = manifest(b3["stamp"])
    assert gone not in {p["name"] for p in m3["presets"]} and m3["deleted"] == [gone]
    assert pc.run() == "installed"
    assert gone not in pc.names() and not (pc.base / f"{gone}.info").exists()
    assert (h2d - {gone}) <= pc.names()
    assert preset_for(SUNLU[0], "O1D", 0.6) is None                          # no preset: never a Generic one
    # (that the step-6 edit also survives this second rebuild is test_inapp_edit_survives_a_second_rebuild)

    # 8. half of the generated presets vanish at once: an app reset, so all of them come back
    left = sorted(h2d - {gone})
    vanish = left[: (len(h2d) + 1) // 2]
    assert len(vanish) / len(left) > 0.25
    for name in vanish:
        (pc.base / f"{name}.json").unlink()
    uploaded_then_rebuild(pc)
    b4 = build(sm)
    m4 = manifest(b4["stamp"])
    assert m4["deleted"] == []
    assert {p["name"] for p in m4["presets"]} == built                       # the one deleted in step 7 too
    assert pc.run() == "installed"
    assert built <= pc.names()
    assert preset_for(SUNLU[0], "O1D", 0.6) is not None

    # 9. a second device is not the sync PC: other_pc, and nothing it has reaches the server
    before = pc.client.state()
    other = Pc(tmp_path / "pc2", port, system_copy(tmp_path / "pc2"))
    assert other.pair(monkeypatch, pairing.issue("pc").code) == 0
    assert store.load_config(other.dirs)["device"] != me
    (other.base / "mine.json").write_text("{}", encoding="utf-8")
    assert other.run() == "other_pc"
    assert sync.load_state(other.dirs).get("uploaded") is None
    after = pc.client.state()
    assert (after["owner"], after["live_hash"], after["system_hash"]) == \
        (me, before["live_hash"], before["system_hash"])
    with pytest.raises(fkclient.ApiError) as e:
        other.client.upload("live", b"PK\x05\x06" + b"\0" * 18, user_id="x")
    assert e.value.status == 409 and e.value.code == "other_pc"
    assert pc.run() == "up_to_date"


def test_inapp_edit_survives_a_second_rebuild(tmp_path, server, monkeypatch):
    _, sm = server
    pc, _ = installed_first_build(tmp_path, server, monkeypatch)
    edited = sunlu("0.4")
    cfg = pc.preset(edited)
    flow = ["0.91"] * len(cfg["filament_flow_ratio"])
    cfg["filament_flow_ratio"] = flow
    pc.write(edited, cfg)
    uploaded_then_rebuild(pc)
    build(sm)
    assert pc.run() == "installed"
    assert pc.preset(edited)["filament_flow_ratio"] == flow                  # first rebuild: kept
    _density(sm, 1.30)                                                       # any later reason to rebuild
    builds.request_rebuild("spoolman changed")
    b3 = build(sm)
    assert pc.run() == "installed"                                           # nothing over the existing ones
    assert pc.preset(edited)["filament_density"] != ["1.3"]
    assert accept_all()
    assert pc.run() == "installed"                                           # the accepted updates
    assert pc.client.state()["installed"]["stamp"] == b3["stamp"]
    assert pc.preset(edited)["filament_density"] == ["1.3"]
    assert pc.preset(edited)["filament_flow_ratio"] == flow                  # second rebuild: still his value


def test_app_reset_keeps_the_owners_notes(tmp_path, server, monkeypatch):
    """Final review C1: a line typed in the notes survives an app reset that removed the preset."""
    _, sm = server
    pc, stamp = installed_first_build(tmp_path, server, monkeypatch)
    edited = sunlu("0.4")
    cfg = pc.preset(edited)
    cfg["filament_notes"] = cfg["filament_notes"].replace(IDS_LINE, "dry 8 h at 55 C\n" + IDS_LINE)
    pc.write(edited, cfg)
    assert pc.run() == "uploaded"                   # notes alone never ask for a rebuild (S31); any later one
    builds.request_rebuild("spoolman changed")
    build(sm)
    assert pc.run() == "installed"
    assert "dry 8 h at 55 C" in pc.preset(edited)["filament_notes"]
    h2d = sorted(n for n in pc.names() if f"@{H2D} " in n)
    vanish = [edited] + [n for n in h2d if n != edited][: len(h2d) // 2]
    for name in vanish:                                                      # an app reset
        (pc.base / f"{name}.json").unlink()
    uploaded_then_rebuild(pc)
    b = build(sm)
    assert manifest(b["stamp"])["deleted"] == []
    assert pc.run() == "installed"
    notes = pc.preset(edited)["filament_notes"].splitlines()
    assert notes[-2:] == ["dry 8 h at 55 C", IDS_LINE], notes


def test_restore_deleted_before_the_deletion_build_installs(tmp_path, server, monkeypatch):
    """Final review I3b: restore-deleted right after a deletion in the app: the build brings the preset back and
    the PC installs it (no stale_build refusal that would repeat forever)."""
    _, sm = server
    pc, _ = installed_first_build(tmp_path, server, monkeypatch)
    gone = sunlu("0.6")
    (pc.base / f"{gone}.json").unlink()
    assert pc.run() == "rebuild_requested"
    builds.restore_deleted_next()
    builds.request_rebuild("restore deleted presets")
    b = build(sm)
    assert manifest(b["stamp"])["restored"] == [gone]
    assert pc.run() == "installed"
    assert gone in pc.names()


def test_inapp_nil_value_installs(tmp_path, server, monkeypatch):
    """Final review I3c: a "nil" typed in the app is carried and filled by the generator; the PC installs that build
    instead of refusing it as older than the owner's change."""
    _, sm = server
    pc, _ = installed_first_build(tmp_path, server, monkeypatch)
    edited = sunlu("0.4")
    cfg = pc.preset(edited)
    temps = cfg["nozzle_temperature"]
    assert isinstance(temps, list) and len(temps) >= 2, temps
    cfg["nozzle_temperature"] = ["231"] + ["nil"] * (len(temps) - 1)
    pc.write(edited, cfg)
    uploaded_then_rebuild(pc)
    build(sm)
    assert [u["name"] for u in accept_all()] == [edited]                     # the filled "nil": an update
    assert pc.run() == "installed"
    assert pc.preset(edited)["nozzle_temperature"] == ["231"] * len(temps)


def test_inapp_gcode_edit_installs_after_an_app_reset(tmp_path, server, monkeypatch):
    """Final review I3a: the owner's own G-code (accepted once, so in dirs.installed) is carried after an app reset
    and installed, although no live copy and no system preset holds it."""
    _, sm = server
    pc, _ = installed_first_build(tmp_path, server, monkeypatch)
    edited = sunlu("0.4")
    cfg = pc.preset(edited)
    mine = ["; my own end G-code"]
    cfg["filament_end_gcode"] = mine
    pc.write(edited, cfg)
    uploaded_then_rebuild(pc)
    build(sm)
    assert pc.run() == "installed"
    h2d = sorted(n for n in pc.names() if f"@{H2D} " in n)
    for name in [edited] + [n for n in h2d if n != edited][: len(h2d) // 2]:  # an app reset
        (pc.base / f"{name}.json").unlink()
    uploaded_then_rebuild(pc)
    build(sm)
    assert pc.run() == "installed"
    assert pc.preset(edited)["filament_end_gcode"] == mine


def test_restored_backup_without_system_presets_is_resynced(tmp_path, server, monkeypatch):
    """Final review I5: a server backup leaves out live/system but keeps meta.json; the PC's next run uploads the
    system presets again and builds work."""
    _, sm = server
    pc, _ = installed_first_build(tmp_path, server, monkeypatch)
    shutil.rmtree(config.paths().state / "profiles" / "live" / "system")
    assert pc.client.state()["system_hash"] is None
    assert pc.run() == "uploaded"
    assert pc.client.state()["system_hash"] == builds.tree_hash(pc.folders.system_filament)
    builds.request_rebuild("after restore")
    assert builds.run_build(sm)["ok"] is True


# ---------- interrupted installs ----------

def _crash_after(monkeypatch, writes: int) -> None:
    """The installer's live writes fail (OSError) after `writes` files, as a crash or a full disk would."""
    real, n = installer._write_live, [0]

    def write(target, data):
        if n[0] >= writes:
            raise OSError(28, "No space left on device (test)")
        n[0] += 1
        real(target, data)
    monkeypatch.setattr(installer, "_write_live", write)


def _density(sm, value: float) -> None:
    for f in sm.filaments:
        f["density"] = value


def test_interrupted_install_is_resumed(tmp_path, server, monkeypatch):
    _, sm = server
    pc, _ = installed_first_build(tmp_path, server, monkeypatch)
    _density(sm, 1.31)
    builds.request_rebuild("spoolman changed")
    b2 = build(sm)
    accept_all()
    with monkeypatch.context() as m:
        _crash_after(m, 2)                       # the first preset's .json + .info, then the disk is full
        with pytest.raises(OSError):
            pc.run()
    assert sync.marker_path(pc.dirs).exists()
    first, *rest = sorted(p["name"] for p in manifest(b2["stamp"])["presets"])
    assert pc.preset(first)["filament_density"] == ["1.31"]
    assert all(pc.preset(n)["filament_density"] != ["1.31"] for n in rest)

    assert pc.run() == "installed"               # resumed: the same build, no live-hash gate
    assert not sync.marker_path(pc.dirs).exists()
    assert pc.client.state()["installed"]["stamp"] == b2["stamp"]
    for n in [first, *rest]:
        assert pc.preset(n)["filament_density"] == ["1.31"], n
    assert pc.run() == "up_to_date"


def test_interrupted_install_values_are_not_inapp_edits(tmp_path, server, monkeypatch):
    _, sm = server
    pc, _ = installed_first_build(tmp_path, server, monkeypatch)
    _density(sm, 1.31)
    builds.request_rebuild("spoolman changed")
    b2 = build(sm)
    accept_all()
    with monkeypatch.context() as m:
        _crash_after(m, 2)
        with pytest.raises(OSError):
            pc.run()
    first, *rest = sorted(p["name"] for p in manifest(b2["stamp"])["presets"])
    assert pc.preset(first)["filament_density"] == ["1.31"]

    # edited in Bambu Studio before the next run: the resume is declined, the normal path follows
    edited = rest[0]
    cfg = pc.preset(edited)
    flow = ["0.9"] * len(cfg["filament_flow_ratio"])
    cfg["filament_flow_ratio"] = flow
    pc.write(edited, cfg)
    _density(sm, 1.35)                            # and Spoolman changed again meanwhile
    assert pc.run() == "rebuild_requested"
    assert not sync.marker_path(pc.dirs).exists()
    b3 = build(sm)
    accept_all()
    out = pc.run()
    assert out == "installed", (out, sync.load_state(pc.dirs).get("last"))
    assert pc.client.state()["installed"]["stamp"] == b3["stamp"]
    assert pc.preset(edited)["filament_flow_ratio"] == flow                # the real in-app edit is kept
    edits = manifest(b3["stamp"]).get("edits", [])
    assert not any(first in e and "filament_density" in e for e in edits), edits
    for n in [first, *rest]:
        assert pc.preset(n)["filament_density"] == ["1.35"], n            # the half-install's 1.31 is not "his"


def test_failed_reupload_after_a_reported_install_is_sent_next_run(tmp_path, server, monkeypatch):
    """S32 + round 3: the install is reported, the live re-upload fails; builds wait for the PC's next sync, which
    sends the owed live upload, and the build then runs with no false in-app edits."""
    _, sm = server
    pc, _ = installed_first_build(tmp_path, server, monkeypatch)
    _density(sm, 1.31)
    builds.request_rebuild("spoolman changed")
    b2 = build(sm)
    real = pc.client.upload

    def offline(*a, **kw):
        raise fkclient.Offline("server unreachable (test)")
    monkeypatch.setattr(pc.client, "upload", offline)
    with pytest.raises(fkclient.Offline):
        pc.run()
    monkeypatch.setattr(pc.client, "upload", real)
    assert pc.client.state()["installed"]["stamp"] == b2["stamp"]
    _density(sm, 1.35)
    builds.request_rebuild("spoolman changed")
    r = builds.run_build(sm)
    assert r["waiting"] is True and r["error"] == builds.WAIT_LIVE
    assert pc.run() in ("uploaded", "up_to_date")
    assert sync.load_state(pc.dirs).get("live_owed") is None
    b3 = build(sm)
    m3 = manifest(b3["stamp"])
    assert m3["edits"] == [] and m3["inapp"] == {}, m3["edits"]
    accept_all()
    assert pc.run() == "installed"
    for p in m3["presets"]:
        assert pc.preset(p["name"])["filament_density"] == ["1.35"], p["name"]


# ---------- uploads the server refuses ----------

def test_unparsable_system_preset_is_a_problem_not_a_refusal(tmp_path, server, monkeypatch):
    """Ruling S29a: the unmodified fixture folder holds broken.json; the server takes the system zip, keeps the
    file (the hashes agree, so it is not sent again) and the builds list it as a store problem."""
    port, sm = server
    pc = Pc(tmp_path / "pc1", port, BBL)
    assert pc.pair(monkeypatch, pairing.issue("pc").code) == 0
    assert pc.run() == "uploaded"
    assert "rejected" not in sync.load_state(pc.dirs)
    st = pc.client.state()
    assert st["system_hash"] == builds.tree_hash(pc.folders.system_filament) and st["live_hash"] is not None
    assert pc.run() == "no_build"
    r = build(sm)
    assert any(p.startswith("broken.json: unreadable") for p in r["problems"]), r["problems"]
    choose_parent(port, store.load_config(pc.dirs)["fp"], "Generic PLA")
    r = build(sm)
    assert manifest(r["stamp"])["presets"]
    assert pc.run() == "installed"


# ---------- existing presets are never replaced; updates are listed and applied on request ----------

def test_existing_presets_stay_until_their_update_is_accepted(tmp_path, server, monkeypatch, capsys):
    from filament_kit import cli
    _, sm = server
    pc, b1 = installed_first_build(tmp_path, server, monkeypatch)
    assert pc.run() == "up_to_date"
    before = {p.name: p.read_bytes() for p in pc.base.iterdir()}
    _density(sm, 1.31)
    builds.request_rebuild("spoolman changed")
    b2 = build(sm)
    assert pc.run() == "installed"                          # nothing new: every preset already exists
    assert {p.name: p.read_bytes() for p in pc.base.iterdir() if p.name in before} == before
    assert pc.run() in ("up_to_date", "uploaded")
    names = sorted(p["name"] for p in manifest(b2["stamp"])["presets"])
    view = builds.updates_view()
    assert view["count"] == len(names) and view["lines"] == 1

    assert cli.main(["profiles", "status"]) == 0
    assert f"{len(names)} updates available (1 line)" in capsys.readouterr().out
    assert cli.main(["profiles", "apply-updates", "--line", LID, "--dry-run"]) == 0
    assert pc.run() in ("up_to_date", "uploaded")           # a dry run accepted nothing
    assert {p.name: p.read_bytes() for p in pc.base.iterdir() if p.name in before} == before

    # accept one preset's update (as the line command would, narrowed to one name): exactly that one is written
    from filament_kit.profiles import updates as updates_mod
    acc = updates_mod.accepted(config.paths().state / "profiles")
    acc["base"] = {sunlu("0.4")}
    updates_mod.save_accepted(config.paths().state / "profiles", acc, builds._write_json)
    assert pc.run() == "installed"
    assert pc.preset(sunlu("0.4"))["filament_density"] == ["1.31"]
    for name in names:
        if name != sunlu("0.4"):
            assert (pc.base / f"{name}.json").read_bytes() == before[f"{name}.json"], name
    assert builds.updates_view()["count"] == len(names) - 1
    assert builds.state_view(store.load_config(pc.dirs)["device"])["accepted_updates"]["base"] == []

    # the rest, by line
    assert cli.main(["profiles", "apply-updates", "--line", LID]) == 0
    assert pc.run() == "installed"
    for name in names:
        assert pc.preset(name)["filament_density"] == ["1.31"], name
    assert builds.updates_view()["count"] == 0
    assert b1


def test_owner_preset_present_before_the_first_install_is_kept(tmp_path, server, monkeypatch):
    _, sm = server
    pc = paired_pc(tmp_path, server, monkeypatch)
    mine = {"type": "filament", "name": sunlu("0.4"), "inherits": "", "from": "User", "filament_id": "P0000abc",
            "filament_type": ["PLA"], "nozzle_temperature": ["199"]}
    pc.write(sunlu("0.4"), mine)
    own = (pc.base / f"{sunlu('0.4')}.json").read_bytes()
    assert pc.run() == "uploaded"
    build(sm)
    choose_parent(pc.port, store.load_config(pc.dirs)["fp"], "Generic PLA")
    build(sm)
    assert pc.run() == "installed"
    assert (pc.base / f"{sunlu('0.4')}.json").read_bytes() == own
    assert sunlu("0.6") in pc.names()                       # the new ones are added
    assert sunlu("0.4") in {u["name"] for u in builds.updates_view()["updates"]}
