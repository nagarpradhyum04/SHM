#!/usr/bin/env bash
# Run backend (pytest) and frontend (typecheck + vitest) test suites.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
echo "== backend =="
(cd "$ROOT/backend" && .venv/bin/python -m pip show pytest >/dev/null 2>&1 || .venv/bin/pip install -q -r requirements-dev.txt; cd "$ROOT/backend" && .venv/bin/python -m pytest -q)
echo "== frontend =="
(cd "$ROOT/frontend" && npx tsc -b --noEmit && npx vitest run)
