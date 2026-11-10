#!/usr/bin/env bash
# Thin wrapper: the setup (prompt, Gmail login test, save) lives in set_smtp.py.
set -euo pipefail
cd "$(dirname "$0")/.."
exec uv run python scripts/set_smtp.py
