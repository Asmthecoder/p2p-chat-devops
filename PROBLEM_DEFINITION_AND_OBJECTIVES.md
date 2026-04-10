# Problem Definition and Objectives (Assessment Appendix)

## Clear Distributed Computing Problem
Centralized chat systems place routing and state handling in one server, creating reliability and scalability bottlenecks. This project addresses the distributed computing problem of maintaining real-time communication, availability, and consistency across independent peer nodes without a central coordinator.

## Explicit System Requirements
- R1: Decentralized communication architecture (no central routing server)
- R2: Reliable peer-to-peer message exchange over TCP
- R3: Concurrent processing of inbound/outbound traffic
- R4: Local persistence of chat history per node
- R5: Discovery and membership awareness for peers
- R6: Fault detection and automatic reconnection
- R7: Secure message transport with authenticated encryption behavior
- R8: Quantitative performance evaluation with reproducible method

## Objectives Mapped to Requirements
| Objective | Requirement Coverage | Implementation Evidence |
|---|---|---|
| CO1 Eliminate central server | R1, R2 | peer.py, README architecture |
| CO2 Concurrent messaging | R3 | asyncio networking loops in peer.py |
| CO3 Eventual consistency | R4 | message_store.py and history retrieval |
| CO4 Fault tolerance | R5, R6 | discovery + heartbeat + reconnect logic |
| CO5 Data-in-transit security | R7 | encryption.py integration in peer.py |
| CO6 Performance evaluation | R8 | eval/latency_test.py and reported results |

## Measurable Acceptance Criteria
- AC1: Nodes communicate directly with no central server process.
- AC2: Broadcast and direct messaging semantics are correct.
- AC3: Restarted node retains local message history.
- AC4: Peer offline/online transitions are reflected in UI and storage.
- AC5: Encryption behavior is verifiable under key match/mismatch scenarios.
- AC6: Benchmark script executes and produces latency outputs for multiple peer counts.

## Validation Artifacts
- README.md section 1
- TESTING_GUIDE.md functional test steps
- eval/smoke_p2p.py runtime smoke validation
- eval/latency_test.py performance test
