#!/usr/bin/env python3
"""Privacy-safe screenshot harness for the real golos Settings window.

Captures the five public Help Center images by instantiating
``build_settings_window`` in a *separate* worker process with:

- an explicit temporary synthetic data directory (never ~/.golos / ~/.dictate)
- a stub app controller (no live app, mic, hotkeys, clipboard, AX, network)
- prompt/history/dictionary/suggestion path helpers patched only in-worker
- blank API key and canonical default prompts (no personal prompt files)

Does not repurpose HOME. Does not stop or interact with a running golos app.
Screenshots only the Settings window (AppKit view bitmap), never the desktop.

Usage (from repo root)::

    .venv/bin/python scripts/capture_docs_screenshots.py

Replace targets (only after a full successful capture)::

    site/docs/images/settings-history.png
    site/docs/images/settings-general.png
    site/docs/images/settings-prompt.png
    site/docs/images/settings-learning.png
    site/docs/images/settings-dictionary.png
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import subprocess
import sys
import tempfile
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "site" / "docs" / "images"

# Public Help Center files — only these five are replaced on success.
SHOTS: list[tuple[str, str]] = [
    ("history", "settings-history.png"),
    ("general", "settings-general.png"),
    ("prompt", "settings-prompt.png"),
    ("learning", "settings-learning.png"),
    ("dictionary", "settings-dictionary.png"),
]

WORKER_ENV = "GOLOS_DOCS_CAPTURE_WORKER"
DATA_DIR_ENV = "GOLOS_DOCS_CAPTURE_DATA"
OUT_DIR_ENV = "GOLOS_DOCS_CAPTURE_OUT"

# Fictional safe demo content only — no real names, clients, URLs, or paths.
_TS0 = datetime(2026, 7, 15, 14, 22, 10, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# ---------------------------------------------------------------------------
# Synthetic data (written only under the explicit temp directory)
# ---------------------------------------------------------------------------


def _write_synthetic_data(data_dir: Path) -> Path:
    """Populate *data_dir* with safe demo state. Returns path to config.toml."""
    data_dir.mkdir(parents=True, exist_ok=True)

    # Seed from the in-repo key-free config; rewrite paths to this data dir.
    seed_path = REPO_ROOT / "config.toml"
    if sys.version_info >= (3, 11):
        import tomllib
    else:  # pragma: no cover
        import tomli as tomllib

    with open(seed_path, "rb") as f:
        cfg = tomllib.load(f)

    # Hard privacy defaults for capture.
    cfg.setdefault("openrouter", {})["api_key"] = ""
    cfg.setdefault("formatting", {})["enabled"] = True
    cfg.setdefault("formatting", {})["fast_mode"] = False
    cfg.setdefault("formatting", {})["answer_questions"] = False
    cfg.setdefault("formatting", {})["send_audio"] = False
    # No personal prompt files — loaders fall back to canonical defaults.
    cfg["formatting"].pop("prompt_file", None)
    cfg.setdefault("learning", {})["reviewer_enabled"] = False
    cfg["learning"].pop("reviewer_prompt_file", None)

    paths = {
        "dictionary": str(data_dir / "dictionary.txt"),
        "corrections": str(data_dir / "corrections.tsv"),
        "history": str(data_dir / "history.jsonl"),
        "suggestions": str(data_dir / "suggestions.jsonl"),
        "dismissed": str(data_dir / "dismissed.jsonl"),
    }
    cfg["paths"] = paths

    # Terms / corrections — clearly fictional.
    (data_dir / "dictionary.txt").write_text(
        "# fictional demo terms for docs screenshots\n"
        "Mercey\n"
        "README.md\n"
        "golos\n"
        "project update\n",
        encoding="utf-8",
    )
    (data_dir / "corrections.tsv").write_text(
        "# wrong\tright  (fictional demo pairs)\n"
        "mercey\tMercey\n"
        "read me\tREADME.md\n",
        encoding="utf-8",
    )
    (data_dir / "dismissed.jsonl").write_text("", encoding="utf-8")

    # History rows (oldest → newest; UI shows newest first).
    history_rows = [
        {
            "schema_version": 2,
            "kind": "run",
            "run_id": "demo0001project",
            "attempt": 0,
            "ts": _iso(_TS0),
            "app": "Notes",
            "bundle_id": "com.apple.Notes",
            "raw": "um here is the project update for this week",
            "final": "Here is the project update for this week.",
            "context": {
                "app_name": "Notes",
                "bundle_id": "com.apple.Notes",
                "window_title": "Project notes",
            },
            "audio": None,
            "audio_retained": False,
            "fast": False,
            "stage": "complete",
            "status": "success",
            "error": None,
            "format_fallback": False,
        },
        {
            "schema_version": 2,
            "kind": "run",
            "run_id": "demo0002readme",
            "attempt": 0,
            "ts": _iso(_TS0 + timedelta(minutes=18)),
            "app": "Code",
            "bundle_id": "com.microsoft.VSCode",
            "raw": "please update the read me dot md file with the steps",
            "final": "Please update the README.md file with the steps.",
            "context": {
                "app_name": "Code",
                "bundle_id": "com.microsoft.VSCode",
                "window_title": "README.md — demo-project",
                "workspace_files": "README.md\nsrc/main.py",
            },
            "audio": None,
            "audio_retained": False,
            "fast": False,
            "stage": "complete",
            "status": "success",
            "error": None,
            "format_fallback": False,
        },
        {
            "schema_version": 2,
            "kind": "run",
            "run_id": "demo0003mercey",
            "attempt": 0,
            "ts": _iso(_TS0 + timedelta(minutes=42)),
            "app": "Notes",
            "bundle_id": "com.apple.Notes",
            "raw": "ask mercey to review the project update draft",
            "final": "Ask Mercey to review the project update draft.",
            "context": {
                "app_name": "Notes",
                "bundle_id": "com.apple.Notes",
                "window_title": "Project notes",
            },
            "audio": None,
            "audio_retained": False,
            "fast": True,
            "stage": "complete",
            "status": "success",
            "error": None,
            "format_fallback": False,
        },
    ]
    with open(data_dir / "history.jsonl", "w", encoding="utf-8") as f:
        for row in history_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # Suggestion from a fictional edit (Mercey name correction).
    sug = {
        "ts": _iso(_TS0 + timedelta(minutes=45)),
        "app": "Notes",
        "wrong": "mercey",
        "right": "Mercey",
        "provenance": "deterministic",
    }
    (data_dir / "suggestions.jsonl").write_text(
        json.dumps(sug, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Persist config for the worker (absolute path entries).
    try:
        import toml
    except ImportError as e:  # pragma: no cover
        raise SystemExit(
            "capture_docs_screenshots requires the `toml` package "
            "(install app extras). Original error: " + str(e)
        ) from e

    cfg_path = data_dir / "config.toml"
    with open(cfg_path, "w", encoding="utf-8") as f:
        toml.dump(cfg, f)
    return cfg_path


# ---------------------------------------------------------------------------
# PNG helpers (no EXIF / path metadata)
# ---------------------------------------------------------------------------


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def strip_png_metadata(png_bytes: bytes) -> bytes:
    """Keep only structural/color PNG chunks; drop text/EXIF/etc."""
    if len(png_bytes) < 8 or png_bytes[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    allowed = {
        b"IHDR",
        b"PLTE",
        b"IDAT",
        b"IEND",
        b"tRNS",
        b"sBIT",
        b"gAMA",
        b"cHRM",
        b"sRGB",
        b"iCCP",
        b"pHYs",
    }
    out = bytearray(png_bytes[:8])
    pos = 8
    while pos + 8 <= len(png_bytes):
        length = struct.unpack(">I", png_bytes[pos : pos + 4])[0]
        tag = png_bytes[pos + 4 : pos + 8]
        chunk_end = pos + 12 + length
        if chunk_end > len(png_bytes):
            raise ValueError("truncated PNG chunk")
        data = png_bytes[pos + 8 : pos + 8 + length]
        if tag in allowed:
            out.extend(_png_chunk(tag, data))
        pos = chunk_end
        if tag == b"IEND":
            break
    return bytes(out)


def png_dimensions(png_bytes: bytes) -> tuple[int, int]:
    if len(png_bytes) < 24 or png_bytes[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    # IHDR is first chunk: 8 sig + 4 len + 4 type + 4 width + 4 height
    w, h = struct.unpack(">II", png_bytes[16:24])
    return int(w), int(h)


# ---------------------------------------------------------------------------
# Worker: real AppKit Settings UI + window-only capture
# ---------------------------------------------------------------------------


class _StubBubble:
    """No-op bubble stand-in (never touches UI outside Settings)."""

    def notice(self, *args, **kwargs):
        return None

    def cue(self, *args, **kwargs):
        return None

    def suggestion_ready(self, *args, **kwargs):
        return None

    def set_state(self, *args, **kwargs):
        return None

    def set_sensitivity(self, *args, **kwargs):
        return None

    def set_show_text(self, *args, **kwargs):
        return None


class _StubAppController:
    """Minimal controller surface required by SettingsController."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.bubble = _StubBubble()
        self.last_insertion = None

    def apply_settings(self):
        return None

    def reload_dictionary(self):
        return None

    def copy_ready_for_record(self, record):
        from dictate.history import copy_ready

        return copy_ready(record)

    def retry_capabilities_for_record(self, record):
        from dictate.history import retry_capabilities

        return retry_capabilities(record)


