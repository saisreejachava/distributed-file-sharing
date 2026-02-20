#!/usr/bin/env bash
set -euo pipefail

BASE_DIR=${1:-.}

PYTHONPATH="$BASE_DIR/src" python3 "$BASE_DIR/src/dashboard_server.py" --base-dir "$BASE_DIR" --config "$BASE_DIR/config.json" --host 127.0.0.1 --port 8080 &
DASH_PID=$!
PYTHONPATH="$BASE_DIR/src" python3 "$BASE_DIR/src/run_peer.py" --peer-id 1001 --config "$BASE_DIR/config.json" --base-dir "$BASE_DIR" &
P1=$!
PYTHONPATH="$BASE_DIR/src" python3 "$BASE_DIR/src/run_peer.py" --peer-id 1002 --config "$BASE_DIR/config.json" --base-dir "$BASE_DIR" &
P2=$!
PYTHONPATH="$BASE_DIR/src" python3 "$BASE_DIR/src/run_peer.py" --peer-id 1003 --config "$BASE_DIR/config.json" --base-dir "$BASE_DIR" &
P3=$!

echo "Dashboard: http://127.0.0.1:8080"
trap 'kill $DASH_PID $P1 $P2 $P3 2>/dev/null || true' EXIT
wait
