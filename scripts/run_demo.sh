#!/usr/bin/env bash
set -euo pipefail

BASE_DIR=${1:-.}

PYTHONPATH="$BASE_DIR/src" python3 "$BASE_DIR/src/run_peer.py" --peer-id 1001 --config "$BASE_DIR/config.json" --base-dir "$BASE_DIR" &
P1=$!
PYTHONPATH="$BASE_DIR/src" python3 "$BASE_DIR/src/run_peer.py" --peer-id 1002 --config "$BASE_DIR/config.json" --base-dir "$BASE_DIR" &
P2=$!
PYTHONPATH="$BASE_DIR/src" python3 "$BASE_DIR/src/run_peer.py" --peer-id 1003 --config "$BASE_DIR/config.json" --base-dir "$BASE_DIR" &
P3=$!

trap 'kill $P1 $P2 $P3 2>/dev/null || true' EXIT
wait
