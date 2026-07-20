"""STT helpers: languages, WAV encoding, backend factory (mocked, no network)."""

from __future__ import annotations

import io
import sys
import wave
from types import SimpleNamespace

import numpy as np
import pytest

from dictate_core.stt import (
    DeepgramBackend,
    MlxWhisperBackend,
    OpenAICompatibleBackend,
    OpenRouterSTTBackend,
    DEFAULT_MLX_MODEL,
    download_local_model,
    language_hint,
    local_model_is_downloaded,
    local_model_support,
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


def test_make_backend_mlx_requires_supported_download(monkeypatch):
    import dictate_core.stt as stt_mod
    monkeypatch.setattr(stt_mod, "local_model_support", lambda: (True, ""))
    monkeypatch.setattr(stt_mod, "local_model_is_downloaded", lambda model: True)
    backend = make_backend({"stt": {"backend": "mlx", "languages": ["en"]}}, lambda s: None)
    assert isinstance(backend, MlxWhisperBackend)
    assert backend.language == "en"


def test_make_backend_mlx_refuses_unsupported_or_missing(monkeypatch):
    import dictate_core.stt as stt_mod
    cfg = {"stt": {"backend": "mlx"}}
    monkeypatch.setattr(stt_mod, "local_model_support", lambda: (False, "Intel"))
    assert make_backend(cfg, lambda s: None) is None
    monkeypatch.setattr(stt_mod, "local_model_support", lambda: (True, ""))
    monkeypatch.setattr(stt_mod, "local_model_is_downloaded", lambda model: False)
    assert make_backend(cfg, lambda s: None) is None


def test_mlx_transcribe_refuses_implicit_download(monkeypatch):
    import dictate_core.stt as stt_mod
    monkeypatch.setattr(stt_mod, "local_model_support", lambda: (True, ""))
    monkeypatch.setattr(stt_mod, "local_model_is_downloaded", lambda model: False)
    backend = MlxWhisperBackend(DEFAULT_MLX_MODEL)
    with pytest.raises(RuntimeError, match="not downloaded"):
        backend.transcribe(np.zeros(1600, dtype=np.float32))


def test_make_backend_openrouter_requires_key():
    backend = make_backend({"stt": {"backend": "openrouter"}}, lambda s: None)
    assert backend is None


def test_make_backend_defaults_to_cloud_first_openrouter():
    assert make_backend({}, lambda s: None) is None


def test_local_model_path_status_is_offline(tmp_path):
    model = tmp_path / "model"
    model.mkdir()
    assert local_model_is_downloaded(str(model)) is False
    (model / "config.json").write_text("{}")
    (model / "weights.safetensors").write_bytes(b"weights")
    assert local_model_is_downloaded(str(model)) is True


def test_local_model_support_rejects_intel(monkeypatch):
    import dictate_core.stt as stt_mod
    monkeypatch.setattr(stt_mod.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(stt_mod.platform, "machine", lambda: "x86_64")
    ok, reason = local_model_support()
    assert ok is False
    assert "Apple Silicon" in reason


def test_explicit_local_download_uses_requested_repo(monkeypatch):
    import dictate_core.stt as stt_mod
    monkeypatch.setattr(stt_mod, "local_model_support", lambda: (True, ""))
    calls = []
    monkeypatch.setitem(
        sys.modules,
        "huggingface_hub",
        SimpleNamespace(snapshot_download=lambda repo_id: calls.append(repo_id) or "/cache/model"),
    )
    assert download_local_model(DEFAULT_MLX_MODEL) == "/cache/model"
    assert calls == [DEFAULT_MLX_MODEL]


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
