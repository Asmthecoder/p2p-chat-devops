"""
peer.py — Core P2P Networking Engine
=====================================
Rubric: Distributed System Architecture & Design (CO1, CO6)
         Process, Communication & Coordination (CO2)
         Consistency, Replication & Fault Tolerance (CO3, CO4)

Bug fixes in this version
--------------------------
1. TOCTOU race in heartbeat: writers are now snapshot inside the lock so
   concurrent disconnects can't cause a stale-writer access.
2. Stale-peer default: last_heartbeat defaults to now-TIMEOUT-1 so a brand-
   new peer with no recorded heartbeat is correctly eligible for timeout.
3. Write-before-send: store.save_message() now called BEFORE the network
   loop (write-ahead pattern) so no messages are lost on crash.
4. send_message() returns the message_id for UI delivery tracking.
5. Reconnect loop capped at MAX_RECONNECT_ATTEMPTS to avoid infinite retry.
6. Per-peer rate limiting (RATE_LIMIT_COUNT msgs per RATE_LIMIT_WINDOW s).
7. ACK message type: recipient sends delivery ACK; sender updates UI.
8. TYPING no longer queued — stored directly in typing_peers dict.
9. USERNAME_UPDATE system message propagates live name changes to peers.
10. UDP beacons authenticated with HMAC truncated tag when shared key set.
"""

import asyncio
import hashlib
import hmac as _hmac_mod
import json
import logging
import re
import socket
import struct
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional, Set

from encryption import EncryptionService
from message_store import MessageStore

logger = logging.getLogger(__name__)

# ── Network constants ──────────────────────────────────────────────────────────
DISCOVERY_PORT         = 9999
DISCOVERY_INTERVAL     = 30      # seconds between UDP hello broadcasts
HEARTBEAT_INTERVAL     = 15      # seconds between TCP heartbeats
HEARTBEAT_TIMEOUT      = 60      # seconds before peer is considered dead
MAX_BACKOFF            = 60      # max seconds for reconnection backoff
MAX_RECONNECT_ATTEMPTS = 20      # give up reconnecting after this many attempts
RECV_BUFFER            = 4096
MSG_LENGTH_PREFIX      = 4

# Debounce: suppress duplicate join/leave events within this window
SYSTEM_MSG_DEBOUNCE    = 10      # seconds

# Rate limiting: drop messages from a peer exceeding this rate
RATE_LIMIT_COUNT       = 20      # messages
RATE_LIMIT_WINDOW      = 10.0    # seconds

MAX_USERNAME_LENGTH    = 32
SAFE_USERNAME_REGEX    = re.compile(r"[^A-Za-z0-9_. -]")


# ── Wire helpers ───────────────────────────────────────────────────────────────

async def _send_message(writer: asyncio.StreamWriter, data: dict):
    raw    = json.dumps(data).encode("utf-8")
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


def _sanitize_username(name: str) -> str:
    cleaned = SAFE_USERNAME_REGEX.sub("", (name or "").strip())
    if not cleaned:
        return "Unknown"
    return cleaned[:MAX_USERNAME_LENGTH]


# ── Auth-tag helpers ───────────────────────────────────────────────────────────

