"""filament_kit.station panel pieces (speech on the panel's speaker, room air, the webcam picture, the HTTP view):
ported from filament-ops station/test_panel.py; the intake flow itself is in test_station_flow_panel.py. That test drove a fake D1 mini on a pty with espeak-ng and ffmpeg for real;
these use subprocess fakes and a recording serial port, so they run anywhere."""
from __future__ import annotations

import json
import struct
import subprocess
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from filament_kit.station import air, beep, camera, nfc, panel, speech, wire
from filament_kit.station import http as station_http
from filament_kit.station import state as st

JPEG = b"\xff\xd8\xff\xe0" + b"j" * 20000


class Done:
    """What subprocess.run returns."""
    def __init__(self, out=b"", code=0, err=b""):
        self.stdout, self.returncode, self.stderr = out, code, err


class Ser:
    """A serial port that keeps what was written."""
    port = "/dev/ttyFAKE"

    def __init__(self):
        self.out = b""

    def write(self, data):
        self.out += data


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    with st.lock:
        saved = dict(st.state)
        st.state.update(tag=None, tag_at=None, scale=None, scale_at=None, last=None, last_at=None, held=None,
                        held_at=None, blink_until=0, air=None, air_at=None, photo=None,
                        photo_at=None)
    monkeypatch.setitem(st.panel, "ser", None)
    monkeypatch.setitem(st.settings, "speech", True)
    monkeypatch.setitem(st.settings, "camera", "auto")
    speech.speech_ready.clear()
    speech.speech["text"] = None
    monkeypatch.setattr(beep, "beep", lambda kind="scan": None)
    yield
    with st.lock:
        st.state.clear()
        st.state.update(saved)


def pcm(n, amp=1000):
    return struct.pack(f"<{n}h", *[amp if i % 2 else -amp for i in range(n)])


def frames(raw):
    """Split the bytes written to the panel into ("A", payload) frames and ("L", text line)s."""
    out = []
    while raw:
        if raw.startswith(b"A "):
            nl = raw.index(b"\n")
            n = int(raw[2:nl])
            out.append(("A", raw[nl + 1:nl + 1 + n]))
            raw = raw[nl + 1 + n:]
        else:
            ln, raw = raw.split(b"\n", 1)
            out.append(("L", ln.decode()))
    return out


# --- air -----------------------------------------------------------------------------------------------------------

def test_air_bme280_and_bmp280():
    air.on_air(b"AIR 21.43 45.2 1013.25")
    assert st.state["air"] == {"temp_c": 21.43, "rh": 45.2, "hpa": 1013.25}
    assert st.state["air_at"] is not None
    air.on_air(b"AIR -3.05 - 990.10")
    assert st.state["air"] == {"temp_c": -3.05, "rh": None, "hpa": 990.10}


def test_air_aht20_alone_has_no_pressure():
    air.on_air(b"AIR 21.5 40.0 -")
    assert st.state["air"] == {"temp_c": 21.5, "rh": 40.0, "hpa": None}
    air.on_air(b"AIR 20.0 - -")  # neither sensor reading: still parsed, both null
    assert st.state["air"] == {"temp_c": 20.0, "rh": None, "hpa": None}


def test_air_garbage_ignored():
    air.on_air(b"AIR 21.43 45.2 1013.25")
    for bad in (b"AIR", b"AIR x y z", b"AIR 1 2"):
        air.on_air(bad)
    assert st.state["air"]["temp_c"] == 21.43


# --- panel_send ----------------------------------------------------------------------------------------------------

def test_panel_send_text_and_bytes():
    ser = st.panel["ser"] = Ser()
    assert wire.panel_send("L 1 0") and wire.panel_send(b"A 2\n\x01\x02")
    assert ser.out == b"L 1 0\nA 2\n\x01\x02"


def test_panel_send_without_panel():
    assert wire.panel_send(b"A 1\n\x00") is False


# --- speech --------------------------------------------------------------------------------------------------------

def test_say_respects_the_switch():
    speech.say("hello")
    assert speech.speech["text"] == "hello" and speech.speech_ready.is_set()
    speech.speech_ready.clear()
    st.settings["speech"] = False
    speech.say("quiet")
    assert speech.speech["text"] == "hello" and not speech.speech_ready.is_set()


