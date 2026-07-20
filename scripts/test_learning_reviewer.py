#!/usr/bin/env python3
"""Focused script for learning reviewer (mirrors tests/test_learning_reviewer.py).

Run: .venv/bin/python scripts/test_learning_reviewer.py
Exit 0 = all pass. No network.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dictate_core.learning_reviewer import (  # noqa: E402
    ReviewCandidate,
    build_payload,
    parse_candidates,
    review_edit,
    validate_candidate,
)


def main() -> int:
    payload = build_payload(
        model="m", system_prompt="s",
        raw="formatted alarm", inserted="formatted alarm",
        edited="formatter LLM", audio_wav=b"RIFF" + b"\x00" * 40,
    )
    assert any(p.get("type") == "input_audio"
               for p in payload["messages"][1]["content"])

    cands = parse_candidates(
        '```json\n{"candidates":[{"wrong":"alarm","right":"LLM","confidence":0.9}]}\n```'
    )
    assert cands and cands[0].wrong == "alarm"

    ok, _ = validate_candidate(
        ReviewCandidate("alarm", "LLM", 0.9),
        raw="formatted alarm", inserted="formatted alarm",
        edited="formatter LLM", audio_used=True,
    )
    assert ok

    assert review_edit(
        raw="teh", inserted="teh", edited="the",
        cfg={"learning": {"reviewer_enabled": False}, "openrouter": {}},
        chat_post=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no")),
    ) == []

    print("OK learning_reviewer")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
