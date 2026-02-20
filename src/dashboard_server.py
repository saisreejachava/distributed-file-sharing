from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from p2p.config import AppConfig, load_config


PIECE_RE = re.compile(r"downloaded piece (\d+) \(now (\d+)/(\d+)\)")
PREF_RE = re.compile(r"preferred neighbors: \[(.*?)\]")
OPT_RE = re.compile(r"optimistic unchoke: (.*)$")


@dataclass
class PeerStatus:
    peer_id: int
    host: str
    port: int
    has_file_in_config: bool
    pieces_owned: int
    total_pieces: int
    completion_ratio: float
    complete: bool
    preferred_neighbors: list[int]
    optimistic_neighbor: int | None
    last_piece: int | None
    last_activity: str


class DashboardState:
    def __init__(self, base_dir: Path, config_path: Path) -> None:
        self.base_dir = base_dir
        self.config_path = config_path
        self.config: AppConfig = load_config(config_path)

    def reload_config(self) -> None:
        self.config = load_config(self.config_path)

    def _peer_log_path(self, peer_id: int) -> Path:
        return self.base_dir / "logs" / f"peer_{peer_id}.log"

    def _peer_file_path(self, peer_id: int) -> Path:
        return self.base_dir / "data" / f"peer_{peer_id}" / self.config.common.file_name

    def _read_recent_log_lines(self, peer_id: int, limit: int = 80) -> list[str]:
        path = self._peer_log_path(peer_id)
        if not path.exists():
            return []
        lines = path.read_text(errors="replace").splitlines()
        return lines[-limit:]

    def peer_status(self, peer_id: int) -> PeerStatus:
        peer_cfg = next(p for p in self.config.peers if p.id == peer_id)
        total = self.config.piece_count
        lines = self._read_recent_log_lines(peer_id, limit=500)

        pieces_owned = total if peer_cfg.has_file else 0
        last_piece = None
        preferred_neighbors: list[int] = []
        optimistic_neighbor: int | None = None
        last_activity = "No activity yet"

        for line in lines:
            if line:
                last_activity = line

            piece_match = PIECE_RE.search(line)
            if piece_match:
                last_piece = int(piece_match.group(1))
                pieces_owned = max(pieces_owned, int(piece_match.group(2)))

            pref_match = PREF_RE.search(line)
            if pref_match:
                raw = pref_match.group(1).strip()
                if raw:
                    preferred_neighbors = [int(item.strip()) for item in raw.split(",") if item.strip()]
                else:
                    preferred_neighbors = []

            opt_match = OPT_RE.search(line)
            if opt_match:
                raw = opt_match.group(1).strip()
                if raw == "None":
                    optimistic_neighbor = None
                elif raw.isdigit():
                    optimistic_neighbor = int(raw)

        file_path = self._peer_file_path(peer_id)
        if file_path.exists() and file_path.stat().st_size == self.config.common.file_size:
            pieces_owned = total

        completion_ratio = 0 if total == 0 else pieces_owned / total
        return PeerStatus(
            peer_id=peer_cfg.id,
            host=peer_cfg.host,
            port=peer_cfg.port,
            has_file_in_config=peer_cfg.has_file,
            pieces_owned=pieces_owned,
            total_pieces=total,
            completion_ratio=completion_ratio,
            complete=(pieces_owned >= total and total > 0),
            preferred_neighbors=preferred_neighbors,
            optimistic_neighbor=optimistic_neighbor,
            last_piece=last_piece,
            last_activity=last_activity,
        )

    def full_status(self) -> dict:
        peers = [self.peer_status(p.id) for p in self.config.peers]
        complete_count = sum(1 for p in peers if p.complete)
        return {
            "as_of": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "file": {
                "name": self.config.common.file_name,
                "size": self.config.common.file_size,
                "piece_size": self.config.common.piece_size,
                "piece_count": self.config.piece_count,
            },
            "swarm": {
                "peer_count": len(peers),
                "completed_peers": complete_count,
            },
            "peers": [asdict(p) for p in peers],
        }


class DashboardHandler(SimpleHTTPRequestHandler):
    state: DashboardState
    frontend_dir: Path

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(self.frontend_dir), **kwargs)

    def _send_json(self, payload: dict, status: int = 200) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/config":
            self.state.reload_config()
            self._send_json(
                {
                    "common": asdict(self.state.config.common),
                    "peers": [asdict(peer) for peer in self.state.config.peers],
                    "piece_count": self.state.config.piece_count,
                }
            )
            return

        if parsed.path == "/api/status":
            self.state.reload_config()
            self._send_json(self.state.full_status())
            return

        if parsed.path == "/api/logs":
            query = parse_qs(parsed.query)
            try:
                peer_id = int(query.get("peer_id", [""])[0])
            except ValueError:
                self._send_json({"error": "Invalid peer_id"}, status=400)
                return
            lines = self.state._read_recent_log_lines(peer_id, limit=120)
            self._send_json({"peer_id": peer_id, "lines": lines})
            return

        if parsed.path == "/":
            self.path = "/index.html"
        return super().do_GET()


def run_server(host: str, port: int, base_dir: Path, config_path: Path) -> None:
    frontend_dir = base_dir / "frontend"
    if not frontend_dir.exists():
        raise SystemExit(f"frontend directory not found: {frontend_dir}")

    state = DashboardState(base_dir=base_dir, config_path=config_path)

    handler = type("ConfiguredDashboardHandler", (DashboardHandler,), {})
    handler.state = state
    handler.frontend_dir = frontend_dir

    with ThreadingHTTPServer((host, port), handler) as httpd:
        print(f"Dashboard running on http://{host}:{port}")
        httpd.serve_forever()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="P2P dashboard server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--base-dir", type=Path, default=Path("."))
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_server(host=args.host, port=args.port, base_dir=args.base_dir, config_path=args.config)
