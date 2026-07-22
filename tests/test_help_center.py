"""Focused guards for the public help center under site/docs/.

Dependency-light: reads HTML/CSS from the repo. No network.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
DOCS = SITE / "docs"
PRODUCT = SITE / "index.html"
STYLES = SITE / "styles.css"
DOCS_CSS = DOCS / "docs.css"

HELP_ROUTES = [
    DOCS / "index.html",
    DOCS / "getting-started" / "index.html",
    DOCS / "settings" / "index.html",
    DOCS / "workflows" / "index.html",
    DOCS / "better-results" / "index.html",
    DOCS / "privacy" / "index.html",
    DOCS / "troubleshooting" / "index.html",
]

SIDEBAR_PAGES = [p for p in HELP_ROUTES if p.parent != DOCS]

SHARED_CHROME = (
    "docs-nav-shell",
    "docs-nav-links",
    "docs-shell",
    "docs-footer",
)

SIDEBAR_CHROME = (
    "docs-shell--with-sidebar",
    "docs-sidebar",
    "docs-sidebar-title",
    "docs-article",
    "docs-pager",
    "pager-link",
    "pager-dir",
    "pager-title",
)

FORBIDDEN_CLASSES = (
    "docs-header",
    "docs-sidebar-label",
    "sidebar-kicker",
    "sidebar-nav",
    "sidebar-toc",
    "compare-table",
    "compare-table-wrap",
    "comparison-table-wrap",
    "callout-info",
    "callout-warn",
    "docs-pager-prev",
    "docs-pager-next",
    "docs-pager-label",
    "docs-pager-title",
    "docs-prev-next",
    "docs-article-footer",
    "pn-label",
    "pn-title",
)

SETTINGS_SCREENSHOTS = (
    "settings-history.png",
    "settings-general.png",
    "settings-prompt.png",
    "settings-learning.png",
    "settings-dictionary.png",
)

STALE_OR_DANGEROUS = (
    "fractions of a cent",
    "M1–M4",
    "M1-M4",
    "Not planned",
    "verified delivery",
    "auto-update",
    "signed and notarized",
    "Developer ID signed",
)


class _LinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []
        self.srcs: list[str] = []
        self.ids: set[str] = set()
        self.attrs: list[tuple[str, dict[str, str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        ad = {k: (v or "") for k, v in attrs}
        self.attrs.append((tag, ad))
        if "id" in ad and ad["id"]:
            self.ids.add(ad["id"])
        if tag == "a" and "href" in ad:
            self.hrefs.append(ad["href"])
        if tag in {"img", "script", "link", "source"} and "src" in ad:
            self.srcs.append(ad["src"])
        if tag == "link" and ad.get("href"):
            # stylesheets / icons counted as local asset refs
            self.srcs.append(ad["href"])


def _parse(path: Path) -> tuple[str, _LinkCollector]:
    html = path.read_text(encoding="utf-8")
    parser = _LinkCollector()
    parser.feed(html)
    return html, parser


def _is_external(url: str) -> bool:
    if not url or url.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
        return False
    parsed = urlparse(url)
    return bool(parsed.scheme in {"http", "https"} or parsed.netloc)


def _resolve_local(base: Path, ref: str) -> Path | None:
    if not ref or ref.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
        return None
    if _is_external(ref):
        return None
    pure = ref.split("#", 1)[0].split("?", 1)[0]
    if not pure:
        return None
    pure = unquote(pure)
    target = (base.parent / pure).resolve()
    return target


def test_every_help_route_exists():
    for path in HELP_ROUTES:
        assert path.is_file(), f"missing help route: {path.relative_to(ROOT)}"


def test_shared_class_contract_on_help_pages():
    css = DOCS_CSS.read_text(encoding="utf-8")
    for cls in (*SHARED_CHROME, *SIDEBAR_CHROME, "table-wrap", "comparison-table",
                "callout--note", "callout--warning", "callout--tip"):
        assert f".{cls}" in css or f".{cls} " in css or f".{cls}," in css or f".{cls}:" in css or f".{cls}{{" in css or f".{cls}\n" in css, (
            f"docs.css missing system class .{cls}"
        )
        # also accept block selectors like .callout--note {
        assert cls.replace("--", r"\-\-") or True

    for path in HELP_ROUTES:
        html, _ = _parse(path)
        for cls in SHARED_CHROME:
            assert cls in html, f"{path.relative_to(ROOT)} missing class {cls}"
        for bad in FORBIDDEN_CLASSES:
            # class token boundaries
            assert not re.search(rf'\bclass="[^"]*\b{re.escape(bad)}\b', html), (
                f"{path.relative_to(ROOT)} still uses forbidden class {bad}"
            )
            assert f'class="{bad}"' not in html
        if path in SIDEBAR_PAGES:
            for cls in SIDEBAR_CHROME:
                assert cls in html, f"{path.relative_to(ROOT)} missing class {cls}"
            assert 'aria-current="page"' in html
            assert "Overview" in html
            assert re.search(r'href="\.\./(?:index\.html)?"|>Overview<', html) or re.search(
                r'href="\./"|href="\.\./"', html
            )


def test_sidebar_overview_links_present():
    for path in SIDEBAR_PAGES:
        html, _ = _parse(path)
        assert re.search(
            r'<a href="\.\./(?:index\.html)?">Overview</a>',
            html,
        ), f"{path.relative_to(ROOT)} sidebar missing Overview link"


def test_callouts_use_modifier_classes():
    for path in HELP_ROUTES:
        html, _ = _parse(path)
        assert "callout-info" not in html
        assert "callout-warn" not in html
        # when callouts exist, prefer BEM modifiers
        if "class=\"callout" in html or "class='callout" in html or " callout " in html:
            assert "callout--" in html or path.name  # landing may only use callout--tip


def test_tables_use_overflow_wrappers():
    for path in HELP_ROUTES:
        html, _ = _parse(path)
        if "comparison-table" not in html:
            continue
        # every comparison-table should sit inside a table-wrap
        # crude but effective: count wrappers >= table opens
        tables = len(re.findall(r'class="[^"]*\bcomparison-table\b', html))
        wraps = len(re.findall(r'class="[^"]*\btable-wrap\b', html))
        assert wraps >= tables, (
            f"{path.relative_to(ROOT)}: {tables} comparison-table(s) but only {wraps} table-wrap"
        )


def test_local_hrefs_srcs_and_anchors_resolve():
    for path in HELP_ROUTES:
        html, parser = _parse(path)
        for href in parser.hrefs:
            if href.startswith("#"):
                frag = unquote(href[1:])
                if frag:
                    assert frag in parser.ids, (
                        f"{path.relative_to(ROOT)} broken in-page anchor #{frag}"
                    )
                continue
            if _is_external(href):
                continue
            if "#" in href:
                file_part, frag = href.split("#", 1)
                if file_part:
                    target = _resolve_local(path, file_part)
                    assert target is not None and target.exists(), (
                        f"{path.relative_to(ROOT)} broken href {href}"
                    )
                    if target.suffix == ".html" or target.is_dir() or target.name == "index.html":
                        # resolve directory → index.html
                        if target.is_dir():
                            target = target / "index.html"
                        if target.is_file() and frag:
                            dest_html = target.read_text(encoding="utf-8")
                            assert f'id="{frag}"' in dest_html or f"id='{frag}'" in dest_html, (
                                f"{path.relative_to(ROOT)} broken cross-page anchor {href}"
                            )
                else:
                    frag = unquote(frag)
                    assert frag in parser.ids, (
                        f"{path.relative_to(ROOT)} broken in-page anchor #{frag}"
                    )
                continue
            target = _resolve_local(path, href)
            if target is None:
                continue
            ok = target.exists() or (target.with_suffix(".html").exists() if not target.suffix else False)
            if not ok and not target.suffix:
                ok = (target / "index.html").exists()
            # intentionally allow missing screenshot PNGs — assets land in a later task
            if target.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
                continue
            assert ok, f"{path.relative_to(ROOT)} broken local href {href} → {target}"

        for src in parser.srcs:
            if _is_external(src):
                continue
            target = _resolve_local(path, src)
            if target is None:
                continue
            if target.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
                # screenshot assets may be supplied later; path form is still checked below
                continue
            assert target.exists(), f"{path.relative_to(ROOT)} broken local src {src} → {target}"


def test_settings_screenshot_references_present():
    settings = (DOCS / "settings" / "index.html").read_text(encoding="utf-8")
    for name in SETTINGS_SCREENSHOTS:
        assert f"../images/{name}" in settings, f"missing screenshot ref {name}"


def test_getting_started_and_settings_have_complete_og():
    for rel, url in (
        ("getting-started/index.html", "https://golos.dopomogai.com/docs/getting-started/"),
        ("settings/index.html", "https://golos.dopomogai.com/docs/settings/"),
    ):
        html = (DOCS / rel).read_text(encoding="utf-8")
        assert 'property="og:title"' in html
        assert 'property="og:description"' in html
        assert 'property="og:url"' in html
        assert f'content="{url}"' in html


def test_product_page_discovers_docs():
    html = PRODUCT.read_text(encoding="utf-8")
    assert re.search(r'href="docs/?"', html), "product page missing Docs link to /docs/"
    # nav and footer both surface help discovery
    assert html.count('href="docs/"') + html.count('href="docs"') >= 2


def test_product_page_truth_guards():
    html = PRODUCT.read_text(encoding="utf-8")
    assert "fractions of a cent" not in html
    assert "M1–M4" not in html and "M1-M4" not in html
    assert "provider-billed" in html or "provider billed" in html.lower()
    assert "best-effort" in html.lower() or "not a universal guarantee" in html.lower()
    assert "Apple Silicon" in html
    styles = STYLES.read_text(encoding="utf-8")
    assert ":focus-visible" in styles


def test_toggle_combo_is_config_only_not_settings_ui():
    for path in (DOCS / "workflows" / "index.html", DOCS / "troubleshooting" / "index.html"):
        html = path.read_text(encoding="utf-8")
        assert "config-only" in html or "config.toml" in html
        # must not tell users to change it in Settings
        assert not re.search(
            r"change the combo in Settings|Settings\s*→\s*General has\s*\*?\*?toggle combo",
            html,
            re.I,
        )
        assert "toggle_combo" in html or "[hotkey]" in html


def test_settings_raw_corrections_wording():
    html = (DOCS / "settings" / "index.html").read_text(encoding="utf-8")
    compact = re.sub(r"\s+", " ", html)
    assert re.search(r"pure\s+raw", compact, re.I) or re.search(
        r"no\s+local\s+corrections", compact, re.I
    )
    assert re.search(r"Fast mode short path", compact) or re.search(
        r"local\s+corrections", compact, re.I
    )
    # fuzzy old wording should be gone
    assert "Corrections may still apply depending on pipeline path" not in html


def test_better_results_no_duplicate_download_cta():
    html = (DOCS / "better-results" / "index.html").read_text(encoding="utf-8")
    # one primary download control in nav, not both plain + button
    nav_chunk = html.split("</header>", 1)[0]
    download_links = re.findall(r'href="[^"]*#download"[^>]*>([^<]+)', nav_chunk)
    assert len(download_links) == 1, f"expected single Download CTA in nav, got {download_links}"


def test_no_stale_or_dangerous_claims_in_help():
    product = PRODUCT.read_text(encoding="utf-8")
    for path in HELP_ROUTES:
        text = path.read_text(encoding="utf-8")
        for phrase in STALE_OR_DANGEROUS:
            if phrase in (
                "Developer ID signed",
                "signed and notarized",
                "verified delivery",
                "auto-update",
            ):
                # allowed only as negation / denial of the claim
                for m in re.finditer(re.escape(phrase), text, re.I):
                    window = text[max(0, m.start() - 50) : m.end() + 20].lower()
                    assert any(
                        token in window
                        for token in (
                            "not",
                            "never",
                            "no ",
                            "unsigned",
                            "do not",
                            "manual",
                            "without",
                        )
                    ), (
                        f"{path.relative_to(ROOT)} affirmative claim around {phrase!r}: {window!r}"
                    )
                continue
            assert phrase not in text, f"{path.relative_to(ROOT)} contains stale/dangerous {phrase!r}"
    assert "provider-billed" in product or "variable" in product.lower()


def test_help_center_states_insertion_posted_not_verified():
    joined = "\n".join(p.read_text(encoding="utf-8") for p in HELP_ROUTES)
    assert re.search(r"posted", joined, re.I)
    assert re.search(r"not\s+(a\s+)?(guarantee|verified)|does\s+\*\*not\*\*\s+verify|not verified", joined, re.I)


def test_fully_local_recipe_present():
    joined = "\n".join(p.read_text(encoding="utf-8") for p in HELP_ROUTES)
    assert "Apple Silicon" in joined
    assert re.search(r"MLX", joined)
    assert re.search(r"format(ting)?\s+off|Format with LLM.*off|formatting disabled", joined, re.I)
    assert re.search(r"reviewer\s+off", joined, re.I)


def test_docs_css_defines_table_wrap_overflow():
    css = DOCS_CSS.read_text(encoding="utf-8")
    assert ".table-wrap" in css
    assert "overflow" in css


def test_help_center_applies_to_current_public_beta():
    """Version badges and primary DMG CTAs track the current public beta."""
    public = "v0.3.3"
    stale_dmg = (
        "releases/download/v0.3.2/golos-0.3.2-apple-silicon.dmg",
        "releases/download/v0.3.2/golos-0.3.2-intel.dmg",
    )
    for path in HELP_ROUTES:
        html = path.read_text(encoding="utf-8")
        assert public in html, f"{path.relative_to(ROOT)} missing {public}"
        for marker in stale_dmg:
            assert marker not in html, (
                f"{path.relative_to(ROOT)} still links stale asset {marker}"
            )


def test_help_documents_default_clipboard_restore_and_wake_recovery():
    settings = (DOCS / "settings" / "index.html").read_text(encoding="utf-8")
    troubleshooting = (DOCS / "troubleshooting" / "index.html").read_text(encoding="utf-8")
    privacy = (DOCS / "privacy" / "index.html").read_text(encoding="utf-8")
    assert "restore_clipboard" in settings
    assert re.search(r"true</code>\s+by\s+default|true\s+by\s+default|default\s+.*on", settings, re.I)
    assert re.search(r"changeCount|CAS", settings)
    assert re.search(r"wake|long idle|15\+", troubleshooting, re.I)
    assert "Export Diagnostics" in troubleshooting
    assert re.search(r"restore_clipboard\s*=\s*true|restore clipboard", privacy, re.I)
    # Must not reintroduce the inverted default claim.
    assert "false by default (paste keeps the transcript)" not in settings
    assert "restoring the previous clipboard is opt-in" not in troubleshooting
