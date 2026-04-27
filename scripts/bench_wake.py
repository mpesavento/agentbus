#!/usr/bin/env python3
"""Bench wake-script latency: openclaw CLI vs gateway-bridge.

Measures the time spent in the wake script *before* the receiving agent
starts producing output. Both wake paths are invoked against an agent
id that does not exist in the OpenClaw config — the gateway/CLI rejects
the call early, so we measure bootstrap + handshake + dispatch overhead
without spending tokens or waking a real agent.

Usage:
    python scripts/bench_wake.py [--runs N] [--bogus-agent ID]

Prereqs:
    - OpenClaw gateway daemon running (~/.openclaw/openclaw.json present).
    - Both wake scripts present under examples/.
"""
from __future__ import annotations

import argparse
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def run_once(script: Path, agent_id: str, timeout_s: int = 30) -> float:
    """Invoke a wake script with a small body; return elapsed seconds.

    Exit codes are ignored — the bench measures wall time regardless
    of whether the wake path accepts or rejects the (deliberately bogus)
    agent id.
    """
    env = os.environ.copy()
    env.update({
        "SWARMBUS_FROM": "bench",
        "SWARMBUS_TO": "bench-target",
        "SWARMBUS_ID": f"bench-{int(time.time() * 1000)}",
        "SWARMBUS_SUBJECT": "bench",
        "SWARMBUS_CONTENT_TYPE": "text/plain",
        "SWARMBUS_PRIORITY": "normal",
        "SWARMBUS_TS": str(int(time.time())),
        "SWARMBUS_REPLY_TO": "",
        "OPENCLAW_BRIDGE_TIMEOUT_MS": str(timeout_s * 1000),
    })
    t0 = time.perf_counter()
    subprocess.run(
        [str(script), agent_id],
        input=b"bench probe\n",
        env=env,
        timeout=timeout_s,
        check=False,
        capture_output=True,
    )
    return time.perf_counter() - t0


def summarise(label: str, samples: list[float]) -> None:
    mean = statistics.mean(samples)
    median = statistics.median(samples)
    lo, hi = min(samples), max(samples)
    print(
        f"{label:>16}  n={len(samples)}  "
        f"mean={mean*1000:7.0f}ms  med={median*1000:7.0f}ms  "
        f"min={lo*1000:7.0f}ms  max={hi*1000:7.0f}ms"
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--runs", type=int, default=3,
                   help="samples per wake path (default 3)")
    p.add_argument("--bogus-agent", default="bench-nonexistent-agent",
                   help="agent id that will be rejected by both paths")
    args = p.parse_args()

    root = repo_root()
    cli_script = root / "examples" / "openclaw-wake.sh"
    bridge_script = root / "examples" / "openclaw-bridge-wake.sh"
    for s in (cli_script, bridge_script):
        if not s.exists():
            print(f"missing wake script: {s}", file=sys.stderr)
            return 2

    print(f"bench: bogus agent='{args.bogus_agent}', runs={args.runs}\n")

    print("warmup (1 run each, discarded)")
    run_once(cli_script, args.bogus_agent)
    run_once(bridge_script, args.bogus_agent)
    print()

    cli_samples = [run_once(cli_script, args.bogus_agent) for _ in range(args.runs)]
    bridge_samples = [run_once(bridge_script, args.bogus_agent) for _ in range(args.runs)]

    summarise("openclaw CLI", cli_samples)
    summarise("bridge (WS)", bridge_samples)

    cli_med = statistics.median(cli_samples)
    bridge_med = statistics.median(bridge_samples)
    if bridge_med > 0:
        speedup = cli_med / bridge_med
        savings_ms = (cli_med - bridge_med) * 1000
        print(f"\nspeedup: {speedup:.1f}x  (saves ~{savings_ms:.0f}ms per wake)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