def test_synth_runs_espeak_and_survives_a_missing_one(monkeypatch):
    seen = []
    monkeypatch.setattr(speech.subprocess, "run", lambda a, **kw: seen.append(a) or Done(b"RIFFwav"))
    assert speech.synth("Held, 1042 grams") == b"RIFFwav"
    assert seen == [["espeak-ng", "-v", "en-us", "-s", "165", "--stdout", "Held, 1042 grams"]]

    def missing(a, **kw):
        raise FileNotFoundError("espeak-ng")
    monkeypatch.setattr(speech.subprocess, "run", missing)
    assert speech.synth("x") is None
    monkeypatch.setattr(speech.subprocess, "run", lambda a, **kw: Done(b"", 1))
    assert speech.synth("x") is None


def test_to_panel_ramps_and_stays_in_duty_range(monkeypatch):
    seen = []
    monkeypatch.setattr(speech.subprocess, "run", lambda a, **kw: seen.append((a, kw)) or Done(pcm(4000, 20000)))
    out = speech.to_panel(b"wav")
    af = seen[0][0][seen[0][0].index("-af") + 1]
    assert af == ("highpass=f=450,highpass=f=450,equalizer=f=2500:t=q:w=1:g=8,lowpass=f=3600,"
                  "acompressor=threshold=0.03:ratio=10:attack=2:release=50")
    assert seen[0][1]["input"] == b"wav"
    pad = speech.RATE // 20
    body = out[speech.RAMP + pad:-(speech.RAMP + pad)]
    assert len(body) == 4000
    assert out[0] == 0 and out[-1] == 0 and out[speech.RAMP] == 128
    assert min(body) == 16 and max(body) == 240  # peak-normalised to +-112 around 128


