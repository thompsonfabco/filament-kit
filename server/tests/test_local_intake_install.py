"""Installing, upgrading and removing the local label reader from its signed release (local_intake_install.py), the
CLI commands and the setup page's plan and jobs, against a fake signed release (never a real download)."""
from __future__ import annotations

import io
import json
import tarfile

import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519
from fakes import module_release_fake as mrf

from filament_kit import cli, config, local_intake_install as lii, release, setup_helper


@pytest.fixture(autouse=True)
def fk_env(tmp_path, monkeypatch):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    monkeypatch.setenv("FK_NO_SYSTEMD", "1")
    monkeypatch.setenv("FK_LOCAL_INTAKE_STORE", str(tmp_path / "store"))
    cfg = config.load()
    cfg["modules"] = {"spoolman": True, "server": True}
    config.save(cfg)


@pytest.fixture
def key(monkeypatch):
    priv = ed25519.Ed25519PrivateKey.generate()
    monkeypatch.setattr(lii, "MODULE_PUBKEY", mrf.pubkey(priv))
    return priv


@pytest.fixture
def server():
    made = []

    def make(releases):
        s = mrf.Served(releases)
        made.append(s)
        cfg = config.load()
        cfg.setdefault("local_intake", {})["api"] = s.api
        cfg["local_intake"]["repo"] = "o/r"
        config.save(cfg)
        return s
    yield make
    for s in made:
        s.close()


class Run:
    def __init__(self, rc=0):
        self.rc, self.calls = rc, []

    def __call__(self, cmd, log):
        self.calls.append(cmd)
        log("installer output line")
        return self.rc


def fetcher(s):
    return release.Fetcher(s.api)


# ---------------------------------------------------------------- the release check

def test_no_key_pinned_means_nothing_is_downloaded(server, monkeypatch):
    priv = ed25519.Ed25519PrivateKey.generate()
    s = server({"0.1.0": mrf.make_release(priv)})
    monkeypatch.setattr(lii, "MODULE_PUBKEY", "")
    with pytest.raises(lii.InstallError, match="no release key"):
        lii.plan(config.load(), fetcher=fetcher(s))
    assert s.requests == []


def test_the_plan_states_sizes_before_any_model_is_downloaded(key, server):
    s = server({"0.1.0": mrf.make_release(key)})
    p = lii.plan(config.load(), tier="cpu", fetcher=fetcher(s))
    assert p["version"] == "0.1.0" and p["installed"] is None and not p["upgrade"]
    assert p["tiers"]["cpu"] == {"download_mb": 180, "disk_mb": 420, "minutes": 3,
                                 "assets": ["cpu-models-0.1.0.tar.gz"], "fetched_at_install": ""}
    text = lii.plan_text(p)
    assert text[0] == ("Install the local label reader 0.1.0, cpu tier: download about 180 MB, about 420 MB of disk, "
                       "about 3 min.")
    assert any(t.startswith("Other tiers: auto: 900 MB download") for t in text)
    assert s.downloaded() == ["SHA256SUMS", "SHA256SUMS.sig", "manifest.json"]
    g = lii.plan_text(lii.plan(config.load(), tier="gpu", fetcher=fetcher(s)))
    assert "The installer also fetches: the base vision model from its publisher (about 5 GB)." in g


@pytest.mark.parametrize("kw,match", [
    ({"tamper_sig": True}, "signature"),
    ({"manifest_over": {"api_version": "2.0"}}, "update the kit first"),
    ({"manifest_over": {"api_version": "0.9"}}, "newer reader release"),
    ({"manifest_over": {"kit_min": "9.0.0"}}, "needs filament-kit 9.0.0"),
    ({"manifest_over": {"tiers": {"cpu": {"assets": ["../x"]}}}}, "bad entry"),
])
def test_a_bad_release_is_refused(key, server, kw, match):
    s = server({"0.1.0": mrf.make_release(key, **kw)})
    with pytest.raises(lii.InstallError, match=match):
        lii.plan(config.load(), fetcher=fetcher(s))


def test_a_release_signed_with_another_key_is_refused(key, server):
    s = server({"0.1.0": mrf.make_release(ed25519.Ed25519PrivateKey.generate())})
    with pytest.raises(lii.InstallError, match="signature"):
        lii.install(config.load(), tier="cpu", fetcher=fetcher(s), run=Run())
    assert lii.installed() is None


