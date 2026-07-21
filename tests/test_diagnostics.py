import json
import logging
import zipfile

from dictate.diagnostics import (
    _safe_config,
    _sanitized_log,
    configure_logging,
    create_support_bundle,
)


def test_safe_config_excludes_credentials_paths_and_prompts():
    cfg = {
        "openrouter": {"api_key": "sk-or-v1-secret"},
        "paths": {"history": "/private/client/history.jsonl"},
        "formatting": {
            "enabled": True,
            "model": "google/gemini",
            "system_prompt": "private company instructions",
        },
        "bubble": {"style": "notch", "show_text": True},
    }
    safe = _safe_config(cfg)
    rendered = json.dumps(safe)
    assert safe["formatting"] == {"enabled": True, "model": "google/gemini"}
    assert safe["bubble"] == {"style": "notch", "show_text": True}
    assert "secret" not in rendered
    assert "private company" not in rendered
    assert "/private/client" not in rendered


def test_sanitized_log_removes_spoken_text_prompt_and_secrets():
    source = (
        "INFO Raw transcript: 'my private thought'\n"
        "INFO === FORMATTER SYSTEM PROMPT ===\n"
        "private prompt and visible context\n"
        "INFO === END FORMATTER DEBUG ===\n"
        "INFO authorization: sk-or-v1-supersecretvalue\n"
        "INFO State: processing\n"
    )
    out = _sanitized_log(source)
    assert "my private thought" not in out
    assert "private prompt" not in out
    assert "supersecretvalue" not in out
    assert "State: processing" in out


def test_support_bundle_contains_metadata_not_content(tmp_path):
    data = tmp_path / "data"
    logs = data / "logs"
    logs.mkdir(parents=True)
    (logs / "golos.log").write_text(
        "INFO Raw transcript: 'do not share me'\nINFO State: success\n")
    (data / "history.jsonl").write_text(json.dumps({
        "ts": "2026-07-21T00:00:00Z",
        "run_id": "run-1",
        "status": "success",
        "stage": "complete",
        "raw": "private raw words",
        "final": "private final words",
        "context": {"visible_text": "private page"},
        "audio": "/private/voice.wav",
    }) + "\n")
    dest = create_support_bundle(
        tmp_path / "support.zip", data_dir=data,
        cfg={"bubble": {"style": "notch"}},
        permission_status={"accessibility": True},
    )
    with zipfile.ZipFile(dest) as zf:
        names = set(zf.namelist())
        combined = "\n".join(
            zf.read(name).decode("utf-8") for name in names)
        history = json.loads(zf.read("history-metadata.json"))
    assert {"manifest.json", "system.json", "config-sanitized.json",
            "history-metadata.json", "logs/golos.log"} <= names
    assert "private raw words" not in combined
    assert "private final words" not in combined
    assert "private page" not in combined
    assert "do not share me" not in combined
    assert history[0]["raw_chars"] == len("private raw words")
    assert history[0]["final_chars"] == len("private final words")


def test_configure_logging_rotates_to_private_file(tmp_path):
    root = logging.getLogger()
    old_handlers = list(root.handlers)
    old_level = root.level
    try:
        path = configure_logging(tmp_path, stream=False)
        logging.getLogger("diagnostic-test").info("hello")
        for handler in root.handlers:
            handler.flush()
        assert path.exists()
        assert "hello" in path.read_text()
        assert (path.stat().st_mode & 0o777) == 0o600
    finally:
        for handler in list(root.handlers):
            handler.close()
        root.handlers[:] = old_handlers
        root.setLevel(old_level)
