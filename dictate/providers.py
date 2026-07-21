"""App context providers: enrich the formatter prompt with live context.

Registry keyed by bundle_id. Every provider is wrapped in try/except with a
hard subprocess timeout (osascript, timeout=1.5s); any failure contributes
nothing. Providers never AppleScript an app that isn't running — osascript
would LAUNCH it otherwise (and trigger Automation consent dialogs).

First use of a browser/Finder provider may trigger a macOS Automation consent
dialog — expected; denying simply disables that provider.

Privacy: gathered fields (URLs, workspace paths, AX text) leave the Mac only
when the formatter is enabled and the matching [context] toggle is on.
include_visible=False skips AX text reads entirely (formatting disabled path).
"""

import logging
import os
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

OSASCRIPT_TIMEOUT = 1.5
SEP = "\x1f"  # unit separator, safe join/split for AppleScript results

VSCODE_ROOT_CANDIDATES = ("~", "~/Documents", "~/Documents/GitHub", "~/Projects")
MAX_WORKSPACE_FILES = 200
_SKIP_DIRS = {".git", "node_modules"}


# ---------------------------------------------------------------------------
# helpers


def is_running(bundle_id: str) -> bool:
    try:
        from AppKit import NSWorkspace
        for app in NSWorkspace.sharedWorkspace().runningApplications():
            if app.bundleIdentifier() == bundle_id:
                return True
    except Exception:
        pass
    return False


def run_osascript(script: str, timeout: float = OSASCRIPT_TIMEOUT) -> str | None:
    """Run an AppleScript snippet; stdout on success, None on any failure."""
    try:
        proc = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=timeout,
        )
        if proc.returncode != 0:
            log.info("osascript failed: %s", proc.stderr.strip()[:200])
            return None
        return proc.stdout.strip()
    except subprocess.TimeoutExpired:
        log.info("osascript timed out (%.1fs)", timeout)
    except Exception as e:
        log.info("osascript error: %s", e)
    return None


# ---------------------------------------------------------------------------
# providers (bundle_id -> callable(window_title) -> dict)


def _browser_provider(app_name: str, tab_kind: str, title_prop: str):
    def provider(window_title: str) -> dict:
        script = (
            f'tell application "{app_name}"\n'
            f'  set t to {title_prop} of {tab_kind} of front window\n'
            f'  set u to URL of {tab_kind} of front window\n'
            f'  return t & character id 31 & u\n'
            f'end tell'
        )
        out = run_osascript(script)
        if not out or SEP not in out:
            return {}
        title, _, url = out.partition(SEP)
        return {"current_page_title": title.strip(),
                "current_page_url": url.strip()}
    return provider


BROWSER_PROVIDERS = {
    "com.apple.Safari": _browser_provider("Safari", "current tab", "name"),
    "com.google.Chrome": _browser_provider("Google Chrome", "active tab", "title"),
    "com.brave.Browser": _browser_provider("Brave Browser", "active tab", "title"),
    "com.microsoft.edgemac": _browser_provider("Microsoft Edge", "active tab", "title"),
    "com.company.thebrowser.Browser": _browser_provider("Arc", "active tab", "title"),
}


def _finder_provider(window_title: str) -> dict:
    script = (
        'tell application "Finder"\n'
        '  set out to ""\n'
        '  try\n'
        '    set out to POSIX path of (target of front window as alias)\n'
        '  end try\n'
        '  set sel to selection\n'
        '  repeat with i in sel\n'
        '    set out to out & character id 31 & POSIX path of (i as alias)\n'
        '  end repeat\n'
        '  return out\n'
        'end tell'
    )
    out = run_osascript(script)
    if out is None:
        return {}
    parts = [p for p in out.split(SEP) if p]
    ctx = {}
    if parts:
        ctx["finder_window"] = parts[0]
        if len(parts) > 1:
            ctx["finder_selection"] = ", ".join(parts[1:])
    return ctx


# -- VS Code -----------------------------------------------------------------


def parse_vscode_folder(window_title: str) -> str | None:
    """'file — folder — Visual Studio Code' -> 'folder' (None if unparseable)."""
    parts = [p.strip() for p in window_title.split(" — ")]
    if len(parts) >= 2 and parts[-1].startswith("Visual Studio Code"):
        return parts[-2] or None
    return None


