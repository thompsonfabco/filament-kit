"""bridge.klipper.moonraker: the HTTP client and the websocket subscriber, against FakeMoonraker."""
import http.server
import json
import threading
import time

import pytest

from filament_kit.bridge.klipper import moonraker as mr


def _client(fake, **kw):
    return mr.Moonraker(fake.host, fake.port, **kw)


def wait_for(pred, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


def test_info_objects_and_query(moonraker):
    c = _client(moonraker)
    assert c.info()["state"] == "ready"
    assert "print_stats" in c.objects()
    st = c.query({"print_stats": ["state"], "toolhead": None, "nope": None})
    assert st == {"print_stats": {"state": "standby"}, "toolhead": {"extruder": "extruder"}}


def test_gcode_ok_and_spool(moonraker):
    c = _client(moonraker)
    c.gcode("SET_ACTIVE_SPOOL ID=7")
    assert moonraker.gcode_log == ["SET_ACTIVE_SPOOL ID=7"]
    assert c.spool_id() == 7


def test_gcode_error_message(moonraker):
    moonraker.gcode_errors["FOO"] = "Unknown command:\"FOO\""
    with pytest.raises(mr.GcodeError) as e:
        _client(moonraker).gcode("FOO")
    assert "Unknown command" in str(e.value)


def test_unauthorized(moonraker):
    moonraker.api_key = "s3cret"
    with pytest.raises(mr.Unauthorized):
        _client(moonraker).info()


def test_api_key_header_sent(moonraker):
    moonraker.api_key = "s3cret"
    assert _client(moonraker, api_key="s3cret").info()["state"] == "ready"


def test_offline():
    with pytest.raises(mr.Offline):
        mr.Moonraker("127.0.0.1", 9, timeout=0.5).info()


def test_print_actions_history_db_webcams(moonraker):
    c = _client(moonraker)
    c.print_action("pause")
    assert moonraker.actions == ["pause"]
    with pytest.raises(ValueError):
        c.print_action("explode")
    moonraker.history = [{"job_id": "2"}, {"job_id": "1"}]
    assert c.history_last() == {"job_id": "2"}
    assert c.db_get("lane_data") is None
    c.db_post("lane_data", "lane0", {"lane": "0"})
    assert c.db_get("lane_data") == {"lane0": {"lane": "0"}}
    assert c.db_namespaces() == ["lane_data"]
    moonraker.webcams = [{"name": "cam", "enabled": True, "stream_url": "/webcam/?action=stream"}]
    assert c.webcams()[0]["name"] == "cam"
    assert c.server_config()["spoolman"]["server"].endswith(":7912")
    assert c.spoolman_status()["spoolman_connected"] is True


def test_subscriber_gets_status_events_and_reconnects(moonraker):
    got, events = [], []
    sub = mr.Subscriber(_client(moonraker), {"print_stats": None}, got.append,
                        lambda name, params: events.append(name), backoff=(0.1, 0.5))
    sub.start()
    try:
        assert wait_for(lambda: got and got[0] == {"print_stats": {"state": "standby", "filename": "", "info": {}}})
        assert wait_for(lambda: moonraker._subs)
        moonraker.push({"print_stats": {"state": "printing"}})
        assert wait_for(lambda: {"print_stats": {"state": "printing"}} in got)
        moonraker.set_spool(5)
        assert wait_for(lambda: "notify_active_spool_set" in events)
        n = len(got)
        moonraker.drop()
        assert wait_for(lambda: len(got) > n, 5)          # a fresh snapshot after the reconnect
        assert sub.connected
    finally:
        sub.stop()
    assert not sub.connected


def test_subscriber_resubscribes_on_klippy_ready(moonraker):
    got = []
    sub = mr.Subscriber(_client(moonraker), {"print_stats": None}, got.append, lambda *a: None, backoff=(0.1, 0.5))
    sub.start()
    try:
        assert wait_for(lambda: len(got) == 1)
        moonraker.event("notify_klippy_ready")
        assert wait_for(lambda: len(got) == 2)
    finally:
        sub.stop()


def _capture_tool():
    import importlib.util
    import pathlib
    spec = importlib.util.spec_from_file_location(
        "capture_klipper", pathlib.Path(__file__).parents[2] / "tools" / "capture_klipper.py")
    cap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cap)
    return cap


def test_capture_strips_secrets(moonraker, tmp_path):
    cap = _capture_tool()
    moonraker.server_config = {"spoolman": {"server": "http://x"}, "authorization": {"api_key": "abc"},
                               "notifier": {"token": "t"}}
    moonraker.history = [{"job_id": "1", "filename": "a.gcode"}]
    assert cap.main(["--host", moonraker.host, "--port", str(moonraker.port), "--out", str(tmp_path)]) == 0
    names = sorted(p.name for p in tmp_path.iterdir())
    for want in ("objects.json", "info.json", "server_info.json", "status.json", "webcams.json", "history.json",
                 "spoolman_status.json", "db_namespaces.json", "server_config.json"):
        assert want in names
    blob = "".join(p.read_text() for p in tmp_path.iterdir())
    assert "abc" not in blob and '"t"' not in blob
    assert json.loads((tmp_path / "status.json").read_text())["print_stats"]["state"] == "standby"


