#!/bin/sh
# Container entrypoint (see ../Dockerfile): the FastAPI backend listens privately on
# 127.0.0.1:$SENTINEL_API_PORT and the Next.js app serves $PORT, forwarding /api/* to it.
set -eu
APP_DIR="${APP_DIR:-/app}"
API_PORT="${SENTINEL_API_PORT:-8000}"

cd "$APP_DIR/command-center/backend"
python -m uvicorn main:app --host 127.0.0.1 --port "$API_PORT" &
API_PID=$!

# Accept traffic only once the backend answers, so the first visitor never sees an API error.
tries=0
until python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:$API_PORT/api/health', timeout=2)" 2>/dev/null; do
  tries=$((tries + 1))
  if [ "$tries" -gt 90 ] || ! kill -0 "$API_PID" 2>/dev/null; then
    echo "SENTINEL backend did not start" >&2
    exit 1
  fi
  sleep 1
done

cd "$APP_DIR/command-center/frontend"
exec node node_modules/next/dist/bin/next start --hostname 0.0.0.0 --port "${PORT:-8080}"