def test_to_panel_normalises_to_the_98th_percentile_and_clips_the_loudest(monkeypatch):
    samples = [1000] * 99 + [20000]  # one spike in 100: the loudest 1 % sit above the 98 % mark and clip
    monkeypatch.setattr(speech.subprocess, "run", lambda a, **kw: Done(struct.pack(f"<{len(samples)}h", *samples)))
    out = speech.to_panel(b"wav")
    body = out[speech.RAMP + speech.RATE // 20:-(speech.RAMP + speech.RATE // 20)]
    assert body[0] == 240 and body[-1] == 240 and max(body) == 240  # 1000 is the 98 % level -> full scale


def test_to_panel_ffmpeg_failure_raises(monkeypatch):
    monkeypatch.setattr(speech.subprocess, "run", lambda a, **kw: Done(b"", 1, b"boom"))
    with pytest.raises(OSError, match="boom"):
        speech.to_panel(b"wav")


def test_speak_streams_256_byte_frames_in_real_time(monkeypatch):
    ser = st.panel["ser"] = Ser()
    samples = bytes(range(16, 240)) * 20  # 4480 bytes = 0.56 s
    monkeypatch.setattr(speech, "synth", lambda t: b"wav")
    monkeypatch.setattr(speech, "to_panel", lambda w: samples)
    t0 = time.monotonic()
    speech.speak("Held")
    took = time.monotonic() - t0
    fs = frames(ser.out)
    assert [len(p) for k, p in fs] == [256] * 17 + [128] and b"".join(p for k, p in fs) == samples
    assert abs(took - (len(samples) / speech.RATE - 0.25)) < 0.3  # 0.25 s ahead of real time


def test_newer_phrase_cuts_off_the_old_one_fading_to_zero(monkeypatch):
    ser = st.panel["ser"] = Ser()
    monkeypatch.setattr(speech, "synth", lambda t: b"wav")
    monkeypatch.setattr(speech, "to_panel", lambda w: bytes([200]) * 8000)
    speech.speech_ready.set()  # a newer phrase is already waiting
    speech.speak("old")
    data = b"".join(p for k, p in frames(ser.out))
    assert len(data) == speech.RAMP  # nothing of the old phrase but the fade
    assert data[0] == 200 and data[-1] <= 1 and list(data) == sorted(data, reverse=True)


def test_speech_without_panel_plays_on_the_beep_output(monkeypatch):
    calls = []
    monkeypatch.setattr(speech, "synth", lambda t: b"wav")
    monkeypatch.setattr(beep, "beep_device", lambda: "plughw:2,0")
    monkeypatch.setattr(speech.subprocess, "run", lambda a, **kw: calls.append((a, kw["input"])) or Done())
    speech.speak("Discarded")
    assert calls == [(["aplay", "-q", "-D", "plughw:2,0", "-"], b"wav")]
    calls.clear()
    monkeypatch.setattr(beep, "beep_device", lambda: None)
    speech.speak("Discarded")
    assert calls == []


def test_speech_loop_survives_aplay_trouble(monkeypatch):
    """aplay missing or hung must not end the speech thread: the next phrase is still spoken."""
    spoken = []

    def speak(text):
        spoken.append(text)
        if len(spoken) == 1:
            raise subprocess.TimeoutExpired("aplay", 15)
        if len(spoken) == 2:
            raise FileNotFoundError("aplay")
        raise SystemExit  # ends the loop thread's run in the test
    monkeypatch.setattr(speech, "speak", speak)
    done = threading.Event()

    def run():
        try:
            speech.speech_loop()
        except SystemExit:
            done.set()
    threading.Thread(target=run, daemon=True).start()
    for text in ("a", "b", "c"):
        speech.say(text)
        deadline = time.time() + 5
        while len(spoken) < "abc".index(text) + 1 and time.time() < deadline:
            time.sleep(0.01)
    assert done.wait(5) and spoken == ["a", "b", "c"]


def test_speak_survives_a_missing_synth_or_ffmpeg(monkeypatch):
    ser = st.panel["ser"] = Ser()
    monkeypatch.setattr(speech, "synth", lambda t: None)
    speech.speak("x")
    monkeypatch.setattr(speech, "synth", lambda t: b"wav")

    def broken(w):
        raise OSError("no ffmpeg")
    monkeypatch.setattr(speech, "to_panel", broken)
    speech.speak("x")
    assert ser.out == b""


# --- camera --------------------------------------------------------------------------------------------------------

def test_camera_dev(monkeypatch):
    monkeypatch.setattr(camera.glob, "glob", lambda p: ["/dev/v4l/by-id/usb-B-video-index0",
                                                       "/dev/v4l/by-id/usb-A-video-index0"])
    assert camera.camera_dev() == "/dev/v4l/by-id/usb-A-video-index0"
    st.settings["camera"] = "/dev/video4"
    assert camera.camera_dev() == "/dev/video4"
    st.settings["camera"] = "off"
    assert camera.camera_dev() is None
    st.settings["camera"] = "auto"
    monkeypatch.setattr(camera.glob, "glob", lambda p: [])
    assert camera.camera_dev() is None


def test_grab_photo_returns_the_jpeg(monkeypatch):
    monkeypatch.setattr(camera, "camera_dev", lambda: "/dev/video-fake")
    seen = []
    monkeypatch.setattr(camera.subprocess, "run", lambda a, **kw: seen.append(a) or Done(JPEG))
    assert camera.grab_photo() == (JPEG, None)
    assert len(seen) == 1 and "v4l2" in seen[0] and "1920x1080" in seen[0] and "/dev/video-fake" in seen[0]
    assert r"select=gte(n\,15)" in seen[0]


def test_grab_photo_falls_back_to_the_cameras_own_format(monkeypatch):
    monkeypatch.setattr(camera, "camera_dev", lambda: "/dev/video-fake")
    seen = []

    def run(a, **kw):
        seen.append(a)
        return Done(b"", 1, b"no 1080p") if "1920x1080" in a else Done(JPEG)
    monkeypatch.setattr(camera.subprocess, "run", run)
    assert camera.grab_photo() == (JPEG, None)
    assert len(seen) == 2 and "1920x1080" not in seen[1]


@pytest.mark.parametrize("result", [Done(b"not a jpeg"), Done(b"", 1, b"busy"), FileNotFoundError("ffmpeg"),
                                    subprocess.TimeoutExpired("ffmpeg", 15)])
def test_grab_photo_failures(monkeypatch, result):
    monkeypatch.setattr(camera, "camera_dev", lambda: "/dev/video-fake")

    def run(a, **kw):
        if isinstance(result, BaseException):
            raise result
        return result
    monkeypatch.setattr(camera.subprocess, "run", run)
    assert camera.grab_photo() == (None, "camera failed")


def test_grab_photo_without_a_camera(monkeypatch):
    monkeypatch.setattr(camera, "camera_dev", lambda: None)
    monkeypatch.setattr(camera.subprocess, "run", lambda *a, **kw: pytest.fail("no camera, no ffmpeg"))
    assert camera.grab_photo() == (None, "no camera")


# --- HTTP: air, photo, /photo, read-only ---------------------------------------------------------------------------

def _serve(view, allow):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), station_http.make_handler(view, allow))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def _raw(now, **kw):
    s = {"tag": "4:aa:bb", "tag_at": now - 5, "scale": None, "scale_at": None, "last": None, "last_at": None,
         "held": 1098.0, "held_at": now - 3, "blink_until": 0, "panel": "/dev/ttyUSB1", "panel_version": "7",
         "air": None, "air_at": None, "photo": None, "photo_at": None,
         "flow": {"step": "ready", "message": "", "spool": None, "filament": {"id": 45}}}
    s.update(kw)
    return s


