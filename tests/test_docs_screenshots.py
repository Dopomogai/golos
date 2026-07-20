"""Guards for public Settings Help Center screenshots.

Validates that the five docs images exist, are well-formed PNGs with
legible dimensions, carry no text/EXIF metadata, and that adjacent HTML
does not embed obvious secrets. Does not launch AppKit or read ~/.golos.
"""

from __future__ import annotations

import re
import struct
import zlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
IMAGES = ROOT / "site" / "docs" / "images"
SETTINGS_HTML = ROOT / "site" / "docs" / "settings" / "index.html"
SCRIPT = ROOT / "scripts" / "capture_docs_screenshots.py"

SHOTS = (
    "settings-history.png",
    "settings-general.png",
    "settings-prompt.png",
    "settings-learning.png",
    "settings-dictionary.png",
)

# Point-size window is 620×600; native retina capture includes shadow chrome
# and is typically ~1300+ px. Floors stay conservative for non-retina hosts.
MIN_WIDTH = 600
MIN_HEIGHT = 500
MIN_FILE_BYTES = 40_000

# Obvious secret / PII patterns that must not appear in docs HTML or PNG text.
SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9]{10,}"),
    re.compile(r"OPENROUTER_API_KEY\s*=\s*\S+"),
    re.compile(r"api_key\s*=\s*[\"'][^\"']{8,}[\"']"),
    re.compile(r"/Users/[^/\s]+/\.golos"),
    re.compile(r"/Users/[^/\s]+/\.dictate"),
    re.compile(r"-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----"),
)


def _png_chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "PNG signature missing"
    chunks: list[tuple[bytes, bytes]] = []
    pos = 8
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        tag = data[pos + 4 : pos + 8]
        start = pos + 8
        end = start + length
        assert end + 4 <= len(data), f"truncated chunk {tag!r}"
        payload = data[start:end]
        crc = struct.unpack(">I", data[end : end + 4])[0]
        expect = zlib.crc32(tag + payload) & 0xFFFFFFFF
        assert crc == expect, f"bad CRC for {tag!r}"
        chunks.append((tag, payload))
        pos = end + 4
        if tag == b"IEND":
            break
    return chunks


def _png_size(data: bytes) -> tuple[int, int]:
    chunks = _png_chunks(data)
    assert chunks[0][0] == b"IHDR"
    w, h = struct.unpack(">II", chunks[0][1][:8])
    return int(w), int(h)


def _text_from_png(data: bytes) -> str:
    """Decode any textual ancillary chunks (should be empty for our shots)."""
    parts: list[str] = []
    for tag, payload in _png_chunks(data):
        if tag == b"tEXt":
            parts.append(payload.decode("latin-1", errors="replace"))
        elif tag == b"iTXt":
            parts.append(payload.decode("utf-8", errors="replace"))
        elif tag == b"zTXt":
            parts.append(payload.decode("latin-1", errors="replace"))
        elif tag == b"eXIf":
            parts.append(payload.decode("latin-1", errors="replace"))
    return "\n".join(parts)


@pytest.mark.parametrize("name", SHOTS)
def test_screenshot_exists_valid_png(name: str):
    path = IMAGES / name
    assert path.is_file(), f"missing public screenshot: {path}"
    data = path.read_bytes()
    assert len(data) >= MIN_FILE_BYTES, f"{name}: file too small ({len(data)} bytes)"
    w, h = _png_size(data)
    assert w >= MIN_WIDTH, f"{name}: width {w} < {MIN_WIDTH}"
    assert h >= MIN_HEIGHT, f"{name}: height {h} < {MIN_HEIGHT}"
    # Must end cleanly with IEND.
    tags = [t for t, _ in _png_chunks(data)]
    assert tags[-1] == b"IEND"
    assert b"IDAT" in tags


@pytest.mark.parametrize("name", SHOTS)
def test_screenshot_has_no_text_or_exif_metadata(name: str):
    data = (IMAGES / name).read_bytes()
    tags = {t for t, _ in _png_chunks(data)}
    for banned in (b"tEXt", b"iTXt", b"zTXt", b"eXIf", b"tIME"):
        assert banned not in tags, f"{name}: unexpected PNG chunk {banned!r}"
    text = _text_from_png(data)
    assert text == ""
    for pat in SECRET_PATTERNS:
        assert not pat.search(text)


def test_all_five_shots_present():
    missing = [n for n in SHOTS if not (IMAGES / n).is_file()]
    assert not missing, f"missing screenshots: {missing}"


def test_settings_html_references_shots_and_no_secrets():
    assert SETTINGS_HTML.is_file()
    html = SETTINGS_HTML.read_text(encoding="utf-8")
    for name in SHOTS:
        assert f"../images/{name}" in html, f"settings HTML missing {name}"
    for pat in SECRET_PATTERNS:
        assert not pat.search(html), f"secret-like pattern in settings HTML: {pat.pattern}"


def test_capture_harness_script_exists_and_documents_safety():
    assert SCRIPT.is_file()
    src = SCRIPT.read_text(encoding="utf-8")
    # Safety contracts the harness must keep.
    assert "build_settings_window" in src
    assert "GOLOS_DOCS_CAPTURE_WORKER" in src or "WORKER_ENV" in src
    assert "~/.golos" in src or ".golos" in src
    assert "strip_png_metadata" in src
    assert "_bitmap_has_unrendered_tab_strip" in src
    assert "Mercey" in src  # fictional demo content
    assert "README.md" in src
    assert "project update" in src
    # Must not repurpose HOME for capture isolation.
    assert 'os.environ["HOME"]' not in src
    assert "os.environ['HOME']" not in src
    assert 'setenv("HOME"' not in src
