"""Unit tests for dictate_core.learning_reviewer (no network)."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from dictate_core.learning_reviewer import (
    DEFAULT_MIN_CONFIDENCE,
    DEFAULT_REVIEWER_MODEL,
    ReviewCandidate,
    build_payload,
    build_user_text,
    candidates_to_pairs,
    extract_json_object,
    filter_candidates,
    parse_candidates,
    read_wav_bytes,
    review_edit,
    reviewer_config,
    validate_candidate,
)
from dictate.learning import append_suggestions, propose_pairs


def _minimal_wav(path: Path) -> Path:
    """Write a tiny valid-enough WAV (header + silence)."""
    # 44-byte header + 16 samples of silence @ 16kHz mono 16-bit
    import struct
    n_samples = 16
    data_size = n_samples * 2
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + data_size, b"WAVE", b"fmt ", 16,
        1, 1, 16000, 32000, 2, 16, b"data", data_size,
    )
    path.write_bytes(header + b"\x00" * data_size)
    return path


def _cfg(**learning_overrides):
    learning = {
        "enabled": True,
        "reviewer_enabled": True,
        "reviewer_model": DEFAULT_REVIEWER_MODEL,
        "reviewer_send_audio": True,
        "reviewer_min_confidence": DEFAULT_MIN_CONFIDENCE,
    }
    learning.update(learning_overrides)
    return {
        "learning": learning,
        "openrouter": {"api_key": "sk-test"},
        "paths": {},
    }


# ---------------------------------------------------------------------------
# Payload construction
# ---------------------------------------------------------------------------


def test_audio_payload_includes_wav_and_text_evidence(tmp_path):
    wav = _minimal_wav(tmp_path / "clip.wav").read_bytes()
    payload = build_payload(
        model="m",
        system_prompt="sys",
        raw="formatted alarm",
        inserted="formatted alarm",
        edited="formatter LLM",
        audio_wav=wav,
    )
    user = payload["messages"][1]["content"]
    assert isinstance(user, list)
    types = {p["type"] for p in user}
    assert "input_audio" in types
    assert "text" in types
    audio_part = next(p for p in user if p["type"] == "input_audio")
    assert audio_part["input_audio"]["format"] == "wav"
    decoded = base64.b64decode(audio_part["input_audio"]["data"])
    assert decoded == wav
    text_part = next(p for p in user if p["type"] == "text")
    assert "RAW_TRANSCRIPT" in text_part["text"]
    assert "formatted alarm" in text_part["text"]
    assert "EDITED_TEXT" in text_part["text"]
    assert "formatter LLM" in text_part["text"]
    assert payload["model"] == "m"
    assert payload["response_format"]["type"] == "json_object"


def test_text_only_payload_when_audio_absent():
    payload = build_payload(
        model="m",
        system_prompt="sys",
        raw="teh",
        inserted="teh",
        edited="the",
        audio_wav=None,
    )
    user = payload["messages"][1]["content"]
    assert isinstance(user, str)
    assert "teh" in user
    assert "the" in user


def test_text_only_when_send_audio_off(tmp_path):
    wav_path = str(_minimal_wav(tmp_path / "a.wav"))
    calls = []

    def chat_post(payload, headers, timeout):
        calls.append(payload)
        return json.dumps({"candidates": []})

    review_edit(
        raw="teh", inserted="teh", edited="the",
        cfg=_cfg(reviewer_send_audio=False),
        audio_path=wav_path,
        chat_post=chat_post,
    )
    assert calls
    user = calls[0]["messages"][1]["content"]
    assert isinstance(user, str)


def test_text_only_when_audio_path_missing():
    calls = []

    def chat_post(payload, headers, timeout):
        calls.append(payload)
        return json.dumps({"candidates": []})

    review_edit(
        raw="teh", inserted="teh", edited="the",
        cfg=_cfg(reviewer_send_audio=True),
        audio_path=None,
        chat_post=chat_post,
    )
    user = calls[0]["messages"][1]["content"]
    assert isinstance(user, str)


def test_user_text_caps_large_edited_field():
    edited = "x" * 10_000
    text = build_user_text(raw="a", inserted="a", edited=edited)
    assert len(text) < 10_000


# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------


def test_parse_clean_json():
    body = json.dumps({
        "candidates": [
            {"wrong": "teh", "right": "the", "confidence": 0.9, "reason": "typo"},
        ]
    })
    cands = parse_candidates(body)
    assert cands is not None
    assert len(cands) == 1
    assert cands[0].wrong == "teh"
    assert cands[0].right == "the"
    assert cands[0].confidence == 0.9


def test_parse_fenced_json():
    body = 'Here you go:\n```json\n{"candidates":[{"wrong":"a","right":"b"}]}\n```\n'
    cands = parse_candidates(body)
    assert cands is not None
    assert cands[0].wrong == "a"


def test_parse_malformed_returns_none():
    assert parse_candidates("not json at all") is None
    assert parse_candidates("") is None
    assert extract_json_object("[1,2,3]") is None


def test_parse_single_object_without_candidates_array():
    body = '{"wrong":"x","right":"y","confidence":0.8}'
    cands = parse_candidates(body)
    assert cands is not None
    assert cands[0].wrong == "x"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_validate_near_miss_text_only():
    ok, _ = validate_candidate(
        ReviewCandidate("teh", "the", 0.9),
        raw="teh", inserted="teh", edited="the",
        min_confidence=0.5, audio_used=False,
    )
    assert ok


def test_validate_audio_low_similarity_alarm_to_llm():
    ok, _ = validate_candidate(
        ReviewCandidate("alarm", "LLM", 0.85),
        raw="formatted alarm",
        inserted="formatted alarm",
        edited="formatter LLM",
        min_confidence=0.5,
        audio_used=True,
    )
    assert ok


def test_reject_audio_low_similarity_without_audio_flag():
    # "formatter" vs "neural" is far below the 0.5 similarity gate;
    # "alarm"/"LLM" is exactly 0.5 and would still pass text-only.
    ok, reason = validate_candidate(
        ReviewCandidate("formatter", "neural", 0.85),
        raw="formatter alarm",
        inserted="formatter alarm",
        edited="neural LLM",
        min_confidence=0.5,
        audio_used=False,
    )
    assert not ok
    assert reason


def test_audio_allows_far_pair_text_only_rejects():
    cand = ReviewCandidate("formatter", "neural", 0.9)
    ok_audio, _ = validate_candidate(
        cand, raw="formatter alarm", inserted="formatter alarm",
        edited="neural LLM", min_confidence=0.5, audio_used=True,
    )
    ok_text, _ = validate_candidate(
        cand, raw="formatter alarm", inserted="formatter alarm",
        edited="neural LLM", min_confidence=0.5, audio_used=False,
    )
    assert ok_audio
    assert not ok_text


def test_reject_hallucinated_right():
    ok, reason = validate_candidate(
        ReviewCandidate("teh", "xyzzy", 0.99),
        raw="teh", inserted="teh", edited="the",
        min_confidence=0.5, audio_used=True,
    )
    assert not ok
    assert "right not in edited" in reason


def test_reject_absent_wrong():
    ok, reason = validate_candidate(
        ReviewCandidate("missing", "the", 0.99),
        raw="teh", inserted="teh", edited="the",
        min_confidence=0.5, audio_used=True,
    )
    assert not ok
    assert "wrong not in raw" in reason


def test_min_confidence_gate():
    ok, reason = validate_candidate(
        ReviewCandidate("teh", "the", 0.2),
        raw="teh", inserted="teh", edited="the",
        min_confidence=0.55, audio_used=False,
    )
    assert not ok
    assert "confidence" in reason


def test_bounded_length_rejection():
    long_w = "word " * 10
    ok, reason = validate_candidate(
        ReviewCandidate(long_w.strip(), "short", 0.9),
        raw=long_w, inserted=long_w, edited="short",
        min_confidence=0.1, audio_used=True,
    )
    assert not ok


def test_filter_candidates_dedupes():
    cands = [
        ReviewCandidate("teh", "the", 0.9),
        ReviewCandidate("teh", "the", 0.8),
    ]
    out = filter_candidates(
        cands, raw="teh", inserted="teh", edited="the",
        min_confidence=0.5, audio_used=False,
    )
    assert len(out) == 1


# ---------------------------------------------------------------------------
# review_edit + fallback
# ---------------------------------------------------------------------------


def test_reviewer_disabled_returns_empty():
    def boom(*a, **k):
        raise AssertionError("should not call network")

    out = review_edit(
        raw="teh", inserted="teh", edited="the",
        cfg=_cfg(reviewer_enabled=False),
        chat_post=boom,
    )
    assert out == []


def test_reviewer_api_error_returns_empty():
    def boom(*a, **k):
        raise RuntimeError("network down")

    out = review_edit(
        raw="teh", inserted="teh", edited="the",
        cfg=_cfg(),
        chat_post=boom,
    )
    assert out == []


def test_reviewer_malformed_returns_empty():
    out = review_edit(
        raw="teh", inserted="teh", edited="the",
        cfg=_cfg(),
        chat_post=lambda *a, **k: "not-json",
    )
    assert out == []


def test_reviewer_success_path(tmp_path):
    wav = str(_minimal_wav(tmp_path / "c.wav"))

    def chat_post(payload, headers, timeout):
        assert "Bearer sk-test" in headers["Authorization"]
        user = payload["messages"][1]["content"]
        assert isinstance(user, list)
        return json.dumps({
            "candidates": [
                {"wrong": "alarm", "right": "LLM", "confidence": 0.9},
            ]
        })

    out = review_edit(
        raw="formatted alarm",
        inserted="formatted alarm",
        edited="formatter LLM",
        cfg=_cfg(),
        audio_path=wav,
        chat_post=chat_post,
    )
    assert len(out) == 1
    assert out[0].wrong == "alarm"
    assert out[0].right == "LLM"


def test_propose_pairs_reviewer_then_dedupe_flag():
    calls = {"n": 0}

    def chat_post(payload, headers, timeout):
        calls["n"] += 1
        return json.dumps({
            "candidates": [
                {"wrong": "teh", "right": "the", "confidence": 0.9},
            ]
        })

    li = {"raw": "teh", "final": "teh", "audio_path": None}
    cfg = _cfg()
    pairs1, meta1 = propose_pairs(li, "the", cfg, chat_post=chat_post)
    assert pairs1 == [("teh", "the")]
    assert meta1["from_reviewer"] is True
    assert li["_reviewer_done"] is True

    # Second call must not hit the network again.
    pairs2, meta2 = propose_pairs(li, "the", cfg, chat_post=chat_post)
    assert calls["n"] == 1
    # Deterministic fallback still works after reviewer is done.
    assert pairs2 == [("teh", "the")]
    assert meta2["from_reviewer"] is False


def test_propose_pairs_fallback_on_empty_reviewer():
    def chat_post(*a, **k):
        return json.dumps({"candidates": []})

    li = {"raw": "hello wrld", "final": "hello wrld"}
    pairs, meta = propose_pairs(li, "hello world", _cfg(), chat_post=chat_post)
    assert pairs == [("wrld", "world")]
    assert meta["provenance"] == "deterministic"


def test_propose_pairs_untouched_does_not_burn_reviewer():
    def boom(*a, **k):
        raise AssertionError("no network for untouched")

    li = {"raw": "hello", "final": "hello"}
    pairs, _ = propose_pairs(li, "hello there hello", _cfg(), chat_post=boom)
    assert pairs == []
    assert "_reviewer_done" not in li


def test_append_suggestions_provenance(tmp_path):
    path = str(tmp_path / "suggestions.jsonl")
    append_suggestions(
        path, "Notes",
        [("teh", "the")],
        provenance="reviewer",
        model="m",
        confidence=0.9,
    )
    row = json.loads(Path(path).read_text().strip())
    assert row["wrong"] == "teh"
    assert row["provenance"] == "reviewer"
    assert row["model"] == "m"
    assert row["confidence"] == 0.9


def test_reviewer_config_defaults():
    r = reviewer_config({})
    assert r["enabled"] is False
    assert r["model"] == DEFAULT_REVIEWER_MODEL
    assert r["send_audio"] is True


def test_read_wav_bytes(tmp_path):
    p = _minimal_wav(tmp_path / "x.wav")
    assert read_wav_bytes(p) is not None
    assert read_wav_bytes(tmp_path / "missing.wav") is None
    assert read_wav_bytes(None) is None


def test_candidates_to_pairs():
    assert candidates_to_pairs([
        ReviewCandidate("a", "b", 0.9),
    ]) == [("a", "b")]


def test_last_insertion_audio_path_shape():
    """last_insertion contract: path string only, no bytes."""
    li = {
        "ts": 1.0,
        "raw": "x",
        "final": "x",
        "audio_path": "/tmp/fake.wav",
    }
    assert isinstance(li["audio_path"], str)
    assert not isinstance(li["audio_path"], (bytes, bytearray))
