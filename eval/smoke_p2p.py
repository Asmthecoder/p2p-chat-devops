import asyncio
import os

from encryption import EncryptionService, generate_key
from message_store import MessageStore
from peer import PeerManager


async def main() -> None:
    key = generate_key()

    db1 = "smoke_9101.db"
    db2 = "smoke_9102.db"
    for path in [db1, db2, db1 + "-shm", db1 + "-wal", db2 + "-shm", db2 + "-wal"]:
        if os.path.exists(path):
            os.remove(path)

    s1 = MessageStore(db1)
    s2 = MessageStore(db2)
    await s1.init()
    await s2.init()

    p1 = PeerManager("Alice", "127.0.0.1", 9101, s1, EncryptionService(key))
    p2 = PeerManager("Bob",   "127.0.0.1", 9102, s2, EncryptionService(key))

    await p1.start()
    await p2.start()

    await p1.connect_to_peer("127.0.0.1", 9102, "Bob")
    await asyncio.sleep(1.0)   # allow handshake to complete

    await p1.send_message("broadcast hello")
    await asyncio.sleep(0.6)

    peers_p1 = await p1.get_connected_peers()
    peers_p2 = await p2.get_connected_peers()

    # ── Assertions: peer connectivity ────────────────────────────────────────
    assert len(peers_p1) > 0, (
        f"P1 should have ≥1 connected peer, got {peers_p1}"
    )
    assert len(peers_p2) > 0, (
        f"P2 should have ≥1 connected peer, got {peers_p2}"
    )

    target_id = peers_p1[0]["peer_id"]
    await p1.send_message("direct hello", target_id)
    await asyncio.sleep(0.8)   # allow message + ACK round-trip

    # ── Assertions: message delivery ─────────────────────────────────────────
    # Broadcast view (is_broadcast=1 only, since we fixed get_all_messages)
    broadcast_msgs_bob = await s2.get_all_messages(20)
    # Direct message history from Bob's perspective
    direct_msgs_bob = await s2.get_history("127.0.0.1:9101", 20)

    assert len(broadcast_msgs_bob) >= 1, (
        f"Bob should have ≥1 broadcast message, got {broadcast_msgs_bob}"
    )
    assert len(direct_msgs_bob) >= 1, (
        f"Bob should have ≥1 direct message, got {direct_msgs_bob}"
    )

    # Verify contents
    bc_contents = [m["content"] for m in broadcast_msgs_bob]
    dm_contents = [m["content"] for m in direct_msgs_bob]
    assert any("broadcast hello" in c for c in bc_contents), (
        f"Expected 'broadcast hello' in broadcast messages, got: {bc_contents}"
    )
    assert any("direct hello" in c for c in dm_contents), (
        f"Expected 'direct hello' in direct messages, got: {dm_contents}"
    )

    # Direct messages must NOT appear in the broadcast view
    assert all(m["is_broadcast"] == 1 for m in broadcast_msgs_bob), (
        "Broadcast view must not contain direct (non-broadcast) messages"
    )

    # ── Assertions: search ───────────────────────────────────────────────────
    search_results = await s2.search_messages("hello")
    assert len(search_results) >= 2, (
        f"Search for 'hello' should return ≥2 messages, got {search_results}"
    )

    # ── Pretty print ─────────────────────────────────────────────────────────
    print("P1 connected peers:", peers_p1)
    print("P2 connected peers:", peers_p2)
    print("Bob broadcast messages:", broadcast_msgs_bob)
    print("Bob direct messages:", direct_msgs_bob)
    print("Search results (hello):", search_results)
    print()
    print("✅  All smoke-test assertions passed!")

    await p1.stop()
    await p2.stop()


if __name__ == "__main__":
    asyncio.run(main())
