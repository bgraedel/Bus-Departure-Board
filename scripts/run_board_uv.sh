#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  source .env
fi

EXTRA_ARGS=()
if [[ -n "${BOARD_ARGS:-}" ]]; then
  # shellcheck disable=SC2206
  EXTRA_ARGS=(${BOARD_ARGS})
fi

exec uv run python ojp_departures.py "${EXTRA_ARGS[@]}" "$@"
