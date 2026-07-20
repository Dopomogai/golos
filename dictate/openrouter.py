"""Compatibility shim — the implementation moved to dictate_core.openrouter."""
from dictate_core.openrouter import *  # noqa: F401,F403
from dictate_core.openrouter import (  # noqa: F401
    BASE_URL, DEFAULT_CHAT_MODEL, DEFAULT_STT_MODEL, TRANSCRIPTION_MODELS,
    audio_model_ids, fetch_models, get_api_key, text_model_ids,
    transcription_model_ids,
)
