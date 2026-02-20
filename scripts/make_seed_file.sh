#!/usr/bin/env bash
set -euo pipefail

BASE_DIR=${1:-.}
TARGET="$BASE_DIR/data/peer_1001/shared.bin"
mkdir -p "$(dirname "$TARGET")"

# 1 MiB deterministic payload for demo.
TARGET_PATH="$TARGET" python3 - <<'PY'
import os
from pathlib import Path
p = Path(os.environ["TARGET_PATH"])
p.write_bytes((b"P2P-DEMO-" * (1048576 // 9 + 1))[:1048576])
print(f"wrote {p} ({p.stat().st_size} bytes)")
PY