# ---------------------------------------------------------------- install, upgrade, remove

def test_install_downloads_checks_unpacks_and_runs_the_installer(key, server, tmp_path):
    s = server({"0.1.0": mrf.make_release(key)})
    run, said = Run(), []
    rec = lii.install(config.load(), tier="cpu", fetcher=fetcher(s), run=run, say=said.append)
    assert rec["version"] == "0.1.0" and rec["tier"] == "cpu" and rec["port"] == 7915 and lii.installed() == rec
    store = tmp_path / "store" / "0.1.0"
    assert (store / "assets" / "cpu-models-0.1.0.tar.gz").read_bytes() == b"CPU MODELS 0.1.0"
    assert not (store / "assets" / "gpu-adapter-0.1.0.tar.gz").exists()           # the cpu tier's assets only
    cmd = run.calls[0]
    assert cmd[0] == "bash" and cmd[1] == str(store / "filament-kit-image-0.1.0" / "install" / "filament-kit-image.sh")
    assert cmd[2:] == ["--tier", "cpu", "--port", "7915", "--bind", "127.0.0.1", "--user", "filament-kit-image",
                       "--prefix", "/opt/filament-kit-image", "--assets", str(store / "assets")]
    assert "installer output line" in said and (store / "SHA256SUMS.sig").is_file()


def test_a_changed_asset_installs_nothing(key, server, tmp_path):
    s = server({"0.1.0": mrf.make_release(key, tamper_asset=True)})
    run = Run()
    with pytest.raises(lii.InstallError, match="does not match"):
        lii.install(config.load(), tier="cpu", fetcher=fetcher(s), run=run)
    assert not run.calls and lii.installed() is None and not any((tmp_path / "store").iterdir())


@pytest.mark.parametrize("tar,match", [
    (lambda v: mrf.code_tarball(v, extra=_entry("filament-kit-image-0.1.0/../../evil", 3)), "unexpected entry"),
    (lambda v: mrf.code_tarball(v, extra=_link("filament-kit-image-0.1.0/link")), "unexpected entry"),
    (lambda v: mrf.code_tarball(v, script=False), "has no filament-kit-image-0.1.0/install"),
])
def test_a_bad_tarball_installs_nothing(key, server, tar, match):
    s = server({"0.1.0": mrf.make_release(key, tarball=tar("0.1.0"))})
    run = Run()
    with pytest.raises(lii.InstallError, match=match):
        lii.install(config.load(), tier="cpu", fetcher=fetcher(s), run=run)
    assert not run.calls


def _entry(name, size):
    ti = tarfile.TarInfo(name)
    ti.size = size
    return ti


def _link(name):
    ti = tarfile.TarInfo(name)
    ti.type, ti.linkname = tarfile.SYMTYPE, "/etc/passwd"
    return ti


def test_a_failed_installer_leaves_the_kit_as_it_was(key, server):
    s = server({"0.1.0": mrf.make_release(key)})
    with pytest.raises(lii.InstallError, match="installer failed"):
        lii.install(config.load(), tier="cpu", fetcher=fetcher(s), run=Run(rc=3))
    assert lii.installed() is None


def test_upgrade_keeps_the_release_before_and_prunes_older_ones(key, server, tmp_path):
    rels = {"0.1.0": mrf.make_release(key, "0.1.0")}
    s = server(rels)
    lii.install(config.load(), tier="cpu", fetcher=fetcher(s), run=Run())
    rels["0.2.0"] = mrf.make_release(key, "0.2.0")
    p = lii.plan(config.load(), tier="cpu", fetcher=fetcher(s))
    assert p["upgrade"] and p["installed"] == "0.1.0" and lii.plan_text(p)[1].startswith("Upgrade to")
    rec = lii.install(config.load(), tier="cpu", fetcher=fetcher(s), run=Run())
    assert rec["version"] == "0.2.0" and rec["previous"] == "0.1.0"
    rels["0.3.0"] = mrf.make_release(key, "0.3.0")
    lii.install(config.load(), tier="cpu", fetcher=fetcher(s), run=Run())
    assert sorted(d.name for d in (tmp_path / "store").iterdir() if d.is_dir()) == ["0.2.0", "0.3.0"]
    assert (tmp_path / "store" / "installed.json").is_file()       # the record lives in root's store


