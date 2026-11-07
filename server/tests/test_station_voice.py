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


@pytest.fixture
def fake_voice(monkeypatch):
    """A two-file voice whose pinned hashes match ONNX and JSON."""
    files = {voice.MODEL: hashlib.sha256(ONNX).hexdigest(), voice.MODEL + ".json": hashlib.sha256(JSON).hexdigest()}
    monkeypatch.setattr(voice, "FILES", files)
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

def test_the_voice_is_named_once():
    assert voice.MODEL == voice.NAME + ".onnx"
    assert set(voice.FILES) == {voice.MODEL, voice.MODEL + ".json"}
    assert all(len(h) == 64 for h in voice.FILES.values())
    assert voice.URL.startswith("https://") and voice.URL.endswith("/")
    assert voice.model_path("/x/voice").replace("\\", "/") == "/x/voice/" + voice.MODEL


def test_settings_tts_and_piper_voice(monkeypatch):
    monkeypatch.delenv("STATION_TTS", raising=False)
    monkeypatch.delenv("STATION_PIPER_VOICE", raising=False)
    s = st.settings_from_env()
    assert s["tts"] == "auto"
    assert s["piper_voice"] == "/opt/filament-kit/resources/voice/" + voice.MODEL
    monkeypatch.setenv("STATION_TTS", "espeak")
    monkeypatch.setenv("STATION_PIPER_VOICE", "/srv/v.onnx")
    s = st.settings_from_env()
    assert (s["tts"], s["piper_voice"]) == ("espeak", "/srv/v.onnx")


def test_dropin_carries_tts_and_the_voice_path(monkeypatch):
    monkeypatch.setenv("FK_OPT", "/opt/filament-kit")
    cfg = {"modules": {"station": True}, "station": {"allow": ["127.0.0.1"]}}
    text = apply.station_dropin(cfg, ["127.0.0.1"])
    assert "STATION_TTS=auto" in text
    assert f"STATION_PIPER_VOICE=/opt/filament-kit/resources/voice/{voice.MODEL}" in text
    cfg["station"]["tts"] = "espeak"
    assert "STATION_TTS=espeak" in apply.station_dropin(cfg, ["127.0.0.1"])
    assert config.DEFAULTS["station"]["tts"] == "auto"


# --- the installer's download ---------------------------------------------------------------------------------------

def test_fetch_writes_both_files_checked(tmp_path, fake_voice):
    seen = []
    served = {voice.MODEL: ONNX, voice.MODEL + ".json": JSON}
    assert voice.fetch(tmp_path, urlopen=urlopen_serving(served, seen)) == "installed"
    assert (tmp_path / voice.MODEL).read_bytes() == ONNX and (tmp_path / (voice.MODEL + ".json")).read_bytes() == JSON
    assert seen == [voice.URL + voice.MODEL, voice.URL + voice.MODEL + ".json"]
    assert not list(tmp_path.glob("*.part"))
    seen.clear()
    assert voice.fetch(tmp_path, urlopen=urlopen_serving(served, seen)) == "present" and seen == []


def test_fetch_refuses_a_hash_mismatch(tmp_path, fake_voice):
    served = {voice.MODEL: b"something else", voice.MODEL + ".json": JSON}
    with pytest.raises(voice.HashMismatch, match=voice.MODEL):
        voice.fetch(tmp_path, urlopen=urlopen_serving(served, []))
    assert not (tmp_path / voice.MODEL).exists() and not list(tmp_path.glob("*.part"))


def test_fetch_offline_skips_quietly(tmp_path, fake_voice):
    assert voice.fetch(tmp_path, urlopen=urlopen_serving({}, [])) == "offline"
    assert list(tmp_path.iterdir()) == []


def test_fetch_replaces_a_damaged_copy(tmp_path, fake_voice):
    (tmp_path / voice.MODEL).write_bytes(b"truncated")
    served = {voice.MODEL: ONNX, voice.MODEL + ".json": JSON}
    assert voice.fetch(tmp_path, urlopen=urlopen_serving(served, [])) == "installed"
    assert (tmp_path / voice.MODEL).read_bytes() == ONNX


def test_main_exit_codes(tmp_path, fake_voice, monkeypatch, capsys):
    monkeypatch.setattr(voice, "fetch", lambda d: "offline")
    assert voice.main([str(tmp_path)]) == 0
    assert "espeak-ng" in capsys.readouterr().err

    def bad(d):
        raise voice.HashMismatch("x: hash mismatch")
    monkeypatch.setattr(voice, "fetch", bad)
    assert voice.main([str(tmp_path)]) == 1


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
    model = tmp_path / voice.MODEL
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
    assert speech.engine() == f"Piper ({voice.MODEL})"
    st.settings["tts"] = "espeak"
    assert speech.engine() == "espeak-ng"


# --- the installer --------------------------------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[2]  # from the test file: CI installs the package


def test_install_sh_fetches_the_voice_only_for_a_station_and_keeps_it():
    text = (ROOT / "install" / "install.sh").read_text(encoding="utf-8")
    assert '"${WHEEL}[station-tts]"' in text
    assert '-m filament_kit.station.voice "$OPT/resources/voice"' in text
    assert '"station" in modules.enabled(cfg)' in text and "FK_STATION_TTS" in text
    assert 'rm -rf "$OPT/resources"' not in text and "! -name voice" in text  # an upgrade keeps the 63 MB
    assert voice.FILES[voice.MODEL] not in text  # the hashes live in voice.py only
    assert 'station-tts = ["piper-tts==1.8.0"]' in (ROOT / "server" / "pyproject.toml").read_text(encoding="utf-8")
