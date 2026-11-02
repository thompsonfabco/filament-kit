import io
import json
import socket
import sys
import urllib.parse

import pytest

import studio_fixture
from fksync import __main__ as cli
from fksync import store, studio
from tls_helper import TlsServer, make_cert

LINK_TOKEN = "LinkToken-Secret-0123456789abcdef"
CODE_TOKEN = "CodeToken-Secret-fedcba9876543210"


def _respond(m, p, b):
    if p == "/api/info":
        return 200, "application/json", {"name": "fk-server", "version": "0.2.0", "api": 1}
    if p == "/api/pair":
        if json.loads(b).get("code") == "123456":
            return 200, "application/json", {"token": CODE_TOKEN}
        return 401, "application/json", {"error": "unauthorized", "message": "invalid, expired or locked pairing code"}
    if p == "/api/sync/state":
        return 200, "application/json", {"owner": None, "you": "dev42", "user_id": None, "live_hash": None,
                                         "system_hash": None, "build": None, "last_attempt": None,
                                         "installed": None, "rebuild_requested": None}
    if p.startswith("/api/sync/live"):
        return 200, "application/json", {"live_hash": "x"}
    if p == "/api/sync/system":
        return 200, "application/json", {"system_hash": "y", "presets": 1}
    if p == "/api/sync/rebuild":
        return 202, "application/json", {"requested": True}
    return 404, "application/json", {"error": "not_found", "message": "no"}


@pytest.fixture(autouse=True)
def _studio_closed(monkeypatch):
    """The real tasklist would see this PC's own Bambu Studio; the CLI tests decide instead."""
    monkeypatch.setattr(studio, "running", lambda tasklist=None: False)


@pytest.fixture
def srv(tmp_path):
    cert, key, fp = make_cert(tmp_path / "cert")
    with TlsServer(cert, key, respond=_respond) as s:
        s.fp = fp
        yield s


@pytest.fixture
def paths(tmp_path):
    appdata, local = tmp_path / "appdata", tmp_path / "local"
    folders = studio_fixture.make(appdata, base={"Acme PLA": ({"name": "Acme PLA", "from": "User"},
                                                              {"setting_id": ""})})
    return appdata, local, folders


def _main(paths, *args, stdin=""):
    appdata, local, _ = paths
    old = sys.stdin
    sys.stdin = io.StringIO(stdin)
    try:
        return cli.main(["--appdata", str(appdata), "--localappdata", str(local), *args])
    finally:
        sys.stdin = old


def _dirs(paths):
    return store.AppDirs(paths[1] / "filament-kit-sync")


def _link(srv):
    q = urllib.parse.urlencode({"h": "127.0.0.1", "p": srv.port, "t": LINK_TOKEN, "fp": srv.fp,
                                "ip": ["127.0.0.2"]}, doseq=True)
    return f"fkit://pair?{q}"


def test_pair_link_then_run_never_shows_token(srv, paths, capsys):
    assert _main(paths, "pair", stdin=_link(srv) + "\n") == 0
    dirs = _dirs(paths)
    assert store.load_token(dirs) == LINK_TOKEN
    cfg = store.load_config(dirs)
    assert cfg["host"] == "127.0.0.1" and cfg["port"] == srv.port and cfg["fp"] == srv.fp
    assert cfg["ips"] == ["127.0.0.2"] and cfg["device"] == "dev42"
    assert LINK_TOKEN not in json.dumps(cfg)
    assert _main(paths, "run") == 0
    out = capsys.readouterr()
    assert "Paste the pairing link, or type the server address:" in out.out
    assert "uploaded" in out.out
    log = dirs.log_file.read_text(encoding="utf-8")
    assert "uploaded" in log
    for text in (out.out, out.err, log):
        assert LINK_TOKEN not in text
    auths = {r["auth"] for r in srv.requests if r["path"].startswith("/api/sync")}
    assert auths == {f"Bearer {LINK_TOKEN}"}


