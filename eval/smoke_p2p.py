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
    p2 = PeerManager("Bob", "127.0.0.1", 9102, s2, EncryptionService(key))

    await p1.start()
    await p2.start()

    await p1.connect_to_peer("127.0.0.1", 9102, "Bob")
    await asyncio.sleep(1.0)

    await p1.send_message("broadcast hello")
    await asyncio.sleep(0.6)

    peers_p1 = await p1.get_connected_peers()
    peers_p2 = await p2.get_connected_peers()

    if not peers_p1:
        raise RuntimeError("P1 has no connected peers")

    target_id = peers_p1[0]["peer_id"]
    await p1.send_message("direct hello", target_id)
    await asyncio.sleep(0.8)

    messages_bob = await s2.get_all_messages(20)
    print("P1 connected peers:", peers_p1)
    print("P2 connected peers:", peers_p2)
    print("Bob messages:")
    for m in messages_bob:
        print(m)

    await p1.stop()
    await p2.stop()


if __name__ == "__main__":
    asyncio.run(main())
