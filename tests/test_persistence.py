"""Config / history / dictionary persistence using temporary directories only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dictate.config import (
    _heal_char_arrays,
    _is_char_array,
    bundled_config_path,
    configure_frozen_ca,
    ensure_data_dir,
    env_key,
    load_config,
    update_config,
)
from dictate.history import append_history
from dictate_core.dictionary import load_corrections, load_terms


def test_is_char_array():
    assert _is_char_array(list("ab"))
    assert not _is_char_array(["ab"])
    assert not _is_char_array([])
    assert not _is_char_array("ab")


def test_heal_char_arrays_nested():
    node = {"openrouter": {"api_key": list("sk-x")}, "nested": [{"m": list("ab")}]}
    _heal_char_arrays(node)
    assert node["openrouter"]["api_key"] == "sk-x"
    assert node["nested"][0]["m"] == "ab"


def test_env_key(monkeypatch):
    assert env_key({}) is None
    assert env_key({"api_key_env": ""}) is None
    monkeypatch.setenv("TEST_GOL_KEY", "secret")
    assert env_key({"api_key_env": "TEST_GOL_KEY"}) == "secret"
    monkeypatch.delenv("TEST_GOL_KEY")
    assert env_key({"api_key_env": "TEST_GOL_KEY"}) is None


def test_ensure_data_dir_creates_empty(tmp_path):
    data = tmp_path / "golos"
    old = tmp_path / "dictate_old"
    project = tmp_path / "project"
    project.mkdir()
    out = ensure_data_dir(data_dir=data, project_root=project, old_data_dir=old)
    assert out == data
    assert data.is_dir()
    assert not (data / "config.toml").exists()


def test_ensure_data_dir_migrates_from_old(tmp_path):
    data = tmp_path / "golos"
    old = tmp_path / "dictate_old"
    project = tmp_path / "project"
    old.mkdir()
    project.mkdir()
    (old / "config.toml").write_text('[stt]\nbackend = "mlx"\n', encoding="utf-8")
    (old / "dictionary.txt").write_text("golos\n", encoding="utf-8")
    (old / "recordings").mkdir()
    (old / "recordings" / "x.wav").write_bytes(b"RIFF")
    out = ensure_data_dir(data_dir=data, project_root=project, old_data_dir=old)
    assert out == data
    assert (data / "config.toml").exists()
    assert (data / "dictionary.txt").read_text(encoding="utf-8") == "golos\n"
    assert (data / "recordings" / "x.wav").exists()
    # originals kept
    assert (old / "config.toml").exists()
    # second call is no-op when config exists
    ensure_data_dir(data_dir=data, project_root=project, old_data_dir=old)


def test_ensure_data_dir_migrates_from_project(tmp_path):
    data = tmp_path / "golos"
    old = tmp_path / "missing_old"
    project = tmp_path / "project"
    project.mkdir()
    (project / "config.toml").write_text('[hotkey]\nhold_key = "fn"\n', encoding="utf-8")
    ensure_data_dir(data_dir=data, project_root=project, old_data_dir=old)
    assert "fn" in (data / "config.toml").read_text(encoding="utf-8")


def test_bundled_config_path_finds_py2app_resource(tmp_path, monkeypatch):
    contents = tmp_path / "golos.app" / "Contents"
    executable = contents / "MacOS" / "golos"
    resource = contents / "Resources" / "config.toml"
    executable.parent.mkdir(parents=True)
    resource.parent.mkdir(parents=True)
    executable.write_text("", encoding="utf-8")
    resource.write_text('[stt]\nbackend = "openrouter"\n', encoding="utf-8")
    monkeypatch.setattr("dictate.config.sys.frozen", True, raising=False)
    monkeypatch.setattr("dictate.config.sys.executable", str(executable))
    missing_source = tmp_path / "missing-source"
    assert bundled_config_path(missing_source) == resource
    data = tmp_path / "new-home" / ".golos"
    ensure_data_dir(
        data_dir=data,
        project_root=missing_source,
        old_data_dir=tmp_path / "missing-old",
    )
    assert 'backend = "openrouter"' in (data / "config.toml").read_text()
    assert (data / "config.toml").stat().st_mode & 0o777 == 0o600


def test_configure_frozen_ca_uses_bundle_resource(tmp_path, monkeypatch):
    contents = tmp_path / "golos.app" / "Contents"
    executable = contents / "MacOS" / "golos"
    ca = contents / "Resources" / "cacert.pem"
    executable.parent.mkdir(parents=True)
    ca.parent.mkdir(parents=True)
    executable.write_text("", encoding="utf-8")
    ca.write_text("test-ca", encoding="utf-8")
    monkeypatch.setattr("dictate.config.sys.frozen", True, raising=False)
    monkeypatch.setattr("dictate.config.sys.executable", str(executable))
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    assert configure_frozen_ca() == ca
    assert __import__("os").environ["SSL_CERT_FILE"] == str(ca)


def test_load_config_absolute_paths_preserved(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.toml"
    hist = tmp_path / "h.jsonl"
    dct = tmp_path / "d.txt"
    cor = tmp_path / "c.tsv"
    cfg_path.write_text(
        f'''
[paths]
dictionary = "{dct}"
corrections = "{cor}"
history = "{hist}"
suggestions = "{tmp_path / "s.jsonl"}"
dismissed = "{tmp_path / "dis.jsonl"}"
[stt]
backend = "mlx"
''',
        encoding="utf-8",
    )
    cfg = load_config(cfg_path)
    assert cfg["paths"]["dictionary"] == str(dct)
    assert cfg["paths"]["history"] == str(hist)
    assert cfg["stt"]["backend"] == "mlx"


def test_load_config_heals_char_array_key(tmp_path):
    # Write a TOML array of single-char strings that heal to a key string
    cfg_path = tmp_path / "config.toml"
    # Use a value that _heal will fix after parse — tomllib will give list of chars
    # if written as array of strings of length 1
    cfg_path.write_text(
        'openrouter = { api_key = ["s", "k"] }\n[paths]\n',
        encoding="utf-8",
    )
    cfg = load_config(cfg_path)
    assert cfg["openrouter"]["api_key"] == "sk"


def test_update_config_writes_temp_only(tmp_path):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[stt]\nbackend = "mlx"\n[formatting]\nenabled = true\n',
        encoding="utf-8",
    )
    out = update_config({"stt": {"backend": "openrouter"}, "formatting": {"enabled": False}},
                        path=cfg_path)
    assert out["stt"]["backend"] == "openrouter"
    assert out["formatting"]["enabled"] is False
    text = cfg_path.read_text(encoding="utf-8")
    assert "openrouter" in text
    assert "false" in text.lower() or "False" in text


def test_append_history_jsonl(tmp_path):
    path = tmp_path / "sub" / "history.jsonl"
    append_history(
        str(path),
        "Slack",
        "com.tinyspeck.slackmacgap",
        "raw text",
        "final text",
        context={"app_name": "Slack"},
        audio=None,
        fast=True,
    )
    append_history(str(path), "Notes", "com.apple.Notes", "a", "b")
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    rec = json.loads(lines[0])
    assert rec["app"] == "Slack"
    assert rec["raw"] == "raw text"
    assert rec["final"] == "final text"
    assert rec["fast"] is True
    assert "ts" in rec
    # Schema v2 recovery fields (backward-compatible extras)
    assert rec["schema_version"] == 2
    assert rec["status"] == "success"
    assert rec["stage"] == "complete"
    assert rec["run_id"]
    assert rec["audio_retained"] is False


def test_audio_retained_requires_file_on_disk(tmp_path):
    """Persisted audio_retained must not be true for a missing path."""
    from dictate.history import append_history, load_history, normalize_record

    missing = str(tmp_path / "nope.wav")
    path = str(tmp_path / "history.jsonl")
    append_history(
        path, "Notes", "com.apple.Notes", "raw", "Final.",
        audio=missing,
    )
    raw_line = json.loads(Path(path).read_text(encoding="utf-8").strip())
    assert raw_line["audio"] == missing
    assert raw_line["audio_retained"] is False
    assert load_history(path)[0]["audio_retained"] is False
    # Path present in dict alone still normalizes to not retained.
    assert normalize_record({"audio": missing})["audio_retained"] is False


def test_dictionary_and_corrections_roundtrip_temp(tmp_path):
    d = tmp_path / "dictionary.txt"
    c = tmp_path / "corrections.tsv"
    d.write_text("golos\n# c\nWispr\n", encoding="utf-8")
    c.write_text("teh\tthe\n", encoding="utf-8")
    assert load_terms(str(d)) == ["golos", "Wispr"]
    assert load_corrections(str(c)) == [("teh", "the")]
