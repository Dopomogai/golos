"""Pure unit tests for dictate_core.learning (from scripts/test_learning.py)."""

from __future__ import annotations

import logging

from dictate_core.learning import (
    extract_replacement_pairs,
    normalize_visible,
    norm_text,
    pair_is_plausible,
    suggest_pairs,
)


def _assert_pairs(full: str, inserted: str, expected: list[tuple[str, str]], label: str):
    got = suggest_pairs(full, inserted)
    assert got == expected, f"{label}: expected {expected!r}, got {got!r}"


def _assert_empty(full: str, inserted: str, label: str):
    got = suggest_pairs(full, inserted)
    assert got == [], f"{label}: expected [], got {got!r}"


def test_teh_to_the():
    _assert_pairs("the", "teh", [("teh", "the")], "teh→the")


def test_golos_case_fix():
    _assert_pairs("Golos", "golos", [("golos", "Golos")], "golos→Golos")


def test_short_phrase_one_word():
    _assert_pairs(
        "hello world", "hello wrld",
        [("wrld", "world")],
        "hello wrld→hello world",
    )


def test_send_email_near_miss():
    _assert_pairs(
        "sent email", "send email",
        [("send", "sent")],
        "send→sent email",
    )


def test_short_multiword_phrase():
    _assert_pairs(
        "a short phrase with one wrong word",
        "a short phrase with one wrong wrd",
        [("wrd", "word")],
        "phrase one wrong word",
    )


def test_wisper_flow_case_under_8_anchor():
    _assert_pairs(
        "wisper Flow", "wisper flow",
        [("flow", "Flow")],
        "wisper flow case under 8-char anchor",
    )


def test_short_insertion_embedded_in_large_field():
    field = ("sidebar chrome " * 8) + "the" + (" trailing status" * 8)
    _assert_empty(field, "teh", "embedded teh→the in large field")


def test_short_phrase_embedded_anchor_7():
    field = ("PREFIX " * 12) + "hello world" + (" SUFFIX" * 12)
    _assert_empty(field, "hello wrld", "embedded hello wrld, anchor 7")


def test_unrelated_short_field():
    _assert_empty("completely different text here", "teh", "unrelated short")


def test_wholesale_rewrite_sameish_length():
    _assert_empty("call me later now", "meeting tomorrow ok", "wholesale rewrite")


def test_wholesale_expand_short_to_long():
    _assert_empty("the quick brown fox jumps", "teh", "expand short→long")


def test_append_still_contains_insertion():
    _assert_empty("teh extra words", "teh", "append")


def test_prepend_still_contains_insertion():
    _assert_empty("pre teh", "teh", "prepend")


def test_punctuation_only_no_pair():
    _assert_empty("tomorrow?", "tomorrow", "punct-only")


def test_unchanged_returns_empty():
    _assert_empty("hello world", "hello world", "unchanged")


def test_implausible_cat_dog():
    _assert_empty("dog", "cat", "implausible cat→dog")


def test_implausible_pair_helper():
    ok, reason = pair_is_plausible("We", "likely")
    assert not ok and reason


def test_empty_inputs():
    _assert_empty("", "teh", "empty field")
    _assert_empty("the", "", "empty insertion")
    _assert_empty("", "", "both empty")


def test_long_insertion_embedded_still_learns():
    ins = "The quick brown fox jumps over the lazy dog with wisper flow today"
    edited = "The quick brown fox jumps over the lazy dog with Wispr Flow today"
    field = ("UI chrome title " * 4) + edited + (" trailer" * 4)
    _assert_pairs(
        field, ins,
        [("wisper flow", "Wispr Flow")],
        "long insertion embedded (12+ anchor)",
    )


def test_scroll_tolerance_tail_visible():
    ins = ("AAAA " * 20) + "the end has a typo wrd here"
    full = "the end has a typo word here"
    _assert_pairs(full, ins, [("wrd", "word")], "scroll-tolerant tail")


def test_eight_char_anchor_with_coverage():
    _assert_pairs(
        "1234567 bagword", "1234567 badword",
        [("badword", "bagword")],
        "exactly 8-char anchor",
    )


def test_twelve_char_anchor_relaxed_coverage():
    ins = "abcdefghijkl wronger"
    full = "abcdefghijkl righter"
    pairs = suggest_pairs(full, ins)
    assert pairs == [("wronger", "righter")]


def test_short_edit_refusal_logs_reason():
    logger = logging.getLogger("dictate_core.learning")
    records: list[logging.LogRecord] = []

    class _H(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = _H()
    handler.setLevel(logging.INFO)
    prev = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        suggest_pairs("x" * 50 + " the " + "y" * 50, "teh")
        suggest_pairs("the", "teh")
    finally:
        logger.removeHandler(handler)
        logger.setLevel(prev)

    refusal = [r for r in records if "short-edit refused" in r.getMessage()]
    assert refusal
    success_noise = [
        r for r in records
        if r.levelno >= logging.INFO
        and "teh" in r.getMessage()
        and "refused" not in r.getMessage()
        and "skipped" not in r.getMessage()
    ]
    assert not success_noise


def test_extract_replacement_min_length():
    assert extract_replacement_pairs("a b", "x b") == []


def test_norm_text_collapses_whitespace():
    assert norm_text("  a   b\tc  ") == "a b c"


def test_normalize_visible_strips_box_drawing():
    assert "│" not in normalize_visible("hello │ world")
    out = normalize_visible("a\n\n\n\nb")
    assert "\n\n\n" not in out


def test_pair_is_plausible_contains():
    ok, _ = pair_is_plausible("ok", "okay")
    assert ok


def test_pair_is_plausible_too_many_tokens():
    ok, reason = pair_is_plausible("a b c d e f g", "a b c d e f h")
    assert not ok
    assert "6 tokens" in reason
