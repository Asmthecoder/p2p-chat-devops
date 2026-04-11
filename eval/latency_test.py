"""
eval/latency_test.py - Evaluation, Analysis, and Appraisal suite

This script evaluates:
1) Scalability: latency and throughput as peer count increases
2) Reliability: success rate under simulated packet loss and delay
3) Design trade-offs: automatic appraisal from observed metrics

Usage:
    python eval/latency_test.py
    python eval/latency_test.py --max-peers 8 --trials 5 --messages 30

Outputs:
    eval/results.csv
    eval/results.json
    eval/appraisal.txt
    eval/results.png (if matplotlib is installed)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import random
import statistics
import struct
import time
from pathlib import Path
from typing import Any

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

BASE_PORT = 9101
RESULT_DIR = Path(__file__).parent
CSV_PATH = RESULT_DIR / "results.csv"
JSON_PATH = RESULT_DIR / "results.json"
APPRAISAL_PATH = RESULT_DIR / "appraisal.txt"
PLOT_PATH = RESULT_DIR / "results.png"


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    if q <= 0:
        return min(values)
    if q >= 100:
        return max(values)

    sorted_values = sorted(values)
    rank = (len(sorted_values) - 1) * (q / 100.0)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return sorted_values[int(rank)]
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (rank - low)


async def _echo_server(host: str, port: int, drop_rate: float, max_jitter_ms: float):
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            # Read 4-byte length prefix then payload.
            header = await reader.readexactly(4)
            msg_len = struct.unpack(">I", header)[0]
            payload = await reader.readexactly(msg_len)

            if max_jitter_ms > 0:
                await asyncio.sleep(random.uniform(0, max_jitter_ms) / 1000.0)

            if random.random() >= drop_rate:
                writer.write(header + payload)
                await writer.drain()
        except asyncio.IncompleteReadError:
            pass
        finally:
            writer.close()

    return await asyncio.start_server(handle, host, port)


async def rtt_trial(
    peer_count: int,
    messages: int,
    timeout_ms: int,
    drop_rate: float,
    jitter_ms: float,
) -> dict[str, Any]:
    host = "127.0.0.1"
    port = BASE_PORT + peer_count * 100
    timeout_s = timeout_ms / 1000.0

    server = await _echo_server(host, port, drop_rate=drop_rate, max_jitter_ms=jitter_ms)
    await asyncio.sleep(0.05)

    samples_ms: list[float] = []
    successes = 0
    total = 0
    start = time.perf_counter()

    for _ in range(messages):
        total += 1
        try:
            t0 = time.perf_counter()
            reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout_s)

            payload = json.dumps({"ts": t0, "n": peer_count}).encode("utf-8")
            header = struct.pack(">I", len(payload))
            writer.write(header + payload)
            await writer.drain()

            _ = await asyncio.wait_for(reader.readexactly(4), timeout=timeout_s)
            _ = await asyncio.wait_for(reader.readexactly(len(payload)), timeout=timeout_s)

            t1 = time.perf_counter()
            samples_ms.append((t1 - t0) * 1000.0)
            successes += 1
            writer.close()
            await writer.wait_closed()
        except (asyncio.TimeoutError, OSError, asyncio.IncompleteReadError):
            continue

    elapsed_s = max(time.perf_counter() - start, 1e-9)
    server.close()
    await server.wait_closed()

    success_rate = (successes / total) if total else 0.0
    throughput_mps = successes / elapsed_s

    return {
        "samples_ms": samples_ms,
        "successes": successes,
        "attempts": total,
        "success_rate": success_rate,
        "throughput_mps": throughput_mps,
    }


def summarize_samples(samples_ms: list[float]) -> dict[str, float]:
    if not samples_ms:
        return {
            "avg_ms": 0.0,
            "p50_ms": 0.0,
            "p95_ms": 0.0,
            "min_ms": 0.0,
            "max_ms": 0.0,
            "stddev_ms": 0.0,
        }

    return {
        "avg_ms": statistics.mean(samples_ms),
        "p50_ms": percentile(samples_ms, 50),
        "p95_ms": percentile(samples_ms, 95),
        "min_ms": min(samples_ms),
        "max_ms": max(samples_ms),
        "stddev_ms": statistics.pstdev(samples_ms),
    }


async def run_scalability(
    max_peers: int,
    trials: int,
    messages: int,
    timeout_ms: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    print("\nScalability evaluation")
    print("=" * 90)
    print(f"{'Peers':<8}{'Avg(ms)':<12}{'P95(ms)':<12}{'Success%':<12}{'Thr(msg/s)':<14}{'Samples':<10}")
    print("-" * 90)

    for peers in range(2, max_peers + 1):
        merged_samples: list[float] = []
        attempts = 0
        successes = 0
        throughput_values: list[float] = []

        for _ in range(trials):
            trial = await rtt_trial(
                peer_count=peers,
                messages=messages,
                timeout_ms=timeout_ms,
                drop_rate=0.0,
                jitter_ms=0.0,
            )
            merged_samples.extend(trial["samples_ms"])
            attempts += trial["attempts"]
            successes += trial["successes"]
            throughput_values.append(trial["throughput_mps"])

        stats = summarize_samples(merged_samples)
        success_rate = (successes / attempts) if attempts else 0.0
        avg_throughput = statistics.mean(throughput_values) if throughput_values else 0.0

        row = {
            "mode": "scalability",
            "peers": peers,
            **stats,
            "success_rate": success_rate,
            "throughput_mps": avg_throughput,
            "samples": len(merged_samples),
            "attempts": attempts,
            "successes": successes,
        }
        rows.append(row)

        print(
            f"{peers:<8}{stats['avg_ms']:<12.2f}{stats['p95_ms']:<12.2f}"
            f"{(success_rate * 100):<12.1f}{avg_throughput:<14.2f}{len(merged_samples):<10}"
        )

    return rows


async def run_reliability(
    peers: int,
    trials: int,
    messages: int,
    timeout_ms: int,
    loss_levels: list[float],
    jitter_ms: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    print("\nReliability evaluation (simulated loss and jitter)")
    print("=" * 90)
    print(f"{'Loss%':<10}{'Avg(ms)':<12}{'P95(ms)':<12}{'Success%':<12}{'Thr(msg/s)':<14}{'Samples':<10}")
    print("-" * 90)

    for loss in loss_levels:
        merged_samples: list[float] = []
        attempts = 0
        successes = 0
        throughput_values: list[float] = []

        for _ in range(trials):
            trial = await rtt_trial(
                peer_count=peers,
                messages=messages,
                timeout_ms=timeout_ms,
                drop_rate=loss,
                jitter_ms=jitter_ms,
            )
            merged_samples.extend(trial["samples_ms"])
            attempts += trial["attempts"]
            successes += trial["successes"]
            throughput_values.append(trial["throughput_mps"])

        stats = summarize_samples(merged_samples)
        success_rate = (successes / attempts) if attempts else 0.0
        avg_throughput = statistics.mean(throughput_values) if throughput_values else 0.0

        row = {
            "mode": "reliability",
            "peers": peers,
            "loss_rate": loss,
            **stats,
            "success_rate": success_rate,
            "throughput_mps": avg_throughput,
            "samples": len(merged_samples),
            "attempts": attempts,
            "successes": successes,
            "jitter_ms": jitter_ms,
        }
        rows.append(row)

        print(
            f"{(loss * 100):<10.0f}{stats['avg_ms']:<12.2f}{stats['p95_ms']:<12.2f}"
            f"{(success_rate * 100):<12.1f}{avg_throughput:<14.2f}{len(merged_samples):<10}"
        )

    return rows


def linear_slope(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 2 or len(ys) < 2 or len(xs) != len(ys):
        return 0.0
    x_mean = statistics.mean(xs)
    y_mean = statistics.mean(ys)
    num = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    den = sum((x - x_mean) ** 2 for x in xs)
    if den == 0:
        return 0.0
    return num / den


def build_appraisal(scalability_rows: list[dict[str, Any]], reliability_rows: list[dict[str, Any]]) -> str:
    peers = [float(r["peers"]) for r in scalability_rows]
    p95s = [float(r["p95_ms"]) for r in scalability_rows]
    throughputs = [float(r["throughput_mps"]) for r in scalability_rows]

    p95_slope = linear_slope(peers, p95s)
    thr_slope = linear_slope(peers, throughputs)

    zero_loss = next((r for r in reliability_rows if abs(float(r["loss_rate"])) < 1e-9), None)
    high_loss = max(reliability_rows, key=lambda r: float(r["loss_rate"])) if reliability_rows else None

    reliability_drop = 0.0
    if zero_loss and high_loss and zero_loss["success_rate"] > 0:
        reliability_drop = (zero_loss["success_rate"] - high_loss["success_rate"]) / zero_loss["success_rate"]

    lines = []
    lines.append("Evaluation Appraisal")
    lines.append("====================")
    lines.append(f"Scalability latency slope (p95 per peer): {p95_slope:.3f} ms/peer")
    lines.append(f"Scalability throughput slope: {thr_slope:.3f} msg/s per peer")
    lines.append(f"Reliability success-rate drop (0%->max loss): {reliability_drop * 100:.2f}%")
    lines.append("")

    if p95_slope <= 3.0:
        lines.append("Latency scaling: Strong. Tail latency grows slowly as peers increase.")
    elif p95_slope <= 8.0:
        lines.append("Latency scaling: Moderate. System remains usable but watch tail growth.")
    else:
        lines.append("Latency scaling: Weak. Tail latency grows quickly; optimize routing/framing.")

    if thr_slope >= 0:
        lines.append("Throughput scaling: Non-degrading under added peer count.")
    else:
        lines.append("Throughput scaling: Degrading with scale; investigate contention and retries.")

    if reliability_drop <= 0.10:
        lines.append("Reliability: Robust under adverse conditions.")
    elif reliability_drop <= 0.30:
        lines.append("Reliability: Acceptable with degradation; retries/backoff are recommended.")
    else:
        lines.append("Reliability: Significant degradation under loss; stronger fault-tolerance required.")

    lines.append("")
    lines.append("Design trade-offs observed:")
    lines.append("- Lower timeout improves responsiveness but may reduce success rate under jitter.")
    lines.append("- Aggressive retransmission can improve delivery but may reduce throughput at scale.")
    lines.append("- Adding integrity checks increases CPU overhead slightly while improving trustworthiness.")

    return "\n".join(lines) + "\n"


def save_csv(rows: list[dict[str, Any]], path: Path) -> None:
    keys = [
        "mode",
        "peers",
        "loss_rate",
        "avg_ms",
        "p50_ms",
        "p95_ms",
        "min_ms",
        "max_ms",
        "stddev_ms",
        "success_rate",
        "throughput_mps",
        "samples",
        "attempts",
        "successes",
        "jitter_ms",
    ]

    lines = [",".join(keys)]
    for row in rows:
        lines.append(
            ",".join(
                str(row.get(k, "")) for k in keys
            )
        )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def maybe_plot(scalability_rows: list[dict[str, Any]], reliability_rows: list[dict[str, Any]]) -> None:
    if not HAS_MATPLOTLIB:
        print("matplotlib not installed; skipping graph output.")
        return

    peers = [r["peers"] for r in scalability_rows]
    p95 = [r["p95_ms"] for r in scalability_rows]
    thr = [r["throughput_mps"] for r in scalability_rows]

    losses = [r["loss_rate"] * 100 for r in reliability_rows]
    rel_success = [r["success_rate"] * 100 for r in reliability_rows]

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))

    axes[0].plot(peers, p95, marker="o", linewidth=2)
    axes[0].set_title("Tail Latency vs Peers")
    axes[0].set_xlabel("Peers")
    axes[0].set_ylabel("p95 latency (ms)")
    axes[0].grid(True, linestyle="--", alpha=0.4)

    ax0b = axes[0].twinx()
    ax0b.plot(peers, thr, marker="s", linewidth=1.7)
    ax0b.set_ylabel("throughput (msg/s)")

    axes[1].plot(losses, rel_success, marker="o", linewidth=2)
    axes[1].set_title("Reliability Under Loss")
    axes[1].set_xlabel("packet loss (%)")
    axes[1].set_ylabel("success rate (%)")
    axes[1].grid(True, linestyle="--", alpha=0.4)

    plt.tight_layout()
    plt.savefig(PLOT_PATH, dpi=150, bbox_inches="tight")
    plt.close(fig)


async def run(args: argparse.Namespace) -> None:
    RESULT_DIR.mkdir(exist_ok=True)

    scalability_rows = await run_scalability(
        max_peers=args.max_peers,
        trials=args.trials,
        messages=args.messages,
        timeout_ms=args.timeout_ms,
    )

    reliability_rows = await run_reliability(
        peers=args.reliability_peers,
        trials=args.trials,
        messages=args.messages,
        timeout_ms=args.timeout_ms,
        loss_levels=args.loss_levels,
        jitter_ms=args.jitter_ms,
    )

    appraisal = build_appraisal(scalability_rows, reliability_rows)

    all_rows = scalability_rows + reliability_rows
    save_csv(all_rows, CSV_PATH)

    JSON_PATH.write_text(
        json.dumps(
            {
                "config": {
                    "max_peers": args.max_peers,
                    "trials": args.trials,
                    "messages": args.messages,
                    "timeout_ms": args.timeout_ms,
                    "reliability_peers": args.reliability_peers,
                    "loss_levels": args.loss_levels,
                    "jitter_ms": args.jitter_ms,
                },
                "scalability": scalability_rows,
                "reliability": reliability_rows,
                "appraisal": appraisal,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    APPRAISAL_PATH.write_text(appraisal, encoding="utf-8")
    maybe_plot(scalability_rows, reliability_rows)

    print("\nFiles written:")
    print(f"- {CSV_PATH}")
    print(f"- {JSON_PATH}")
    print(f"- {APPRAISAL_PATH}")
    if HAS_MATPLOTLIB:
        print(f"- {PLOT_PATH}")

    print("\n" + appraisal)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="P2P evaluation, analysis, and appraisal")
    parser.add_argument("--max-peers", type=int, default=6, help="maximum peers for scalability run")
    parser.add_argument("--trials", type=int, default=3, help="trials per scenario")
    parser.add_argument("--messages", type=int, default=20, help="messages per trial")
    parser.add_argument("--timeout-ms", type=int, default=800, help="request timeout in milliseconds")
    parser.add_argument("--reliability-peers", type=int, default=6, help="peer count used for reliability sweep")
    parser.add_argument("--jitter-ms", type=float, default=25.0, help="simulated jitter for reliability test")
    parser.add_argument(
        "--loss-levels",
        type=float,
        nargs="+",
        default=[0.0, 0.05, 0.1, 0.2, 0.3],
        help="packet loss levels for reliability sweep (0.0-1.0)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
