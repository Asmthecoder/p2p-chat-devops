"""
peer.py — Core P2P Networking Engine
=====================================
Rubric: Distributed System Architecture & Design (CO1, CO6)
         Process, Communication & Coordination (CO2)
         Consistency, Replication & Fault Tolerance (CO3, CO4)

Fault Tolerance
---------------
- Heartbeat sent every HEARTBEAT_INTERVAL seconds to each connected peer
- 3 consecutive heartbeat failures → peer marked offline, connection closed
- Exponential backoff reconnection: 1s → 2s → 4s → … → MAX_BACKOFF
- All state changes are async-safe (asyncio.Lock, asyncio.Queue)
- System messages are debounced — same peer can't spam join/leave events
"""

import asyncio
import json
import logging
import socket
import struct
import time
from datetime import datetime, timezone
from typing import Callable, Dict, Optional, Set

from encryption import EncryptionService
from message_store import MessageStore

logger = logging.getLogger(__name__)

# ── Network constants ──────────────────────────────────────────────────────────
DISCOVERY_PORT      = 9999   # UDP broadcast port
DISCOVERY_INTERVAL  = 30     # seconds between UDP hello broadcasts
HEARTBEAT_INTERVAL  = 15     # seconds between TCP heartbeats (increased)
HEARTBEAT_TIMEOUT   = 60     # seconds before considering a peer dead (increased)
MAX_BACKOFF         = 60     # max seconds for reconnection backoff
RECV_BUFFER         = 4096
MSG_LENGTH_PREFIX   = 4

# Debounce: don't emit a system event for the same peer within this window
SYSTEM_MSG_DEBOUNCE = 10     # seconds


async def _send_message(writer: asyncio.StreamWriter, data: dict):
    raw = json.dumps(data).encode("utf-8")
    header = struct.pack(">I", len(raw))
    writer.write(header + raw)
    await writer.drain()


async def _recv_message(reader: asyncio.StreamReader) -> Optional[dict]:
    try:
        header = await reader.readexactly(MSG_LENGTH_PREFIX)
        length = struct.unpack(">I", header)[0]
        if length > 10_000_000:
            raise ValueError(f"Message too large: {length} bytes")
        raw = await reader.readexactly(length)
        return json.loads(raw.decode("utf-8"))
    except (asyncio.IncompleteReadError, ConnectionResetError, json.JSONDecodeError):
        return None


def _peer_id(host: str, port: int) -> str:
    return f"{host}:{port}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ═══════════════════════════════════════════════════════════════════════════════
# Discovery Service
# ═══════════════════════════════════════════════════════════════════════════════

class DiscoveryService:
    """
    UDP broadcast-based LAN peer discovery.
    Beacon format:  HELLO:<username>:<tcp_port>
    """
    BEACON_PREFIX = "HELLO:"

    def __init__(self, username, tcp_port, on_peer_discovered):
        self.username = username
        self.tcp_port = tcp_port
        self._on_discovered = on_peer_discovered
        self._running = False

    async def start(self):
        self._running = True
        await asyncio.gather(self._broadcast_loop(), self._listen_loop())

    def stop(self):
        self._running = False

    async def _broadcast_loop(self):
        while self._running:
            try:
                self._send_beacon()
            except Exception as exc:
                logger.debug("Broadcast error: %s", exc)
            await asyncio.sleep(DISCOVERY_INTERVAL)

    def _send_beacon(self):
        payload = f"{self.BEACON_PREFIX}{self.username}:{self.tcp_port}".encode()
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.sendto(payload, ("<broadcast>", DISCOVERY_PORT))

    async def _listen_loop(self):
        loop = asyncio.get_event_loop()
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            try:
                sock.bind(("", DISCOVERY_PORT))
            except OSError as e:
                logger.warning("Could not bind UDP discovery port %d: %s", DISCOVERY_PORT, e)
                return
            sock.setblocking(False)
            while self._running:
                try:
                    data, addr = await loop.sock_recvfrom(sock, 1024)
                    await self._handle_beacon(data.decode("utf-8", errors="ignore"), addr[0])
                except Exception:
                    await asyncio.sleep(0.1)

    async def _handle_beacon(self, payload: str, sender_host: str):
        if not payload.startswith(self.BEACON_PREFIX):
            return
        parts = payload[len(self.BEACON_PREFIX):].rsplit(":", 1)
        if len(parts) != 2:
            return
        username, port_str = parts
        try:
            port = int(port_str)
        except ValueError:
            return
        if port == self.tcp_port and sender_host in ("127.0.0.1", self._local_ip()):
            return
        self._on_discovered(sender_host, port, username)

    @staticmethod
    def _local_ip() -> str:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"


