"""VoicePipeline pure helpers: wav decode contract (no live STT)."""

from __future__ import annotations

import importlib
import io
import wave

import numpy as np
import pytest

from dictate_core import VoicePipeline
from dictate_core.stt import wav_bytes

core_mod = importlib.import_module("dictate_core")


def _make_wav(audio: np.ndarray, rate: int = 16000, width: int = 2, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(width)
        wf.setframerate(rate)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


def test_decode_wav_ok():
    audio = np.array([0.0, 0.25, -0.25], dtype=np.float32)
    data = wav_bytes(audio)
    out = core_mod._decode_wav(data)
    assert out.dtype == np.float32
    assert len(out) == 3


def test_decode_wav_rejects_bad_rate():
    data = _make_wav(np.zeros(10, dtype=np.float32), rate=44100)
    with pytest.raises(ValueError, match="16 kHz"):
        core_mod._decode_wav(data)


def test_decode_wav_rejects_stereo():
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * 4)
    with pytest.raises(ValueError, match="mono"):
        core_mod._decode_wav(buf.getvalue())


def test_voice_pipeline_requires_key_for_openrouter(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(core_mod, "_key_from_config", lambda: None)
    with pytest.raises(ValueError, match="API key"):
        VoicePipeline(stt_backend="openrouter")


def test_voice_pipeline_mlx_constructs(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    vp = VoicePipeline(stt_backend="mlx", formatter_enabled=False)
    assert vp.suggest_corrections("teh", "the") == [("teh", "the")]


def test_voice_pipeline_unknown_backend():
    with pytest.raises(ValueError, match="unknown stt_backend"):
        VoicePipeline(stt_backend="nope", openrouter_key="k")
