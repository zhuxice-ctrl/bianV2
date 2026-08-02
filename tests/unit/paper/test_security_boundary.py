"""AST/string boundary tests: no live-order surface may exist in the paper package."""

from __future__ import annotations

import ast
from pathlib import Path

from bian_quant.paper.models import ALLOWED_ENDPOINTS

PACKAGE_DIR = Path(__file__).resolve().parents[3] / "src" / "bian_quant" / "paper"

#: Substrings that must never appear in the paper package source.
FORBIDDEN_SUBSTRINGS = (
    "/fapi/v1/order",
    "/fapi/v1/leverage",
    "/fapi/v1/positionSide",
    "/fapi/v1/account",
    "/sapi/v1",
    "X-MBX-APIKEY",
    "api_secret",
    "api_key",
    "websocket",
    "WebSocket",
)

#: Import module prefixes that would couple paper trading to a live adapter.
FORBIDDEN_IMPORT_PREFIXES = (
    "bian_quant.execution",
    "ccxt",
    "python_binance",
    "binance",
)


def _source_files() -> list[Path]:
    return sorted(PACKAGE_DIR.rglob("*.py"))


def test_package_directory_exists() -> None:
    assert PACKAGE_DIR.is_dir(), f"paper package not found at {PACKAGE_DIR}"
    assert _source_files(), "paper package has no source files"


def test_no_forbidden_substrings_in_source() -> None:
    for path in _source_files():
        text = path.read_text(encoding="utf-8")
        for token in FORBIDDEN_SUBSTRINGS:
            assert token not in text, f"{token!r} found in {path}"


def test_no_forbidden_imports() -> None:
    for path in _source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            else:
                continue
            for module in modules:
                for prefix in FORBIDDEN_IMPORT_PREFIXES:
                    assert not module.startswith(prefix), f"forbidden import {module!r} in {path}"


def test_public_allowlist_is_exactly_three_endpoints() -> None:
    assert ALLOWED_ENDPOINTS == (
        "/fapi/v1/klines",
        "/fapi/v1/exchangeInfo",
        "/fapi/v1/fundingRate",
    )


def test_no_caller_supplied_headers_anywhere() -> None:
    """No function signature in the package accepts a headers/api_key parameter."""
    for path in _source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                arg_names = {arg.arg for arg in node.args.args}
                arg_names |= {arg.arg for arg in node.args.kwonlyargs}
                assert "headers" not in arg_names, f"headers param in {path}:{node.name}"
                assert "api_key" not in arg_names, f"api_key param in {path}:{node.name}"
