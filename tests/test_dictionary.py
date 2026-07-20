"""Dictionary and corrections loaders (temp paths only)."""

from __future__ import annotations

from dictate_core.dictionary import load_corrections, load_terms


def test_load_terms_missing_file(tmp_path):
    assert load_terms(str(tmp_path / "missing.txt")) == []


def test_load_terms_ignores_blank_and_comments(tmp_path):
    p = tmp_path / "dictionary.txt"
    p.write_text("# header\n\ngolos\n  Wispr Flow  \n# skip\n", encoding="utf-8")
    assert load_terms(str(p)) == ["golos", "Wispr Flow"]


def test_load_corrections_missing_file(tmp_path):
    assert load_corrections(str(tmp_path / "missing.tsv")) == []


def test_load_corrections_parses_tsv(tmp_path):
    p = tmp_path / "corrections.tsv"
    p.write_text(
        "# comment\n"
        "teh\tthe\n"
        "wisper flow\tWispr Flow\n"
        "badline\n"
        "\tempty-wrong\n"
        "  ok  \t  okay  \n",
        encoding="utf-8",
    )
    assert load_corrections(str(p)) == [
        ("teh", "the"),
        ("wisper flow", "Wispr Flow"),
        ("ok", "okay"),
    ]
