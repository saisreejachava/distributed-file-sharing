from __future__ import annotations

import asyncio
import logging
import random
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from p2p.bitfield import bitfield_to_bools, bools_to_bitfield
from p2p.config import AppConfig, PeerConfig
from p2p.messages import (
    HANDSHAKE_LEN,
    Message,
    MessageType,
    decode_handshake,
    encode_handshake,
)


@dataclass
class RemoteState:
    peer_id: int
    bitfield: list[bool]
    interested_in_us: bool = False
    we_are_interested: bool = False
    choked_by_us: bool = True
    choked_us: bool = True
    requested_piece: Optional[int] = None


class PeerNode:
    def __init__(self, config: AppConfig, self_peer: PeerConfig, base_dir: Path) -> None:
        self.config = config
        self.self_peer = self_peer
        self.base_dir = base_dir
        self.data_dir = base_dir / "data" / f"peer_{self_peer.id}"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.file_path = self.data_dir / config.common.file_name
        self.piece_count = config.piece_count
        self.piece_size = config.common.piece_size

        self.local_pieces: list[bytes | None] = [None] * self.piece_count
        if self_peer.has_file:
            self._load_full_file()

        self.logger = self._setup_logger()
        self.server: asyncio.AbstractServer | None = None
        self.sessions: dict[int, "PeerSession"] = {}
        self.preferred_neighbors: set[int] = set()
        self.optimistic_neighbor: Optional[int] = None

    def _setup_logger(self) -> logging.Logger:
        logger = logging.getLogger(f"peer-{self.self_peer.id}")
        logger.setLevel(logging.INFO)
        logger.handlers.clear()

        log_dir = self.base_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_dir / f"peer_{self.self_peer.id}.log")
        fh.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        logger.addHandler(fh)

        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        logger.addHandler(sh)
        return logger

    def _load_full_file(self) -> None:
        raw = self.file_path.read_bytes()
        if len(raw) != self.config.common.file_size:
            raise ValueError(
                f"seed file size mismatch: expected {self.config.common.file_size}, got {len(raw)}"
            )
        for i in range(self.piece_count):
            start = i * self.piece_size
            end = min((i + 1) * self.piece_size, len(raw))
            self.local_pieces[i] = raw[start:end]

    def _assemble_file_if_complete(self) -> None:
        if all(piece is not None for piece in self.local_pieces):
            self.file_path.write_bytes(b"".join(piece for piece in self.local_pieces if piece is not None))

    def local_bitfield(self) -> list[bool]:
        return [piece is not None for piece in self.local_pieces]

    async def run(self) -> None:
        self.server = await asyncio.start_server(
            self._handle_incoming,
            host=self.self_peer.host,
            port=self.self_peer.port,
        )
        self.logger.info(
            "Peer %s listening on %s:%s",
            self.self_peer.id,
            self.self_peer.host,
            self.self_peer.port,
        )

        for peer in self.config.peers:
            if peer.id < self.self_peer.id:
                asyncio.create_task(self._connect_to_peer(peer))

        asyncio.create_task(self._preferred_neighbor_loop())
        asyncio.create_task(self._optimistic_unchoke_loop())

        async with self.server:
            await self.server.serve_forever()

    async def _connect_to_peer(self, peer: PeerConfig) -> None:
        while peer.id not in self.sessions:
            try:
                reader, writer = await asyncio.open_connection(peer.host, peer.port)
                await self._perform_handshake(reader, writer, expect_peer_id=peer.id)
                session = PeerSession(self, reader, writer, peer.id, initiated=True)
                self.sessions[peer.id] = session
                asyncio.create_task(session.run())
                self.logger.info("Peer %s connected to peer %s", self.self_peer.id, peer.id)
                return
            except Exception as exc:
                self.logger.info("Retry connect %s failed: %s", peer.id, exc)
                await asyncio.sleep(1)

    async def _handle_incoming(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            peer_id = await self._perform_handshake(reader, writer, expect_peer_id=None)
            if peer_id in self.sessions:
                writer.close()
                await writer.wait_closed()
                return
            session = PeerSession(self, reader, writer, peer_id, initiated=False)
            self.sessions[peer_id] = session
            self.logger.info("Peer %s accepted connection from peer %s", self.self_peer.id, peer_id)
            await session.run()
        except Exception as exc:
            self.logger.info("Incoming session failed: %s", exc)
            writer.close()
            await writer.wait_closed()

    async def _perform_handshake(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        expect_peer_id: Optional[int],
    ) -> int:
        writer.write(encode_handshake(self.self_peer.id))
        await writer.drain()

        raw = await reader.readexactly(HANDSHAKE_LEN)
        remote_id = decode_handshake(raw)
        if expect_peer_id is not None and remote_id != expect_peer_id:
            raise ValueError(f"unexpected peer id: {remote_id}, expected {expect_peer_id}")
        return remote_id

    def missing_from_remote(self, remote_bitfield: list[bool]) -> list[int]:
        local = self.local_bitfield()
        return [i for i, (r, l) in enumerate(zip(remote_bitfield, local)) if r and not l]

    def receive_piece(self, index: int, data: bytes) -> bool:
        if self.local_pieces[index] is not None:
            return False
        self.local_pieces[index] = data
        self.logger.info(
            "Peer %s downloaded piece %s (now %s/%s)",
            self.self_peer.id,
            index,
            sum(1 for p in self.local_pieces if p is not None),
            self.piece_count,
        )
        self._assemble_file_if_complete()
        return True

    async def broadcast_have(self, piece_index: int) -> None:
        payload = struct.pack(">I", piece_index)
        for session in list(self.sessions.values()):
            await session.send(Message(MessageType.HAVE, payload))

    async def _preferred_neighbor_loop(self) -> None:
        while True:
            interested = [
                s
                for s in self.sessions.values()
                if s.remote_state and s.remote_state.interested_in_us
            ]
            random.shuffle(interested)
            chosen = {
                s.peer_id
                for s in interested[: self.config.common.num_preferred_neighbors]
            }
            self.preferred_neighbors = chosen
            self.logger.info("Peer %s preferred neighbors: %s", self.self_peer.id, sorted(chosen))
            await self._apply_choke_policy()
            await asyncio.sleep(self.config.common.unchoking_interval)

    async def _optimistic_unchoke_loop(self) -> None:
        while True:
            candidates = [
                s.peer_id
                for s in self.sessions.values()
                if s.remote_state and s.remote_state.interested_in_us
            ]
            self.optimistic_neighbor = random.choice(candidates) if candidates else None
            self.logger.info(
                "Peer %s optimistic unchoke: %s", self.self_peer.id, self.optimistic_neighbor
            )
            await self._apply_choke_policy()
            await asyncio.sleep(self.config.common.optimistic_unchoking_interval)

    async def _apply_choke_policy(self) -> None:
        allow = set(self.preferred_neighbors)
        if self.optimistic_neighbor is not None:
            allow.add(self.optimistic_neighbor)

        for session in self.sessions.values():
            if session.remote_state is None:
                continue
            should_choke = session.peer_id not in allow
            if session.remote_state.choked_by_us != should_choke:
                session.remote_state.choked_by_us = should_choke
                kind = MessageType.CHOKE if should_choke else MessageType.UNCHOKE
                await session.send(Message(kind))


class PeerSession:
    def __init__(
        self,
        node: PeerNode,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        peer_id: int,
        initiated: bool,
    ) -> None:
        self.node = node
        self.reader = reader
        self.writer = writer
        self.peer_id = peer_id
        self.initiated = initiated
        self.remote_state: RemoteState | None = None

    async def run(self) -> None:
        self.remote_state = RemoteState(peer_id=self.peer_id, bitfield=[False] * self.node.piece_count)

        await self.send(Message(MessageType.BITFIELD, bools_to_bitfield(self.node.local_bitfield())))

        try:
            while True:
                msg = await self._recv_message()
                await self._on_message(msg)
        except asyncio.IncompleteReadError:
            pass
        except Exception as exc:
            self.node.logger.info("Session %s error: %s", self.peer_id, exc)
        finally:
            self.writer.close()
            await self.writer.wait_closed()
            self.node.sessions.pop(self.peer_id, None)

    async def send(self, msg: Message) -> None:
        self.writer.write(msg.encode())
        await self.writer.drain()

    async def _recv_message(self) -> Message:
        length = struct.unpack(">I", await self.reader.readexactly(4))[0]
        raw = await self.reader.readexactly(length)
        return Message.decode(raw)

    async def _on_message(self, msg: Message) -> None:
        assert self.remote_state is not None

        if msg.kind == MessageType.BITFIELD:
            self.remote_state.bitfield = bitfield_to_bools(msg.payload, self.node.piece_count)
            await self._update_interest()
            await self._request_next_piece_if_possible()
            return

        if msg.kind == MessageType.HAVE:
            idx = struct.unpack(">I", msg.payload)[0]
            self.remote_state.bitfield[idx] = True
            await self._update_interest()
            await self._request_next_piece_if_possible()
            return

        if msg.kind == MessageType.INTERESTED:
            self.remote_state.interested_in_us = True
            await self.node._apply_choke_policy()
            return

        if msg.kind == MessageType.NOT_INTERESTED:
            self.remote_state.interested_in_us = False
            await self.node._apply_choke_policy()
            return

        if msg.kind == MessageType.CHOKE:
            self.remote_state.choked_us = True
            return

        if msg.kind == MessageType.UNCHOKE:
            self.remote_state.choked_us = False
            await self._request_next_piece_if_possible()
            return

        if msg.kind == MessageType.REQUEST:
            index = struct.unpack(">I", msg.payload)[0]
            piece = self.node.local_pieces[index]
            if piece is None:
                return
            payload = struct.pack(">I", index) + piece
            await self.send(Message(MessageType.PIECE, payload))
            return

        if msg.kind == MessageType.PIECE:
            index = struct.unpack(">I", msg.payload[:4])[0]
            data = msg.payload[4:]
            self.remote_state.requested_piece = None
            if self.node.receive_piece(index, data):
                await self.node.broadcast_have(index)
            await self._update_interest()
            await self._request_next_piece_if_possible()
            return

    async def _update_interest(self) -> None:
        assert self.remote_state is not None
        needed = self.node.missing_from_remote(self.remote_state.bitfield)
        interested = bool(needed)
        if interested and not self.remote_state.we_are_interested:
            self.remote_state.we_are_interested = True
            await self.send(Message(MessageType.INTERESTED))
        elif not interested and self.remote_state.we_are_interested:
            self.remote_state.we_are_interested = False
            await self.send(Message(MessageType.NOT_INTERESTED))

    async def _request_next_piece_if_possible(self) -> None:
        assert self.remote_state is not None
        if self.remote_state.choked_us:
            return
        if self.remote_state.requested_piece is not None:
            return

        candidates = self.node.missing_from_remote(self.remote_state.bitfield)
        if not candidates:
            return

        index = random.choice(candidates)
        self.remote_state.requested_piece = index
        await self.send(Message(MessageType.REQUEST, struct.pack(">I", index)))
