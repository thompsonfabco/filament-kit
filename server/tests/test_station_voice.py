"""The station's Piper voice: where it is, the installer's pinned download (station/voice.py), and speech.py using
Piper first with espeak-ng as the fallback. No network, no piper-tts: urlopen and PiperVoice are fakes."""
from __future__ import annotations

import hashlib
import io
import sys
import types
import urllib.error
import wave
from pathlib import Path

import pytest

from filament_kit import apply, config
from filament_kit.station import speech, voice
from filament_kit.station import state as st

ONNX, JSON = b"onnx model bytes", b'{"audio": {"sample_rate": 22050}}'


MODEL = voice.DEFAULT + ".onnx"
URL = "https://example.com/voices/"


@pytest.fixture
def fake_voice(monkeypatch):
    """The default voice's row, with pinned hashes that match ONNX and JSON."""
    files = {MODEL: hashlib.sha256(ONNX).hexdigest(), MODEL + ".json": hashlib.sha256(JSON).hexdigest()}
    monkeypatch.setitem(voice.VOICES, voice.DEFAULT, {"url": URL, "licence": "test", "files": files})
    return files


def urlopen_serving(served: dict, seen: list):
    def urlopen(url, timeout=None):
        seen.append(url)
        name = url.rsplit("/", 1)[1]
        if name not in served:
            raise urllib.error.URLError("offline")
        return io.BytesIO(served[name])
    return urlopen


# --- the one place the voice is named -------------------------------------------------------------------------------

def test_the_voice_table():
    assert voice.DEFAULT in voice.VOICES and "public domain" in voice.VOICES["en_US-ljspeech-medium"]["licence"]
    for name, v in voice.VOICES.items():
        assert set(v["files"]) == {name + ".onnx", name + ".onnx.json"}
        assert all(len(h) == 64 for h in v["files"].values())
        assert v["url"].startswith("https://huggingface.co/rhasspy/piper-voices/") and v["url"].endswith("/")
    assert "research" in voice.VOICES["en_US-lessac-medium"]["licence"]  # only when the owner picks it
    assert voice.DEFAULT != "en_US-lessac-medium"
    lib = voice.VOICES["en_US-libritts_r-medium"]
    assert lib["licence"].startswith("CC BY 4.0") and "LibriTTS-R" in lib["credit"]  # the credit THIRD-PARTY.md carries
    assert voice.model_path("/x/voice") == f"/x/voice/{voice.DEFAULT}.onnx"
    assert voice.model_path("/x/voice", "en_US-lessac-medium") == "/x/voice/en_US-lessac-medium.onnx"
    with pytest.raises(ValueError, match="unknown Piper voice"):
        voice.model_path("/x/voice", "nope")


def test_settings_tts_and_piper_voice(monkeypatch):
    monkeypatch.delenv("STATION_TTS", raising=False)
    monkeypatch.delenv("STATION_PIPER_VOICE", raising=False)
    s = st.settings_from_env()
    assert s["tts"] == "auto"
    assert s["piper_voice"] == f"/opt/filament-kit/resources/voice/{voice.DEFAULT}.onnx"
    monkeypatch.setenv("STATION_TTS", "espeak")
    monkeypatch.setenv("STATION_PIPER_VOICE", "/srv/v.onnx")
    s = st.settings_from_env()
    assert (s["tts"], s["piper_voice"]) == ("espeak", "/srv/v.onnx")


def test_dropin_carries_tts_and_the_voice_path(monkeypatch, tmp_path):
    for name in ("etc", "state", "opt"):  # nothing is written; still, never the real paths
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    opt = (tmp_path / "opt").as_posix()
    cfg = {"modules": {"station": True}, "station": {"allow": ["127.0.0.1"]}}
    text = apply.station_dropin(cfg, ["127.0.0.1"])
    assert "STATION_TTS=auto" in text
    assert f"STATION_PIPER_VOICE={opt}/resources/voice/{voice.DEFAULT}.onnx" in text
    cfg["station"].update(tts="espeak", voice="en_US-lessac-medium")  # the owner's explicit pick
    text = apply.station_dropin(cfg, ["127.0.0.1"])
    assert "STATION_TTS=espeak" in text and "voice/en_US-lessac-medium.onnx" in text
    assert config.DEFAULTS["station"]["tts"] == "auto" and config.DEFAULTS["station"]["voice"] is None
    cfg["station"]["voice"] = "nope"
    with pytest.raises(apply.ModuleError, match="station.voice"):
        apply.station_dropin(cfg, ["127.0.0.1"])


