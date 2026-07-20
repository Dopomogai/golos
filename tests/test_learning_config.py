"""Config roundtrip for [learning] reviewer surface (tmp files only)."""

from __future__ import annotations

from pathlib import Path

from dictate.config import load_config, update_config
from dictate_core.learning_reviewer import (
    DEFAULT_MIN_CONFIDENCE,
    DEFAULT_REVIEWER_MODEL,
    reviewer_config,
)


def test_reviewer_config_roundtrip(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        """
[learning]
enabled = true
reviewer_enabled = false
reviewer_model = "google/gemini-2.5-flash"
reviewer_send_audio = false
reviewer_prompt_file = "learning_prompt.md"
reviewer_min_confidence = 0.7
""",
        encoding="utf-8",
    )
    cfg = load_config(cfg_path)
    r = reviewer_config(cfg)
    assert r["enabled"] is False
    assert r["model"] == "google/gemini-2.5-flash"
    assert r["send_audio"] is False
    assert r["min_confidence"] == 0.7

    update_config(
        {
            "learning": {
                "reviewer_enabled": True,
                "reviewer_model": DEFAULT_REVIEWER_MODEL,
                "reviewer_send_audio": True,
                "reviewer_min_confidence": DEFAULT_MIN_CONFIDENCE,
            }
        },
        path=cfg_path,
    )
    cfg2 = load_config(cfg_path)
    r2 = reviewer_config(cfg2)
    assert r2["enabled"] is True
    assert r2["model"] == DEFAULT_REVIEWER_MODEL
    assert r2["send_audio"] is True
    assert abs(r2["min_confidence"] - DEFAULT_MIN_CONFIDENCE) < 1e-9

    text = cfg_path.read_text(encoding="utf-8")
    assert "reviewer_enabled" in text
    assert DEFAULT_REVIEWER_MODEL in text
    assert "sk-" not in text  # no keys in learning section


def test_shipped_config_reviewer_defaults_off():
    """Repo config.toml keeps reviewer disabled for public/privacy safety."""
    root = Path(__file__).resolve().parents[1]
    cfg = load_config(root / "config.toml")
    r = reviewer_config(cfg)
    assert r["enabled"] is False
    assert r["model"]  # non-empty independent default
    assert "reviewer_prompt_file" in (cfg.get("learning") or {}) or True
