"""Guards for open-source community files (CONTRIBUTING, SECURITY, issue/PR templates).

Dependency-light: reads repo-root Markdown and .github templates. No network.
Follows the same metadata pattern as tests/test_site.py.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRIBUTING = ROOT / "CONTRIBUTING.md"
SECURITY = ROOT / "SECURITY.md"
ISSUE_CONFIG = ROOT / ".github" / "ISSUE_TEMPLATE" / "config.yml"
BUG_REPORT = ROOT / ".github" / "ISSUE_TEMPLATE" / "bug_report.yml"
FEATURE_REQUEST = ROOT / ".github" / "ISSUE_TEMPLATE" / "feature_request.yml"
PR_TEMPLATE = ROOT / ".github" / "pull_request_template.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_contributing_exists_with_budai_front_matter_and_beta_facts():
    assert CONTRIBUTING.is_file()
    body = _text(CONTRIBUTING)
    assert body.lstrip().startswith("---")
    assert "@purpose:" in body
    assert "v0.3.3" in body
    assert "unsigned" in body.lower()
    assert "macOS 13" in body
    assert "Apple Silicon" in body
    assert "Intel" in body
    assert "~/.golos" in body
    assert "pytest" in body
    assert "docs/TESTING.md" in body
    assert "right-click" in body.lower()
    assert "auto-updat" in body.lower() or "automatic updater" in body.lower()


def test_security_exists_without_invented_email():
    assert SECURITY.is_file()
    body = _text(SECURITY)
    assert body.lstrip().startswith("---")
    assert "@purpose:" in body
    assert "v0.3.3" in body
    assert "private vulnerability" in body.lower()
    assert "github.com/Dopomogai/golos" in body
    # No fabricated security@ addresses in this file.
    assert "security@" not in body.lower()
    assert "mailto:" not in body.lower()
    assert "API key" in body or "api keys" in body.lower()
    assert "~/.golos" in body


def test_issue_template_config_and_forms():
    assert ISSUE_CONFIG.is_file()
    config = _text(ISSUE_CONFIG)
    assert "blank_issues_enabled" in config
    assert "SECURITY.md" in config or "security" in config.lower()

    assert BUG_REPORT.is_file()
    bug = _text(BUG_REPORT)
    # GitHub issue forms are YAML documents, not Budai front matter docs.
    assert bug.lstrip().startswith("name:")
    assert "architecture" in bug.lower() or "Apple Silicon" in bug
    assert "macOS" in bug
    assert "version" in bug.lower()
    assert "Cloud" in bug or "cloud" in bug
    assert "Local MLX" in bug or "local" in bug.lower()
    assert "Steps to reproduce" in bug or "steps" in bug.lower()
    assert "Expected" in bug
    assert "Actual" in bug
    assert "Sanitized" in bug or "sanitize" in bug.lower()
    assert "API key" in bug or "API keys" in bug
    assert "Never paste" in bug or "never paste" in bug.lower()

    assert FEATURE_REQUEST.is_file()
    feature = _text(FEATURE_REQUEST)
    assert feature.lstrip().startswith("name:")
    assert "ROADMAP" in feature or "roadmap" in feature.lower()


def test_pull_request_template_checklist():
    assert PR_TEMPLATE.is_file()
    body = _text(PR_TEMPLATE)
    assert "Focused tests" in body or "focused tests" in body.lower()
    assert "pytest" in body
    assert "docs" in body.lower()
    assert "secret" in body.lower() or "API key" in body
    assert "unsigned" in body.lower()
    assert "notariz" in body.lower() or "sign" in body.lower()
    assert "personal" in body.lower() or "recording" in body.lower()
    assert "v0.3.3" in body
