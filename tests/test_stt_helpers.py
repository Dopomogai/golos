"""STT helpers: languages, WAV encoding, backend factory (mocked, no network)."""

from __future__ import annotations

import io
import wave

import numpy as np
import pytest

from dictate_core.stt import (
    DeepgramBackend,
    MlxWhisperBackend,
    OpenAICompatibleBackend,
    OpenRouterSTTBackend,
    language_hint,
    make_backend,
    validate_languages,
    wav_bytes,
    write_wav,
)


def test_validate_languages_filters_invalid():
    assert validate_languages(["EN", " uk ", "bad!", "1", "", None]) == ["en", "uk"]
    assert validate_languages(None) == []
    assert validate_languages([]) == []


def test_language_hint():
    assert language_hint([]) == ""
    assert "English" in language_hint(["en"])
    assert "Ukrainian" in language_hint(["en", "uk"])
    assert "xx" in language_hint(["xx"])  # unknown code passes through


def test_wav_bytes_and_write_wav_roundtrip(tmp_path):
    audio = np.array([0.0, 0.5, -0.5, 1.0, -1.0], dtype=np.float32)
    data = wav_bytes(audio, sample_rate=16000)
    assert data[:4] == b"RIFF"
    assert b"WAVE" in data[:12]

    path = tmp_path / "t.wav"
    write_wav(str(path), audio, sample_rate=16000)
    with wave.open(str(path), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 16000
        frames = wf.readframes(wf.getnframes())
    assert len(frames) == len(audio) * 2


def test_wav_bytes_clips_out_of_range():
    audio = np.array([2.0, -2.0], dtype=np.float32)
    data = wav_bytes(audio)
    with wave.open(io.BytesIO(data), "rb") as wf:
        pcm = np.frombuffer(wf.readframes(2), dtype=np.int16)
    assert pcm[0] == 32767
    assert pcm[1] == -32767


def test_make_backend_mlx():
    backend = make_backend({"stt": {"backend": "mlx", "languages": ["en"]}}, lambda s: None)
    assert isinstance(backend, MlxWhisperBackend)
    assert backend.language == "en"


def test_make_backend_openrouter_requires_key():
    backend = make_backend({"stt": {"backend": "openrouter"}}, lambda s: None)
    assert backend is None


def test_make_backend_openrouter_with_key():
    cfg = {
        "stt": {"backend": "openrouter", "openrouter": {"model": "deepgram/nova-3"},
                "languages": ["en", "uk"]},
        "openrouter": {"api_key": "sk-test"},
    }
    backend = make_backend(cfg, lambda s: None)
    assert isinstance(backend, OpenRouterSTTBackend)
    assert backend.model == "deepgram/nova-3"
    assert backend.languages == ["en", "uk"]


def test_make_backend_openrouter_char_array_model():
    cfg = {
        "stt": {"backend": "openrouter", "openrouter": {"model": list("abc")}},
        "openrouter": {"api_key": "k"},
    }
    backend = make_backend(cfg, lambda s: None)
    assert backend.model == "abc"


def test_make_backend_openai_compatible():
    section = {"api_key_env": "X", "base_url": "https://example.com/v1", "model": "w"}
    backend = make_backend(
        {"stt": {"backend": "openai_compatible", "cloud": section}},
        lambda s: "secret",
    )
    assert isinstance(backend, OpenAICompatibleBackend)
    assert backend.base_url == "https://example.com/v1"


def test_make_backend_openai_compatible_missing_key():
    backend = make_backend(
        {"stt": {"backend": "openai_compatible", "cloud": {"api_key_env": "X"}}},
        lambda s: None,
    )
    assert backend is None


def test_make_backend_deepgram():
    backend = make_backend(
        {"stt": {"backend": "deepgram", "deepgram": {"api_key_env": "D", "model": "nova-3"}}},
        lambda s: "dg-key",
    )
    assert isinstance(backend, DeepgramBackend)


def test_make_backend_unknown():
    with pytest.raises(ValueError, match="Unknown stt.backend"):
        make_backend({"stt": {"backend": "nope"}}, lambda s: None)


def test_openrouter_stt_posts_json_body(monkeypatch):
    """Contract: base64 wav JSON body — no live HTTP."""
    captured = {}

    class Resp:
        status_code = 200

        def json(self):
            return {"text": " hi "}

    class Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json=None, headers=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return Resp()

    import httpx
    monkeypatch.setattr(httpx, "Client", Client)
    backend = OpenRouterSTTBackend(
        "https://openrouter.ai/api/v1", "sk", "deepgram/nova-3", languages=["en", "uk"]
    )
    audio = np.zeros(100, dtype=np.float32)
    text = backend.transcribe(audio, prompt="golos")
    assert text == "hi"
    assert "transcriptions" in captured["url"]
    body = captured["json"]
    assert body["model"] == "deepgram/nova-3"
    assert body["language"] == "multi"  # deepgram multi for >1 lang
    assert body["prompt"]  # includes language hint + dict
    assert body["input_audio"]["format"] == "wav"
    assert isinstance(body["input_audio"]["data"], str)


def test_openrouter_stt_error_raises(monkeypatch):
    class Resp:
        status_code = 400
        text = '{"error":{"message":"bad model"}}'

        def json(self):
            return {"error": {"message": "bad model"}}

    class Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **k):
            return Resp()

    import httpx
    monkeypatch.setattr(httpx, "Client", Client)
    backend = OpenRouterSTTBackend("https://x", "k", "m")
    with pytest.raises(RuntimeError, match="400"):
        backend.transcribe(np.zeros(10, dtype=np.float32))
