"""Guards for the polished macOS DMG installer presentation.

Source-level checks always run. An optional integration build uses a tiny
synthetic .app (never the real ~127 MB dist/golos.app) when explicitly
enabled or when macOS packaging tools are available and GOLOS_DMG_INTEGRATION
is not set to 0.
"""

from __future__ import annotations

import os
import plistlib
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MAKE_DMG = ROOT / "make_dmg.sh"
BG_SVG = ROOT / "assets" / "dmg-background.svg"
ICNS = ROOT / "golos.icns"
SITE_MARK = ROOT / "site" / "golos-mark.svg"


def _script() -> str:
    return MAKE_DMG.read_text(encoding="utf-8")


def _svg() -> str:
    return BG_SVG.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Source layout / identity
# ---------------------------------------------------------------------------


def test_make_dmg_script_exists_and_is_executableish():
    assert MAKE_DMG.is_file()
    text = _script()
    assert text.startswith("#!/bin/bash") or "set -euo pipefail" in text


def test_make_dmg_uses_writable_then_udzo_pipeline():
    text = _script()
    # Writable intermediate (blank UDIF or UDRW), then compressed UDZO.
    assert "UDIF" in text or "UDRW" in text
    assert "UDZO" in text
    assert "hdiutil create" in text
    assert "hdiutil convert" in text
    assert "hdiutil attach" in text
    assert "hdiutil detach" in text
    assert "readwrite" in text


def test_make_dmg_configures_finder_via_osascript():
    text = _script()
    assert "osascript" in text
    assert "icon view" in text
    assert "toolbar visible" in text
    assert "statusbar visible" in text
    assert "sidebar width" in text
    assert "background picture" in text
    assert ".background" in text
    assert "Applications" in text
    assert "golos.app" in text


def test_make_dmg_window_and_icon_geometry():
    text = _script()
    assert re.search(r"WIN_W=680", text)
    assert re.search(r"WIN_H=430", text)
    assert re.search(r"ICON_SIZE=128", text)
    assert re.search(r"APP_ICON_X=160", text)
    assert re.search(r"APPS_ICON_X=520", text)
    # Background SVG documents the same pad positions.
    svg = _svg()
    assert "160" in svg and "520" in svg
    assert 'width="680"' in svg and 'height="430"' in svg


def test_make_dmg_is_architecture_neutral():
    """Packages whichever .app the caller points at; no arch rebuild inside."""
    text = _script()
    assert "GOLOS_APP" in text
    assert "py2app" not in text
    assert "build_app" not in text
    assert "dist/golos.app" in text  # default source
    assert 'dist/golos-${VERSION}.dmg' in text or 'golos-${VERSION}.dmg' in text


def test_make_dmg_quotes_and_avoids_broad_rm():
    text = _script()
    # No unresolved recursive globs as rm targets.
    assert not re.search(r"rm\s+-rf\s+[\"']?/\$", text)
    assert "rm -rf /" not in text
    assert "rm -rf *" not in text
    # Cleanup trap present.
    assert "trap cleanup EXIT" in text
    assert "SetFile" in text  # with fallback path


def test_background_matches_dark_golos_identity():
    svg = _svg()
    # Site / brand palette
    assert "#080b12" in svg  # site --bg
    assert "#baff68" in svg  # site --lime
    assert "#5b8cff" in svg or "#5c9efa" in svg  # blue family
    assert "Drag golos to Applications" in svg
    # Canonical mark colors from site/golos-mark.svg
    mark = SITE_MARK.read_text(encoding="utf-8")
    assert "#0d1224" in mark and "#0d1224" in svg
    assert "#e0edff" in mark and "#e0edff" in svg
    # Volume icon identity asset must exist (not reinvented).
    assert ICNS.is_file()
    assert "golos.icns" in _script()


def test_background_hides_implementation_cues_in_script():
    text = _script()
    assert ".background" in text
    assert ".VolumeIcon.icns" in text
    # Dot-prefixed implementation files stay out of Finder's normal view.
    assert '"$MOUNT_POINT/.background"' in text
    assert '"$MOUNT_POINT/.VolumeIcon.icns"' in text


