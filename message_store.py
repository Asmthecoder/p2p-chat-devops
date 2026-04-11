"""
message_store.py — Persistent Message & Peer Storage
=====================================================
Rubric: Consistency, Replication & Fault Tolerance (CO3, CO4)

Design decisions:
  - SQLite via aiosqlite for async, non-blocking disk I/O
  - WAL mode for concurrent read-write performance
  - Migration helper guarantees forward-compatible schema changes
  - is_broadcast flag allows clean separation of channel vs DM history

Bug fixes in this version
--------------------------
1. Migration crash: the unique index on message_id now created AFTER the
   column migration helper, so old DBs without the column no longer crash.
2. get_all_messages now filters WHERE is_broadcast=1 preventing direct
   messages from leaking into the global broadcast channel view.
3. Added search_messages() for full-text history search.
4. Added update_peer_username() for live username propagation.
"""

import aiosqlite
import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Dict, Optional

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
        # Step 1 — create base tables WITHOUT the unique index on message_id yet.
        # executescript() issues an implicit COMMIT so we keep index creation separate.
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS messages (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id   TEXT,
                peer_id      TEXT NOT NULL,
                direction    TEXT NOT NULL CHECK(direction IN ('in','out')),
                content      TEXT NOT NULL,
                timestamp    TEXT NOT NULL,
                is_broadcast INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS peers (
                id        TEXT PRIMARY KEY,
                username  TEXT NOT NULL,
                host      TEXT NOT NULL,
                port      INTEGER NOT NULL,
                online    INTEGER DEFAULT 0,
                last_seen TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_messages_peer
                ON messages(peer_id, timestamp);
        """)

        # Step 2 — ensure message_id column exists in older DBs (migration).
        # Must run BEFORE the unique index that references it.
        await self._ensure_message_id_column()

        # Step 3 — now safe to create the unique index (column is guaranteed present).
        await self._db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_message_id "
            "ON messages(message_id) WHERE message_id IS NOT NULL"
        )
        await self._db.commit()

    async def _ensure_message_id_column(self):
        """Migration helper: add message_id column to pre-existing databases."""
        async with self._db.execute("PRAGMA table_info(messages)") as cursor:
            cols = await cursor.fetchall()
        existing_cols = {row[1] for row in cols}
        if "message_id" not in existing_cols:
            await self._db.execute("ALTER TABLE messages ADD COLUMN message_id TEXT")
            await self._db.commit()
            logger.info("Migrated messages table: added message_id column")

    # ──────────────────────────── Messages ────────────────────────────

    async def save_message(
        self,
        peer_id: str,
        direction: str,
        content: str,
        is_broadcast: bool = False,
        message_id: Optional[str] = None,
        timestamp: Optional[str] = None,
    ) -> Dict:
        """
        Persist a chat message.

        Parameters
        ----------
        peer_id      : unique identifier for the remote peer (host:port)
        direction    : 'in' (received) or 'out' (sent)
        content      : *decrypted* plaintext content to store
        is_broadcast : True if this was a broadcast to all peers
        """
        ts = timestamp or datetime.now(timezone.utc).isoformat()
        async with self._lock:
            if message_id:
                await self._db.execute(
                    """INSERT OR IGNORE INTO messages
                       (message_id, peer_id, direction, content, timestamp, is_broadcast)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (message_id, peer_id, direction, content, ts, int(is_broadcast)),
                )
            else:
                await self._db.execute(
                    """INSERT INTO messages
                       (peer_id, direction, content, timestamp, is_broadcast)
                       VALUES (?, ?, ?, ?, ?)""",
                    (peer_id, direction, content, ts, int(is_broadcast)),
                )
            await self._db.commit()
        return {
            "message_id": message_id,
            "peer_id":    peer_id,
            "direction":  direction,
            "content":    content,
            "timestamp":  ts,
        }

    async def get_history(self, peer_id: str, limit: int = 50) -> List[Dict]:
        """Fetch the last `limit` direct messages for a given peer_id."""
        async with self._db.execute(
            """SELECT message_id, peer_id, direction, content, timestamp, is_broadcast
               FROM messages
               WHERE peer_id = ? AND is_broadcast = 0
               ORDER BY timestamp DESC
               LIMIT ?""",
            (peer_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(r) for r in reversed(rows)]

    async def get_all_messages(self, limit: int = 200) -> List[Dict]:
        """
        Fetch recent broadcast messages for the global channel view.

        BUG FIX: Previously fetched ALL messages regardless of is_broadcast,
        which caused direct (DM) messages to leak into the global channel.
        Now correctly filters WHERE is_broadcast = 1.
        """
        async with self._db.execute(
            """SELECT message_id, peer_id, direction, content, timestamp, is_broadcast
               FROM messages
               WHERE is_broadcast = 1
               ORDER BY timestamp DESC
               LIMIT ?""",
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(r) for r in reversed(rows)]

    async def search_messages(
        self,
        query: str,
        peer_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict]:
        """
        Full-text search across message history using SQL LIKE.

        Parameters
        ----------
        query   : search term (case-insensitive substring match)
        peer_id : if given, restrict results to this conversation channel
        limit   : maximum number of results to return
        """
        q = f"%{query}%"
        if peer_id:
            sql = """SELECT message_id, peer_id, direction, content, timestamp, is_broadcast
                     FROM messages WHERE content LIKE ? AND peer_id = ?
                     ORDER BY timestamp DESC LIMIT ?"""
            params = (q, peer_id, limit)
        else:
            sql = """SELECT message_id, peer_id, direction, content, timestamp, is_broadcast
                     FROM messages WHERE content LIKE ?
                     ORDER BY timestamp DESC LIMIT ?"""
            params = (q, limit)

        async with self._db.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
        return [dict(r) for r in reversed(rows)]

    async def has_message_id(self, message_id: str) -> bool:
        if not message_id:
            return False
        async with self._db.execute(
            "SELECT 1 FROM messages WHERE message_id = ? LIMIT 1", (message_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return row is not None

    # ──────────────────────────── Peers ───────────────────────────────

    async def upsert_peer(self, peer_id: str, username: str, host: str, port: int):
        """Insert or update a peer record when discovered or reconnected."""
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
        """Mark a peer as offline (heartbeat failure or disconnect)."""
        async with self._lock:
            await self._db.execute(
                "UPDATE peers SET online=0 WHERE id=?", (peer_id,)
            )
            await self._db.commit()

    async def update_peer_username(self, peer_id: str, username: str):
        """Update a peer's display name when a USERNAME_UPDATE is received."""
        async with self._lock:
            await self._db.execute(
                "UPDATE peers SET username=? WHERE id=?", (username, peer_id)
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
            "SELECT id, username, host, port, online, last_seen FROM peers "
            "WHERE online=1 ORDER BY username"
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def close(self):
        if self._db:
            await self._db.close()
            logger.info("MessageStore closed.")
