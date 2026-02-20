from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from p2p.config import load_config
from p2p.peer import PeerNode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one P2P peer")
    parser.add_argument("--peer-id", type=int, required=True, help="Peer ID from config")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config.json"),
        help="Path to JSON config",
    )
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=Path("."),
        help="Project base dir for logs/data",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    peer = next((p for p in config.peers if p.id == args.peer_id), None)
    if peer is None:
        raise SystemExit(f"Peer {args.peer_id} not found in {args.config}")

    node = PeerNode(config=config, self_peer=peer, base_dir=args.base_dir)
    asyncio.run(node.run())


if __name__ == "__main__":
    main()
