"""OpenRouter integration: API key resolution, model listing, defaults."""

import logging
import os

log = logging.getLogger(__name__)

BASE_URL = "https://openrouter.ai/api/v1"

# Default STT model for the openrouter backend: fast, cheap, strong multilingual.
DEFAULT_STT_MODEL = "deepgram/nova-3"
# Cheap fast chat model for the formatting second pass.
DEFAULT_CHAT_MODEL = "google/gemini-2.5-flash"

# Verified-good /audio/transcriptions model ids.
# Verified 2026-07-18 by probing the live API with a real key (JSON base64 wav
# body; each id returned 200 with {"text": ...}). The public /models catalog
# does NOT list these — they are curated here instead of fetched.
# Known-DEAD ids (400 "does not exist" as of that date): deepgram/nova-2,
# google/chirp-2, mistralai/voxtral-mini-2507.
TRANSCRIPTION_MODELS = [
    "qwen/qwen3-asr-flash-2026-02-10",
    "deepgram/nova-3",
    "google/chirp-3",
    "nvidia/parakeet-tdt-0.6b-v3",
    "mistralai/voxtral-mini-transcribe",
    "microsoft/mai-transcribe-1.5",
    "openai/whisper-1",
    "openai/gpt-4o-transcribe",
    "openai/gpt-4o-mini-transcribe",
]


def transcription_model_ids() -> list[str]:
    """Curated ids that work with /audio/transcriptions (see comment above)."""
    return list(TRANSCRIPTION_MODELS)


def get_api_key(cfg: dict) -> str | None:
    """OPENROUTER_API_KEY env var takes precedence over [openrouter] api_key.

    Defensive: a config bug once saved the key as a TOML array of single
    characters — join list values back into a string.
    """
    env = os.environ.get("OPENROUTER_API_KEY")
    if env:
        return env
    key = (cfg.get("openrouter") or {}).get("api_key") or None
    if isinstance(key, list):
        key = "".join(str(c) for c in key)
        log.warning("openrouter.api_key was a TOML array — joined it back into "
                    "a string. Re-save the key in Settings to fix the file.")
    return key or None


def fetch_models(api_key: str | None = None, base_url: str = BASE_URL,
                 timeout: float = 20) -> list[dict]:
    """GET /models. Returns the raw model list; raises on failure (caller handles)."""
    import httpx

    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    with httpx.Client(timeout=timeout) as client:
        resp = client.get(f"{base_url.rstrip('/')}/models", headers=headers)
        resp.raise_for_status()
        return resp.json().get("data", [])


def _modalities(model: dict, key: str) -> list:
    return ((model.get("architecture") or {}).get(key)) or []


def audio_model_ids(models: list[dict]) -> list[str]:
    """Models that accept audio input (candidates for /audio/transcriptions)."""
    return sorted(m["id"] for m in models
                  if m.get("id") and "audio" in _modalities(m, "input_modalities"))


def text_model_ids(models: list[dict]) -> list[str]:
    """Models that produce text output (candidates for the formatter)."""
    return sorted(m["id"] for m in models
                  if m.get("id") and "text" in _modalities(m, "output_modalities"))
