#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${VOICE_SERVER_DIR:-/workspace/voices/server}"
UVICORN_BIN="${UVICORN_BIN:-$APP_DIR/.venv/bin/uvicorn}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
LOG_DIR="${VOICE_LOG_DIR:-/workspace/voices/logs}"
LOG_FILE="${VOICE_LOG_FILE:-$LOG_DIR/fastapi.log}"
PID_FILE="${VOICE_PID_FILE:-/tmp/voices-fastapi.pid}"

mkdir -p "$LOG_DIR"

if [[ ! -d "$APP_DIR" ]]; then
  echo "Voice server directory not found: $APP_DIR" >&2
  exit 1
fi

if [[ ! -x "$UVICORN_BIN" ]]; then
  echo "uvicorn not found or not executable: $UVICORN_BIN" >&2
  exit 1
fi

cd "$APP_DIR"

if [[ -f "$PID_FILE" ]]; then
  existing_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ "$existing_pid" =~ ^[0-9]+$ ]] && kill -0 "$existing_pid" 2>/dev/null; then
    existing_cmd="$(ps -p "$existing_pid" -o args= 2>/dev/null || true)"
    if [[ "$existing_cmd" == *"uvicorn app.main:app"* ]]; then
      echo "Voice server already running with PID $existing_pid"
      exit 0
    fi
  fi
  rm -f "$PID_FILE"
fi

running_pid="$(pgrep -f "uvicorn app.main:app.*--port $PORT" | head -n 1 || true)"
if [[ -n "$running_pid" ]]; then
  echo "$running_pid" > "$PID_FILE"
  echo "Voice server already running with PID $running_pid"
  exit 0
fi

echo "Starting voice server from $APP_DIR on $HOST:$PORT"
nohup "$UVICORN_BIN" app.main:app --host "$HOST" --port "$PORT" >> "$LOG_FILE" 2>&1 &
server_pid="$!"
echo "$server_pid" > "$PID_FILE"

sleep 2
if ! kill -0 "$server_pid" 2>/dev/null; then
  echo "Voice server failed to start. Last log lines:" >&2
  tail -n 80 "$LOG_FILE" >&2 || true
  exit 1
fi

echo "Voice server started with PID $server_pid; logs: $LOG_FILE"