def test_remove_runs_the_installed_releases_uninstaller(key, server, tmp_path):
    s = server({"0.1.0": mrf.make_release(key)})
    lii.install(config.load(), tier="cpu", fetcher=fetcher(s), run=Run())
    run = Run()
    assert lii.remove(run=run) is True
    assert run.calls[0][2:] == ["--uninstall", "--prefix", "/opt/filament-kit-image"]
    assert lii.installed() is None and not (tmp_path / "store").exists()
    assert lii.remove(run=Run()) is False


# ---------------------------------------------------------------- the CLI

@pytest.fixture
def applied(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "_run_apply", lambda pairing=True: calls.append(config.load()) or 0)
    return calls


def test_cli_install_shows_the_plan_asks_then_switches_the_module_on(key, server, applied, fake_reader, monkeypatch,
                                                                     capsys):
    url, _ = fake_reader
    s = server({"0.1.0": mrf.make_release(key)})
    monkeypatch.setattr(cli, "_ask", lambda prompt: "n")
    assert cli.cmd_local_intake_install("cpu", None, False, fetcher=fetcher(s), run=Run()) == 0
    out = capsys.readouterr().out
    assert "download about 180 MB, about 420 MB of disk, about 3 min" in out and "Nothing was installed." in out
    assert lii.installed() is None and not applied
    # the fake reader stands in for the installed one (the CLI points local_intake.url at the port it installed on)
    monkeypatch.setattr(lii, "wait_healthy", lambda cfg, *a, **k: lii.local_reader.health(
        {**cfg, "local_intake": {**cfg["local_intake"], "url": url}}))
    assert cli.cmd_local_intake_install("cpu", None, True, fetcher=fetcher(s), run=Run()) == 0
    cfg = config.load()
    assert cfg["modules"]["local_intake"] is True and cfg["local_intake"]["url"] == "http://127.0.0.1:7915"
    assert cfg["local_intake"]["tier"] == "cpu" and len(applied) == 1
    assert "The reader answers: version 0.1.0, API 1.0." in capsys.readouterr().out


def test_cli_install_says_when_the_reader_does_not_answer(key, server, applied, monkeypatch, capsys):
    s = server({"0.1.0": mrf.make_release(key)})
    monkeypatch.setattr(lii, "wait_healthy", lambda cfg, *a, **k: {"ok": False, "error": "it does not answer"})
    assert cli.cmd_local_intake_install(None, None, True, fetcher=fetcher(s), run=Run()) == 1
    assert "installed, but the reader does not answer yet: it does not answer" in capsys.readouterr().err


def test_cli_remove_switches_off_what_needs_only_this_reader(key, server, applied, capsys):
    s = server({"0.1.0": mrf.make_release(key)})
    lii.install(config.load(), tier="cpu", fetcher=fetcher(s), run=Run())
    cfg = config.load()
    cfg["modules"].update(local_intake=True, orders=True)
    cfg["orders"] = {"file": "/x.json"}
    config.save(cfg)
    assert cli.cmd_local_intake_remove(True, run=Run()) == 0
    cfg = config.load()
    assert cfg["modules"]["local_intake"] is False and cfg["modules"]["orders"] is False
    assert "that also turns off: orders" in capsys.readouterr().out and lii.installed() is None


def test_cli_remove_with_nothing_installed_and_the_module_off(capsys):
    assert cli.cmd_local_intake_remove(True) == 0
    assert "nothing to do" in capsys.readouterr().out


def test_cli_parses_the_commands(monkeypatch):
    seen = []
    monkeypatch.setattr(cli, "cmd_local_intake_install", lambda *a, **k: seen.append(("install", a, k)) or 0)
    monkeypatch.setattr(cli, "cmd_local_intake_remove", lambda *a: seen.append(("remove", a, {})) or 0)
    monkeypatch.setattr(cli, "cmd_local_intake_plan", lambda: seen.append(("plan", (), {})) or 0)
    assert cli.main(["local-intake", "install", "--tier", "gpu", "--version", "0.2.0", "--yes"]) == 0
    assert cli.main(["local-intake", "install", "--yes", "--planned"]) == 0
    assert cli.main(["local-intake", "remove"]) == 0
    assert cli.main(["local-intake", "plan"]) == 0
    assert seen == [("install", ("gpu", "0.2.0", True), {"planned": False}),
                    ("install", (None, None, True), {"planned": True}), ("remove", (False,), {}), ("plan", (), {})]


