"""macOS permission diagnostics: Accessibility, Input Monitoring, Microphone.

Checked (not requested) at startup; each missing permission logs a loud
warning with the exact System Settings deep link. Also used by the status
item's Permissions submenu.
"""

import logging
import subprocess

log = logging.getLogger(__name__)

DEEP_LINKS = {
    "accessibility": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
    "input_monitoring": "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent",
    "microphone": "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone",
}

TITLES = {
    "accessibility": "Accessibility (paste insertion)",
    "input_monitoring": "Input Monitoring (global hotkeys)",
    "microphone": "Microphone (audio capture)",
}

WHY = {
    "accessibility": "the synthetic Cmd+V paste will be silently dropped by macOS",
    "input_monitoring": "global fn hotkeys won't be seen while other apps are focused",
    "microphone": "audio capture will fail or return silence",
}


def check_accessibility() -> bool:
    """True if this process is trusted for Accessibility (AX + synthetic keys)."""
    from ApplicationServices import AXIsProcessTrusted
    return bool(AXIsProcessTrusted())


def check_input_monitoring() -> bool:
    """True if Input Monitoring is granted (required for a live CGEventTap)."""
    from Quartz import CGPreflightListenEventAccess
    return bool(CGPreflightListenEventAccess())


def check_microphone() -> str:
    """Returns 'authorized' | 'denied' | 'restricted' | 'not_determined' | 'unknown'."""
    try:
        from AVFoundation import AVCaptureDevice, AVMediaTypeAudio
        status = int(AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio))
        return {0: "not_determined", 1: "restricted", 2: "denied",
                3: "authorized"}.get(status, "unknown")
    except Exception as e:
        log.warning("Could not check microphone authorization: %s", e)
        return "unknown"


def check_all() -> dict:
    """Snapshot of all three permissions. Microphone reports a status string;
    the others report bool."""
    return {
        "accessibility": check_accessibility(),
        "input_monitoring": check_input_monitoring(),
        "microphone": check_microphone(),
    }


def granted(status) -> bool:
    """Normalize bool (AX/IM) and mic status string into a single truthy check."""
    return status is True or status == "authorized"


def permission_snapshot(status: dict | None = None) -> dict:
    """Content-free permission snapshot for wake/diagnostics logs.

    Never includes deep links, paths, or user content — only grant flags
    (bool for Accessibility/Input Monitoring) and the mic status string.
    When *status* is None, runs ``check_all()`` (live TCC preflight).
    """
    if status is None:
        status = check_all()
    return {
        "accessibility": bool(status.get("accessibility")),
        "input_monitoring": bool(status.get("input_monitoring")),
        "microphone": status.get("microphone", "unknown"),
    }


def missing_kinds(status: dict | None = None) -> list[str]:
    """Permission keys that are not granted, in stable TITLES order."""
    if status is None:
        status = check_all()
    out = []
    for kind in TITLES:
        if kind not in status:
            continue
        if not granted(status[kind]):
            out.append(kind)
    return out


def wake_permission_notice(missing: list[str]) -> str:
    """Single idle-safe warning when permissions are gone after wake.

    One combined line (not one prompt per kind). Mentions observe-only when
    Input Monitoring is among the missing set. Content-free — no deep links.
    """
    if not missing:
        return ""
    labels = [TITLES.get(k, k) for k in missing]
    msg = "Permissions missing after wake: " + "; ".join(labels)
    if "input_monitoring" in missing:
        msg += " — hotkeys observe-only until Input Monitoring is granted"
    return msg


def open_settings_page(kind: str) -> None:
    """Open the System Settings pane for the given permission."""
    link = DEEP_LINKS[kind]
    log.info("Opening %s", link)
    subprocess.Popen(["open", link])


def log_report(status: dict | None = None) -> dict:
    """Log one line per granted permission and a loud warning per missing one."""
    if status is None:
        status = check_all()
    for kind, value in status.items():
        if granted(value):
            log.info("Permission OK: %s", TITLES[kind])
        else:
            log.warning(
                "⚠️  MISSING PERMISSION: %s — %s. "
                "Grant it in System Settings → Privacy & Security, then restart dictate. "
                "Open it now with: open \"%s\"",
                TITLES[kind], WHY[kind], DEEP_LINKS[kind],
            )
    return status
