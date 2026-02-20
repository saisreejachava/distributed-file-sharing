from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PeerConfig:
    id: int
    host: str
    port: int
    has_file: bool


@dataclass(frozen=True)
class CommonConfig:
    file_name: str
    file_size: int
    piece_size: int
    num_preferred_neighbors: int
    unchoking_interval: int
    optimistic_unchoking_interval: int


@dataclass(frozen=True)
class AppConfig:
    common: CommonConfig
    peers: list[PeerConfig]

    @property
    def piece_count(self) -> int:
        full, rem = divmod(self.common.file_size, self.common.piece_size)
        return full + (1 if rem else 0)


def load_config(path: str | Path) -> AppConfig:
    data = json.loads(Path(path).read_text())
    common = CommonConfig(
        file_name=data["file_name"],
        file_size=int(data["file_size"]),
        piece_size=int(data["piece_size"]),
        num_preferred_neighbors=int(data.get("num_preferred_neighbors", 2)),
        unchoking_interval=int(data.get("unchoking_interval", 10)),
        optimistic_unchoking_interval=int(data.get("optimistic_unchoking_interval", 30)),
    )
    peers = [
        PeerConfig(
            id=int(peer["id"]),
            host=peer["host"],
            port=int(peer["port"]),
            has_file=bool(peer.get("has_file", False)),
        )
        for peer in data["peers"]
    ]
    return AppConfig(common=common, peers=peers)
