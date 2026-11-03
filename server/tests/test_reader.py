"""web.reader: the bench NFC reader's API (printers, slots, scan, healthz, fw/*), the reader tokens (stored hashed,
XML) and their CLI, the queue-on-empty port, and the speech vocabulary of the hardware file's say= texts."""
from __future__ import annotations

import contextlib
import hashlib
import json
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from defusedxml import ElementTree as DET  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from filament_kit import cli, config, modules  # noqa: E402
from filament_kit.bridge import hardware  # noqa: E402
from filament_kit.web import app as web_app, auth, reader, slots  # noqa: E402

PUBLIC = "https://mcp.example.test/filament"
ORIGIN = "https://mcp.example.test"
HOME = ("192.168.1.20", 50000)
AWAY = ("203.0.113.9", 50000)
UID = "4:c7:96:11:9:22:89"
UID_OLD = "4:c7:96:11:9:22:8a"
UID_NEW = "4:c7:96:11:9:22:8b"

# The reader firmware's speech table (reader/lib/reader_core/src/speech.cpp, TABLE[]), copied here.
# KEEP IN SYNC with the firmware: a say= token missing there is spoken as a beep. Numbers 0-99 written as digits
# are spoken too (expandToken), so they are not listed.
FIRMWARE_VOCAB = frozenset("""
zero oh one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen
seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety
a b c d e f g h i j k l m n o p q r s t u v w x y z
external ext left right top bottom middle center front back set load ready connect fail power cycle printer
unit number plus light high low up down on off and error red green blue yellow black white gray grey
""".split())


def speakable(token: str) -> bool:
    t = token.lower()
    return t in FIRMWARE_VOCAB or (t.isdigit() and len(t) <= 2)


# ---------- speech vocabulary ----------

def test_every_say_token_in_the_hardware_file_is_in_the_firmware_vocabulary():
    xml = Path(hardware.__file__).with_name("bambu_hardware.xml").read_bytes()
    root = DET.fromstring(xml)
    bad = [(el.tag, el.get("code") or el.get("label") or el.get("key") or el.get("text"), tok)
           for el in root.iter() if el.get("say") is not None
           for tok in el.get("say").split() if not speakable(tok)]
    assert bad == []


def test_generic_and_label_say_tokens_are_speakable():
    hw = hardware.load()
    assert all(speakable(t) for t in hw.model("NOPE").say.split())
    for label in ("A1", "AA4", "HT-A", "HT-AB", "Ext", "Ext-L", "Ext-R"):
        assert all(speakable(t) for t in hw.say(label, "O1D")), label


# ---------- environment ----------

@pytest.fixture
def env(tmp_path, monkeypatch):
    for name in ("etc", "state", "opt"):
        (tmp_path / name).mkdir()
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    mods = {n: True for n in modules.MODES["server"]}
    mods["web"] = True
    config.save({"modules": mods, "web": {"public_url": PUBLIC, "lan": ["192.168.1.0/24"]}})
    return tmp_path


class FakeSM:
    def __init__(self, spools):
        self.spools = spools

    def get(self, path):
        assert path == "spool?allow_archived=true", path
        return self.spools


def spool(sid, uid, *, archived=False, name="PLA+ Grey", vendor="SUNLU"):
    return {"id": sid, "archived": archived, "extra": {"nfc_id": json.dumps(uid)},
            "filament": {"id": 100 + sid, "name": name, "vendor": {"name": vendor}}}


def slot(label, *, present=True, reading=False, kind="ams", typ="PLA", preset_id="", spool=None, say=None):
    return {"label": label, "say": say if say is not None else list(label.lower().replace("-", "")),
            "type": typ, "present": present, "reading": reading, "preset_id": preset_id, "spool": spool,
            "_kind": kind}


