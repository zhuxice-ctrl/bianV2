"""Smoke tests for the research terminal HTML page.

Validates that ``dashboard/research.html`` contains the required structural
markers for the single-asset ETH strategy comparison section and does not
introduce any forbidden trading/order controls.
"""

from __future__ import annotations

from pathlib import Path

import pytest

RESEARCH_HTML = Path(__file__).resolve().parents[2] / "dashboard" / "research.html"

REQUIRED_MARKERS = [
    "ETH 单币策略对比",
    "当前是否建议参与",
    "原始策略",
    "置信度加权",
    "胜率",
    "手续费后净利润",
    "READ-ONLY · RESEARCH ONLY · NO LIVE TRADING",
]

FORBIDDEN_MARKERS = [
    "下单",
    "买入",
    "卖出",
    "placeOrder",
    "submitOrder",
    "download",
    "api_key",
    "apikey",
    "secret",
]


@pytest.fixture
def html_content() -> str:
    """Load the research.html file content."""
    if not RESEARCH_HTML.is_file():
        pytest.skip(f"research.html not found at {RESEARCH_HTML}")
    return RESEARCH_HTML.read_text(encoding="utf-8")


def test_required_markers_present(html_content: str):
    """All required HTML markers must be present in research.html."""
    for marker in REQUIRED_MARKERS:
        assert marker in html_content, f"Missing required marker: {marker}"


def test_no_forbidden_trading_controls(html_content: str):
    """The page must not contain any trading, ordering, or API key controls."""
    for marker in FORBIDDEN_MARKERS:
        assert marker not in html_content, f"Forbidden marker found: {marker}"


def test_single_asset_render_function_exists(html_content: str):
    """The page must include a JavaScript function to render single-asset evaluations."""
    assert "renderSingleAssetEvaluations" in html_content, (
        "Missing renderSingleAssetEvaluations function"
    )


def test_escape_html_used_for_api_text(html_content: str):
    """All API-derived text must be passed through escapeHtml."""
    assert "escapeHtml" in html_content, "escapeHtml function not found"
    # Check that escapeHtml is used in the single-asset rendering section
    # by looking for its usage pattern
    assert html_content.count("escapeHtml") >= 5, (
        "escapeHtml should be used multiple times for API text safety"
    )
