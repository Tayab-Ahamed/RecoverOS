#!/usr/bin/env python3
"""Run the benchmark and write a labelled result artifact.

Usage:
    python -m scripts.run_benchmark --events 10000 --seed 42

Every artifact records the seed, the dataset run id and the data provenance so
that any number quoted from it can be reproduced or challenged.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.evaluation.generator import generate  # noqa: E402
from app.evaluation.harness import compare  # noqa: E402

OUT_DIR = pathlib.Path(__file__).resolve().parents[2] / "evaluation" / "runs"


def main() -> int:
    parser = argparse.ArgumentParser(description="RecoverOS benchmark")
    parser.add_argument("--events", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--profile", default="benchmark")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    started = time.time()
    dataset = generate(n_events=args.events, seed=args.seed, profile=args.profile)
    report = compare(dataset)
    elapsed = round(time.time() - started, 3)
    report["data_label"] = "SYNTHETIC EVALUATION DATA"
    report["disclaimer"] = (
        "Recovery outcomes are produced by a seeded simulation whose conversion "
        "priors were chosen by the authors. These numbers demonstrate that the "
        "control system behaves correctly at batch scale. They are NOT a "
        "prediction of real-world recovery rates."
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = pathlib.Path(args.out) if args.out else OUT_DIR / f"{dataset.run_id}.json"
    out.write_text(json.dumps(report, indent=2) + "\n")

    g, b, u = report["governed"], report["fixed_baseline"], report["ungoverned"]
    print(f"\n=== RecoverOS benchmark: {dataset.run_id} ===")
    print(f"SYNTHETIC EVALUATION DATA  seed={args.seed}  events={args.events}")
    print(f"wall clock: {elapsed}s\n")
    row = "{:<26} {:>18} {:>18}"
    print(row.format("metric", "adaptive", "fixed baseline"))
    print("-" * 64)
    for key, label in [
        ("cases", "cases"),
        ("revenue_at_risk_rupees", "revenue at risk (Rs)"),
        ("recovered_revenue_rupees", "recovered (Rs)"),
        ("recovery_rate", "recovery rate"),
        ("recovered_cases", "recovered cases"),
        ("contacts_made", "customer contacts"),
        ("provider_calls", "provider calls"),
        ("denied_cases", "stopped by policy"),
        ("escalated_cases", "escalated"),
        ("audit_records", "audit records"),
        ("policy_violations", "POLICY VIOLATIONS"),
    ]:
        print(row.format(label, str(g[key]), str(b[key])))
    print("-" * 64)
    lift = report["ai_lift"]
    print(
        "\nAdaptive planner vs fixed baseline: "
        f"{lift['recovered_revenue_delta_paise'] / 100:.2f} Rs recovered delta, "
        f"{lift['contacts_delta']} contacts delta, "
        f"{lift['recovery_per_contact_delta_paise'] / 100:.2f} Rs/contact delta"
    )
    print(f"\nartifact: {out}")

    if g["policy_violations"] != 0 or b["policy_violations"] != 0:
        print("\nFAIL: the governed run violated policy. This is a hard failure.")
        return 1
    print("\nPASS: governed run completed with zero policy violations.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