class FakeKit:
    """The kit server's API as the web process sees it (KitApi.get/post), one H2D 'SER1' + one offline P1S."""

    def __init__(self):
        self.lock = threading.Lock()
        self.loads: list[tuple[str, dict]] = []
        self.state = {"SER1": "connected", "SER2": "offline"}
        self.slots = {"SER1": [slot("A1", spool={"id": 7, "name": "SUNLU PLA+ Grey", "material": "PLA"}),
                               slot("A2", present=False, typ=""),
                               slot("HT-A", kind="ams_ht", present=None, say=["h", "t", "a"]),
                               slot("Ext-L", kind="ext", present=None, typ="", say=["external", "left"]),
                               slot("Ext-R", kind="ext", present=None, typ="", say=["external", "right"])],
                      "SER2": [slot("A1")]}
        self.load_error: slots.SlotError | None = None
        self.load_delay = 0.0
        self.preset = {"filament_id": "PFUS1", "name": "SUNLU PLA+ @H2D", "filament_type": "PLA"}

    def get(self, path):
        if path == "/api/printers":
            return {"printers": [
                {"id": "SER1", "name": "H2D", "model": "O1D", "configured": True, "state": self.state["SER1"]},
                {"id": "SER2", "name": "Garage", "model": "C12", "configured": True, "state": self.state["SER2"]},
                {"id": "SER3", "name": "New", "model": "N7", "configured": False, "state": "not_configured"}]}
        sid = path.rsplit("/", 1)[1]
        if sid not in self.slots:
            raise slots.SlotError("no such printer", code="not_found", http=404)
        units = {}
        for s in self.slots[sid]:
            k = s["_kind"]
            units.setdefault((k, s["label"] if k != "ams" else s["label"][0]), []).append(
                {k2: v for k2, v in s.items() if k2 != "_kind"})
        return {"printer": {"id": sid, "name": "H2D", "state": self.state[sid]},
                "status": {"gcode_state": "IDLE", "ams": [{"unit": i, "label": key[1], "kind": key[0], "slots": sl}
                                                          for i, (key, sl) in enumerate(units.items())]}}

    def post(self, path, body):
        with self.lock:
            self.loads.append((path, body))
        if self.load_delay:
            time.sleep(self.load_delay)
        if self.load_error is not None:
            raise self.load_error
        return {"preset": dict(self.preset), "dry_run": body["dry_run"], "confirmed": None if body["dry_run"] else True,
                "spool": {"id": body["spool_id"]}}


@pytest.fixture
def kit():
    return FakeKit()


@pytest.fixture
def sm():
    return FakeSM([spool(7, UID), spool(8, UID_OLD, archived=True)])


@pytest.fixture
def token(env):
    return reader.TokenStore().issue("bench")[1]


@pytest.fixture
def queue(kit):
    """The app's queue, injected (no worker thread: the queue tests tick it themselves)."""
    return reader.LoadQueue(lambda: kit, start_thread=False)


@pytest.fixture
def app(env, sm, kit, queue):
    return web_app.build_app(sm=sm, kit_api=kit, store=auth.Store(web_app.oauth_file()), lockout=auth.Lockout(),
                             reader_queue=queue)


@contextlib.contextmanager
def client(app, who=HOME):
    """A client without the app's lifespan (the MCP session manager runs once per app; the reader routes need
    none), so one test can open several."""
    c = TestClient(app, base_url=ORIGIN, client=who)
    try:
        yield c
    finally:
        c.close()


# ---------- tokens ----------

def test_tokens_are_stored_hashed_in_xml(env):
    ts = reader.TokenStore()
    tid, tok = ts.issue("bench")
    _, tok2 = ts.issue("spare")
    f = env / "state" / "web" / "reader_tokens"
    text = f.read_text(encoding="utf-8")
    assert tok not in text and tok2 not in text
    assert hashlib.sha256(tok.encode()).hexdigest() in text
    root = DET.fromstring(text.encode())
    assert root.tag == "reader-tokens" and len(root.findall("token")) == 2
    assert len(tok) >= 32 and tok.replace("-", "").replace("_", "").isalnum()
    fresh = reader.TokenStore()
    assert fresh.check(tok) and fresh.check(tok2) and not fresh.check("nope") and not fresh.check("")
    assert [t["name"] for t in fresh.list()] == ["bench", "spare"]
    assert fresh.revoke(tid) and not fresh.revoke(tid)
    assert not fresh.check(tok) and fresh.check(tok2)
    assert fresh.revoke("spare") and fresh.list() == []