# --- the installer's download ---------------------------------------------------------------------------------------

def test_fetch_writes_both_files_checked(tmp_path, fake_voice):
    seen = []
    served = {MODEL: ONNX, MODEL + ".json": JSON}
    assert voice.fetch(tmp_path, urlopen=urlopen_serving(served, seen)) == "installed"
    assert (tmp_path / MODEL).read_bytes() == ONNX and (tmp_path / (MODEL + ".json")).read_bytes() == JSON
    assert seen == [URL + MODEL, URL + MODEL + ".json"]
    assert not list(tmp_path.glob("*.part"))
    seen.clear()
    assert voice.fetch(tmp_path, urlopen=urlopen_serving(served, seen)) == "present" and seen == []


def test_fetch_refuses_a_hash_mismatch(tmp_path, fake_voice):
    served = {MODEL: b"something else", MODEL + ".json": JSON}
    with pytest.raises(voice.HashMismatch, match=MODEL):
        voice.fetch(tmp_path, urlopen=urlopen_serving(served, []))
    assert not (tmp_path / MODEL).exists() and not list(tmp_path.glob("*.part"))


def test_fetch_offline_skips_quietly(tmp_path, fake_voice):
    assert voice.fetch(tmp_path, urlopen=urlopen_serving({}, [])) == "offline"
    assert list(tmp_path.iterdir()) == []


def test_fetch_replaces_a_damaged_copy(tmp_path, fake_voice):
    (tmp_path / MODEL).write_bytes(b"truncated")
    served = {MODEL: ONNX, MODEL + ".json": JSON}
    assert voice.fetch(tmp_path, urlopen=urlopen_serving(served, [])) == "installed"
    assert (tmp_path / MODEL).read_bytes() == ONNX


def test_main_exit_codes(tmp_path, fake_voice, monkeypatch, capsys):
    seen = []
    monkeypatch.setattr(voice, "fetch", lambda d, name: seen.append(name) or "offline")
    assert voice.main([str(tmp_path)]) == 0 and voice.main([str(tmp_path), ""]) == 0
    assert "espeak-ng" in capsys.readouterr().err and seen == [voice.DEFAULT, voice.DEFAULT]
    assert voice.main([str(tmp_path), "en_US-lessac-medium"]) == 0 and seen[-1] == "en_US-lessac-medium"

    def bad(d, name):
        raise voice.HashMismatch("x: hash mismatch")
    monkeypatch.setattr(voice, "fetch", bad)
    assert voice.main([str(tmp_path)]) == 1
    monkeypatch.undo()
    assert voice.main([str(tmp_path), "nope"]) == 1  # not in the table


# --- speech: Piper first, espeak-ng as the fallback ------------------------------------------------------------------

class Done:
    def __init__(self, out=b"", code=0):
        self.stdout, self.returncode, self.stderr = out, code, b""


class FakePiper:
    loads: list[str] = []

    @classmethod
    def load(cls, path):
        cls.loads.append(path)
        return cls()

    def synthesize_wav(self, text, w):
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(22050)
        w.writeframes(b"\x00\x01" * 100)


@pytest.fixture
def piper_env(tmp_path, monkeypatch):
    model = tmp_path / MODEL
    model.write_bytes(ONNX)
    monkeypatch.setitem(st.settings, "tts", "auto")
    monkeypatch.setitem(st.settings, "piper_voice", str(model))
    monkeypatch.setitem(sys.modules, "piper", types.SimpleNamespace(PiperVoice=FakePiper))
    speech.piper.clear()
    FakePiper.loads = []
    espeak = []
    monkeypatch.setattr(speech.subprocess, "run", lambda a, **kw: espeak.append(a) or Done(b"RIFFespeak"))
    yield model, espeak
    speech.piper.clear()


def test_synth_uses_piper_when_its_voice_is_installed(piper_env):
    model, espeak = piper_env
    wav = speech.synth("Saved.")
    with wave.open(io.BytesIO(wav)) as w:
        assert (w.getframerate(), w.getsampwidth(), w.getnframes()) == (22050, 2, 100)
    speech.synth("Cancelled.")
    assert FakePiper.loads == [str(model)] and espeak == []  # loaded once, kept


