"""No folder of the kit is writable by the web unit's user. Its preset/line writes, the
shared label-read cap and the order history go through the kit API; its failed reads stay in its own folder; the
kit's writers never follow a link planted where the web could once write; the H2D slot token is readable by it."""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from filament_kit import api, config, intake, modules, pairing, web_access
from filament_kit.spoolman import Spoolman

ROOT = Path(__file__).resolve().parents[2]
LINUX = pytest.mark.skipif(sys.platform == "win32", reason="POSIX only")


@pytest.fixture
def kit(tmp_path, monkeypatch):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    pairing.make_cert("fkhost", [], tmp_path / "etc")
    cfg = config.load()
    cfg["modules"] = {n: True for n in modules.MODES["server"] | {"ai_intake", "orders"}}
    config.save(cfg)
    return tmp_path


def _client(**kw):
    app = api.create_app(Spoolman("http://127.0.0.1:9"), printers=object(), camera_hub=object(), mapper=object(),
                         enabled_modules=frozenset(modules.enabled(config.load())) - {"printers"}, **kw)
    tok = pairing.redeem_code(pairing.issue("web (MCP)", role="web").code)
    return TestClient(app), {"Authorization": f"Bearer {tok}"}


def _bearer(name: str, role=None) -> dict:
    return {"Authorization": f"Bearer {pairing.redeem_code(pairing.issue(name, role=role).code)}"}


# ---------- the read cap and the orders, through the kit ----------

def test_kit_cap_routes_take_and_refund_the_kits_cap(kit):
    cfg = config.load()
    cfg["reads_per_day"] = 2
    config.save(cfg)
    c, h = _client()
    t1 = c.post("/api/intake/cap/take", headers=h, json={}).json()["ticket"]
    assert c.post("/api/intake/cap/take", headers=h, json={}).status_code == 200
    r = c.post("/api/intake/cap/take", headers=h, json={})
    assert r.status_code == 429 and r.json()["error"] == "daily_cap"
    assert c.post("/api/intake/cap/refund", headers=h, json={"ticket": t1}).status_code == 200
    assert c.post("/api/intake/cap/take", headers=h, json={}).status_code == 200
    assert c.post("/api/intake/cap/take", json={}).status_code == 401


def test_kit_cap_refund_needs_a_live_ticket_of_the_same_device(kit):
    c, h = _client()
    other = {"Authorization": f"Bearer {pairing.redeem_code(pairing.issue('phone').code)}"}
    reads = kit / "state" / "reads.json"
    t = c.post("/api/intake/cap/take", headers=h, json={}).json()["ticket"]
    for body in ({}, {"ticket": "made-up"}, {"ticket": 5}):
        r = c.post("/api/intake/cap/refund", headers=h, json=body)
        assert r.status_code == 409 and r.json()["error"] == "refund_refused", body
    r = c.post("/api/intake/cap/refund", headers=other, json={"ticket": t})
    assert r.status_code == 409 and intake.reads_today(reads) == 1
    assert c.post("/api/intake/cap/refund", headers=h, json={"ticket": t}).status_code == 200
    assert intake.reads_today(reads) == 0
    assert c.post("/api/intake/cap/refund", headers=h, json={"ticket": t}).status_code == 409
    assert c.post("/api/intake/cap/refund", json={"ticket": t}).status_code == 401


def test_kit_orders_route_leaves_the_block_out_for_a_missing_file(kit):
    cfg = config.load()
    cfg["orders"] = {"file": str(kit / "state" / "no-such-orders.json")}
    config.save(cfg)
    c, h = _client()
    assert c.get("/api/intake/orders", headers=h).json() == {"orders": None}


def test_kit_orders_route_reads_the_orders_file(kit):
    f = kit / "state" / "orders.json"
    f.write_text(json.dumps({"items": [{"order": "o1", "asin": "B0EXAMPLE", "title": "PLA"}]}), encoding="utf-8")
    cfg = config.load()
    cfg["orders"] = {"file": str(f)}
    config.save(cfg)
    c, h = _client()
    assert c.get("/api/intake/orders", headers=h).json()["orders"][0]["asin"] == "B0EXAMPLE"
    assert c.get("/api/intake/orders").status_code == 401


def _orders_file(kit):
    f = kit / "state" / "orders.json"
    f.write_text(json.dumps({"items": [{"order": "o1", "asin": "B0EXAMPLE", "title": "PLA"}]}), encoding="utf-8")
    cfg = config.load()
    cfg["orders"] = {"file": str(f)}
    config.save(cfg)


