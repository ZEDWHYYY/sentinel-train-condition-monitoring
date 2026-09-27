#!/usr/bin/env bash
# SENTINEL — start the app on localhost.
#
#   ./run.sh           set up if needed, start API (:8000) + web app (:3000), open the browser
#   ./run.sh --dev     same, but run the web app in development mode (hot reload)
#   ./run.sh --stop    stop a SENTINEL started by this script in another terminal
#
# Ctrl+C stops this instance. Logs: .logs/run-<api-port>-<web-port>/
# Options via environment: SENTINEL_API_PORT, SENTINEL_WEB_PORT, SENTINEL_NO_BROWSER=1
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_DIR="$ROOT/command-center/backend"
WEB_DIR="$ROOT/command-center/frontend"
API_PORT="${SENTINEL_API_PORT:-8000}"
WEB_PORT="${SENTINEL_WEB_PORT:-3000}"
LOGS="$ROOT/.logs/run-$API_PORT-$WEB_PORT"
PIDS="$LOGS/pids"
MODE="start"
WEB_MODE="prod"
for a in "$@"; do
  case "$a" in
    --dev) WEB_MODE="dev" ;;
    --stop) MODE="stop" ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "Unknown option: $a (see ./run.sh --help)"; exit 2 ;;
  esac
done

say()  { printf '\033[1;34m==>\033[0m %s\n' "$1"; }
ok()   { printf '\033[1;32m ok\033[0m %s\n' "$1"; }
fail() { printf '\033[1;31merror\033[0m %s\n' "$1"; exit 1; }
mkdir -p "$LOGS"

stop_all() {
  if [[ -f "$PIDS" ]]; then
    while read -r pid; do
      [[ -n "$pid" ]] || continue
      pkill -TERM -P "$pid" 2>/dev/null || true
      kill "$pid" 2>/dev/null || true
    done < "$PIDS"
    rm -f "$PIDS"
  fi
}

if [[ "$MODE" == "stop" ]]; then
  stop_all
  ok "SENTINEL stopped"
  exit 0
fi

# ---------------------------------------------------------------- prerequisites
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
command -v python3 >/dev/null || fail "python3 not found. Install Python 3.13+."
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 13) else 1)' || fail "Python 3.13+ is required for the pinned numerical packages."
command -v node >/dev/null || fail "Node.js not found. Install Node 22+."
[[ "$(node -p 'process.versions.node.split(".")[0]')" -ge 22 ]] || fail "Node 22+ is required."
for t in door acv rail shm; do
  [[ -f "$ROOT/artifacts/ps3/$t/model.json" ]] || fail "Frozen model for '$t' is missing (artifacts/ps3/$t). Rebuild with training/train_all.py."
done
ok "node $(node --version), frozen models present"

# Never stop an existing app implicitly; --stop is the explicit shutdown action.
for p in "$API_PORT" "$WEB_PORT"; do
  if lsof -nP -iTCP:"$p" -sTCP:LISTEN >/dev/null 2>&1; then
    fail "Port $p is already in use. Stop that program, or run e.g. SENTINEL_WEB_PORT=3001 ./run.sh"
  fi
done

# ---------------------------------------------------------------- backend setup
cd "$API_DIR"
if [[ -d .venv ]] && ! .venv/bin/python -c 'pass' >/dev/null 2>&1; then
  say "Python environment is broken (copied from another machine?) — rebuilding"
  mv .venv ".venv.broken-$(date +%s)"
fi
if [[ ! -d .venv ]]; then
  say "Creating Python environment (first run, about a minute)"
  python3 -m venv .venv
fi
if [[ ! -f .venv/.installed || requirements.txt -nt .venv/.installed ]]; then
  say "Installing Python packages"
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install --quiet -r requirements.txt
  touch .venv/.installed
fi
ok "backend ready (Python $(.venv/bin/python -c "import platform; print(platform.python_version())"))"

# ---------------------------------------------------------------- frontend setup
cd "$WEB_DIR"
export SENTINEL_API_ORIGIN="http://127.0.0.1:$API_PORT" NEXT_TELEMETRY_DISABLED=1
export NEXT_DIST_DIR="${NEXT_DIST_DIR:-.next-app-$API_PORT}"
if [[ ! -x node_modules/.bin/next || package-lock.json -nt node_modules/.installed ]]; then
  say "Installing web packages (first run, about a minute)"
  npm ci --no-fund --no-audit >"$LOGS/npm.log" 2>&1 || { cat "$LOGS/npm.log"; fail "npm install failed (see above)"; }
  touch node_modules/.installed
fi
if [[ "$WEB_MODE" == "prod" ]]; then
  newest_src="$(find app components lib next.config.mjs tailwind.config.ts package-lock.json -type f -newer "$NEXT_DIST_DIR/BUILD_ID" 2>/dev/null | head -1 || true)"
  # the /api proxy target is fixed at build time, so rebuild when it changes
  if [[ ! -f "$NEXT_DIST_DIR/BUILD_ID" || -n "$newest_src" || "$(cat "$NEXT_DIST_DIR/.api_origin" 2>/dev/null)" != "$SENTINEL_API_ORIGIN" ]]; then
    say "Building the web app (about 20 seconds)"
    node_modules/.bin/next build >"$LOGS/build.log" 2>&1 || { tail -30 "$LOGS/build.log"; fail "web build failed (see above)"; }
    echo "$SENTINEL_API_ORIGIN" > "$NEXT_DIST_DIR/.api_origin"
  fi
fi
ok "web app ready"

# ---------------------------------------------------------------- start
cleanup() {
  echo
  say "Stopping SENTINEL"
  stop_all
  ok "stopped"
}
trap cleanup EXIT INT TERM

cd "$API_DIR"
.venv/bin/uvicorn main:app --host 127.0.0.1 --port "$API_PORT" >"$LOGS/api.log" 2>&1 &
echo $! >>"$PIDS"

cd "$WEB_DIR"
if [[ "$WEB_MODE" == "prod" ]]; then
  node_modules/.bin/next start --port "$WEB_PORT" --hostname 127.0.0.1 >"$LOGS/web.log" 2>&1 &
else
  node_modules/.bin/next dev --port "$WEB_PORT" --hostname 127.0.0.1 >"$LOGS/web.log" 2>&1 &
fi
echo $! >>"$PIDS"

say "Starting (API :$API_PORT, web app :$WEB_PORT)"
for _ in $(seq 1 90); do
  if curl -sf "http://127.0.0.1:$WEB_PORT/api/health" >/dev/null 2>&1; then break; fi
  sleep 1
done
curl -sf "http://127.0.0.1:$WEB_PORT/api/health" >/dev/null 2>&1 || fail "SENTINEL did not start — see $LOGS/api.log and $LOGS/web.log"

URL="http://localhost:$WEB_PORT"
printf '\n\033[1;32mSENTINEL is running at %s\033[0m\n' "$URL"
printf 'Logs: %s   Stop: Ctrl+C (or ./run.sh --stop)\n\n' "$LOGS"
[[ -z "${SENTINEL_NO_BROWSER:-}" ]] && command -v open >/dev/null && open "$URL" || true
wait