def test_synth_falls_back_to_espeak(piper_env, monkeypatch):
    model, espeak = piper_env
    st.settings["tts"] = "espeak"  # forced
    assert speech.synth("x") == b"RIFFespeak" and FakePiper.loads == []
    st.settings["tts"] = "auto"
    model.unlink()  # no voice installed
    assert speech.synth("x") == b"RIFFespeak" and FakePiper.loads == []
    assert len(espeak) == 2 and espeak[0][0] == "espeak-ng"


def test_a_broken_piper_falls_back_once_loaded(piper_env, monkeypatch):
    _, espeak = piper_env

    class Broken:
        @staticmethod
        def load(path):
            raise RuntimeError("onnxruntime missing")
    monkeypatch.setitem(sys.modules, "piper", types.SimpleNamespace(PiperVoice=Broken))
    assert speech.synth("a") == b"RIFFespeak" and speech.synth("b") == b"RIFFespeak"
    assert speech.piper == {"voice": None}  # not retried every phrase


def test_a_phrase_piper_fails_on_goes_to_espeak(piper_env, monkeypatch):
    _, espeak = piper_env
    monkeypatch.setattr(FakePiper, "synthesize_wav", lambda self, t, w: (_ for _ in ()).throw(ValueError("bad")))
    assert speech.synth("a") == b"RIFFespeak" and len(espeak) == 1


def test_engine_name(piper_env):
    model, _ = piper_env
    assert speech.engine() == f"Piper ({MODEL})"
    st.settings["tts"] = "espeak"
    assert speech.engine() == "espeak-ng"


# --- the installer --------------------------------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[2]  # from the test file: CI installs the package


def test_install_sh_keeps_the_voice_and_leaves_the_fetch_to_modules_apply():
    text = (ROOT / "install" / "install.sh").read_text(encoding="utf-8")
    assert 'rm -rf "$OPT/resources"' not in text and "! -name voice" in text  # an upgrade keeps the voice
    assert "filament_kit.station.voice" not in text and '"${WHEEL}[station-tts]"' not in text  # apply's step
    assert "exec /usr/local/bin/filament-kit modules apply" in text
    assert 'station-tts = ["piper-tts==1.8.0"]' in (ROOT / "server" / "pyproject.toml").read_text(encoding="utf-8")


# --- fix round 1 ----------------------------------------------------------------------------------------------------

def test_fetch_keeps_the_model_when_the_json_fails(tmp_path, fake_voice):
    """M6: the .onnx that arrived stays (checked); only the missing .json is fetched on the next run."""
    assert voice.fetch(tmp_path, urlopen=urlopen_serving({MODEL: ONNX}, [])) == "offline"
    assert (tmp_path / MODEL).read_bytes() == ONNX and not (tmp_path / (MODEL + ".json")).exists()
    assert "nothing kept" not in voice.fetch.__doc__ and "is kept" in voice.fetch.__doc__
    seen = []
    assert voice.fetch(tmp_path, urlopen=urlopen_serving({MODEL: ONNX, MODEL + ".json": JSON}, seen)) == "installed"
    assert seen == [URL + MODEL + ".json"]


def _station_plan(tts="auto", name=None):
    from filament_kit import modules
    cfg = modules.set_mode(config._merge(config.DEFAULTS, {}), "all-in-one", say=None)
    cfg["station"].update(tts=tts, voice=name)
    return apply.plan(cfg, resolve=lambda h: [h])


def test_the_station_module_brings_piper_and_its_voice(tmp_path, monkeypatch):
    """M7: `modules enable station` (any apply with the station on) installs the [station-tts] extra and the voice,
    not only install.sh."""
    for name in ("etc", "state", "opt"):
        monkeypatch.setenv(f"FK_{name.upper()}", str(tmp_path / name))
    acts = [a for a in _station_plan() if a.kind == "station_voice"]
    assert [a.arg for a in acts] == [voice.DEFAULT]
    assert [a for a in _station_plan(name="en_US-ljspeech-medium") if a.kind == "station_voice"][0].arg \
        == "en_US-ljspeech-medium"
    assert not [a for a in _station_plan(tts="espeak") if a.kind == "station_voice"]
    monkeypatch.delenv("FK_NO_SYSTEMD", raising=False)
    monkeypatch.delenv("FK_STATION_TTS", raising=False)
    ran = []
    apply.execute(acts, run=ran.append, root=tmp_path / "root")
    assert ran[0][:4] == [sys.executable, "-m", "pip", "install"] and "piper-tts==1.8.0" in ran[0]
    assert ran[1] == [sys.executable, "-I", "-m", "filament_kit.station.voice",
                      f"{(tmp_path / 'opt').as_posix()}/resources/voice", voice.DEFAULT]