@pytest.mark.parametrize("name", ["phone", "pc", "station"])
def test_kit_orders_route_refuses_every_device_but_the_web_unit(kit, name):
    _orders_file(kit)
    c, h = _client()
    r = c.get("/api/intake/orders", headers=_bearer(name))
    assert r.status_code == 403 and r.json()["error"] == "forbidden"
    assert c.get("/api/intake/orders", headers=h).status_code == 200


def test_kit_orders_route_refuses_a_device_only_named_like_the_web_unit_until_apply_marks_it(kit):
    _orders_file(kit)
    c, _ = _client()
    old = _bearer("web (MCP)")                           # paired before roles existed
    assert c.get("/api/intake/orders", headers=old).status_code == 403
    assert web_access.mark_web_device() == 1
    assert c.get("/api/intake/orders", headers=old).json()["orders"][0]["asin"] == "B0EXAMPLE"
    assert web_access.mark_web_device() == 0             # marked once


@LINUX
def test_root_pairing_of_the_web_unit_marks_its_device(kit):
    web_access.pair(os.getuid(), os.getgid(), chown=lambda *a: None)
    devs = json.loads((kit / "state" / "devices.json").read_text(encoding="utf-8"))
    assert [d.get("role") for d in devs if d["name"] == "web (MCP)"] == ["web"]


def test_apply_marks_the_web_units_old_pairing(kit, monkeypatch):
    from filament_kit import apply
    import types
    seen = []
    monkeypatch.delenv("FK_NO_SYSTEMD", raising=False)
    monkeypatch.setitem(sys.modules, "pwd", types.SimpleNamespace(getpwnam=lambda n: types.SimpleNamespace(
        pw_uid=54321, pw_gid=54321)))
    for name in ("migrate", "shared_files", "pair", "grant"):
        monkeypatch.setattr(web_access, name, lambda *a, _n=name, **k: seen.append(_n) or [])
    monkeypatch.setattr(web_access, "mark_web_device", lambda: seen.append("mark") or 0)
    apply._web_state(apply._Exec(lambda cmd: None, Path("."), Path("/")))
    assert seen.index("mark") < seen.index("pair")


def test_web_cap_asks_the_kit():
    pytest.importorskip("mcp")  # the web extra
    from filament_kit.web import slots
    from filament_kit.web.intake_app import KitCap

    class Kit:
        def __init__(self):
            self.calls = []

        def post(self, path, body):
            self.calls.append((path, body))
            if len(self.calls) > 1 and path.endswith("/take"):
                raise slots.SlotError("daily limit of 60 label reads reached", code="daily_cap", http=429)
            return {"ok": True, "ticket": "T1"} if path.endswith("/take") else {"ok": True}
    k = Kit()
    cap = KitCap(k)
    cap.take()
    cap.refund()
    assert k.calls == [("/api/intake/cap/take", {}), ("/api/intake/cap/refund", {"ticket": "T1"})]
    with pytest.raises(intake.CapReached):
        KitCap(k).take()
    KitCap(k).refund()                     # nothing taken: nothing to give back, no call
    assert len(k.calls) == 3


def test_read_context_takes_the_orders_from_the_kit(kit, monkeypatch):
    monkeypatch.setattr(intake.tagsources, "fresh_unknown_tag", lambda cfg, sm: None)
    ctx = intake.read_context(config.load(), None, None, orders_from=lambda: [{"asin": "B0EXAMPLE"}])
    assert ctx["orders"] == [{"asin": "B0EXAMPLE"}]


def test_failed_reads_go_to_the_web_units_own_folder(kit, monkeypatch, tmp_path):
    monkeypatch.setenv("FK_FAILED_DIR", str(tmp_path / "web-failed"))
    assert intake._failed_dir() == tmp_path / "web-failed"
    unit = (ROOT / "install/systemd/filament-kit-web.service").read_text(encoding="utf-8")
    assert "Environment=FK_FAILED_DIR=/var/lib/filament-kit-web/failed\n" in unit


def test_an_unconfigured_web_unit_is_not_restarted_forever():
    """FA-044: __main__ exits 2 when web.public_url is missing; a restart every 5 s would only repeat it."""
    unit = (ROOT / "install/systemd/filament-kit-web.service").read_text(encoding="utf-8")
    assert "RestartPreventExitStatus=2\n" in unit and "return 2" in (
        ROOT / "server/filament_kit/web/__main__.py").read_text(encoding="utf-8")


# ---------- preset writes through the kit ----------

