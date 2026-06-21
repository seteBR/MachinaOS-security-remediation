#!/usr/bin/env sh
set -eu

mkdir -p "${DATA_DIR:-/data}"

cd /app/server/nodejs
node dist/index.js &
NODEJS_PID=$!

cd /app/server
/app/server/.venv/bin/python -m uvicorn main:app \
  --host "${HOST:-0.0.0.0}" \
  --port "${PORT:-3010}" \
  --log-level "${UVICORN_LOG_LEVEL:-warning}" &
SERVER_PID=$!

term() {
  kill "$SERVER_PID" "$NODEJS_PID" 2>/dev/null || true
  wait "$SERVER_PID" "$NODEJS_PID" 2>/dev/null || true
}

trap term INT TERM
wait "$SERVER_PID"