def _patch_path_helpers(data_dir: Path) -> None:
    """Redirect prompt helpers to the synthetic data dir (in-worker only).

    History / dictionary / suggestions already use absolute paths from cfg.
    """

    def _prompt_under_data(name: str) -> Path:
        p = Path(name)
        return p if p.is_absolute() else data_dir / p

    import dictate_core.formatter as formatter_mod
    import dictate_core.learning_reviewer as reviewer_mod

    formatter_mod._prompt_file_path = _prompt_under_data  # type: ignore[attr-defined]
    reviewer_mod.prompt_file_path = _prompt_under_data  # type: ignore[attr-defined]

    # Belt-and-suspenders: if any code path hits update_config defaults,
    # write only under the synthetic data dir — never ~/.golos.
    import dictate.config as config_mod

    config_mod.DATA_DIR = data_dir
    config_mod.CONFIG_PATH = data_dir / "config.toml"
    config_mod.LOCK_PATH = data_dir / "dictate.lock"
    # Do not point OLD_DATA_DIR at a real user tree for migration.
    config_mod.OLD_DATA_DIR = data_dir / "_no_legacy_dictate"


def _pump(seconds: float = 0.35) -> None:
    from Foundation import NSDate, NSRunLoop

    NSRunLoop.currentRunLoop().runUntilDate_(
        NSDate.dateWithTimeIntervalSinceNow_(seconds)
    )