def _canonical_auth_payload(msg: dict) -> str:
    payload = {
        "type":        msg.get("type", ""),
        "sender":      msg.get("sender", ""),
        "peer_id":     msg.get("peer_id", ""),
        "content":     msg.get("content", ""),
        "timestamp":   msg.get("timestamp", ""),
        "meta_port":   msg.get("meta_port", ""),
        "message_id":  msg.get("message_id", ""),
        "is_broadcast": int(bool(msg.get("is_broadcast", 0))),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _attach_auth_tag(crypto: EncryptionService, msg: dict) -> dict:
    tagged    = dict(msg)
    canonical = _canonical_auth_payload(tagged)
    tagged["auth_tag"] = crypto.sign_payload(canonical)
    return tagged


def _verify_auth_tag(crypto: EncryptionService, msg: dict) -> bool:
    canonical = _canonical_auth_payload(msg)
    signature = msg.get("auth_tag", "")
    return crypto.verify_payload(canonical, signature)


# ═══════════════════════════════════════════════════════════════════════════════
# Discovery Service
# ═══════════════════════════════════════════════════════════════════════════════

class DiscoveryService:
    """
    UDP broadcast-based LAN peer discovery.

    Beacon format (unauthenticated): HELLO:<username>:<tcp_port>
    Beacon format (authenticated):   HELLO:<username>:<tcp_port>:<hmac16>

    When an integrity_key is provided (derived from the shared encryption key),
    each beacon carries a 16-character hex HMAC tag. Nodes with the same key
    will reject spoofed beacons from intruders on the local network.
    Nodes without a matching key fall back to accepting any beacon for
    backward compatibility.
    """

    BEACON_PREFIX = "HELLO:"

    def __init__(
        self,
        username: str,
        tcp_port: int,
        on_peer_discovered,
        integrity_key: Optional[bytes] = None,
    ):
        self.username        = username
        self.tcp_port        = tcp_port
        self._on_discovered  = on_peer_discovered
        self._integrity_key  = integrity_key
        self._running        = False

    async def start(self):
        self._running = True
        await asyncio.gather(self._broadcast_loop(), self._listen_loop())

    def stop(self):
        self._running = False

    # ── Beacon construction ───────────────────────────────────────────

    def _make_beacon_payload(self) -> str:
        base = f"{self.BEACON_PREFIX}{self.username}:{self.tcp_port}"
        if self._integrity_key:
            mac = _hmac_mod.new(
                self._integrity_key, base.encode(), hashlib.sha256
            ).hexdigest()[:16]
            return f"{base}:{mac}"
        return base

    def _verify_beacon_payload(self, payload: str) -> bool:
        """Verify the optional HMAC tag on a received beacon."""
        if not self._integrity_key:
            return True   # No key configured — accept all beacons
        # Split off the last colon-delimited field
        parts = payload.rsplit(":", 1)
        if len(parts) == 2 and len(parts[1]) == 16:
            base         = parts[0]
            received_mac = parts[1]
            expected_mac = _hmac_mod.new(
                self._integrity_key, base.encode(), hashlib.sha256
            ).hexdigest()[:16]
            return _hmac_mod.compare_digest(expected_mac, received_mac)
        # Old-format or no-key beacon — allow for backwards compatibility
        logger.debug("Unauthenticated beacon received; accepting (backward compat)")
        return True

    # ── Broadcast loop ────────────────────────────────────────────────

    async def _broadcast_loop(self):
        while self._running:
            try:
                self._send_beacon()
            except Exception as exc:
                logger.debug("Broadcast error: %s", exc)
            await asyncio.sleep(DISCOVERY_INTERVAL)

    def _send_beacon(self):
        payload = self._make_beacon_payload().encode()
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.sendto(payload, ("<broadcast>", DISCOVERY_PORT))

    # ── Listen loop ───────────────────────────────────────────────────

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
                    await self._handle_beacon(
                        data.decode("utf-8", errors="ignore"), addr[0]
                    )
                except Exception:
                    await asyncio.sleep(0.1)

    async def _handle_beacon(self, payload: str, sender_host: str):
        if not payload.startswith(self.BEACON_PREFIX):
            return

        # Authenticate before parsing username/port
        if not self._verify_beacon_payload(payload):
            logger.warning("Rejected beacon with invalid MAC from %s", sender_host)
            return

        # Parse inner section (strip HELLO: prefix first)
        inner = payload[len(self.BEACON_PREFIX):]
        try:
            # Could be "username:port" or "username:port:mac16"
            parts = inner.rsplit(":", 2)
            if len(parts) == 3 and len(parts[2]) == 16:
                # Authenticated format: username:port:mac
                username = parts[0]
                port     = int(parts[1])
            else:
                # Unauthenticated format: username:port
                left, port_str = inner.rsplit(":", 1)
                username = left
                port     = int(port_str)
        except (ValueError, IndexError):
            return

        username = _sanitize_username(username)

        # Ignore our own beacon
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

    - Accepts incoming TCP connections (server side)
    - Connects to peers (client side) with exponential backoff
    - Routes inbound messages to the UI via asyncio.Queue
    - Heartbeat liveness detection with stale-peer cleanup
    - Deduplicates system (join/leave) messages via debounce
    - Delivery ACKs for reliable message receipt confirmation
    - Per-peer rate limiting to prevent inbound floods
    - Live username propagation via USERNAME_UPDATE system message
    """

    def __init__(
        self,
        username: str,
        host: str,
        port: int,
        store: MessageStore,
        crypto: EncryptionService,
    ):
        self.username = _sanitize_username(username)
        self.host     = host
        self.port     = port
        self.store    = store
        self.crypto   = crypto
        self.peer_id  = _peer_id("0.0.0.0", port)

        # peer_id → asyncio.StreamWriter
        self._writers: Dict[str, asyncio.StreamWriter] = {}
        # peer_id → {username, host, port, last_heartbeat, missed_beats, online}
        self._peers:   Dict[str, dict] = {}
        # Direct messages queued while peer is offline: peer_id → [message_dict]
        self._pending_direct: Dict[str, list] = {}
        self._lock = asyncio.Lock()

        # Debounce: peer_id → (last_event_time, last_event_type)
        self._system_debounce: Dict[str, tuple] = {}

        # Rate limiting: peer_id → [timestamp, ...]
        self._rate_counters: Dict[str, list] = {}

        # Typing state: peer_id → expiry timestamp — polled by UI directly,
        # NOT queued, so transient events never block real messages.
        self.typing_peers: Dict[str, float] = {}

        # UI reads MESSAGE / ACK / SYSTEM / USERNAME_UPDATE from this queue.
        # HEARTBEAT and TYPING are handled inline and never enqueued.
        self.inbound_queue: asyncio.Queue = asyncio.Queue()

        self._server   = None
        self._running  = False
        self._tasks:   Set[asyncio.Task] = set()
        self.discovery: Optional[DiscoveryService] = None

    # ── Public API ─────────────────────────────────────────────────────────────

    async def start(self):
        self._running = True
        self._server  = await asyncio.start_server(
            self._handle_incoming, self.host, self.port
        )
        logger.info("TCP server listening on %s:%d", self.host, self.port)

        integrity_key = self.crypto._integrity_key if self.crypto.integrity_enabled else None
        self.discovery = DiscoveryService(
            username         = self.username,
            tcp_port         = self.port,
            on_peer_discovered = self._schedule_connect,
            integrity_key    = integrity_key,
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

    async def send_message(
        self, content: str, target_peer_id: Optional[str] = None
    ) -> str:
        """
        Send a chat message. Returns the message_id for UI tracking.

        FIX: store.save_message is called BEFORE the network send loop
        (write-ahead pattern). If the process crashes between persist and
        send, the message is still in the local history instead of being
        silently lost.
        """
        ts           = _now_iso()
        message_id   = str(uuid.uuid4())
        encrypted    = self.crypto.encrypt(content)
        is_broadcast = target_peer_id is None

        msg = {
            "type":         "MESSAGE",
            "message_id":   message_id,
            "sender":       self.username,
            "peer_id":      self.peer_id,
            "content":      encrypted,
            "timestamp":    ts,
            "is_broadcast": int(is_broadcast),
        }
        msg = _attach_auth_tag(self.crypto, msg)

        # Write-ahead: persist BEFORE sending on the wire
        store_pid = "broadcast" if is_broadcast else target_peer_id
        await self.store.save_message(
            store_pid, "out", content, is_broadcast,
            message_id=message_id, timestamp=ts,
        )

        # Build a snapshot of writers under the lock (no TOCTOU)
        async with self._lock:
            targets          = list(self._writers.keys()) if is_broadcast else [target_peer_id]
            writers_snapshot = {pid: self._writers[pid] for pid in targets if pid in self._writers}

        sent_count = 0
        for pid, writer in writers_snapshot.items():
            try:
                await _send_message(writer, msg)
                sent_count += 1
            except Exception as exc:
                logger.warning("Failed to send to %s: %s", pid, exc)
                if not is_broadcast and target_peer_id == pid:
                    self._pending_direct.setdefault(pid, []).append(msg)
                await self._on_peer_disconnected(pid)

        if not is_broadcast and target_peer_id and sent_count == 0:
            self._pending_direct.setdefault(target_peer_id, []).append(msg)
            logger.info("Queued direct message for %s (offline)", target_peer_id)

        return message_id   # ← returned so UI can track delivery ACK

    async def send_typing(self, target_peer_id: Optional[str] = None):
        """Send a transient TYPING event to peer(s)."""
        msg = {
            "type":      "TYPING",
            "sender":    self.username,
            "peer_id":   self.peer_id,
            "content":   "",
            "timestamp": _now_iso(),
        }
        msg = _attach_auth_tag(self.crypto, msg)
        async with self._lock:
            targets          = list(self._writers.keys()) if target_peer_id is None else [target_peer_id]
            writers_snapshot = {pid: self._writers[pid] for pid in targets if pid in self._writers}

        for pid, writer in writers_snapshot.items():
            try:
                await _send_message(writer, msg)
            except Exception:
                pass

    async def broadcast_username_update(self, new_username: str):
        """
        Notify all connected peers of a username change.
        Updates self.username and the discovery beacon atomically.
        """
        self.username = _sanitize_username(new_username)
        if self.discovery:
            self.discovery.username = self.username

        msg = {
            "type":      "SYSTEM",
            "sender":    self.username,
            "peer_id":   self.peer_id,
            "content":   "USERNAME_UPDATE",
            "timestamp": _now_iso(),
        }
        msg = _attach_auth_tag(self.crypto, msg)

        async with self._lock:
            writers_snapshot = dict(self._writers)

        for pid, writer in writers_snapshot.items():
            try:
                await _send_message(writer, msg)
            except Exception:
                pass

        logger.info("Broadcast username update: %s", self.username)

    async def connect_to_peer(self, host: str, port: int, username: str = "Unknown"):
        pid = _peer_id(host, port)
        if pid in self._writers:
            logger.debug("Already connected to %s", pid)
            return
        await self._connect_with_backoff(host, port, _sanitize_username(username))

    async def get_connected_peers(self) -> list:
        return [
            {**info, "peer_id": pid}
            for pid, info in self._peers.items()
            if pid in self._writers
        ]

    # ── Rate limiting ──────────────────────────────────────────────────────────

    def _is_rate_limited(self, pid: str) -> bool:
        """
        Return True and drop the message if this peer exceeds the rate limit.
        Sliding-window algorithm: keep only timestamps within the window.
        """
        now   = time.time()
        times = self._rate_counters.get(pid, [])
        times = [t for t in times if now - t < RATE_LIMIT_WINDOW]
        self._rate_counters[pid] = times
        if len(times) >= RATE_LIMIT_COUNT:
            return True
        times.append(now)
        return False

    # ── Internal ───────────────────────────────────────────────────────────────

    def _spawn(self, coro) -> asyncio.Task:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def _schedule_connect(self, host: str, port: int, username: str):
        pid = _peer_id(host, port)
        if pid not in self._writers:
            self._spawn(
                self._connect_with_backoff(host, port, _sanitize_username(username))
            )

    async def _connect_with_backoff(
        self,
        host: str,
        port: int,
        username: str,
        max_attempts: int = MAX_RECONNECT_ATTEMPTS,
    ):
        """
        Try to establish a TCP connection with exponential backoff.

        FIX: Loop is now capped at max_attempts (default 20, ~16 min total)
        so removed or unreachable peers don't cause indefinite background retry.
        """
        pid      = _peer_id(host, port)
        delay    = 2
        attempts = 0

        while self._running and attempts < max_attempts:
            if pid in self._writers:
                return  # already connected by the time we retried
            attempts += 1
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port), timeout=5
                )
                await self._on_peer_connected(pid, host, port, username, reader, writer)
                return
            except (ConnectionRefusedError, asyncio.TimeoutError, OSError):
                await asyncio.sleep(min(delay, MAX_BACKOFF))
                delay = min(delay * 2, MAX_BACKOFF)

        if attempts >= max_attempts:
            logger.warning(
                "Giving up reconnecting to %s after %d attempts", pid, attempts
            )

    async def _handle_incoming(self, reader, writer):
        addr = writer.get_extra_info("peername")
        msg  = await _recv_message(reader)
        if not msg:
            writer.close()
            return
        if not _verify_auth_tag(self.crypto, msg):
            logger.warning("Rejected unauthenticated initial frame from %s", addr)
            writer.close()
            return
        host     = addr[0]
        port     = msg.get("meta_port", addr[1])
        username = _sanitize_username(msg.get("sender", "Unknown"))
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

        # Send handshake with our metadata
        handshake = {
            "type":      "SYSTEM",
            "sender":    self.username,
            "peer_id":   self.peer_id,
            "meta_port": self.port,
            "content":   "JOINED",
            "timestamp": _now_iso(),
        }
        handshake = _attach_auth_tag(self.crypto, handshake)
        try:
            await _send_message(writer, handshake)
        except Exception:
            pass

        self._emit_system(pid, username, "joined")

        # Flush any messages queued while this peer was offline
        pending = self._pending_direct.pop(pid, [])
        for queued in pending:
            try:
                await _send_message(writer, queued)
            except Exception as exc:
                logger.warning("Failed to flush queued message to %s: %s", pid, exc)
                self._pending_direct.setdefault(pid, []).append(queued)
                break

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
            if not _verify_auth_tag(self.crypto, msg):
                logger.warning("Rejected unauthenticated frame from %s", pid)
                return

            msg_type = msg.get("type", "")

            # ── HEARTBEAT ───────────────────────────────────────────────────
            if msg_type == "HEARTBEAT":
                async with self._lock:
                    if pid in self._peers:
                        self._peers[pid]["last_heartbeat"] = time.monotonic()
                        self._peers[pid]["missed_beats"]   = 0
                        self._peers[pid]["online"]         = 1
                return

            # ── TYPING (not queued — stored directly in typing_peers) ────────
            if msg_type == "TYPING":
                if pid in self._peers:
                    msg["sender"] = self._peers[pid].get("username", msg.get("sender", "Unknown"))
                self.typing_peers[pid] = time.time() + 3.0
                return

            # ── ACK (delivery confirmation) ──────────────────────────────────
            if msg_type == "ACK":
                await self.inbound_queue.put({
                    "type":       "ACK",
                    "message_id": msg.get("message_id", ""),
                    "peer_id":    pid,
                })
                return

            # ── MESSAGE ──────────────────────────────────────────────────────
            if msg_type == "MESSAGE":
                # Rate-limit inbound messages per peer
                if self._is_rate_limited(pid):
                    logger.warning("Rate limit exceeded for peer %s; dropping message", pid)
                    return

                msg_id = msg.get("message_id", "")
                if msg_id and await self.store.has_message_id(msg_id):
                    return   # deduplicate

                try:
                    decrypted      = self.crypto.decrypt(msg.get("content", ""))
                    msg["content"] = decrypted
                except Exception as dec_exc:
                    logger.error("Failed to decrypt message from %s: %s", pid, dec_exc)
                    msg["content"] = "[encrypted message — key mismatch]"

                msg["peer_id"] = pid
                if pid in self._peers:
                    msg["sender"] = self._peers[pid]["username"]

                await self.store.save_message(
                    pid, "in",
                    msg.get("content", ""),
                    msg.get("is_broadcast", False),
                    message_id=msg_id or None,
                    timestamp=msg.get("timestamp"),
                )

                # Send delivery ACK so sender can show ✓✓ indicator
                writer = self._writers.get(pid)
                if writer and msg_id:
                    try:
                        ack = {
                            "type":       "ACK",
                            "message_id": msg_id,
                            "sender":     self.username,
                            "peer_id":    self.peer_id,
                            "content":    "",
                            "timestamp":  _now_iso(),
                        }
                        ack = _attach_auth_tag(self.crypto, ack)
                        await _send_message(writer, ack)
                    except Exception:
                        pass

                await self.inbound_queue.put(msg)
                return

            # ── SYSTEM ───────────────────────────────────────────────────────
            if msg_type == "SYSTEM":
                content = msg.get("content", "")

                if content == "JOINED":
                    async with self._lock:
                        if pid in self._peers:
                            self._peers[pid]["username"]  = _sanitize_username(
                                msg.get("sender", "Unknown")
                            )
                            self._peers[pid]["meta_port"] = msg.get(
                                "meta_port", self._peers[pid]["port"]
                            )
                    return

                if content == "USERNAME_UPDATE":
                    new_name = _sanitize_username(msg.get("sender", "Unknown"))
                    async with self._lock:
                        if pid in self._peers:
                            self._peers[pid]["username"] = new_name
                    await self.store.update_peer_username(pid, new_name)
                    await self.inbound_queue.put({
                        "type":   "USERNAME_UPDATE",
                        "peer_id": pid,
                        "sender":  new_name,
                    })
                    logger.info("Peer %s updated username to %s", pid, new_name)
                    return

                # All other SYSTEM events (joined/left display messages)
                msg["peer_id"] = pid
                await self.inbound_queue.put(msg)

        except Exception as exc:
            logger.error(
                "Error dispatching message from %s: %s", pid, exc, exc_info=True
            )

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
        self._emit_system(pid, username, "left")

        if host and port and self._running:
            self._spawn(self._connect_with_backoff(host, port, username))

    def _emit_system(self, pid: str, username: str, event: str):
        """
        Emit a system (join/leave) message, suppressed if the same event
        was emitted for this peer within SYSTEM_MSG_DEBOUNCE seconds.
        """
        now            = time.monotonic()
        last_t, last_e = self._system_debounce.get(pid, (0, ""))
        if last_e == event and (now - last_t) < SYSTEM_MSG_DEBOUNCE:
            return
        self._system_debounce[pid] = (now, event)
        content = (
            f"{username} joined the network"
            if event == "joined"
            else f"{username} left the network"
        )
        asyncio.ensure_future(self.inbound_queue.put({
            "type":      "SYSTEM",
            "sender":    username,
            "peer_id":   pid,
            "content":   content,
            "timestamp": _now_iso(),
            "event":     event,
        }))

    async def _heartbeat_loop(self):
        """
        Send heartbeat to all peers; remove peers that miss 3 consecutive beats.

        BUG FIX 1: Writers snapshot taken inside the lock so concurrent
                   disconnects can't cause a TOCTOU stale-writer access.
        BUG FIX 2: last_heartbeat default is now - TIMEOUT - 1 so peers
                   that never send a heartbeat are eligible for cleanup.
        """
        while self._running:
            await asyncio.sleep(HEARTBEAT_INTERVAL)

            hb_msg = {
                "type":      "HEARTBEAT",
                "sender":    self.username,
                "peer_id":   self.peer_id,
                "content":   "",
                "timestamp": _now_iso(),
            }
            hb_msg = _attach_auth_tag(self.crypto, hb_msg)

            # FIX: full snapshot inside lock — prevents TOCTOU race
            async with self._lock:
                writers_snapshot = {pid: w for pid, w in self._writers.items()}

            dead = []
            for pid, writer in writers_snapshot.items():
                try:
                    await _send_message(writer, hb_msg)
                except Exception:
                    async with self._lock:
                        if pid in self._peers:
                            self._peers[pid]["missed_beats"] = (
                                self._peers[pid].get("missed_beats", 0) + 1
                            )
                            if self._peers[pid]["missed_beats"] >= 3:
                                dead.append(pid)

            for pid in dead:
                logger.warning("Heartbeat timeout — removing peer %s", pid)
                await self._on_peer_disconnected(pid)

            # FIX: default last_heartbeat to (now - TIMEOUT - 1) so new peers
            # with no recorded heartbeat are NOT exempt from stale detection.
            now   = time.monotonic()
            stale = []
            async with self._lock:
                for pid, info in self._peers.items():
                    lhb = info.get("last_heartbeat", now - HEARTBEAT_TIMEOUT - 1)
                    if pid in self._writers and (now - lhb) > HEARTBEAT_TIMEOUT:
                        stale.append(pid)

            for pid in stale:
                logger.warning("Peer %s exceeded heartbeat timeout window", pid)
                await self._on_peer_disconnected(pid)
