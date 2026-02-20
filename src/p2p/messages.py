from __future__ import annotations

import enum
import struct
from dataclasses import dataclass


HANDSHAKE_HEADER = b"P2PFILESHARINGPROJ"
HANDSHAKE_LEN = 32


class MessageType(enum.IntEnum):
    CHOKE = 0
    UNCHOKE = 1
    INTERESTED = 2
    NOT_INTERESTED = 3
    HAVE = 4
    BITFIELD = 5
    REQUEST = 6
    PIECE = 7


@dataclass(frozen=True)
class Message:
    kind: MessageType
    payload: bytes = b""

    def encode(self) -> bytes:
        length = 1 + len(self.payload)
        return struct.pack(">I", length) + bytes([int(self.kind)]) + self.payload

    @staticmethod
    def decode(raw: bytes) -> "Message":
        if not raw:
            raise ValueError("empty message")
        try:
            kind = MessageType(raw[0])
        except ValueError as exc:
            raise ValueError(f"unknown message type: {raw[0]}") from exc
        return Message(kind=kind, payload=raw[1:])


def encode_handshake(peer_id: int) -> bytes:
    return HANDSHAKE_HEADER + (b"\x00" * 10) + struct.pack(">I", peer_id)


def decode_handshake(raw: bytes) -> int:
    if len(raw) != HANDSHAKE_LEN:
        raise ValueError(f"invalid handshake length: {len(raw)}")
    if raw[: len(HANDSHAKE_HEADER)] != HANDSHAKE_HEADER:
        raise ValueError("invalid handshake header")
    return struct.unpack(">I", raw[-4:])[0]
