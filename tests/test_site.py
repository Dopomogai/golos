"""Guards for the static product page and public roadmap wording.

Dependency-light: reads site/ and docs/ from the repo root. No network.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
INDEX = SITE / "index.html"
MARK = SITE / "golos-mark.svg"
ROADMAP = ROOT / "docs" / "ROADMAP.md"
PRODUCT_PAGE = ROOT / "docs" / "PRODUCT_PAGE.md"
VISION = ROOT / "docs" / "VISION.md"
README = ROOT / "README.md"

APPLE_DMG = (
    "https://github.com/Dopomogai/golos/releases/download/v0.3.2/"
    "golos-0.3.2-apple-silicon.dmg"
)
INTEL_DMG = (
    "https://github.com/Dopomogai/golos/releases/download/v0.3.2/"
    "golos-0.3.2-intel.dmg"
)


def _html() -> str:
    return INDEX.read_text(encoding="utf-8")


def test_favicon_identity_points_at_golos_mark():
    html = _html()
    assert 'rel="icon"' in html
    assert 'href="golos-mark.svg"' in html
    assert MARK.is_file()
    mark = MARK.read_text(encoding="utf-8")
    assert "Golos web mark" in mark or "Vishuddha" in mark
    assert 'viewBox="0 0 1024 1024"' in mark


def test_public_custom_domain_is_canonical():
    html = _html()
    assert '<link rel="canonical" href="https://golos.dopomogai.com/">' in html
    assert '<meta property="og:url" content="https://golos.dopomogai.com/">' in html


def test_direct_architecture_dmg_links():
    html = _html()
    assert APPLE_DMG in html
    assert INTEL_DMG in html
    # Primary flow must not funnel only to the generic releases index.
    assert html.count(APPLE_DMG) >= 2
    assert html.count(INTEL_DMG) >= 2


def test_download_and_roadmap_anchors():
    html = _html()
    assert 'id="download"' in html
    assert 'id="roadmap"' in html
    assert 'href="#download"' in html
    assert 'href="#roadmap"' in html
    # Nav download is the chooser anchor, not the generic release page.
    assert 'href="#download">Download beta</a>' in html


def test_public_roadmap_doc_linked_and_present():
    assert ROADMAP.is_file()
    roadmap = ROADMAP.read_text(encoding="utf-8")
    assert roadmap.lstrip().startswith("---")
    assert "@purpose:" in roadmap
    assert "Shipped now" in roadmap
    assert "Near term" in roadmap
    assert "Pipeline" in roadmap
    assert "Mac is supported today" in roadmap

    html = _html()
    assert "docs/ROADMAP.md" in html
    assert "github.com/Dopomogai/golos/blob/main/docs/ROADMAP.md" in html


def test_platform_wording_not_stale_not_planned():
    html = _html()
    assert "Not planned" not in html
    assert "Is Windows supported?" not in html
    assert "Which platforms are available?" in html
    assert "macOS is supported today" in html
    assert "pipeline" in html.lower()
    assert "cloud-only" in html.lower()
    assert "right-click" in html.lower()

    product = PRODUCT_PAGE.read_text(encoding="utf-8")
    assert "Not planned" not in product
    assert "Which platforms are available?" in product
    assert "pipeline" in product.lower()

    vision = VISION.read_text(encoding="utf-8")
    assert "Explicitly parked" not in vision
    assert "Must-haves before public release" not in vision
    assert "public" in vision.lower() and "0.3.2" in vision
    assert "Mac is supported today" in vision

    readme = README.read_text(encoding="utf-8")
    assert APPLE_DMG in readme
    assert INTEL_DMG in readme
    assert "docs/ROADMAP.md" in readme
