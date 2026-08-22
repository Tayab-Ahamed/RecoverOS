"""One command that proves everything provable without a network.

Runs, in order: static verification, the test suite, the narrated demo, and the
10,000-event benchmark. Any failure stops the run with a non-zero exit code.

    python3 -m scripts.verify            # full, ~2 minutes
    python3 -m scripts.verify --quick    # 2,000 events instead of 10,000
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time


def run(label: str, args: list[str]) -> float:
    print(f"\n{'=' * 74}\n{label}\n{'=' * 74}", flush=True)
    started = time.time()
    result = subprocess.run([sys.executable, *args])
    elapsed = time.time() - started
    if result.returncode != 0:
        print(f"\nFAILED: {label} (exit {result.returncode}) after {elapsed:.1f}s")
        raise SystemExit(result.returncode)
    print(f"\npassed in {elapsed:.1f}s", flush=True)
    return elapsed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    parsed = parser.parse_args()
    events = 2000 if parsed.quick else 10000

    total = 0.0
    total += run("1/5  static verification", ["-m", "scripts.static_check"])
    total += run(
        "2/5  test suite",
        ["-m", "unittest", "discover", "-s", "tests", "-t", ".", "-q"],
    )
    total += run("3/5  narrated demo", ["-m", "scripts.demo"])
    total += run(
        f"4/5  benchmark ({events:,} events)",
        ["-m", "scripts.run_benchmark", "--events", str(events), "--seed", "42"],
    )
    total += run(
        "5/5  paired LLM shadow evaluation (120 events)",
        ["-m", "scripts.run_shadow_eval", "--events", "120", "--seed", "42"],
    )

    print(f"\n{'=' * 74}")
    print(f"ALL OFFLINE VERIFICATION PASSED in {total:.1f}s")
    print("AI proposes. Deterministic software authorizes.")
    print("The provider executes. Webhooks verify.")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