def test_kit_routes_for_the_webs_preset_writes(kit, monkeypatch):
    from filament_kit.web import presets
    seen = []
    monkeypatch.setattr(presets, "add_ids", lambda sm, line, ids: seen.append(("add", line, ids)) or {"output": "a"})
    monkeypatch.setattr(presets, "add_line", lambda sm, *a: seen.append(("new", *a)) or {"output": "n"})
    monkeypatch.setattr(presets, "generate", lambda: seen.append(("gen",)) or {"output": "g"})
    c, h = _client()
    assert c.post("/api/profiles/web/line_add", headers=h, json={"line": "L", "ids": [3]}).json() == {"output": "a"}
    assert c.post("/api/profiles/web/line_new", headers=h, json={
        "name": "Acme PLA", "vendor": "Acme", "ids": [3], "orca_parent": "", "bs_template": "Generic PLA"}).json() \
        == {"output": "n"}
    assert c.post("/api/profiles/web/generate", headers=h, json={}).json() == {"output": "g"}
    assert seen == [("add", "L", [3]), ("new", "Acme PLA", "Acme", [3], "", "Generic PLA"), ("gen",)]
    assert c.post("/api/profiles/web/line_add", headers=h, json={"line": "L", "ids": ["x"]}).status_code == 400
    assert c.post("/api/profiles/web/generate", json={}).status_code == 401


def test_web_tools_send_preset_writes_to_the_kit(kit):
    from filament_kit.web import mcp_tools

    class Kit:
        calls = []

        def post(self, path, body):
            self.calls.append((path, body))
            return {"output": "ok"}
    tools = mcp_tools.Tools(None, kit_api=Kit(), kit_writes=True)
    tools.add_filaments_to_line("L", [3])
    tools.add_line("Acme PLA", "Acme", [3], "", "Generic PLA")
    tools.generate()
    assert [p for p, _ in Kit.calls] == ["/api/profiles/web/line_add", "/api/profiles/web/line_new",
                                         "/api/profiles/web/generate"]


def test_the_web_app_builds_its_tools_with_kit_writes():
    src = (ROOT / "server/filament_kit/web/app.py").read_text(encoding="utf-8")
    assert "mcp_tools.Tools(sm, kit_api=kit_api, kit_writes=True)" in src


# ---------- what the web user is granted now ----------

@LINUX
def test_no_kit_folder_is_writable_by_the_web_user(kit, tmp_path):
    from filament_kit import acl
    if not acl.supported():
        pytest.skip("no xattrs")
    try:
        acl.grant(tmp_path, {54321: acl.R})
    except OSError:
        pytest.skip("no ACLs on this file system")
    st = kit / "state"
    for d in ("profiles", "failed", "library", "web"):
        (st / d).mkdir()
    token = kit / "etc" / "h2d_token"
    token.write_text("t\n", encoding="utf-8")
    cfg = config.load()
    cfg["slot_service"] = {"state_url": "http://h2d.example.com/state", "set_url": "http://h2d.example.com/set",
                           "token_file": str(token)}
    web_access.shared_files(os.getuid(), os.getgid(), chown=lambda *a: None)
    web_access.grant(54321, os.getuid(), cfg)
    for d in ("profiles", "library", "web"):
        assert acl.users_of(st / d)[54321] & acl.W == 0, d
    assert 54321 not in acl.users_of(st / "failed")
    assert acl.users_of(st / "profiles", acl.DEFAULT)[54321] & acl.W == 0
    assert acl.users_of(token) == {54321: acl.R}                     # the H2D slot token
    assert not (st / "reads.json").exists() or 54321 not in acl.users_of(st / "reads.json")
    assert acl.users_of(st / "inventory.lock") == {54321: acl.R}       # a lock is taken on a read-only fd


def test_the_web_writes_only_its_own_folder():
    assert web_access.RW_TREES == ()
    assert set(web_access.LOCK_FILES) == {"inventory.lock", "profiles/lines.lock", "profiles/live.lock",
                                          "profiles/state.lock", "profiles/build.lock"}
    unit = (ROOT / "install/systemd/filament-kit-web.service").read_text(encoding="utf-8")
    assert [ln for ln in unit.splitlines() if ln.startswith("ReadWritePaths=")] == [
        "ReadWritePaths=/var/lib/filament-kit-web"]


@LINUX
def test_a_lock_is_taken_on_a_file_the_process_may_only_read(kit):
    import fcntl
    f = kit / "state" / "ro.lock"
    f.write_text("", encoding="utf-8")
    os.chmod(f, 0o444)
    if os.access(f, os.W_OK):
        pytest.skip("running as root")
    with pairing.open_lock(f) as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


@pytest.mark.parametrize("err", [13, 1, 30])     # EACCES, EPERM, EROFS
def test_open_lock_falls_back_to_read_only_on_any_refused_write(kit, monkeypatch, err):
    f = kit / "state" / "ro.lock"
    f.write_text("", encoding="utf-8")
    real = os.open

    def opener(path, flags, *a):
        if flags & (os.O_WRONLY | os.O_RDWR):
            raise OSError(err, os.strerror(err), str(path))
        return real(path, flags, *a)
    monkeypatch.setattr(pairing.os, "open", opener)
    with pairing.open_lock(f) as fh:
        assert fh.mode == "r"