def test_bash_syntax_of_make_dmg():
    proc = subprocess.run(
        ["bash", "-n", str(MAKE_DMG)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


# ---------------------------------------------------------------------------
# Synthetic integration (tiny .app only)
# ---------------------------------------------------------------------------


def _macos_packaging_available() -> bool:
    if os.environ.get("GOLOS_DMG_INTEGRATION", "1") == "0":
        return False
    if os.uname().sysname != "Darwin":
        return False
    for cmd in ("hdiutil", "osascript", "ditto"):
        if shutil.which(cmd) is None:
            return False
    # Some sandboxes allow hdiutil in PATH but block create/attach (EPERM).
    probe = Path(tempfile.mkdtemp(prefix="golos-hdiutil-probe-"))
    try:
        src = probe / "src"
        src.mkdir()
        (src / "probe.txt").write_text("ok", encoding="utf-8")
        img = probe / "probe.dmg"
        proc = subprocess.run(
            [
                "hdiutil",
                "create",
                "-ov",
                "-volname",
                "golosprobe",
                "-srcfolder",
                str(src),
                "-format",
                "UDZO",
                str(img),
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if proc.returncode != 0:
            return False
        return img.is_file()
    except (OSError, subprocess.TimeoutExpired):
        return False
    finally:
        shutil.rmtree(probe, ignore_errors=True)


def _make_tiny_app(dest: Path) -> Path:
    """Minimal bundle so make_dmg.sh accepts it without a real py2app build."""
    app = dest / "golos.app"
    contents = app / "Contents"
    macos = contents / "MacOS"
    macos.mkdir(parents=True)
    (macos / "golos").write_text("#!/bin/sh\necho synthetic-golos\n", encoding="utf-8")
    (macos / "golos").chmod(0o755)
    info = {
        "CFBundleName": "golos",
        "CFBundleIdentifier": "com.softprom.golos.synthetic",
        "CFBundlePackageType": "APPL",
        "CFBundleExecutable": "golos",
        "CFBundleShortVersionString": "0.0.0-test",
    }
    with (contents / "Info.plist").open("wb") as fh:
        plistlib.dump(info, fh)
    return app


@pytest.mark.skipif(
    not _macos_packaging_available(),
    reason="macOS hdiutil/osascript not available or GOLOS_DMG_INTEGRATION=0",
)
def test_synthetic_dmg_contains_app_applications_and_background():
    """Build a tiny preview DMG, mount it, verify layout assets, clean up."""
    work = Path(tempfile.mkdtemp(prefix="golos-dmg-test-"))
    mount_point = None
    device = None
    try:
        app = _make_tiny_app(work)
        out_dmg = work / "golos-test-preview.dmg"
        work_dir = work / "dmg-build"
        env = os.environ.copy()
        env["GOLOS_APP"] = str(app)
        env["GOLOS_DMG"] = str(out_dmg)
        env["GOLOS_DMG_WORK"] = str(work_dir)
        # Prefer project venv for SVG rasterize when present.
        venv_py = ROOT / ".venv" / "bin" / "python"
        if venv_py.is_file():
            env["GOLOS_VENV"] = str(ROOT / ".venv")

        proc = subprocess.run(
            ["bash", str(MAKE_DMG), "test-preview"],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        assert proc.returncode == 0, (
            f"make_dmg failed:\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
        assert out_dmg.is_file(), "DMG was not created"
        assert out_dmg.stat().st_size > 10_000

        attach = subprocess.run(
            ["hdiutil", "attach", "-readonly", "-noidme", "-nobrowse", str(out_dmg)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert attach.returncode == 0, attach.stderr
        for line in attach.stdout.splitlines():
            if "/Volumes/" in line:
                parts = line.split(maxsplit=2)
                device = parts[0]
                mount_point = parts[2]
                break
        assert mount_point and Path(mount_point).is_dir(), attach.stdout

        root = Path(mount_point)
        assert (root / "golos.app").is_dir()
        assert (root / "golos.app" / "Contents" / "Info.plist").is_file()
        apps = root / "Applications"
        assert apps.is_symlink() or apps.exists()
        if apps.is_symlink():
            assert os.readlink(apps) == "/Applications"

        bg = root / ".background" / "background.png"
        assert bg.is_file(), "background PNG missing on volume"
        assert bg.stat().st_size > 1000

        vol_icon = root / ".VolumeIcon.icns"
        assert vol_icon.is_file()

        # Implementation helpers should be dot-files (hidden by default in Finder).
        visible = {p.name for p in root.iterdir() if not p.name.startswith(".")}
        assert "golos.app" in visible
        assert "Applications" in visible
        assert ".background" not in visible
        assert "background.png" not in visible

        # Volume name is golos (or golos N if name was taken).
        assert Path(mount_point).name.startswith("golos")

    finally:
        if device:
            subprocess.run(
                ["hdiutil", "detach", device, "-force"],
                capture_output=True,
                check=False,
            )
        elif mount_point:
            subprocess.run(
                ["hdiutil", "detach", mount_point, "-force"],
                capture_output=True,
                check=False,
            )
        # Remove only this test's exact tree.
        shutil.rmtree(work, ignore_errors=True)


def test_published_v031_assets_untouched_by_source_changes():
    """Guard: we do not rewrite already-published DMG filenames in this change set.

    The packaging script still emits dist/golos-<version>.dmg; published
    v0.3.1 assets under dist/ must not be modified by unit tests.
    """
    published = [
        ROOT / "dist" / "golos-0.3.1-apple-silicon.dmg",
        ROOT / "dist" / "golos-0.3.1-intel.dmg",
    ]
    for path in published:
        if not path.is_file():
            continue
        # Touch-free: just assert presence; integration test never targets these paths.
        assert path.stat().st_size > 1_000_000
    # Script default version token remains compatible with existing invocation.
    assert 'VERSION="${1:-0.3.1}"' in _script() or "0.3.1" in _script()