def _fetch(url, method="GET"):
    req = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def test_state_air_and_photo():
    now = time.time()
    raw = _raw(now, air={"temp_c": 21.43, "rh": 45.2, "hpa": 1013.25}, air_at=now - 2, photo=JPEG, photo_at=now - 1)
    srv, base = _serve(lambda: dict(raw), {"127.0.0.1"})
    try:
        s = json.loads(_fetch(base + "/state")[2])
        assert s["air"] == {"temp_c": 21.43, "rh": 45.2, "hpa": 1013.25, "age_seconds": 2}
        assert s["photo"] == {"url": "/photo", "taken_at": station_http.iso(now - 1), "age_seconds": 1}
        assert set(s) == {"tag", "scale", "last_weight", "panel", "panel_version", "air", "photo", "flow"}
        assert s["panel_version"] == "7"
        assert s["flow"] == {"step": "ready", "message": "", "spool": None, "filament": {"id": 45}}
        assert s["last_weight"] == {"grams": 1098.0, "age_seconds": 3, "held": True}
    finally:
        srv.shutdown()


def test_state_air_without_pressure_or_humidity_shape():
    now = time.time()
    raw = _raw(now, air={"temp_c": 21.5, "rh": 40.0, "hpa": None}, air_at=now - 1)
    srv, base = _serve(lambda: dict(raw), {"127.0.0.1"})
    try:
        s = json.loads(_fetch(base + "/state")[2])
        assert s["air"] == {"temp_c": 21.5, "rh": 40.0, "hpa": None, "age_seconds": 1}
    finally:
        srv.shutdown()


def test_state_stale_air_dropped_and_no_photo():
    now = time.time()
    raw = _raw(now, air={"temp_c": 20.0, "rh": None, "hpa": 990.0}, air_at=now - 600)
    srv, base = _serve(lambda: dict(raw), {"127.0.0.1"})
    try:
        s = json.loads(_fetch(base + "/state")[2])
        assert s["air"] is None and s["photo"] is None
    finally:
        srv.shutdown()


def test_photo_served_as_jpeg_and_404_without_one():
    now = time.time()
    views = iter([_raw(now, photo=JPEG, photo_at=now), _raw(now)])
    srv, base = _serve(lambda: dict(next(views)), {"127.0.0.1"})
    try:
        code, hdr, body = _fetch(base + "/photo")
        assert (code, hdr["Content-Type"], hdr["Cache-Control"], body) == (200, "image/jpeg", "no-store", JPEG)
        assert int(hdr["Content-Length"]) == len(JPEG)
        code, _, body = _fetch(base + "/photo")
        assert code == 404 and json.loads(body) == {"status": "error", "message": "not found"}
    finally:
        srv.shutdown()


def test_photo_refused_for_a_client_not_in_allow():
    now = time.time()
    srv, base = _serve(lambda: _raw(now, photo=JPEG, photo_at=now), {"10.9.9.9"})
    try:
        code, hdr, body = _fetch(base + "/photo")
        assert code == 403 and JPEG not in body
        assert hdr["Content-Type"] == "application/json"
    finally:
        srv.shutdown()


def test_station_stays_read_only():
    now = time.time()
    srv, base = _serve(lambda: _raw(now, photo=JPEG, photo_at=now), {"127.0.0.1"})
    try:
        for method in ("POST", "PUT", "DELETE"):
            assert _fetch(base + "/photo", method)[0] == 501  # no do_<method> on the handler
    finally:
        srv.shutdown()


# --- settings ------------------------------------------------------------------------------------------------------

def test_speech_and_camera_settings_from_env(monkeypatch):
    monkeypatch.delenv("STATION_SPEECH", raising=False)
    monkeypatch.delenv("STATION_CAMERA", raising=False)
    s = st.settings_from_env()
    assert s["speech"] is True and s["camera"] == "auto"
    monkeypatch.setenv("STATION_SPEECH", "0")
    monkeypatch.setenv("STATION_CAMERA", "/dev/video2")
    s = st.settings_from_env()
    assert s["speech"] is False and s["camera"] == "/dev/video2"
