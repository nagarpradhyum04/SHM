#!/usr/bin/env bash
# Start the StructuraSense AI backend (FastAPI :8000) and frontend (Vite :5173) for local development.
# First run installs dependencies. Ctrl+C stops both.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

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

echo "› backend  http://127.0.0.1:8000  (API docs: /docs)"
(cd "$ROOT/backend" && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000) &
echo "› frontend http://127.0.0.1:5173"
(cd "$ROOT/frontend" && npx vite --host 127.0.0.1 --port 5173) &
wait