def test_a_broken_token_file_accepts_nothing(env):
    ts = reader.TokenStore()
    tok = ts.issue("bench")[1]
    f = env / "state" / "web" / "reader_tokens"
    f.write_text("<reader-tokens><token id='x' sha256='zz'/></reader-tokens>", encoding="utf-8")
    ts = reader.TokenStore()
    assert not ts.check(tok) and ts.errors
    with pytest.raises(reader.TokenFileError):
        reader.TokenStore().issue("other")             # never clobbers a file it cannot read


def test_cli_reader_token_list_revoke(env, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_is_root", lambda: False)
    assert cli.main(["reader", "token"]) == 1
    assert "root" in capsys.readouterr().err
    monkeypatch.setattr(cli, "_is_root", lambda: True)
    assert cli.main(["reader", "token", "--name", "bench"]) == 0
    out = capsys.readouterr().out
    tok = next(w for w in out.split() if len(w) >= 32)
    assert reader.TokenStore().check(tok) and "secrets.h" in out
    assert cli.main(["reader", "tokens"]) == 0
    listed = capsys.readouterr().out
    assert "bench" in listed and tok not in listed
    tid = reader.TokenStore().list()[0]["id"]
    assert cli.main(["reader", "revoke", tid]) == 0
    assert not reader.TokenStore().check(tok)
    assert cli.main(["reader", "revoke", tid]) == 1


# ---------- routes: auth, healthz, fw ----------

def test_reader_routes_need_token_and_lan(app, token):
    with client(app) as c:
        assert c.get("/reader/printers").status_code == 401
        r = c.get("/reader/printers", headers={"X-Auth-Token": "wrong"})
        assert r.status_code == 401 and r.json()["status"] == "error"
        assert c.post("/reader/scan", json={}).json()["status"] == "error"
        assert c.get("/reader/printers", headers={"X-Auth-Token": token}).status_code == 200
    with client(app, AWAY) as c:
        assert c.get("/reader/printers", headers={"X-Auth-Token": token}).status_code == 403
        assert c.get("/reader/healthz").status_code == 403


def test_healthz_and_firmware_files(app, token, env):
    fw = env / "state" / "reader-fw"
    fw.mkdir()
    (fw / "manifest.json").write_text('{"build": 7}', encoding="utf-8")
    (fw / "firmware.bin").write_bytes(b"\xe9" + b"\0" * 100)
    (fw / "secret.txt").write_text("x", encoding="utf-8")
    with client(app) as c:
        assert c.get("/reader/healthz").status_code == 401          # I1: a revoked token fails healthz too
        assert c.get("/reader/healthz", headers={"X-Auth-Token": token}).status_code == 200
        assert c.get("/reader/fw/manifest.json").status_code == 401
        h = {"X-Auth-Token": token}
        r = c.get("/reader/fw/manifest.json", headers=h)
        assert r.status_code == 200 and r.json() == {"build": 7}
        r = c.get("/reader/fw/firmware.bin", headers=h)
        assert r.status_code == 200 and r.content[:1] == b"\xe9" and len(r.content) == 101
        assert r.headers["content-type"] == "application/octet-stream"
        assert c.get("/reader/fw/secret.txt", headers=h).status_code == 404
        assert c.get("/reader/fw/..%2Fweb%2Freader_tokens", headers=h).status_code == 404
    (fw / "manifest.json").unlink()
    with client(app) as c:
        assert c.get("/reader/fw/manifest.json", headers={"X-Auth-Token": token}).status_code == 404


# ---------- routes: lists ----------

def test_printer_list(app, token):
    with client(app) as c:
        r = c.get("/reader/printers", headers={"X-Auth-Token": token})
    assert r.status_code == 200
    ps = r.json()
    assert [p["id"] for p in ps] == ["SER1", "SER2"]             # configured printers only, ids as strings
    assert ps[0] == {"id": "SER1", "name": "H2D", "say": ["h", "two", "d"]}
    assert all(speakable(t) for p in ps for t in p["say"])


def _strings(v):
    if isinstance(v, str):
        yield v
    elif isinstance(v, dict):
        for x in v.values():
            yield from _strings(x)
    elif isinstance(v, list):
        for x in v:
            yield from _strings(x)


def test_every_string_fits_the_firmware(app, token, kit, sm):
    """The firmware cuts each string at 40 bytes and skips printer ids over 64 bytes: names and texts are cut here,
    a label or id too long to send back is left out, and say is split into tokens."""
    long_id = "S" * 65
    kit.slots[long_id] = [slot("A1")]
    kit.state[long_id] = "connected"
    real_get = kit.get

    def get(path):
        r = real_get(path)
        if path == "/api/printers":
            r["printers"][0]["name"] = "Ünïcode printer with a really long name, longer than forty bytes"
            r["printers"].append({"id": long_id, "name": "x", "model": "O1D", "configured": True,
                                  "state": "connected"})
        return r
    kit.get = get
    kit.slots["SER1"][0].update(type="PLA-CF " * 10, say=["external left " * 6, "a"],
                                spool={"id": 7, "name": "Very long vendor name " * 4})
    kit.slots["SER1"].append(slot("X" * 41))
    sm.spools[0]["filament"]["name"] = "Super long filament name " * 4
    h = {"X-Auth-Token": token}
    with client(app) as c:
        ps = c.get("/reader/printers", headers=h).json()
        sl = c.get("/reader/printers/SER1/slots", headers=h).json()
        sc = scan(c, token).json()
    assert [p["id"] for p in ps] == ["SER1", "SER2"]
    assert all(len(p["id"].encode()) <= 64 for p in ps)
    assert "X" * 41 not in [s["label"] for s in sl]
    for body in (ps, sl, sc):
        for s in _strings(body):
            assert len(s.encode("utf-8")) <= 40, s
    assert sl[0]["say"][:3] == ["external", "left", "external"]


def test_slot_list(app, token):
    with client(app) as c:
        r = c.get("/reader/printers/SER1/slots", headers={"X-Auth-Token": token})
        assert r.status_code == 200
        sl = r.json()
        missing = c.get("/reader/printers/NOPE/slots", headers={"X-Auth-Token": token})
    assert [s["label"] for s in sl] == ["A1", "A2", "HT-A", "Ext-L", "Ext-R"]
    a1, a2, ht, extl = sl[0], sl[1], sl[2], sl[3]
    assert a1 == {"label": "A1", "say": ["a", "1"], "kind": "ams", "present": True, "type": "PLA",
                  "spool": {"id": 7, "name": "SUNLU PLA+ Grey"}}
    assert a2["present"] is False and a2["spool"] is None
    assert ht["kind"] == "ams_ht" and ht["present"] is None
    assert extl["kind"] == "external" and extl["say"] == ["external", "left"]
    assert missing.status_code == 404 and missing.json()["status"] == "error"


def test_slot_labels_are_unique_within_what_the_firmware_keeps(app, token, kit):
    """The firmware keeps 40 bytes of a label and sends it back: a printer never gets two slots it cannot tell apart
    (the same label twice, also in another case, as the kit matches labels whatever their case), and never a label
    over 40 bytes (it would come back cut)."""
    long1, long2 = "Ü" * 20 + "x", "Ü" * 20 + "y"        # 41 bytes, equal in the first 40
    kit.slots["SER1"] += [slot("A1", kind="generic"), slot("a1", kind="ams_ht"), slot(long1, kind="generic"),
                          slot(long2, kind="generic"), slot("Ü" * 20, kind="ams_lite")]
    with client(app) as c:
        sl = c.get("/reader/printers/SER1/slots", headers={"X-Auth-Token": token}).json()
    labels = [s["label"] for s in sl if "label" in s]
    assert labels == ["A1", "A2", "HT-A", "Ext-L", "Ext-R", "Ü" * 20]
    cut = [lab.encode("utf-8")[:40].upper() for lab in labels]
    assert len(set(cut)) == len(cut)


def test_reader_slots_and_kit_label_agree_on_a_case_or_space_collision():
    """M3: the reader lists the first of "A1" / "a1" / " a1 "; a scan naming it must reach that same slot."""
    rows = [{"label": "A1"}, {"label": "a1"}, {"label": " a1 "}, {"label": "A2"}]
    listed = [r["label"] for r in reader.reader_slots(rows)]
    assert listed == ["A1", "A2"]
    labels = [r["label"] for r in rows]
    assert slots.kit_label("A1", labels) == "A1"
    assert slots.kit_label(" A1 ", labels) == "A1"
    assert slots.kit_label("a1", labels) == "a1"           # an exact match wins
    assert slots.kit_label("A1", ["a1", "A1"]) == "A1"
    assert slots.kit_label("a1", ["X", "A1", "a1 "]) == "A1"   # no exact match: the first of the collision


# ---------- routes: scan ----------

def scan(c, token, **body):
    req = {"uid": UID, "printer": "SER1", "slot": "A1", "dry_run": False, **body}
    return c.post("/reader/scan", json=req, headers={"X-Auth-Token": token})


def test_scan_sets_a_loaded_slot(app, token, kit):
    with client(app) as c:
        r = scan(c, token)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "set" and body["filament"] == "SUNLU PLA+ Grey" and "SUNLU PLA+ @H2D" in body["message"]
    assert kit.loads == [("/api/printers/SER1/slots/A1/load", {"spool_id": 7, "dry_run": False})]


def test_scan_dry_run_sends_nothing(app, token, kit, queue):
    with client(app) as c:
        body = scan(c, token, dry_run=True).json()
        q = scan(c, token, slot="A2", dry_run=True).json()
    assert body["status"] == "set" and body["dry_run"] is True
    assert q["status"] == "queued" and q["dry_run"] is True
    assert all(b["dry_run"] for _, b in kit.loads)
    assert queue.jobs() == {}


@pytest.mark.parametrize("uid, status", [("4:0:0:0:0:0:1", "unknown_tag"), (UID_OLD, "archived_spool")])
def test_scan_refusals(app, token, kit, uid, status):
    with client(app) as c:
        r = scan(c, token, uid=uid)
    assert r.status_code == 200 and r.json()["status"] == status and r.json()["message"]
    assert kit.loads == []


@pytest.mark.parametrize("code, http, status", [("no_preset", 409, "no_preset"),
                                                 ("printer_offline", 409, "offline"),
                                                 ("printer_busy", 409, "error"),
                                                 ("not_found", 404, "error"),
                                                 ("unreachable", None, "error")])
def test_scan_maps_kit_errors(app, token, kit, code, http, status):
    kit.load_error = slots.SlotError(f"kit says {code}", code=code, http=http)
    with client(app) as c:
        r = scan(c, token)
    assert r.json()["status"] == status and f"kit says {code}" in r.json()["message"]
    assert r.status_code != 200 or status in ("no_preset", "offline")


def test_scan_offline_printer_and_bad_requests(app, token, kit):
    with client(app) as c:
        off = scan(c, token, printer="SER2")
        assert off.json()["status"] == "offline"
        assert scan(c, token, slot="Z9").json()["status"] == "error"
        assert scan(c, token, printer="NOPE").json()["status"] == "error"
        bad = scan(c, token, uid="xyz")
        assert bad.status_code == 400 and bad.json()["status"] == "error"
        assert c.post("/reader/scan", content=b"{", headers={"X-Auth-Token": token}).status_code == 400
        assert scan(c, token, printer=7).json()["status"] == "error"     # a number is read as the string "7"
    assert kit.loads == []


def test_scan_answers_before_a_slow_confirmation(app, token, kit, monkeypatch):
    monkeypatch.setattr(reader, "SCAN_WAIT", 0.2)
    kit.load_delay = 1.0
    t0 = time.monotonic()
    with client(app) as c:
        body = scan(c, token).json()
    assert time.monotonic() - t0 < 0.9
    assert body["status"] == "set" and "SUNLU PLA+ Grey" == body["filament"]


def test_scan_on_an_empty_slot_is_queued(app, token, kit, queue):
    with client(app) as c:
        r = scan(c, token, slot="A2")
    body = r.json()
    assert r.status_code == 200 and body["status"] == "queued" and "A2" in body["message"]
    assert kit.loads == [("/api/printers/SER1/slots/A2/load", {"spool_id": 7, "dry_run": True})]   # preset check
    assert set(queue.jobs()) == {("SER1", "A2")}
    kit.slots["SER1"][1]["present"] = True        # a direct set to that slot replaces the queued tap
    with client(app) as c:
        assert scan(c, token, slot="A2").json()["status"] == "set"
    assert queue.jobs() == {}


def test_scan_on_an_empty_slot_without_preset_is_refused(app, token, kit, queue):
    kit.load_error = slots.SlotError("no preset of yours", code="no_preset", http=409)
    with client(app) as c:
        assert scan(c, token, slot="A2").json()["status"] == "no_preset"
    assert queue.jobs() == {}


# ---------- queue ----------

class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def new_queue(kit):
    clock = Clock()
    return reader.LoadQueue(lambda: kit, clock=clock, start_thread=False), clock


def test_queue_sends_after_settle_and_drops_once_verified(kit):
    q, clock = new_queue(kit)
    a2 = kit.slots["SER1"][1]
    q.add("SER1", "A2", 7)
    q.tick()
    assert kit.loads == []                              # still empty
    a2.update(present=True, reading=True)
    q.tick()
    assert kit.loads == []                              # being read
    a2["reading"] = False
    q.tick()                                            # just seen: settle first
    clock.t += 2
    q.tick()
    assert kit.loads == []
    clock.t += 1.5
    q.tick()
    assert kit.loads == [("/api/printers/SER1/slots/A2/load", {"spool_id": 7, "dry_run": False})]
    clock.t += 2
    q.tick()
    assert len(kit.loads) == 1                          # verify waits 4 s
    a2.update(type="PLA", preset_id="PFUS1")
    clock.t += 3
    q.tick()
    assert q.jobs() == {} and len(kit.loads) == 1


def test_queue_gives_up_after_three_tries_and_expires(kit):
    q, clock = new_queue(kit)
    a2 = kit.slots["SER1"][1]
    q.add("SER1", "A2", 7)
    a2.update(present=True, reading=False, type="PLA", preset_id="GFL99")   # the AMS keeps wiping it
    q.tick()
    for _ in range(4):
        clock.t += 5
        q.tick()
    assert len(kit.loads) == 3 and q.jobs() == {}
    q.add("SER1", "A1", 7)
    kit.slots["SER1"][0]["present"] = False
    clock.t += reader.QUEUE_TTL + 1
    q.tick()
    assert q.jobs() == {}


def test_queue_waits_while_the_state_is_unknown_and_drops_on_no_preset(kit):
    q, clock = new_queue(kit)
    q.add("SER2", "A1", 7)                              # the printer is offline: no state, keep waiting
    q.tick()
    clock.t += 10
    q.tick()
    assert set(q.jobs()) == {("SER2", "A1")} and kit.loads == []
    q.drop("SER2", "A1")
    q.add("SER1", "A1", 7)
    kit.load_error = slots.SlotError("no preset", code="no_preset", http=409)
    q.tick()
    clock.t += 5
    q.tick()
    assert q.jobs() == {}


def test_status_slots_carry_the_preset_id_the_queue_checks():
    from filament_kit.bridge import status
    rep = {"ams": {"ams": [{"id": "0", "tray": [{"id": "0", "tray_type": "PLA", "tray_info_idx": "PFUS1"},
                                                {"id": "1"}]}]}}
    sl = status.summarize(rep, [], model="O1D")["ams"][0]["slots"]
    assert sl[0]["preset_id"] == "PFUS1" and sl[1]["preset_id"] == ""


# ---------- fix round 1 ----------

def test_queue_drops_a_final_refusal_and_waits_quietly_on_a_passing_one(kit, caplog):
    import logging
    q, clock = new_queue(kit)
    q.add("SER1", "A1", 7)
    kit.load_error = slots.SlotError("the printer is busy", code="printer_busy", http=409)
    q.tick()                                            # seen
    with caplog.at_level(logging.WARNING, logger="filament_kit"):
        for _ in range(6):
            clock.t += 5
            q.tick()
    assert len(kit.loads) == 3 and set(q.jobs()) == {("SER1", "A1")}       # backed off: a send every 10 s
    assert q.jobs()[("SER1", "A1")].tries == 0                 # a passing refusal is not a try
    assert sum("printer_busy" in r.getMessage() for r in caplog.records) == 1   # logged once, not every tick
    kit.load_error = slots.SlotError("unreachable", code="unreachable")
    with caplog.at_level(logging.WARNING, logger="filament_kit"):
        clock.t += 5
        q.tick()
    assert sum("unreachable" in r.getMessage() for r in caplog.records) == 1    # a new reason is logged
    kit.load_error = slots.SlotError("turn on Developer Mode", code="needs_developer_mode", http=409)
    clock.t += reader.WAIT_POLL
    q.tick()
    assert q.jobs() == {}


@pytest.mark.parametrize("code", ["write_refused", "needs_developer_mode", "no_preset", "not_found"])
def test_queue_final_refusals_drop_the_job(kit, code):
    q, clock = new_queue(kit)
    q.add("SER1", "A1", 7)
    kit.load_error = slots.SlotError(code, code=code, http=409)
    q.tick()
    clock.t += 5
    q.tick()
    assert q.jobs() == {} and len(kit.loads) == 1


def test_scan_reply_deadline_counts_from_the_start(app, token, kit, sm, monkeypatch):
    """M1: SCAN_WAIT is a deadline from the start of the scan: slow lookups shorten the wait for the load."""
    monkeypatch.setattr(reader, "SCAN_WAIT", 0.6)
    monkeypatch.setattr(reader, "MIN_WAIT", 0.05)
    slow_get = sm.get

    def get(path):
        time.sleep(0.5)
        return slow_get(path)
    sm.get = get
    kit.load_delay = 2.0
    t0 = time.monotonic()
    with client(app) as c:
        body = scan(c, token).json()
    assert time.monotonic() - t0 < 1.0 and body["status"] == "set" and "sent" in body["message"]


def test_unconfirmed_comes_first_in_the_message(app, token, kit):
    """M2: the 40-byte cut must not drop "(not confirmed)"."""
    kit.preset["name"] = "A very long preset name @Bambu Lab H2D 0.4 nozzle"
    real = kit.post

    def post(path, body):
        return {**real(path, body), "confirmed": False}
    kit.post = post
    with client(app) as c:
        body = scan(c, token).json()
    assert body["status"] == "set" and body["message"].startswith("(not confirmed) A1")


def test_token_ids_are_never_reused(env):
    """M9: ids come from the root's next-id, so a revoked id is not handed out again."""
    ts = reader.TokenStore()
    assert ts.issue("a")[0] == "r1" and ts.issue("b")[0] == "r2"
    assert ts.revoke("r2")
    assert ts.issue("c")[0] == "r3"
    root = DET.fromstring((env / "state" / "web" / "reader_tokens").read_bytes())
    assert root.get("next-id") == "4"


def test_long_slot_lists_are_cut_under_16_kb(app, token, kit):
    """M12: at most 128 slots and 16 KB of JSON; a last entry without a label says how many are left out."""
    kit.slots["SER1"] = [slot(f"{reader.slots.letters(i // 4)}{i % 4 + 1}", typ="PLA-CF-LONG-TYPE-NAME",
                              spool={"id": i, "name": "A rather long spool name, cut at forty"})
                         for i in range(200)]
    with client(app) as c:
        r = c.get("/reader/printers/SER1/slots", headers={"X-Auth-Token": token})
    assert r.status_code == 200 and len(r.content) <= 16 * 1024
    rows = r.json()
    labelled = [x for x in rows if "label" in x]
    assert len(labelled) <= 128 and "label" not in rows[-1]
    assert rows[-1]["note"] == f"{200 - len(labelled)} more slots not listed"
    assert reader.cap_slots([{"label": "A1"}]) == [{"label": "A1"}]


def test_reader_cli_without_web_packages(env, monkeypatch, capsys):
    """M13: a missing [web] extra gives an install hint, not a traceback."""
    import sys
    monkeypatch.delattr(sys.modules["filament_kit.web"], "reader", raising=False)
    monkeypatch.setitem(sys.modules, "filament_kit.web.reader", None)
    assert cli.main(["reader", "tokens"]) == 1
    assert "filament-kit[web]" in capsys.readouterr().err


def test_slot_service_printer_slots_says_it_ignores_printer(env, monkeypatch):
    """M11"""
    from filament_kit.web import mcp_tools
    monkeypatch.setattr(slots, "service_slots", lambda svc, sm: {"slots": []})
    cfg = config.load()
    cfg["slot_service"] = {"state_url": "http://x/api/state", "set_url": "http://x/set-slot", "token_file": "t"}
    config.save(cfg)
    t = mcp_tools.Tools(None)
    assert "ignored" in t.printer_slots("H2D")["printer_note"]
    assert "printer_note" not in t.printer_slots()


# ---------- final review M4, M5 ----------

def test_a_hash_label_is_quoted_in_the_load_url(app, token, kit, queue):
    """layout's clash suffix ("#<id>") must not become a URL fragment (the load would hit the wrong slot)."""
    kit.slots["SER1"].append(slot("A1#5", say=["a", "one"]))
    with client(app) as c:
        assert scan(c, token, slot="A1#5").json()["status"] == "set"
    assert kit.loads[-1][0] == "/api/printers/SER1/slots/A1%235/load"
    q, clock = new_queue(kit)
    q.add("SER1", "A1#5", 7)
    q.tick()
    clock.t += 5
    q.tick()
    assert kit.loads[-1] == ("/api/printers/SER1/slots/A1%235/load", {"spool_id": 7, "dry_run": False})


def test_a_queued_tap_dropped_before_its_send_is_never_sent(kit):
    """A direct set drops the queued tap; if the queue thread already read the slot, it must not send the older
    spool afterwards (final review M5)."""
    q, clock = new_queue(kit)
    q.add("SER1", "A1", 8)
    q.tick()                                            # seen
    clock.t += 5
    real_get = kit.get

    def get(path):                                      # the direct set lands while the queue reads the slot
        q.drop("SER1", "A1")
        return real_get(path)
    kit.get = get
    q.tick()
    assert kit.loads == [] and q.jobs() == {}


def test_drop_waits_for_a_send_in_progress(kit):
    """A send already on the wire finishes before drop returns, so the caller's newer set always lands last."""
    q, clock = new_queue(kit)
    q.add("SER1", "A1", 8)
    q.tick()
    clock.t += 5
    started, release = threading.Event(), threading.Event()
    real_post = kit.post

    def post(path, body):
        started.set()
        release.wait(5)
        return real_post(path, body)
    kit.post = post
    t = threading.Thread(target=q.tick)
    t.start()
    assert started.wait(5)
    dropped = threading.Event()
    d = threading.Thread(target=lambda: (q.drop("SER1", "A1"), dropped.set()))
    d.start()
    assert not dropped.wait(0.3)                        # held while the old send is in flight
    release.set()
    t.join(5)
    d.join(5)
    assert dropped.is_set() and q.jobs() == {}
    assert [b["spool_id"] for _, b in kit.loads] == [8]
