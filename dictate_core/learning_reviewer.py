"""Optional OpenRouter learning-review stage (audio-aware, human-gated).

Runs after a user manually edits a recent insertion. Builds a multimodal
(or text-only) chat request, parses a strict JSON candidate list, and
validates each (wrong, right) pair against the raw transcript, inserted
text, and observed edit. Nothing is applied automatically — callers only
record suggestions for explicit human approval.

Deterministic dictate_core.learning.suggest_pairs remains the offline /
failure / disabled fallback (invoked by the app layer, not here).

Privacy: when reviewer_send_audio is true and a retained WAV path is
available, that file is base64-attached as input_audio. Keys and audio
bytes must never be logged. Edited field text is capped before send.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

# Audio-capable default independent of [formatting] model.
DEFAULT_REVIEWER_MODEL = "google/gemini-3.1-flash-lite-preview"
DEFAULT_MIN_CONFIDENCE = 0.55
DEFAULT_PROMPT_FILE = "learning_prompt.md"
DEFAULT_TIMEOUT = 25.0

# Bounds — never ship a whole large document to the model.
MAX_FIELD_CHARS = 4_000
MAX_TRANSCRIPT_CHARS = 2_000
MAX_PAIR_CHARS = 80
MAX_PAIR_TOKENS = 6
MAX_CANDIDATES = 5

DEFAULT_REVIEWER_PROMPT = """\
You are a dictation learning reviewer. The user dictated speech that was
transcribed (raw) and optionally reformatted (inserted). They then manually
edited the inserted text. Your job is to propose small correction pairs the
app can learn from — only real STT/formatting mistakes the user fixed.

Evidence you receive:
- RAW_TRANSCRIPT: what speech-to-text produced
- INSERTED_TEXT: what was typed into the app (after optional formatting)
- EDITED_TEXT: the field after the user paused editing
- Optional: original audio of the dictation (listen when present)

Rules:
- Propose only short replacement pairs (wrong → right).
- wrong MUST appear in RAW_TRANSCRIPT or INSERTED_TEXT.
- right MUST appear in EDITED_TEXT.
- wrong and right must differ and each be at most 6 words / 80 characters.
- Prefer STT confusions and proper-noun fixes (e.g. alarm→LLM when audio
  confirms "LLM", wisper→Wispr). Ignore pure style rewrites, punctuation-only
  edits, and unrelated surrounding text.
- If audio is present, you may confirm low string-similarity pairs when the
  audio clearly supports "right" over "wrong".
- If nothing credible, return an empty candidates list.
- Output STRICT JSON only — no markdown fences, no commentary.

