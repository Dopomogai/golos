"""Load config.toml and resolve mutable-state paths.

All mutable state lives in ~/.golos/ (config, dictionary, corrections,
history, suggestions, dismissed, recordings, lock) so a bundled .app works
without a project dir. On first run after the rename, the dictate-era
~/.dictate set is COPIED over (never moved) and ~/.golos is used from then on.
"""

import logging
import os
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path.home() / ".golos"
OLD_DATA_DIR = Path.home() / ".dictate"
CONFIG_PATH = DATA_DIR / "config.toml"
LOCK_PATH = DATA_DIR / "dictate.lock"

_STATE_FILES = ("dictionary.txt", "corrections.tsv", "history.jsonl",
                "suggestions.jsonl", "dismissed.jsonl")


def ensure_data_dir(data_dir: Path = DATA_DIR,
                    project_root: Path = PROJECT_ROOT,
                    old_data_dir: Path = OLD_DATA_DIR) -> Path:
    """Create ~/.golos and migrate state (copy-once).

    Source preference: an existing ~/.dictate (live data from the dictate
    era) over the project-root bootstrap. Copies config.toml (chmod 600),
    the state files, and recordings/ when present. Originals stay in place.
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    dst_cfg = data_dir / "config.toml"
    if dst_cfg.exists():
        return data_dir
    if (old_data_dir / "config.toml").exists():
        source = old_data_dir
    elif (project_root / "config.toml").exists():
        source = project_root
    else:
        return data_dir
    import shutil
    shutil.copy2(source / "config.toml", dst_cfg)
    os.chmod(dst_cfg, 0o600)  # holds the API key
    migrated = ["config.toml"]
    for name in _STATE_FILES:
        src, dst = source / name, data_dir / name
        if src.exists() and not dst.exists():
            shutil.copy2(src, dst)
            migrated.append(name)
    src_rec = source / "recordings"
    dst_rec = data_dir / "recordings"
    if src_rec.is_dir() and not dst_rec.exists():
        shutil.copytree(src_rec, dst_rec)
        migrated.append("recordings/")
    log.info("Migrated %s from %s to %s (originals kept in place).",
             ", ".join(migrated), source, data_dir)
    return data_dir


def load_config(path: Path | None = None) -> dict:
    """Load config.toml, heal char-array corruption, resolve paths under ~/.golos.

    When `path` is None: ensure_data_dir() first (copy-once migration), then
    read CONFIG_PATH. Relative path entries become absolute under DATA_DIR so
    a bundled .app never depends on cwd. Returns a mutable dict owned by the
    caller — live reloads re-call this rather than mutating a shared global.
    """
    if path is None:
        ensure_data_dir()
        path = CONFIG_PATH
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    _heal_char_arrays(cfg)

    # Resolve file paths relative to the data dir.
    paths = cfg.setdefault("paths", {})
    defaults = {"suggestions": "suggestions.jsonl", "dismissed": "dismissed.jsonl"}
    for key in ("dictionary", "corrections", "history", "suggestions", "dismissed"):
        p = Path(paths.get(key, defaults.get(key, f"{key}.txt")))
        if not p.is_absolute():
            p = DATA_DIR / p
        paths[key] = str(p)

    return cfg


def _heal_char_arrays(node) -> None:
    """In-place repair of the char-array corruption (see update_config note):
    a list whose items are all single-character strings is joined into a str."""
    if isinstance(node, dict):
        for key, value in node.items():
            if _is_char_array(value):
                node[key] = "".join(value)
            else:
                _heal_char_arrays(value)
    elif isinstance(node, list):
        for item in node:
            _heal_char_arrays(item)


def _is_char_array(value) -> bool:
    return (isinstance(value, list) and bool(value)
            and all(isinstance(c, str) and len(c) == 1 for c in value))


def _sanitize(value):
    """Coerce values to types the `toml` writer handles exactly.

    toml.TomlEncoder.dump_value does an EXACT type(v) lookup: bridged NSStrings
    (objc.pyobjc_unicode, a str subclass returned by NSControl.stringValue())
    miss the str entry, fall into the __iter__ branch, and get dumped as a TOML
    array of single characters. Plain str() coercion prevents that.
    """
    if isinstance(value, str) and type(value) is not str:
        return str(value)
    if isinstance(value, dict):
        return {k: _sanitize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(v) for v in value]
    return value


def env_key(cfg_section: dict) -> str | None:
    """Read an API key from the environment variable named by api_key_env."""
    var = cfg_section.get("api_key_env", "")
    if not var:
        return None
    return os.environ.get(var) or None


def update_config(updates: dict, path: Path = CONFIG_PATH) -> dict:
    """Persist `updates` into config.toml and return the full updated config.

    `updates` maps section -> {key: value}; dotted section names ("stt.openrouter")
    address nested tables. The file is re-read with tomllib first, so sections and
    values we don't touch are preserved. (Comments in the file are NOT preserved —
    the `toml` package is a plain writer.)
    """
    import toml

    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    for section, kv in updates.items():
        node = cfg
        parts = section.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
            if not isinstance(node, dict):
                raise ValueError(f"Cannot write into non-table section {section!r}")
        node.setdefault(parts[-1], {})
        if not isinstance(node[parts[-1]], dict):
            raise ValueError(f"Cannot write into non-table section {section!r}")
        node[parts[-1]].update(_sanitize(kv))
    with open(path, "w", encoding="utf-8") as f:
        toml.dump(cfg, f)
    return cfg
