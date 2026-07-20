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
    from ApplicationServices import AXIsProcessTrusted
    return bool(AXIsProcessTrusted())


def check_input_monitoring() -> bool:
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
    return status is True or status == "authorized"


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
