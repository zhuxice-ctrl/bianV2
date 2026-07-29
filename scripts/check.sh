#!/usr/bin/env bash
set -euo pipefail
export PYTHONUTF8=1
uv run ruff check .
uv run ruff format --check .
uv run mypy src/bian_quant
uv run pytest -q
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git diff --check
elif command -v git.exe >/dev/null 2>&1 && command -v wslpath >/dev/null 2>&1; then
  git.exe -C "$(wslpath -w "$PWD")" diff --check
elif command -v wslpath >/dev/null 2>&1 && [[ -f .git ]]; then
  windows_git_dir="$(sed -n 's/^gitdir: //p' .git)"
  git_dir="$(wslpath -u "$windows_git_dir")"
  git --git-dir="$git_dir" --work-tree="$PWD" diff --check
else
  echo "unable to locate Git metadata for diff check" >&2
  exit 1
fi