# ---------------------------------------------------------------- the setup page

def test_the_page_runs_install_and_remove_as_jobs():
    assert setup_helper.JOBS["local_intake_plan"] == ("local-intake", "plan")
    assert setup_helper.JOBS["local_intake_install"] == ("local-intake", "install", "--yes", "--planned")
    assert setup_helper.JOBS["local_intake_remove"] == ("local-intake", "remove", "--yes")
    assert set(setup_helper.BUSY) == set(setup_helper.JOBS)


def test_the_page_reads_the_saved_plan_and_never_fetches(key, server, monkeypatch):
    """Review R148 finding 2: the kit server's unit cannot reach GitHub; the plan runs as a root job and the page
    reads what it saved."""
    from test_setup_page import Helper, client, make
    s = server({"0.1.0": mrf.make_release(key)})
    monkeypatch.setattr(lii, "default_fetcher", lambda cfg: (_ for _ in ()).throw(AssertionError("fetched")))
    cfg = config.load()
    cfg["web"] = {**cfg["web"], "lan": ["192.0.2.0/24"]}
    config.save(cfg)
    c = client(make([], Helper()))
    assert c.get("/setup/api/settings/local-intake/plan").json() == {"saved": None}
    monkeypatch.setattr(lii, "default_fetcher", lambda cfg: fetcher(s))
    assert cli.cmd_local_intake_plan() == 0                       # what the job runs (as root)
    monkeypatch.setattr(lii, "default_fetcher", lambda cfg: (_ for _ in ()).throw(AssertionError("fetched")))
    saved = c.get("/setup/api/settings/local-intake/plan").json()["saved"]
    assert saved["fresh"] and saved["plan"]["version"] == "0.1.0"
    assert saved["text"][0].startswith("Install the local label reader 0.1.0")
    assert c.get("/setup/api/settings/general").json()["local_intake_installed"] is None


# ---------------------------------------------------------------- review R148

def _record(tmp_path, d):
    (tmp_path / "store").mkdir(exist_ok=True)
    (tmp_path / "store" / "installed.json").write_text(json.dumps(d))


@pytest.mark.parametrize("rec", [
    {"version": "../../x", "tier": "cpu", "prefix": "/"},
    {"version": "0.1.0/../../../x", "tier": "cpu"},
    {"version": 7, "tier": "cpu"},
    {"version": "0.1.0", "tier": "rm -rf"},
])
def test_a_record_that_is_not_one_is_never_acted_on(tmp_path, rec):
    """Review R148 finding 1: remove (root) builds nothing from a record that is not an X.Y.Z version."""
    _record(tmp_path, rec)
    run = Run()
    assert lii.installed() is None and lii.remove(run=run) is False and not run.calls


def test_remove_takes_the_fixed_prefix_and_a_script_inside_the_store(key, server, tmp_path):
    s = server({"0.1.0": mrf.make_release(key)})
    lii.install(config.load(), tier="cpu", fetcher=fetcher(s), run=Run())
    rec = json.loads((tmp_path / "store" / "installed.json").read_text())
    _record(tmp_path, {**rec, "prefix": "/"})                       # a prefix in the record is never read
    run = Run()
    lii.remove(run=run)
    assert run.calls[0][-2:] == ["--prefix", "/opt/filament-kit-image"]
    assert run.calls[0][1].startswith(str((tmp_path / "store").resolve()))


def test_remove_refuses_an_uninstaller_that_resolves_outside_the_store(key, server, tmp_path):
    s = server({"0.1.0": mrf.make_release(key)})
    lii.install(config.load(), tier="cpu", fetcher=fetcher(s), run=Run())
    inst = tmp_path / "store" / "0.1.0" / "filament-kit-image-0.1.0" / "install"
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "filament-kit-image.sh").write_text("echo evil")
    import shutil
    shutil.rmtree(inst)
    try:
        inst.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("this machine cannot make symlinks")
    run = Run()
    with pytest.raises(lii.InstallError, match="not in"):
        lii.remove(run=run)
    assert not run.calls


