"""Formatter prompt/context rendering and local correction behavior (no network)."""

from __future__ import annotations

from dictate_core.formatter import (
    DEFAULT_TEMPLATE,
    Formatter,
    apply_literal_corrections,
    render_context_block,
    render_context_rules,
)


def test_apply_literal_corrections_case_insensitive_word_boundary():
    text = "Teh quick xtehy and teh"
    out = apply_literal_corrections(text, [("teh", "the")])
    # word-boundary: substring inside xtehy must not match; "Teh" and trailing teh do
    assert out == "the quick xtehy and the"


def test_apply_literal_corrections_multiword_and_all_occurrences():
    text = "wisper flow then wisper flow"
    out = apply_literal_corrections(text, [("wisper flow", "Wispr Flow")])
    assert out == "Wispr Flow then Wispr Flow"


def test_apply_literal_corrections_empty_wrong_skipped():
    assert apply_literal_corrections("hello", [("", "x")]) == "hello"


def test_render_context_block_labels_and_visible_text():
    block = render_context_block({
        "app_name": "Slack",
        "bundle_id": "com.tinyspeck.slackmacgap",
        "window_title": "#dev",
        "visible_text": "hello context",
        "custom_key": "custom value",
        "empty": "",
    })
    assert "Application: Slack" in block
    assert "Bundle ID: com.tinyspeck.slackmacgap" in block
    assert "Window title: #dev" in block
    assert "VISIBLE TEXT" in block
    assert "hello context" in block
    assert "custom_key: custom value" in block


def test_render_context_block_empty():
    assert "(no context available)" in render_context_block({})


def test_render_context_rules_conditional():
    assert render_context_rules({}) == ""
    refs = render_context_rules({"app_name": "X"})
    assert "CONTEXT describes" in refs
    cont = render_context_rules({"text_before_cursor": "hi"})
    assert "Continue naturally" in cont
    cite = render_context_rules({"visible_text": "body"})
    assert "VISIBLE TEXT" in cite or "Quote the VISIBLE" in cite


def test_formatter_disabled_without_key_passthrough():
    fmt = Formatter(
        {"formatting": {"enabled": True, "provider": "openrouter"}, "openrouter": {}},
        ["golos"],
        [("teh", "the")],
    )
    assert fmt.enabled is False
    assert fmt.format("raw transcript") == "raw transcript"


def test_formatter_empty_raw_passthrough_when_enabled():
    fmt = Formatter(
        {
            "formatting": {"enabled": True, "provider": "openrouter", "model": "m"},
            "openrouter": {"api_key": "sk-test"},
        },
        [],
        [],
    )
    assert fmt.enabled is True
    assert fmt.format("   ") == "   "


def test_build_system_prompt_transcribe_mode():
    fmt = Formatter(
        {
            "formatting": {
                "enabled": True,
                "provider": "openrouter",
                "answer_questions": False,
            },
            "openrouter": {"api_key": "sk-test"},
        },
        ["golos"],
        [("teh", "the")],
    )
    prompt = fmt.build_system_prompt({
        "app_name": "Slack",
        "window_title": "#dev",
        "visible_text": "look here",
    })
    assert "transcription cleaner" in prompt
    assert "NEVER answer" in prompt
    assert "golos" in prompt
    assert '"teh" -> "the"' in prompt
    assert "Application: Slack" in prompt
    assert "look here" in prompt
    assert "cleaned dictation" in prompt.lower() or "Remember:" in prompt


def test_build_system_prompt_answer_mode():
    fmt = Formatter(
        {
            "formatting": {
                "enabled": True,
                "provider": "openrouter",
                "answer_questions": True,
            },
            "openrouter": {"api_key": "sk-test"},
        },
        [],
        [],
    )
    prompt = fmt.build_system_prompt({"app_name": "Notes"})
    assert "EXCEPTION" in prompt or "direct question" in prompt
    assert "transcription cleaner, NOT an assistant" not in prompt


def test_build_system_prompt_kwargs_compat():
    fmt = Formatter(
        {"formatting": {"enabled": False}, "openrouter": {"api_key": "k"}},
        [],
        [],
    )
    prompt = fmt.build_system_prompt(None, app_name="Terminal", window_title="bash")
    assert "Terminal" in prompt
    assert "bash" in prompt


def test_set_vocabulary_live_update():
    fmt = Formatter(
        {"formatting": {"enabled": False}, "openrouter": {}},
        ["a"],
        [],
    )
    fmt.set_vocabulary(["b"], [("x", "y")])
    assert fmt.dictionary_terms == ["b"]
    assert fmt.corrections == [("x", "y")]
    prompt = fmt.build_system_prompt({})
    assert "b" in prompt
    assert '"x" -> "y"' in prompt


def test_default_template_has_placeholders():
    for token in (
        "{{mode_rules}}",
        "{{corrections}}",
        "{{dictionary}}",
        "{{context_block}}",
        "{{context_rules}}",
    ):
        assert token in DEFAULT_TEMPLATE


def test_formatter_network_failure_returns_raw(monkeypatch):
    """Mocked httpx failure must passthrough raw (no live API)."""
    fmt = Formatter(
        {
            "formatting": {"enabled": True, "provider": "openrouter"},
            "openrouter": {"api_key": "sk-test"},
        },
        [],
        [],
    )

    class BoomClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **k):
            raise RuntimeError("network down")

    import httpx
    monkeypatch.setattr(httpx, "Client", BoomClient)
    assert fmt.format("keep me") == "keep me"
