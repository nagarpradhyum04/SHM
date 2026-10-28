#!/usr/bin/env bash
# Start the StructuraSense AI backend (FastAPI :8000) and frontend (Vite :5173) for local development.
# First run installs dependencies. Ctrl+C stops both.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
export VITE_API_PROXY_TARGET="${VITE_API_PROXY_TARGET:-http://127.0.0.1:$BACKEND_PORT}"

cd "$ROOT/backend"
if [ ! -x .venv/bin/python ]; then
  echo "› creating backend virtualenv"
  python3 -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -r requirements.txt
fi
[ -f .env ] || cp .env.example .env

cd "$ROOT/frontend"
[ -d node_modules ] || { echo "› installing frontend packages"; npm install --no-audit --no-fund; }

cleanup() { kill 0 2>/dev/null || true; }
trap cleanup EXIT INT TERM

echo "› backend  http://127.0.0.1:$BACKEND_PORT  (API docs: /docs)"
(cd "$ROOT/backend" && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$BACKEND_PORT") &
echo "› frontend http://127.0.0.1:$FRONTEND_PORT"
(cd "$ROOT/frontend" && npx vite --host 127.0.0.1 --port "$FRONTEND_PORT" --strictPort) &
wait
