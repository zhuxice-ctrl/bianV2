#!/usr/bin/env bash
set -euo pipefail
uv run ruff check .
uv run ruff format --check .
uv run mypy src/bian_quant
uv run pytest -q
git diff --check
