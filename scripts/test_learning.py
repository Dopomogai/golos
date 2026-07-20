#!/usr/bin/env python3
"""Unit tests for dictate_core.learning — short-edit confidence path + gates.

Covers whole-field near-miss learning (teh→the, golos→Golos, short phrases),
embedded short-anchor refusal, appends/prepends, punctuation-only, wholesale
rewrites, implausible pairs, and unchanged long-insertion 8/12-char behavior.

Run: .venv/bin/python scripts/test_learning.py
Exit 0 = all pass.
"""

from __future__ import annotations

import logging

from dictate_core.learning import (
    extract_replacement_pairs,
    pair_is_plausible,
    suggest_pairs,
)


def _assert_pairs(full: str, inserted: str, expected: list[tuple[str, str]], label: str):
    got = suggest_pairs(full, inserted)
    assert got == expected, f"{label}: expected {expected!r}, got {got!r}"


def _assert_empty(full: str, inserted: str, label: str):
    got = suggest_pairs(full, inserted)
    assert got == [], f"{label}: expected [], got {got!r}"


# ---------------------------------------------------------------------------
# Happy paths: short whole-field near-miss
# ---------------------------------------------------------------------------

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
    # anchor max is " email" (6) — short path must accept whole-field near-miss
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
    # "wisper " is 7 exact chars (case split on Flow/flow) — short path
    _assert_pairs(
        "wisper Flow", "wisper flow",
        [("flow", "Flow")],
        "wisper flow case under 8-char anchor",
    )


# ---------------------------------------------------------------------------
# Embedded / large field: short anchors must NOT learn
# ---------------------------------------------------------------------------

def test_short_insertion_embedded_in_large_field():
    # Corrected "teh"→"the" buried in a large field: ambiguous 1–7 anchor.
    field = ("sidebar chrome " * 8) + "the" + (" trailing status" * 8)
    _assert_empty(field, "teh", "embedded teh→the in large field")


def test_short_phrase_embedded_anchor_7():
    # "hello wrld" corrected inside surrounding UI text; longest exact
    # block is 7 ("hello w") — must refuse without trustworthy 8/12 anchor.
    field = ("PREFIX " * 12) + "hello world" + (" SUFFIX" * 12)
    _assert_empty(field, "hello wrld", "embedded hello wrld, anchor 7")


def test_unrelated_short_field():
    _assert_empty("completely different text here", "teh", "unrelated short")


# ---------------------------------------------------------------------------
# Negative: rewrites, appends, prepends, punct, implausible
# ---------------------------------------------------------------------------

def test_wholesale_rewrite_sameish_length():
    _assert_empty("call me later now", "meeting tomorrow ok", "wholesale rewrite")


def test_wholesale_expand_short_to_long():
    _assert_empty("the quick brown fox jumps", "teh", "expand short→long")


def test_append_still_contains_insertion():
    # Pure append: insertion still present → early exit, no pairs
    _assert_empty("teh extra words", "teh", "append")


def test_prepend_still_contains_insertion():
    _assert_empty("pre teh", "teh", "prepend")


def test_punctuation_only_no_pair():
    # Token match is punctuation-insensitive; no replace opcode
    _assert_empty("tomorrow?", "tomorrow", "punct-only")


def test_unchanged_returns_empty():
    _assert_empty("hello world", "hello world", "unchanged")


def test_implausible_cat_dog():
    _assert_empty("dog", "cat", "implausible cat→dog")


def test_implausible_pair_helper():
    ok, reason = pair_is_plausible("We", "likely")
    assert not ok and reason, f"expected implausible, got {ok}, {reason!r}"


def test_empty_inputs():
    _assert_empty("", "teh", "empty field")
    _assert_empty("the", "", "empty insertion")
    _assert_empty("", "", "both empty")


# ---------------------------------------------------------------------------
# Long insertion / 8–12 anchor path unchanged
# ---------------------------------------------------------------------------

def test_long_insertion_embedded_still_learns():
    ins = "The quick brown fox jumps over the lazy dog with wisper flow today"
    edited = "The quick brown fox jumps over the lazy dog with Wispr Flow today"
    field = ("UI chrome title " * 4) + edited + (" trailer" * 4)
    _assert_pairs(
        field, ins,
        [("wisper flow", "Wispr Flow")],
        "long insertion embedded (12+ anchor)",
    )