def locate_folder(name: str, roots=VSCODE_ROOT_CANDIDATES) -> str | None:
    """Find a directory named `name` within depth ≤2 of the candidate roots."""
    if not name:
        return None
    for root in roots:
        root = os.path.expanduser(root)
        if not os.path.isdir(root):
            continue
        # depth 1: root itself
        if os.path.basename(root.rstrip("/")) == name:
            return root
        try:
            entries = sorted(os.scandir(root), key=lambda e: e.name)
        except OSError:
            continue
        for e1 in entries:  # depth 1
            if not e1.is_dir(follow_symlinks=False):
                continue
            if e1.name == name:
                return e1.path
            try:
                subs = sorted(os.scandir(e1.path), key=lambda e: e.name)
            except OSError:
                continue
            for e2 in subs:  # depth 2
                if e2.is_dir(follow_symlinks=False) and e2.name == name:
                    return e2.path
    return None


def list_workspace_files(root: str, max_files: int = MAX_WORKSPACE_FILES) -> list[str]:
    """Files under root, depth ≤3, skipping .git/node_modules, relative paths."""
    out = []
    root = root.rstrip("/")
    base_depth = root.count("/")
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        depth = dirpath.count("/") - base_depth
        if depth >= 3:
            dirnames[:] = []
        for fn in sorted(filenames):
            out.append(os.path.relpath(os.path.join(dirpath, fn), root))
            if len(out) >= max_files:
                return out
    return out


def _vscode_provider(window_title: str) -> dict:
    folder = parse_vscode_folder(window_title)
    if not folder:
        return {}
    root = locate_folder(folder)
    if not root:
        log.info("VS Code workspace folder was not found under candidate roots.")
        return {}
    files = list_workspace_files(root)
    return {"workspace_root": root, "workspace_files": "\n".join(files)}


PROVIDERS = {
    **BROWSER_PROVIDERS,
    "com.apple.finder": _finder_provider,
    "com.microsoft.VSCode": _vscode_provider,
}


# ---------------------------------------------------------------------------
# main entry


# bundle_id -> [context] flag gating its provider (browsers share one flag)
_PROVIDER_FLAG = {
    "com.microsoft.VSCode": "vscode",
    "com.apple.finder": "finder",
}


def gather_context(app_name: str, bundle_id: str, window_title: str,
                   include_visible: bool = True,
                   flags: dict | None = None) -> dict:
    """Base context + whatever the app's provider can contribute +
    text before the cursor (continuation) + focused field text (draft) +
    visible text (surrounding / citation mode).

    `flags` = the [context] config section; every sub-flag defaults to true
    (missing key = on). include_visible=False skips the AX text reads (used
    when LLM formatting is disabled — nothing should leave the machine).

    focused_field_text, text_before_cursor, and visible_text are separate
    keys: the focused input is never silently reused as visible_text."""
    flags = flags or {}
    on = lambda name: bool(flags.get(name, True))

    ctx = {}
    if on("app_info"):
        ctx = {"app_name": app_name, "bundle_id": bundle_id,
               "window_title": window_title}
    if include_visible:
        from .context import (
            focused_field_text, text_before_cursor, visible_text,
        )
        if on("text_before_cursor"):
            try:
                tbc = text_before_cursor()
                if tbc:
                    ctx["text_before_cursor"] = tbc
            except Exception as e:
                log.info("text_before_cursor failed: %s", e)
        if on("focused_field_text"):
            try:
                fft = focused_field_text()
                if fft:
                    ctx["focused_field_text"] = fft
            except Exception as e:
                log.info("focused_field_text failed: %s", e)
        if on("visible_text"):
            try:
                vt = visible_text()
                if vt:
                    ctx["visible_text"] = vt
            except Exception as e:
                log.info("visible_text failed: %s", e)
    provider = PROVIDERS.get(bundle_id)
    if provider is not None:
        flag = _PROVIDER_FLAG.get(bundle_id, "browser")
        if not on(flag):
            provider = None
    if provider is None:
        return ctx
    try:
        # AppleScript providers must never launch the app.
        if bundle_id != "com.microsoft.VSCode" and not is_running(bundle_id):
            return ctx
        extra = provider(window_title or "")
        ctx.update({k: v for k, v in extra.items() if v})
    except Exception as e:
        log.info("Context provider for %s failed: %s", bundle_id, e)
    return ctx