Schema:
{"candidates":[{"wrong":"...","right":"...","confidence":0.0,"reason":"..."}]}
confidence is 0..1. reason is a short optional string.
"""


@dataclass(frozen=True)
class ReviewCandidate:
    wrong: str
    right: str
    confidence: float | None = None
    reason: str | None = None


# Injected HTTP client for unit tests: (payload, headers, timeout) -> response body str
ChatPost = Callable[[dict, dict, float], str]


def prompt_file_path(name: str) -> Path:
    """Resolve a prompt file path; relative names live under ~/.golos/."""
    p = Path(name)
    return p if p.is_absolute() else Path.home() / ".golos" / p


def load_reviewer_prompt(cfg: dict | None = None) -> str:
    """Load the learning-review system prompt (file or built-in default)."""
    learning = (cfg or {}).get("learning") or {}
    path = prompt_file_path(learning.get("reviewer_prompt_file", DEFAULT_PROMPT_FILE))
    if path.exists():
        try:
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return text
        except OSError as e:
            log.warning("Could not read learning prompt %s (%s); using default.",
                        path, e)
    return DEFAULT_REVIEWER_PROMPT


def reviewer_config(cfg: dict) -> dict:
    """Normalized [learning] reviewer settings (does not mutate cfg)."""
    learning = cfg.get("learning") or {}
    return {
        "enabled": bool(learning.get("reviewer_enabled", False)),
        "model": learning.get("reviewer_model") or DEFAULT_REVIEWER_MODEL,
        "send_audio": bool(learning.get("reviewer_send_audio", True)),
        "prompt_file": learning.get("reviewer_prompt_file", DEFAULT_PROMPT_FILE),
        "min_confidence": float(learning.get("reviewer_min_confidence",
                                             DEFAULT_MIN_CONFIDENCE)),
        "timeout": float(learning.get("reviewer_timeout", DEFAULT_TIMEOUT)),
    }


def _cap(text: str, n: int) -> str:
    if len(text) <= n:
        return text
    return text[:n]


def build_user_text(*, raw: str, inserted: str, edited: str) -> str:
    """Bounded evidence block for the user message (no audio)."""
    return (
        f"RAW_TRANSCRIPT:\n{_cap(raw or '', MAX_TRANSCRIPT_CHARS)}\n\n"
        f"INSERTED_TEXT:\n{_cap(inserted or '', MAX_TRANSCRIPT_CHARS)}\n\n"
        f"EDITED_TEXT:\n{_cap(edited or '', MAX_FIELD_CHARS)}\n"
    )


def read_wav_bytes(audio_path: str | Path | None) -> bytes | None:
    """Load WAV bytes from a retained path. None if missing/unreadable."""
    if not audio_path:
        return None
    try:
        p = Path(audio_path)
        if not p.is_file():
            log.info("Learning reviewer: audio path not found (text-only).")
            return None
        data = p.read_bytes()
        if len(data) < 44:  # smaller than a minimal wav header
            log.info("Learning reviewer: audio file too small (text-only).")
            return None
        return data
    except OSError as e:
        log.info("Learning reviewer: could not read audio (%s); text-only.", e)
        return None


def build_messages(
    *,
    system_prompt: str,
    raw: str,
    inserted: str,
    edited: str,
    audio_wav: bytes | None = None,
) -> list[dict]:
    """OpenAI-compatible messages; multimodal when audio_wav is set."""
    user_text = build_user_text(raw=raw, inserted=inserted, edited=edited)
    if audio_wav:
        user_content: Any = [
            {
                "type": "input_audio",
                "input_audio": {
                    "data": base64.b64encode(audio_wav).decode("ascii"),
                    "format": "wav",
                },
            },
            {"type": "text", "text": user_text},
        ]
    else:
        user_content = user_text
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]


def build_payload(
    *,
    model: str,
    system_prompt: str,
    raw: str,
    inserted: str,
    edited: str,
    audio_wav: bytes | None = None,
) -> dict:
    """Full chat/completions JSON body (no network)."""
    return {
        "model": model,
        "messages": build_messages(
            system_prompt=system_prompt,
            raw=raw,
            inserted=inserted,
            edited=edited,
            audio_wav=audio_wav,
        ),
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }


_FENCE_RE = re.compile(
    r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE
)


def extract_json_object(text: str) -> dict | None:
    """Parse a JSON object from model output (fences / leading prose OK).

    Returns None on malformed or non-object JSON. Never raises.
    """
    if not text or not str(text).strip():
        return None
    s = str(text).strip()
    # Prefer fenced blocks when present.
    m = _FENCE_RE.search(s)
    if m:
        s = m.group(1).strip()
    # First {...} span if extra prose remains.
    if not s.startswith("{"):
        start = s.find("{")
        end = s.rfind("}")
        if start < 0 or end <= start:
            return None
        s = s[start:end + 1]
    try:
        obj = json.loads(s)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def parse_candidates(response_text: str) -> list[ReviewCandidate] | None:
    """Parse structured candidates. None = malformed/untrusted; [] = empty ok."""
    obj = extract_json_object(response_text)
    if obj is None:
        return None
    raw_list = obj.get("candidates")
    if raw_list is None and "wrong" in obj and "right" in obj:
        raw_list = [obj]
    if not isinstance(raw_list, list):
        return None
    out: list[ReviewCandidate] = []
    for item in raw_list[:MAX_CANDIDATES * 2]:  # soft cap before validation
        if not isinstance(item, dict):
            continue
        wrong = item.get("wrong")
        right = item.get("right")
        if not isinstance(wrong, str) or not isinstance(right, str):
            continue
        conf = item.get("confidence")
        confidence: float | None
        if conf is None:
            confidence = None
        else:
            try:
                confidence = float(conf)
            except (TypeError, ValueError):
                confidence = None
        reason = item.get("reason")
        if reason is not None and not isinstance(reason, str):
            reason = str(reason)
        out.append(ReviewCandidate(
            wrong=wrong.strip(),
            right=right.strip(),
            confidence=confidence,
            reason=reason.strip() if isinstance(reason, str) else None,
        ))
    return out


def _contains_span(haystack: str, needle: str) -> bool:
    if not needle:
        return False
    return needle in haystack


def validate_candidate(
    cand: ReviewCandidate,
    *,
    raw: str,
    inserted: str,
    edited: str,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    audio_used: bool = False,
) -> tuple[bool, str]:
    """Accept only bounded, evidence-backed replacements.

    wrong must occur in raw or inserted; right must occur in edited.
    With audio, low string-similarity pairs may pass (e.g. alarm→LLM).
    Without audio, near-miss similarity still applies via pair_is_plausible.
    """
    wrong, right = cand.wrong, cand.right
    if not wrong or not right:
        return False, "empty wrong or right"
    if wrong == right:
        return False, "identical"
    if len(wrong) > MAX_PAIR_CHARS or len(right) > MAX_PAIR_CHARS:
        return False, "pair too long"
    if len(wrong.split()) > MAX_PAIR_TOKENS or len(right.split()) > MAX_PAIR_TOKENS:
        return False, "too many tokens"
    if cand.confidence is not None and cand.confidence < min_confidence:
        return False, f"confidence {cand.confidence:.2f} < {min_confidence:.2f}"
    # If confidence is omitted, treat as meeting the threshold only when
    # evidence gates pass (callers may still filter).
    if not (_contains_span(raw, wrong) or _contains_span(inserted, wrong)):
        return False, "wrong not in raw/inserted"
    if not _contains_span(edited, right):
        return False, "right not in edited"
    if not audio_used:
        from .learning import pair_is_plausible
        ok, reason = pair_is_plausible(wrong, right)
        if not ok:
            return False, reason or "not similar enough"
    return True, ""


def filter_candidates(
    candidates: list[ReviewCandidate],
    *,
    raw: str,
    inserted: str,
    edited: str,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    audio_used: bool = False,
) -> list[ReviewCandidate]:
    """Validate and dedupe candidates (first occurrence wins)."""
    seen: set[tuple[str, str]] = set()
    out: list[ReviewCandidate] = []
    for cand in candidates:
        ok, reason = validate_candidate(
            cand, raw=raw, inserted=inserted, edited=edited,
            min_confidence=min_confidence, audio_used=audio_used,
        )
        if not ok:
            log.debug("Reviewer discarded %r -> %r: %s",
                      cand.wrong, cand.right, reason)
            continue
        key = (cand.wrong, cand.right)
        if key in seen:
            continue
        seen.add(key)
        out.append(cand)
        if len(out) >= MAX_CANDIDATES:
            break
    return out


def _default_chat_post(payload: dict, headers: dict, timeout: float) -> str:
    """Live OpenRouter /chat/completions POST (not used in unit tests)."""
    import httpx
    from .openrouter import BASE_URL

    with httpx.Client(timeout=timeout) as client:
        resp = client.post(
            f"{BASE_URL}/chat/completions",
            json=payload,
            headers=headers,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


def review_edit(
    *,
    raw: str,
    inserted: str,
    edited: str,
    cfg: dict,
    audio_path: str | None = None,
    chat_post: ChatPost | None = None,
) -> list[ReviewCandidate]:
    """Run the learning reviewer; return validated candidates (may be empty).

    Returns [] when disabled, missing key, missing edit evidence, API error,
    malformed response, or no credible candidates. Never raises for expected
    failure modes. Does not auto-promote.

    Audio: only uses `audio_path` when reviewer_send_audio is true and the
    path points at an existing retained WAV. Does not retain or invent audio.
    """
    rcfg = reviewer_config(cfg)
    if not rcfg["enabled"]:
        return []
    if not (raw or inserted) or not edited:
        return []

    from .openrouter import get_api_key

    api_key = get_api_key(cfg)
    if not api_key:
        log.info("Learning reviewer: no API key; skipping.")
        return []

    audio_wav = None
    audio_used = False
    if rcfg["send_audio"]:
        if audio_path:
            audio_wav = read_wav_bytes(audio_path)
            audio_used = audio_wav is not None
            if not audio_used:
                log.info("Learning reviewer: send_audio on but no usable WAV "
                         "(text-only).")
        else:
            log.info("Learning reviewer: send_audio on but no audio_path "
                     "(text-only; keep_recordings may be false).")
    # else: text-only by user choice

    system_prompt = load_reviewer_prompt(cfg)
    payload = build_payload(
        model=rcfg["model"],
        system_prompt=system_prompt,
        raw=raw,
        inserted=inserted,
        edited=edited,
        audio_wav=audio_wav,
    )
    # Never log payload contents (prompt / base64 audio / full edited field).
    log.info("Learning reviewer: model=%s audio=%s field_chars=%d",
             rcfg["model"], audio_used, len(edited or ""))

    headers = {"Authorization": f"Bearer {api_key}"}
    post = chat_post or _default_chat_post
    try:
        body = post(payload, headers, rcfg["timeout"])
    except Exception as e:
        log.warning("Learning reviewer request failed (%s).", e)
        return []

    parsed = parse_candidates(body if isinstance(body, str) else str(body))
    if parsed is None:
        log.warning("Learning reviewer: malformed JSON response.")
        return []
    return filter_candidates(
        parsed,
        raw=raw or "",
        inserted=inserted or "",
        edited=edited or "",
        min_confidence=rcfg["min_confidence"],
        audio_used=audio_used,
    )


def candidates_to_pairs(
    candidates: list[ReviewCandidate],
) -> list[tuple[str, str]]:
    """Map validated candidates to (wrong, right) tuples."""
    return [(c.wrong, c.right) for c in candidates]
