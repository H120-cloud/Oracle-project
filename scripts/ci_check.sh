#!/usr/bin/env bash
# CI placeholder — runs the full local check suite that any future CI
# system should mirror. Each stage is gating.

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

echo "[ci_check] Stage 1: py_compile"
mapfile -d '' py_files < <(find src tests -name '*.py' -print0 2>/dev/null || true)
if [ ${#py_files[@]} -gt 0 ]; then
    python -m py_compile "${py_files[@]}"
fi

echo "[ci_check] Stage 2: pytest"
python -m pytest

echo "[ci_check] All stages passed."
