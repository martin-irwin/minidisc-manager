#!/usr/bin/env bash
# Starts MiniDisc Manager from source on Linux (after linux/setup.sh). Close any other recorder program first:
# only one program can use the recorder at a time.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -x "$ROOT/.venv/bin/python" ] && [ -d "$ROOT/runtime/node_modules" ] || { echo "Run linux/setup.sh first."; exit 1; }
cd "$ROOT"
exec "$ROOT/.venv/bin/python" himd_app.py "$@"
