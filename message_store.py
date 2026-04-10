"""
message_store.py — Persistent Message & Peer Storage
=====================================================
Rubric: Consistency, Replication & Fault Tolerance (CO3, CO4)

Design decisions:
  - SQLite via aiosqlite for async, non-blocking disk I/O
  - Messages stored locally on each peer (eventual consistency model)
  - Peer registry updated in real-time (heartbeat-driven)
  - On reconnect, peers exchange recent message history for replication
"""

import aiosqlite
import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Dict, Optional
import os

logger = logging.getLogger(__name__)

DB_PATH = "chat_history.db"


class MessageStore:
    """
    Async SQLite store for messages and peer registry.

    Tables
    ------
    messages  — all chat messages (inbound + outbound)
    peers     — known peers and their online status
    """

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()

    async def init(self):
        """Create database and tables if they don't exist."""
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")  # Write-Ahead Logging for concurrency
        await self._create_tables()
        logger.info("MessageStore initialised at %s", self.db_path)

    async def _create_tables(self):
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS messages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                peer_id     TEXT NOT NULL,
                direction   TEXT NOT NULL CHECK(direction IN ('in','out')),
                content     TEXT NOT NULL,
                timestamp   TEXT NOT NULL,
                is_broadcast INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS peers (
                id          TEXT PRIMARY KEY,
                username    TEXT NOT NULL,
                host        TEXT NOT NULL,
                port        INTEGER NOT NULL,
                online      INTEGER DEFAULT 0,
                last_seen   TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_messages_peer ON messages(peer_id, timestamp);
        """)
        await self._db.commit()

    # ──────────────────────────── Messages ────────────────────────────

    async def save_message(
        self,
        peer_id: str,
        direction: str,
        content: str,
        is_broadcast: bool = False,
    ) -> Dict:
        """
        Persist a chat message.

        Parameters
        ----------
        peer_id   : unique identifier for the remote peer (host:port)
        direction : 'in' (received) or 'out' (sent)
        content   : *decrypted* plaintext content to store
        is_broadcast : True if this was a broadcast to all peers
        """
        ts = datetime.now(timezone.utc).isoformat()
        async with self._lock:
            await self._db.execute(
                """INSERT INTO messages (peer_id, direction, content, timestamp, is_broadcast)
                   VALUES (?, ?, ?, ?, ?)""",
                (peer_id, direction, content, ts, int(is_broadcast)),
            )
            await self._db.commit()
        return {"peer_id": peer_id, "direction": direction, "content": content, "timestamp": ts}

    async def get_history(self, peer_id: str, limit: int = 50) -> List[Dict]:
        """Fetch the last `limit` messages for a given peer_id."""
        async with self._db.execute(
            """SELECT peer_id, direction, content, timestamp, is_broadcast
               FROM messages
               WHERE peer_id = ?
               ORDER BY timestamp DESC
               LIMIT ?""",
            (peer_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(r) for r in reversed(rows)]

    async def get_all_messages(self, limit: int = 200) -> List[Dict]:
        """Fetch recent messages from all peers (for the broadcast/global view)."""
        async with self._db.execute(
            """SELECT peer_id, direction, content, timestamp, is_broadcast
               FROM messages
               ORDER BY timestamp DESC
               LIMIT ?""",
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(r) for r in reversed(rows)]

    # ──────────────────────────── Peers ───────────────────────────────

    async def upsert_peer(self, peer_id: str, username: str, host: str, port: int):
        """Insert or update a peer record (called when a peer is discovered or reconnects)."""
        ts = datetime.now(timezone.utc).isoformat()
        async with self._lock:
            await self._db.execute(
                """INSERT INTO peers (id, username, host, port, online, last_seen)
                   VALUES (?, ?, ?, ?, 1, ?)
                   ON CONFLICT(id) DO UPDATE SET
                       username=excluded.username,
                       host=excluded.host,
                       port=excluded.port,
                       online=1,
                       last_seen=excluded.last_seen""",
                (peer_id, username, host, port, ts),
            )
            await self._db.commit()

    async def mark_peer_offline(self, peer_id: str):
        """Mark a peer as offline (called when heartbeat fails or disconnect detected)."""
        async with self._lock:
            await self._db.execute(
                "UPDATE peers SET online=0 WHERE id=?", (peer_id,)
            )
            await self._db.commit()

    async def get_all_peers(self) -> List[Dict]:
        """Return all known peers."""
        async with self._db.execute(
            "SELECT id, username, host, port, online, last_seen FROM peers ORDER BY username"
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_online_peers(self) -> List[Dict]:
        """Return only currently online peers."""
        async with self._db.execute(
            "SELECT id, username, host, port, online, last_seen FROM peers WHERE online=1 ORDER BY username"
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def close(self):
        if self._db:
            await self._db.close()
            logger.info("MessageStore closed.")