def test_the_record_and_the_plan_live_in_roots_store_not_the_service_state(key, server, tmp_path):
    s = server({"0.1.0": mrf.make_release(key)})
    lii.install(config.load(), tier="cpu", fetcher=fetcher(s), run=Run())
    lii.save_plan(lii.plan(config.load(), tier="cpu", fetcher=fetcher(s)))
    assert {p.name for p in (tmp_path / "store").iterdir() if p.is_file()} == {"installed.json", "plan.json"}
    assert not list(config.paths().state.glob("local-intake*"))


def test_auto_on_a_release_without_an_auto_tier_is_its_cpu_tier(key, server):
    """Review R148 finding 3."""
    m = mrf.manifest("0.1.0")
    del m["tiers"]["auto"]
    s = server({"0.1.0": mrf.make_release(key, manifest_over={"tiers": m["tiers"]})})
    p = lii.plan(config.load(), tier="auto", fetcher=fetcher(s))
    assert p["tier"] == "cpu" and "This release has no auto tier: its cpu tier is used." in lii.plan_text(p)
    run = Run()
    rec = lii.install(config.load(), tier="auto", fetcher=fetcher(s), run=run)
    assert rec["tier"] == "cpu" and run.calls[0][2:4] == ["--tier", "cpu"]


def test_a_downgrade_is_labelled_and_needs_the_version_by_name(key, server):
    """Review R148 finding 4."""
    rels = {"0.2.0": mrf.make_release(key, "0.2.0")}
    s = server(rels)
    lii.install(config.load(), tier="cpu", fetcher=fetcher(s), run=Run())
    s.releases = {"0.2.0": rels["0.2.0"], "0.1.0": mrf.make_release(key, "0.1.0")}     # 0.1.0 is "latest" now
    p = lii.plan(config.load(), tier="cpu", fetcher=fetcher(s))
    assert p["downgrade"] and lii.plan_text(p)[1].startswith("Go back (downgrade) to the local label reader 0.1.0")
    with pytest.raises(lii.InstallError, match="older than the installed 0.2.0"):
        lii.install(config.load(), tier="cpu", fetcher=fetcher(s), run=Run())
    assert lii.install(config.load(), tier="cpu", version="0.1.0", fetcher=fetcher(s), run=Run())["version"] == "0.1.0"


def test_a_record_with_a_bad_version_does_not_break_the_plan(key, server, tmp_path):
    """Review R148 finding 5."""
    s = server({"0.1.0": mrf.make_release(key)})
    _record(tmp_path, {"version": "latest", "tier": "cpu"})
    assert lii.plan(config.load(), fetcher=fetcher(s))["installed"] is None


def test_the_page_job_installs_exactly_the_planned_version(key, server, applied, monkeypatch, capsys):
    """Review R148 finding 6: a release published after the page showed its plan is not installed instead."""
    rels = {"0.1.0": mrf.make_release(key, "0.1.0")}
    s = server(rels)
    monkeypatch.setattr(lii, "wait_healthy", lambda cfg, *a, **k: {"ok": True, "version": "x", "api_version": "1.0"})
    assert cli.cmd_local_intake_install(None, None, True, fetcher=fetcher(s), run=Run(), planned=True) == 1
    assert "no plan from the last hour" in capsys.readouterr().err
    lii.save_plan(lii.plan(config.load(), tier="cpu", fetcher=fetcher(s)))
    rels["0.2.0"] = mrf.make_release(key, "0.2.0")                  # published after the owner saw 0.1.0
    assert cli.cmd_local_intake_install(None, None, True, fetcher=fetcher(s), run=Run(), planned=True) == 0
    assert lii.installed()["version"] == "0.1.0"
    plan = json.loads((lii.store() / "plan.json").read_text())
    plan["at"] -= lii.PLAN_TTL + 1
    (lii.store() / "plan.json").write_text(json.dumps(plan))
    assert cli.cmd_local_intake_install(None, None, True, fetcher=fetcher(s), run=Run(), planned=True) == 1
