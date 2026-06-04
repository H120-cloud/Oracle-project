#!/usr/bin/env bash
# Run the full pytest suite from the project root.
# Usage:  ./scripts/test.sh                   # all tests
#         ./scripts/test.sh -m regression     # one marker
#         ./scripts/test.sh tests/unit        # one path

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
exec python -m pytest "$@"