# ═══════════════════════════════════════════════════════════════════════════════
# Peer Manager
# ═══════════════════════════════════════════════════════════════════════════════

class PeerManager:
    """
    Central coordinator for all P2P TCP connections.

    - Accepts incoming TCP connections (server)
    - Connects to peers (client) with exponential backoff
    - Routes inbound messages to the UI via asyncio.Queue
    - Heartbeat liveness detection
    - Deduplicates system (join/leave) messages via debounce
    """

    def __init__(self, username, host, port, store: MessageStore, crypto: EncryptionService):
        self.username = username
        self.host     = host
        self.port     = port
        self.store    = store
        self.crypto   = crypto
        self.peer_id  = _peer_id("0.0.0.0", port)  # Use port-only ID for self

        # peer_id → asyncio.StreamWriter
        self._writers: Dict[str, asyncio.StreamWriter] = {}
        # peer_id → {username, host, port, last_heartbeat, missed_beats, online}
        self._peers:   Dict[str, dict] = {}
        self._lock = asyncio.Lock()

        # Debounce: peer_id → (last_event_time, last_event_type)
        self._system_debounce: Dict[str, tuple] = {}

        # UI reads from this queue
        self.inbound_queue: asyncio.Queue = asyncio.Queue()

        self._server = None
        self._running = False
        self._tasks: Set[asyncio.Task] = set()
        self.discovery: Optional[DiscoveryService] = None

    # ── Public API ─────────────────────────────────────────────────────────────

    async def start(self):
        self._running = True
        self._server = await asyncio.start_server(
            self._handle_incoming, self.host, self.port
        )
        logger.info("TCP server listening on %s:%d", self.host, self.port)

        self.discovery = DiscoveryService(
            username=self.username,
            tcp_port=self.port,
            on_peer_discovered=self._schedule_connect,
        )
        self._spawn(self._server.serve_forever())
        self._spawn(self.discovery.start())
        self._spawn(self._heartbeat_loop())

    async def stop(self):
        self._running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        for task in list(self._tasks):
            task.cancel()
        if self.discovery:
            self.discovery.stop()
        await self.store.close()

    async def send_message(self, content: str, target_peer_id: Optional[str] = None):
        encrypted    = self.crypto.encrypt(content)
        is_broadcast = target_peer_id is None
        msg = {
            "type":         "MESSAGE",
            "sender":       self.username,
            "peer_id":      self.peer_id,
            "content":      encrypted,
            "timestamp":    _now_iso(),
            "is_broadcast": int(is_broadcast),
        }
        
        # Use lock to safely access _writers dictionary
        async with self._lock:
            targets = list(self._writers.keys()) if is_broadcast else [target_peer_id]
            # Make a copy of writers for this iteration to prevent race conditions
            writers_snapshot = {pid: self._writers.get(pid) for pid in targets if pid in self._writers}
        
        sent_count = 0
        for pid, writer in writers_snapshot.items():
            if writer:
                try:
                    await _send_message(writer, msg)
                    sent_count += 1
                except Exception as exc:
                    logger.warning("Failed to send to %s: %s", pid, exc)
                    await self._on_peer_disconnected(pid)

        store_pid = "broadcast" if is_broadcast else target_peer_id
        await self.store.save_message(store_pid, "out", content, is_broadcast)

    async def send_typing(self, target_peer_id: Optional[str] = None):
        """Send a transient TYPING event to peer(s)."""
        msg = {
            "type":      "TYPING",
            "sender":    self.username,
            "peer_id":   self.peer_id,
            "content":   "",
            "timestamp": _now_iso(),
        }
        async with self._lock:
            targets = list(self._writers.keys()) if target_peer_id is None else [target_peer_id]
            writers_snapshot = {pid: self._writers.get(pid) for pid in targets if pid in self._writers}
            
        for pid, writer in writers_snapshot.items():
            if writer:
                try:
                    await _send_message(writer, msg)
                except Exception:
                    pass

    async def connect_to_peer(self, host: str, port: int, username: str = "Unknown"):
        pid = _peer_id(host, port)
        if pid in self._writers:
            logger.debug("Already connected to %s", pid)
            return
        await self._connect_with_backoff(host, port, username)

    async def get_connected_peers(self) -> list:
        return [
            {**info, "peer_id": pid}
            for pid, info in self._peers.items()
            if pid in self._writers
        ]

    # ── Internal ───────────────────────────────────────────────────────────────

    def _spawn(self, coro) -> asyncio.Task:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def _schedule_connect(self, host: str, port: int, username: str):
        pid = _peer_id(host, port)
        if pid not in self._writers:
            self._spawn(self._connect_with_backoff(host, port, username))

    async def _connect_with_backoff(self, host: str, port: int, username: str):
        pid   = _peer_id(host, port)
        delay = 2
        while self._running:
            if pid in self._writers:
                return  # Already connected by the time we retried
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port), timeout=5
                )
                await self._on_peer_connected(pid, host, port, username, reader, writer)
                return
            except (ConnectionRefusedError, asyncio.TimeoutError, OSError):
                await asyncio.sleep(min(delay, MAX_BACKOFF))
                delay = min(delay * 2, MAX_BACKOFF)

    async def _handle_incoming(self, reader, writer):
        addr = writer.get_extra_info("peername")
        msg  = await _recv_message(reader)
        if not msg:
            writer.close()
            return
        host     = addr[0]
        port     = msg.get("meta_port", addr[1])
        username = msg.get("sender", "Unknown")
        pid      = _peer_id(host, port)
        await self._on_peer_connected(pid, host, port, username, reader, writer)

    async def _on_peer_connected(self, pid, host, port, username, reader, writer):
        async with self._lock:
            self._writers[pid] = writer
            self._peers[pid]   = {
                "username":       username,
                "host":           host,
                "port":           port,
                "last_heartbeat": time.monotonic(),
                "missed_beats":   0,
                "online":         1,
            }
        await self.store.upsert_peer(pid, username, host, port)
        logger.info("Connected to peer %s (%s)", username, pid)

        # Send handshake
        handshake = {
            "type":      "SYSTEM",
            "sender":    self.username,
            "peer_id":   self.peer_id,
            "meta_port": self.port,
            "content":   "JOINED",
            "timestamp": _now_iso(),
        }
        try:
            await _send_message(writer, handshake)
        except Exception:
            pass

        # Emit system message (with debounce)
        self._emit_system(pid, username, "joined")
        self._spawn(self._read_loop(pid, reader))

    async def _read_loop(self, pid: str, reader):
        while self._running and pid in self._writers:
            msg = await _recv_message(reader)
            if msg is None:
                await self._on_peer_disconnected(pid)
                return
            await self._dispatch(pid, msg)

    async def _dispatch(self, pid: str, msg: dict):
        try:
            msg_type = msg.get("type", "")

            if msg_type == "HEARTBEAT":
                async with self._lock:
                    if pid in self._peers:
                        self._peers[pid]["last_heartbeat"] = time.monotonic()
                        self._peers[pid]["missed_beats"]   = 0
                        self._peers[pid]["online"]         = 1
                return

            if msg_type == "TYPING":
                await self.inbound_queue.put(msg)
                return

            if msg_type == "MESSAGE":
                try:
                    decrypted      = self.crypto.decrypt(msg.get("content", ""))
                    msg["content"] = decrypted
                except Exception as dec_exc:
                    logger.error("Failed to decrypt message from %s: %s", pid, dec_exc)
                    msg["content"] = "[Message decryption failed]"
                
                # Use the sender's actual username from peers table if available
                if pid in self._peers:
                    msg["sender"] = self._peers[pid]["username"]
                await self.store.save_message(pid, "in", msg.get("content", ""), msg.get("is_broadcast", False))
                await self.inbound_queue.put(msg)
                return

            if msg_type == "SYSTEM":
                content = msg.get("content", "")
                if content == "JOINED":
                    async with self._lock:
                        if pid in self._peers:
                            self._peers[pid]["username"]  = msg.get("sender", "Unknown")
                            self._peers[pid]["meta_port"] = msg.get("meta_port", self._peers[pid]["port"])
                else:
                    await self.inbound_queue.put(msg)
        except Exception as exc:
            logger.error("Error dispatching message from %s: %s", pid, exc, exc_info=True)

    async def _on_peer_disconnected(self, pid: str):
        async with self._lock:
            writer = self._writers.pop(pid, None)
            info   = self._peers.get(pid, {})
            if pid in self._peers:
                self._peers[pid]["online"] = 0
        if writer:
            try:
                writer.close()
            except Exception:
                pass
        username = info.get("username", pid)
        host     = info.get("host")
        port     = info.get("port")
        logger.warning("Peer %s (%s) disconnected", username, pid)
        await self.store.mark_peer_offline(pid)
        # Emit "left" with debounce
        self._emit_system(pid, username, "left")
        # Schedule reconnection
        if host and port and self._running:
            self._spawn(self._connect_with_backoff(host, port, username))

    def _emit_system(self, pid: str, username: str, event: str):
        """
        Emit a system message only if the same event hasn't been emitted
        for this peer within SYSTEM_MSG_DEBOUNCE seconds.
        """
        now = time.monotonic()
        last_t, last_evt = self._system_debounce.get(pid, (0, ""))
        if last_evt == event and (now - last_t) < SYSTEM_MSG_DEBOUNCE:
            return  # duplicate — suppress
        self._system_debounce[pid] = (now, event)
        content = f"{username} joined the network" if event == "joined" else f"{username} left the network"
        asyncio.ensure_future(self.inbound_queue.put({
            "type":      "SYSTEM",
            "sender":    username,
            "peer_id":   pid,
            "content":   content,
            "timestamp": _now_iso(),
            "event":     event,
        }))

    async def _heartbeat_loop(self):
        """Send heartbeat to all peers. Mark dead peers offline after 3 missed."""
        while self._running:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            hb_msg = {
                "type":      "HEARTBEAT",
                "sender":    self.username,
                "peer_id":   self.peer_id,
                "content":   "",
                "timestamp": _now_iso(),
            }
            async with self._lock:
                pids = list(self._writers.keys())

            dead = []
            for pid in pids:
                writer = self._writers.get(pid)
                if not writer:
                    continue
                try:
                    await _send_message(writer, hb_msg)
                except Exception:
                    async with self._lock:
                        if pid in self._peers:
                            self._peers[pid]["missed_beats"] = \
                                self._peers[pid].get("missed_beats", 0) + 1
                            if self._peers[pid]["missed_beats"] >= 3:
                                dead.append(pid)

            for pid in dead:
                logger.warning("Heartbeat timeout — removing peer %s", pid)
                await self._on_peer_disconnected(pid)