def test_station_voice_step_offline_and_mismatch(tmp_path, monkeypatch, capsys):
    import subprocess
    monkeypatch.delenv("FK_NO_SYSTEMD", raising=False)
    monkeypatch.setenv("FK_OPT", str(tmp_path / "opt"))
    act = apply.Action("station_voice", voice.DEFAULT)

    def pip_offline(cmd):
        if "pip" in cmd:
            raise subprocess.CalledProcessError(1, cmd)
    apply.execute([act], run=pip_offline, root=tmp_path)  # a note, never a failure
    assert "espeak-ng" in capsys.readouterr().out

    def mismatch(cmd):
        if "filament_kit.station.voice" in cmd:
            raise subprocess.CalledProcessError(1, cmd)
    with pytest.raises(apply.ApplyError):
        apply.execute([act], run=mismatch, root=tmp_path)
    ran = []
    monkeypatch.setenv("FK_STATION_TTS", "espeak")
    apply.execute([act], run=ran.append, root=tmp_path)
    assert ran == []


def test_panel_md_and_panel_py_know_firmware_8():
    """M8."""
    text = (ROOT / "station" / "PANEL.md").read_text(encoding="utf-8")
    assert '8: "Waiting for PC" boot title' in text and '"Waiting for PC"' in text.split("## Serial protocol")[1]
    from filament_kit.station import panel
    assert "Protocol (firmware 8)" in panel.__doc__
    assert "station module switched on later" in text or "modules enable station" in text


def test_station_voice_step_pins_the_kits_packages_and_opens_the_voice_folder(tmp_path, monkeypatch):
    """piper-tts goes in with the kit's installed packages as constraints (it may add, never move them), and the
    voice folder is made readable for the station's user whatever root's umask was."""
    monkeypatch.delenv("FK_NO_SYSTEMD", raising=False)
    monkeypatch.delenv("FK_STATION_TTS", raising=False)
    monkeypatch.setenv("FK_OPT", str(tmp_path / "opt"))
    monkeypatch.setattr(apply, "_tts_requirements", lambda: ["piper-tts==1.8.0"])
    ran, seen = [], {}

    def run(cmd):
        ran.append(cmd)
        if "pip" in cmd:
            c = cmd[cmd.index("-c") + 1]
            seen["pins"] = open(c, encoding="utf-8").read()
    apply.execute([apply.Action("station_voice", voice.DEFAULT)], run=run, root=tmp_path)
    pip = next(c for c in ran if "pip" in c)
    assert "-c" in pip and pip[-1] == "piper-tts==1.8.0"
    assert "starlette==" in seen["pins"].lower()
    assert ran[-1][:3] == ["chmod", "-R", "a+rX,go-w"] and ran[-1][3].endswith("/resources/voice")


def test_station_voice_step_says_why_when_the_extra_is_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("FK_NO_SYSTEMD", raising=False)
    monkeypatch.delenv("FK_STATION_TTS", raising=False)
    monkeypatch.setattr(apply, "_tts_requirements", lambda: [])
    ran = []
    apply.execute([apply.Action("station_voice", voice.DEFAULT)], run=ran.append, root=tmp_path)
    assert ran == [] and "no [station-tts] extra" in capsys.readouterr().out


def test_tick_loop_survives_a_bad_tick(monkeypatch):
    from filament_kit.station import flow
    calls = []

    def tick(now):
        calls.append(now)
        if len(calls) == 1:
            raise RuntimeError("boom")
        if len(calls) == 2:
            raise SystemExit  # stop the loop
    monkeypatch.setattr(flow, "flow_tick", tick)
    monkeypatch.setattr(flow.time, "sleep", lambda s: None)
    with pytest.raises(SystemExit):
        flow.tick_loop()
    assert len(calls) == 2