def test_pair_address_confirms_fingerprint_then_code(srv, paths, capsys):
    stdin = f"127.0.0.1:{srv.port}\ny\n123456\n"
    assert _main(paths, "pair", stdin=stdin) == 0
    out = capsys.readouterr().out
    grouped = " ".join(srv.fp[i:i + 4] for i in range(0, 64, 4))
    assert grouped in out
    assert "Does this match the fingerprint shown by 'sudo filament-kit pair'? [y/N]" in out
    assert "6-digit code:" in out
    dirs = _dirs(paths)
    assert store.load_token(dirs) == CODE_TOKEN
    assert store.load_config(dirs)["fp"] == srv.fp
    assert _main(paths, "run", "--quiet") == 0
    out2 = capsys.readouterr()
    assert out2.out == ""
    log = dirs.log_file.read_text(encoding="utf-8")
    for text in (out, out2.out, out2.err, log):
        assert CODE_TOKEN not in text
    assert [r for r in srv.requests if r["path"] == "/api/pair"][0]["auth"] is None


def test_pair_address_declined_saves_nothing(srv, paths, capsys):
    assert _main(paths, "pair", stdin=f"127.0.0.1:{srv.port}\nn\n") == 1
    dirs = _dirs(paths)
    assert store.load_token(dirs) is None and store.load_config(dirs) == {}
    assert not [r for r in srv.requests if r["path"] == "/api/pair"]


def test_pair_wrong_code(srv, paths, capsys):
    assert _main(paths, "pair", stdin=f"127.0.0.1:{srv.port}\ny\n000000\n") == 1
    assert store.load_token(_dirs(paths)) is None
    assert "invalid" in capsys.readouterr().out


def test_pair_bad_code_format_not_sent(srv, paths):
    assert _main(paths, "pair", stdin=f"127.0.0.1:{srv.port}\ny\n12ab\n") == 1
    assert not [r for r in srv.requests if r["path"] == "/api/pair"]


def test_run_not_paired_exits_1_and_logs(paths, capsys):
    assert _main(paths, "run") == 1
    assert "pair" in _dirs(paths).log_file.read_text(encoding="utf-8")


def test_run_offline_exits_1_and_logs(srv, paths):
    assert _main(paths, "pair", stdin=_link(srv) + "\n") == 0
    dirs = _dirs(paths)
    cfg = store.load_config(dirs)
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    cfg.update(host="127.0.0.1", ips=[], port=s.getsockname()[1])
    s.close()
    store.save_config(dirs, cfg)
    assert _main(paths, "run", "--quiet") == 1
    log = dirs.log_file.read_text(encoding="utf-8")
    assert "error" in log and LINK_TOKEN not in log


def test_run_already_running_exits_0(srv, paths):
    assert _main(paths, "pair", stdin=_link(srv) + "\n") == 0
    dirs = _dirs(paths)
    with store.single_instance(dirs):
        assert _main(paths, "run", "--quiet") == 0


def test_status_and_unpair(srv, paths, capsys):
    appdata, local, folders = paths
    assert _main(paths, "pair", stdin=_link(srv) + "\n") == 0
    assert _main(paths, "run", "--quiet") == 0
    dirs = _dirs(paths)
    (dirs.installed).mkdir(parents=True)
    (dirs.installed / "BUILD.json").write_text(json.dumps({"stamp": "20261101-090000"}))
    st = json.loads(dirs.state.read_text())
    st["stale"] = ["Old Preset A"]
    dirs.state.write_text(json.dumps(st))
    capsys.readouterr()
    assert _main(paths, "status") == 0
    out = capsys.readouterr().out
    assert f"127.0.0.1:{srv.port}" in out
    assert str(folders.user_filament) in out and "BambuStudioBeta" in out
    assert "uploaded" in out
    assert "20261101-090000" in out
    assert "Old Preset A" in out
    assert LINK_TOKEN not in out
    assert _main(paths, "unpair") == 0
    out = capsys.readouterr().out
    assert "dev42" in out
    assert store.load_token(dirs) is None and not dirs.config.exists()


def test_help_lists_commands_without_hidden_options(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    out = capsys.readouterr().out
    for word in ("pair", "run", "status", "unpair"):
        assert word in out
    assert "--appdata" not in out


def test_run_while_studio_open_exits_0(srv, paths, monkeypatch, capsys):
    assert _main(paths, "pair", stdin=_link(srv) + "\n") == 0
    monkeypatch.setattr(studio, "running", lambda tasklist=None: True)
    n = len(srv.requests)
    assert _main(paths, "run") == 0
    assert "studio_running" in capsys.readouterr().out
    assert len(srv.requests) == n