def test_open_lock_says_what_is_wrong_when_a_read_only_lock_is_missing(kit, monkeypatch):
    f = kit / "state" / "gone.lock"

    def opener(path, flags, *a):
        if flags & (os.O_WRONLY | os.O_RDWR):
            raise OSError(30, "Read-only file system", str(path))
        raise FileNotFoundError(2, "No such file or directory", str(path))
    monkeypatch.setattr(pairing.os, "open", opener)
    with pytest.raises(pairing.LockUnavailable) as e:
        pairing.open_lock(f)
    assert "gone.lock" in str(e.value) and "modules apply" in str(e.value)
    assert isinstance(e.value, OSError)


def test_web_grant_includes_the_slot_token_whenever_config_is_saved(kit, monkeypatch):
    seen = []
    monkeypatch.setattr(config, "grant_web_read", lambda p: seen.append(Path(p).name))
    token = kit / "etc" / "h2d_token"
    token.write_text("t\n", encoding="utf-8")
    cfg = config.load()
    cfg["slot_service"] = {"state_url": "x", "set_url": "y", "token_file": str(token)}
    config.save(cfg)
    assert "h2d_token" in seen


def test_unreadable_slot_token_says_how_to_fix(tmp_path):
    from filament_kit.web import slots
    with pytest.raises(slots.SlotError) as e:
        slots.service_set_slot({"set_url": "http://h2d.example.com/set", "token_file": str(tmp_path / "none")},
                               1, "1", True)
    assert "sudo filament-kit modules apply" in str(e.value)


# ---------- the writers never follow a planted link ----------

@LINUX
def test_open_lock_does_not_follow_a_link(kit, tmp_path):
    target = tmp_path / "printers.json"
    target.write_text("{}", encoding="utf-8")
    link = kit / "state" / "x.lock"
    link.symlink_to(target)
    with pytest.raises(OSError):
        pairing.open_lock(link)


@LINUX
def test_give_to_state_owner_does_not_follow_a_link(kit, monkeypatch):
    calls = []
    monkeypatch.setattr(pairing.os, "geteuid", lambda: 0)
    monkeypatch.setattr(pairing.os, "chown", lambda p, u, g, **kw: calls.append(kw))
    pairing.give_to_state_owner(kit / "state" / "anything")
    assert calls == [{"follow_symlinks": False}]


@LINUX
def test_write_atomic_sets_mode_and_owner_on_the_open_file(kit, monkeypatch):
    monkeypatch.setattr(pairing.os, "chmod", lambda *a, **k: pytest.fail("chmod by path"))
    f = kit / "state" / "x.json"
    pairing._write_atomic(f, b"{}", 0o640)
    assert f.read_bytes() == b"{}" and (f.stat().st_mode & 0o777) == 0o640


@LINUX
def test_keep_does_not_follow_a_planted_link(kit, monkeypatch, tmp_path):
    monkeypatch.setenv("FK_FAILED_DIR", str(tmp_path / "failed"))
    target = tmp_path / "printers.json"
    target.write_text("{}", encoding="utf-8")
    d = tmp_path / "failed" / "r1"
    d.mkdir(parents=True)
    (d / "meta.json").symlink_to(target)
    with pytest.raises(OSError):
        intake._keep("r1", [b"jpeg"], "hint", None)
    assert target.read_text(encoding="utf-8") == "{}"


# ---------- minors ----------

def test_grant_web_read_warns_with_the_file_name(kit, monkeypatch, caplog):
    from filament_kit import acl
    monkeypatch.setattr(config.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(config, "uid_of", lambda u: 54321)
    monkeypatch.setattr(acl, "supported", lambda: True)

    def boom(*a, **k):
        raise OSError(95, "Operation not supported")
    monkeypatch.setattr(acl, "grant", boom)
    with caplog.at_level(logging.WARNING):
        config.grant_web_read(kit / "etc" / "config.json")
    assert "config.json" in caplog.text and "filament-kit-web" in caplog.text


def test_read_cap_is_replaced_atomically_again(kit):
    f = kit / "state" / "reads.json"
    cap = intake.ReadCap(f, 5)
    cap.take()
    before = f.stat().st_ino
    cap.take()
    assert json.loads(f.read_text(encoding="utf-8")) and (sys.platform == "win32" or f.stat().st_ino != before)
    assert not list(f.parent.glob("reads.json.*tmp*"))


def test_backup_keeps_the_acls():
    text = (ROOT / "install/backup.sh").read_text(encoding="utf-8")
    assert "--acls" in text and "--xattrs" in text