def test_long_field_short_proper_name_mercy_mercey():
    """Long insertion, single 5-char name edit, surrounding field chrome."""
    ins = (
        "I'm talking about something specific, some words that are not "
        "clearly known to an agent, but to a modern LLM. It could be a name "
        "or anything that is yours to remember. \n\nFor example, a name "
        "could be it. Let's say my cat's name is Mercy."
    )
    edited = ins.replace("Mercy", "Mercey")
    _assert_pairs(edited, ins, [("Mercy.", "Mercey.")], "exact field Mercy→Mercey")
    field = ("Earlier email text goes here. " * 10) + edited + (
        "\n--\nSignature block\n" * 3
    )
    pairs = suggest_pairs(field, ins)
    assert ("Mercy.", "Mercey.") in pairs or ("Mercy", "Mercey") in pairs, (
        f"long-field short proper name: expected Mercy→Mercey, got {pairs!r}"
    )
    for wrong, right in pairs:
        if "Mercy" in wrong:
            assert "Signature" not in right and "Earlier" not in right


def test_scroll_tolerance_tail_visible():
    ins = ("AAAA " * 20) + "the end has a typo wrd here"
    full = "the end has a typo word here"  # scrolled input: only tail visible
    _assert_pairs(full, ins, [("wrd", "word")], "scroll-tolerant tail")


def test_eight_char_anchor_with_coverage():
    # Longest exact block "1234567 " = 8 → normal path (60% coverage)
    _assert_pairs(
        "1234567 bagword", "1234567 badword",
        [("badword", "bagword")],
        "exactly 8-char anchor",
    )


def test_twelve_char_anchor_relaxed_coverage():
    ins = "abcdefghijkl wronger"
    full = "abcdefghijkl righter"
    # anchor "abcdefghijkl " = 13; pair must still be plausible
    pairs = suggest_pairs(full, ins)
    assert pairs == [("wronger", "righter")], f"12+ anchor: {pairs!r}"


# ---------------------------------------------------------------------------
# Logging: short-path refusal is explained at INFO; success stays quiet
# ---------------------------------------------------------------------------

def test_short_edit_refusal_logs_reason(caplog_records=None):
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
        suggest_pairs("the", "teh")  # success: no INFO required
    finally:
        logger.removeHandler(handler)
        logger.setLevel(prev)

    refusal = [r for r in records if "short-edit refused" in r.getMessage()]
    assert refusal, f"expected short-edit refusal log, got: {[r.getMessage() for r in records]}"
    success_noise = [
        r for r in records
        if r.levelno >= logging.INFO
        and "teh" in r.getMessage()
        and "refused" not in r.getMessage()
        and "skipped" not in r.getMessage()
    ]
    # Successful short path must not spam INFO
    assert not success_noise, f"unexpected INFO on success: {success_noise}"


def test_extract_replacement_min_length():
    # Single-char tokens ignored
    assert extract_replacement_pairs("a b", "x b") == []


def test_extract_short_name_amid_trailing_chrome():
    pairs = extract_replacement_pairs("Mercy.", "Mercey. -- Signature block")
    assert pairs == [("Mercy.", "Mercey.")], pairs


def test_extract_five_char_name_no_eight_min():
    pairs = extract_replacement_pairs("Mercy", "Mercey")
    assert pairs == [("Mercy", "Mercey")], pairs


# ---------------------------------------------------------------------------

CASES = [
    test_teh_to_the,
    test_golos_case_fix,
    test_short_phrase_one_word,
    test_send_email_near_miss,
    test_short_multiword_phrase,
    test_wisper_flow_case_under_8_anchor,
    test_short_insertion_embedded_in_large_field,
    test_short_phrase_embedded_anchor_7,
    test_unrelated_short_field,
    test_wholesale_rewrite_sameish_length,
    test_wholesale_expand_short_to_long,
    test_append_still_contains_insertion,
    test_prepend_still_contains_insertion,
    test_punctuation_only_no_pair,
    test_unchanged_returns_empty,
    test_implausible_cat_dog,
    test_implausible_pair_helper,
    test_empty_inputs,
    test_long_insertion_embedded_still_learns,
    test_long_field_short_proper_name_mercy_mercey,
    test_scroll_tolerance_tail_visible,
    test_eight_char_anchor_with_coverage,
    test_twelve_char_anchor_relaxed_coverage,
    test_short_edit_refusal_logs_reason,
    test_extract_replacement_min_length,
    test_extract_short_name_amid_trailing_chrome,
    test_extract_five_char_name_no_eight_min,
]


if __name__ == "__main__":
    failed = 0
    for fn in CASES:
        try:
            fn()
            print(f"  ok  {fn.__name__}")
        except Exception as e:
            failed += 1
            print(f" FAIL {fn.__name__}: {e}")
    total = len(CASES)
    if failed:
        print(f"FAIL: {failed}/{total} learning cases")
        raise SystemExit(1)
    print(f"PASS: {total}/{total} learning cases")