# ---------- redirects are refused: the API key must never follow one, to the same host or another ----------

class _Redirects:
    """A server that answers everything but /elsewhere with a redirect to `location`; `hits` holds the X-Api-Key of
    each request that reached /elsewhere, `seen` counts the redirects it gave."""

    def __init__(self, code=302, location="/elsewhere"):
        rec = self
        self.hits, self.seen = [], 0

        class H(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"       # websockets refuses an HTTP/1.0 answer before it looks at a redirect

            def _go(self):
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                if self.path == "/elsewhere":
                    rec.hits.append(self.headers.get("X-Api-Key"))
                    body = b'{"result": {"spool_id": 7, "state": "ready"}}'
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                rec.seen += 1
                self.send_response(code)
                self.send_header("Location", location)
                self.send_header("Content-Length", "0")
                self.end_headers()

            do_GET = do_POST = _go

            def log_message(self, *a):
                pass

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.srv.server_port
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


@pytest.fixture
def redirects():
    made = []

    def make(**kw):
        made.append(_Redirects(**kw))
        return made[-1]
    yield make
    for r in made:
        r.close()


def _pair(redirects, where, code=302, scheme="http"):
    """(the server the client talks to, the server that must never hear from it)."""
    if where == "same host":
        first = redirects(code=code)
        return first, first
    other = redirects()
    return redirects(code=code, location=f"{scheme}://localhost:{other.port}/elsewhere"), other


@pytest.mark.parametrize("where", ["same host", "cross host"])
@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
def test_http_refuses_a_redirect_and_keeps_the_key(redirects, where, code):
    first, target = _pair(redirects, where, code)
    c = mr.Moonraker("127.0.0.1", first.port, api_key="PROBE-KEY", timeout=3)
    with pytest.raises(mr.MoonrakerError, match=f"127.0.0.1:{first.port}.*redirect.*{code}") as e:
        c.spool_id()
    assert "PROBE-KEY" not in str(e.value) and "elsewhere" not in str(e.value)
    assert first.seen == 1 and target.hits == []


@pytest.mark.parametrize("where", ["same host", "cross host"])
@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
def test_gcode_redirect_is_an_error_not_a_false_success(redirects, where, code):
    """A POST on 301/302/303 used to become a bodiless GET and return as if the gcode had run."""
    first, target = _pair(redirects, where, code)
    with pytest.raises(mr.MoonrakerError, match="redirect"):
        mr.Moonraker("127.0.0.1", first.port, api_key="PROBE-KEY", timeout=3).gcode("G28")
    assert target.hits == []


@pytest.mark.parametrize("where", ["same host", "cross host"])
@pytest.mark.parametrize("code", [302, 307])
def test_websocket_refuses_a_redirect_and_keeps_the_key(redirects, where, code):
    first, target = _pair(redirects, where, code, scheme="ws")
    c = mr.Moonraker("127.0.0.1", first.port, api_key="PROBE-KEY", timeout=3)
    sub = mr.Subscriber(c, {}, lambda s: None, lambda n, p: None, backoff=(0.05, 0.1)).start()
    try:
        assert wait_for(lambda: first.seen >= 3)       # it kept trying, and each try stopped at the redirect
        assert sub.connected is False and target.hits == []
    finally:
        sub.stop()


def test_capture_tool_refuses_a_redirect_and_keeps_the_key(redirects, tmp_path, monkeypatch):
    other = redirects()
    first = redirects(location=f"http://localhost:{other.port}/elsewhere")
    monkeypatch.setenv("FK_MOONRAKER_KEY", "PROBE-KEY")
    assert _capture_tool().main(["--host", "127.0.0.1", "--port", str(first.port), "--out", str(tmp_path)]) == 1
    assert first.seen == 1 and other.hits == []


def test_websocket_on_its_own_socket_still_works(moonraker):
    """The socket the subscriber opens itself: subscribes, stays open past the connect timeout, stops cleanly."""
    got = []
    c = _client(moonraker, timeout=0.3)
    sub = mr.Subscriber(c, {"print_stats": None}, got.append, lambda n, p: None, backoff=(0.05, 0.1)).start()
    try:
        assert wait_for(lambda: sub.connected)
        time.sleep(0.8)     # a timeout left on the socket would have dropped this idle connection by now
        assert sub.connected
        moonraker.push({"print_stats": {"state": "printing"}})
        assert wait_for(lambda: any((d.get("print_stats") or {}).get("state") == "printing" for d in got))
    finally:
        sub.stop()
