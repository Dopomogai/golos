"""OpenRouter pure helpers (no network unless mocked)."""

from __future__ import annotations

from dictate_core.openrouter import (
    DEFAULT_CHAT_MODEL,
    DEFAULT_STT_MODEL,
    TRANSCRIPTION_MODELS,
    audio_model_ids,
    get_api_key,
    text_model_ids,
    transcription_model_ids,
)


def test_transcription_model_ids_is_copy():
    ids = transcription_model_ids()
    assert ids == TRANSCRIPTION_MODELS
    ids.append("x")
    assert "x" not in TRANSCRIPTION_MODELS


def test_defaults_nonempty():
    assert DEFAULT_STT_MODEL
    assert DEFAULT_CHAT_MODEL
    assert "deepgram/nova-3" in TRANSCRIPTION_MODELS


def test_get_api_key_env_wins(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "from-env")
    assert get_api_key({"openrouter": {"api_key": "from-cfg"}}) == "from-env"


def test_get_api_key_from_config(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert get_api_key({"openrouter": {"api_key": "cfg-key"}}) == "cfg-key"
    assert get_api_key({}) is None
    assert get_api_key({"openrouter": {}}) is None


def test_get_api_key_joins_char_array(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert get_api_key({"openrouter": {"api_key": list("sk-ab")}}) == "sk-ab"


def test_audio_and_text_model_ids():
    models = [
        {"id": "a", "architecture": {"input_modalities": ["audio", "text"],
                                     "output_modalities": ["text"]}},
        {"id": "b", "architecture": {"input_modalities": ["text"],
                                     "output_modalities": ["text"]}},
        {"id": "c", "architecture": {"input_modalities": ["audio"],
                                     "output_modalities": ["audio"]}},
        {"architecture": {}},  # no id
    ]
    assert audio_model_ids(models) == ["a", "c"]
    assert text_model_ids(models) == ["a", "b"]