def _center_window(window) -> None:
    """Place the window fully on the primary screen (avoid partial captures)."""
    from AppKit import NSScreen

    screen = NSScreen.mainScreen()
    if screen is None:
        return
    visible = screen.visibleFrame()
    frame = window.frame()
    x = visible.origin.x + (visible.size.width - frame.size.width) / 2.0
    y = visible.origin.y + (visible.size.height - frame.size.height) / 2.0
    window.setFrameOrigin_((x, y))


def _bitmap_is_mostly_blank(rep) -> bool:
    """True when the snapshot looks empty/black (mid-transition WindowServer race)."""
    try:
        w = int(rep.pixelsWide())
        h = int(rep.pixelsHigh())
    except Exception:
        return True
    if w < 100 or h < 100:
        return True
    non_dark = 0
    samples = 0
    # Sample a coarse grid inside the window (skip outer shadow).
    x0, x1 = w // 8, (7 * w) // 8
    y0, y1 = h // 8, (7 * h) // 8
    step_x = max(1, (x1 - x0) // 12)
    step_y = max(1, (y1 - y0) // 12)
    for y in range(y0, y1, step_y):
        for x in range(x0, x1, step_x):
            color = rep.colorAtX_y_(x, y)
            if color is None:
                continue
            samples += 1
            try:
                r = float(color.redComponent())
                g = float(color.greenComponent())
                b = float(color.blueComponent())
                a = float(color.alphaComponent())
            except Exception:
                continue
            if a > 0.15 and (r + g + b) > 0.35:
                non_dark += 1
    if samples < 10:
        return True
    return (non_dark / samples) < 0.12


def _bitmap_has_unrendered_tab_strip(rep) -> bool:
    """Detect the transient black NSTabView bar seen before labels composite.

    The capture worker always uses the light system appearance. A finished tab
    strip is light gray with dark labels; a nearly solid black band across the
    upper center means WindowServer caught the control mid-draw.
    """
    try:
        w = int(rep.pixelsWide())
        h = int(rep.pixelsHigh())
    except Exception:
        return True
    y = int(h * 0.92)
    dark = 0
    samples = 0
    for x in range(int(w * 0.24), int(w * 0.76), max(1, w // 80)):
        color = rep.colorAtX_y_(x, y)
        if color is None:
            continue
        try:
            brightness = (
                float(color.redComponent())
                + float(color.greenComponent())
                + float(color.blueComponent())
            ) / 3.0
            alpha = float(color.alphaComponent())
        except Exception:
            continue
        samples += 1
        if alpha > 0.5 and brightness < 0.12:
            dark += 1
    return samples >= 10 and (dark / samples) > 0.70


def _capture_window_png(window, *, attempts: int = 8) -> bytes:
    """Bitmap of *this* Settings window only (titlebar + tabs + content).

    Uses the window-scoped WindowServer snapshot for the given
    ``windowNumber`` so modern NSTabView tab chrome is included. Never
    captures the desktop or other apps — only the single window id.
    Retries when the frame is mostly blank (common mid-tab-switch race).
    """
    from AppKit import NSApp, NSBitmapImageRep, NSPNGFileType
    from Quartz import (
        CGRectNull,
        CGWindowListCreateImage,
        kCGWindowImageDefault,
        kCGWindowListOptionIncludingWindow,
    )

    last_err: Exception | None = None
    for attempt in range(attempts):
        try:
            NSApp.activateIgnoringOtherApps_(True)
            window.makeKeyAndOrderFront_(None)
            _center_window(window)
            try:
                window.displayIfNeeded()
            except Exception:
                pass
            # Let WindowServer composite tab chrome after order-front.
            _pump(0.35 + 0.15 * attempt)

            wid = int(window.windowNumber())
            if wid <= 0:
                raise RuntimeError("settings window has no windowNumber yet")

            cg = CGWindowListCreateImage(
                CGRectNull,
                kCGWindowListOptionIncludingWindow,
                wid,
                kCGWindowImageDefault,
            )
            if cg is None:
                raise RuntimeError(
                    "CGWindowListCreateImage returned None "
                    "(window may not be on-screen yet)"
                )

            rep = NSBitmapImageRep.alloc().initWithCGImage_(cg)
            if rep is None:
                raise RuntimeError("NSBitmapImageRep.initWithCGImage_ failed")
            if _bitmap_is_mostly_blank(rep):
                raise RuntimeError(
                    f"blank/partial window snapshot (attempt {attempt + 1})"
                )
            if _bitmap_has_unrendered_tab_strip(rep):
                raise RuntimeError(
                    f"tab strip not composited yet (attempt {attempt + 1})"
                )

            data = rep.representationUsingType_properties_(NSPNGFileType, None)
            if data is None:
                raise RuntimeError("PNG representation failed")
            return strip_png_metadata(bytes(data))
        except Exception as e:
            last_err = e
            _pump(0.25)
    raise RuntimeError(
        f"window capture failed after {attempts} attempts: {last_err}"
    )


def _select_tab(controller, identifier: str) -> None:
    tabs = controller.tabs
    for item in tabs.tabViewItems():
        if str(item.identifier()) == identifier:
            tabs.selectTabViewItem_(item)
            return
    raise RuntimeError(f"tab not found: {identifier!r}")


def _prepare_history_selection(controller) -> None:
    """Select the newest row so the detail pane shows real content."""
    from Foundation import NSIndexSet

    if not controller._records:
        return
    controller.table.selectRowIndexes_byExtendingSelection_(
        NSIndexSet.indexSetWithIndex_(0), False
    )
    # Ensure detail text is rendered even if the selection notification is soft.
    rec = controller._records[0]
    controller.detail_text.setString_(controller._render_detail(rec))


def worker_main(data_dir: Path, out_dir: Path) -> int:
    """Run inside the capture subprocess: real UI, synthetic data only."""
    # Hard isolation: never authenticate accidental network paths.
    for var in (
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
        "DEEPGRAM_API_KEY",
    ):
        os.environ.pop(var, None)

    # Refuse to proceed if data_dir looks like a real user state tree name
    # that is *outside* a temp prefix (defense in depth).
    resolved = data_dir.resolve()
    home = Path.home().resolve()
    for forbidden in (home / ".golos", home / ".dictate"):
        try:
            if resolved == forbidden or forbidden in resolved.parents:
                print(
                    f"REFUSING to use data dir under {forbidden}",
                    file=sys.stderr,
                )
                return 2
        except Exception:
            pass

    _patch_path_helpers(data_dir)

    if sys.version_info >= (3, 11):
        import tomllib
    else:  # pragma: no cover
        import tomli as tomllib

    cfg_path = data_dir / "config.toml"
    with open(cfg_path, "rb") as f:
        cfg = tomllib.load(f)

    # Absolute path resolution without ensure_data_dir / HOME migration.
    paths = cfg.setdefault("paths", {})
    for key in ("dictionary", "corrections", "history", "suggestions", "dismissed"):
        p = Path(paths.get(key, f"{key}"))
        if not p.is_absolute():
            p = data_dir / p
        paths[key] = str(p)

    # Ensure API key field stays blank.
    cfg.setdefault("openrouter", {})["api_key"] = ""

    # AppKit bootstrap (capture process only — not the founder's app).
    from AppKit import NSApplication, NSApplicationActivationPolicyRegular
    from PyObjCTools import AppHelper

    nsapp = NSApplication.sharedApplication()
    # Regular policy so the window can order front in this isolated process.
    nsapp.setActivationPolicy_(NSApplicationActivationPolicyRegular)

    from dictate.settings import build_settings_window

    stub = _StubAppController(cfg)
    controller = build_settings_window(stub)
    controller.show()
    _center_window(controller.window)
    _pump(0.9)

    out_dir.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="golos-docs-shots-"))
    written: list[Path] = []

    try:
        for tab_id, filename in SHOTS:
            _select_tab(controller, tab_id)
            if tab_id == "history":
                _prepare_history_selection(controller)
            # Tab content + modern tab strip need a full layout pass.
            try:
                controller.window.displayIfNeeded()
            except Exception:
                pass
            _pump(0.9)

            png = _capture_window_png(controller.window)
            w, h = png_dimensions(png)
            if w < 500 or h < 400:
                raise RuntimeError(
                    f"{filename}: capture too small ({w}x{h}); "
                    "window may not have laid out"
                )
            # Reject tiny/highly compressible frames (blank black captures).
            if len(png) < 40_000:
                raise RuntimeError(
                    f"{filename}: PNG only {len(png)} bytes — likely blank"
                )
            dest = staging / filename
            dest.write_bytes(png)
            written.append(dest)
            print(f"captured {filename} ({w}x{h}, {len(png)} bytes)", flush=True)

        # Atomic-ish publish: only replace the five public files after all ok.
        out_dir.mkdir(parents=True, exist_ok=True)
        for src in written:
            target = out_dir / src.name
            # Write via temp neighbor then replace.
            tmp = out_dir / (src.name + ".tmp")
            tmp.write_bytes(src.read_bytes())
            tmp.replace(target)
            print(f"wrote {target.relative_to(REPO_ROOT)}", flush=True)
    finally:
        try:
            controller.window.close()
        except Exception:
            pass
        # Best-effort cleanup of staging.
        for p in staging.glob("*"):
            try:
                p.unlink()
            except OSError:
                pass
        try:
            staging.rmdir()
        except OSError:
            pass

    # Exit the run loop without lingering as a GUI app.
    AppHelper.stopEventLoop()
    return 0


# ---------------------------------------------------------------------------
# Parent: spawn isolated worker
# ---------------------------------------------------------------------------


def _scrub_env() -> dict[str, str]:
    env = os.environ.copy()
    for var in (
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
        "DEEPGRAM_API_KEY",
    ):
        env.pop(var, None)
    # Never inherit a poisoned HOME override from tests into capture if we
    # re-exec; parent does not set HOME either.
    return env


def run_capture(*, out_dir: Path = OUT_DIR) -> int:
    """Create synthetic data, spawn worker, publish five PNGs."""
    out_dir = out_dir.resolve()
    with tempfile.TemporaryDirectory(prefix="golos-docs-capture-") as tmp:
        data_dir = Path(tmp) / "synthetic"
        _write_synthetic_data(data_dir)

        env = _scrub_env()
        env[WORKER_ENV] = "1"
        env[DATA_DIR_ENV] = str(data_dir)
        env[OUT_DIR_ENV] = str(out_dir)

        # Separate process: ObjC class registration + AppKit isolation.
        cmd = [sys.executable, str(Path(__file__).resolve())]
        print(f"spawning capture worker: {cmd[0]}", flush=True)
        proc = subprocess.run(
            cmd,
            env=env,
            cwd=str(REPO_ROOT),
            check=False,
        )
        if proc.returncode != 0:
            print(
                f"capture worker failed with exit {proc.returncode}",
                file=sys.stderr,
            )
            return proc.returncode or 1

    # Post-flight: verify the five public files.
    for _, name in SHOTS:
        path = out_dir / name
        if not path.is_file():
            print(f"missing output: {path}", file=sys.stderr)
            return 1
        raw = path.read_bytes()
        w, h = png_dimensions(raw)
        print(f"ok {name}: {w}x{h}, {len(raw)} bytes", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    # Worker branch — must run before argparse so re-exec stays simple.
    if os.environ.get(WORKER_ENV) == "1":
        data = Path(os.environ[DATA_DIR_ENV])
        out = Path(os.environ[OUT_DIR_ENV])
        try:
            code = worker_main(data, out)
        except Exception as e:
            print(f"capture worker error: {e}", file=sys.stderr)
            import traceback

            traceback.print_exc()
            return 1
        # Hard exit so AppKit cannot keep the process alive.
        os._exit(code)

    parser = argparse.ArgumentParser(
        description="Capture privacy-safe golos Settings screenshots for the Help Center."
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=OUT_DIR,
        help=f"output directory (default: {OUT_DIR})",
    )
    args = parser.parse_args(argv)
    return run_capture(out_dir=args.out_dir)


if __name__ == "__main__":
    raise SystemExit(main())
