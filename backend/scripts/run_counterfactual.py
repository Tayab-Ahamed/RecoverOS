#!/usr/bin/env python3
"""Price every governed constraint by counterfactual replay.

Usage:
    python -m scripts.run_counterfactual --events 2000 --seed 42

Runs the learning planner repeatedly over one dataset, changing only the policy
ruleset, and reports what each loosening would buy and what it would cost. Every
variant is audited against the governed ruleset, so a loosened variant cannot
become compliant by lowering its own bar.

The row that matters is marginal revenue per additional customer contact. A
variant that recovers more money purely by contacting more people is not an
improvement, and this column is what makes that visible.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.evaluation.counterfactual import sweep  # noqa: E402
from app.evaluation.generator import generate  # noqa: E402

OUT_DIR = pathlib.Path(__file__).resolve().parents[2] / "evaluation" / "runs"


def main() -> int:
    parser = argparse.ArgumentParser(description="RecoverOS counterfactual policy sweep")
    parser.add_argument("--events", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--profile", default="benchmark")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    started = time.time()
    dataset = generate(n_events=args.events, seed=args.seed, profile=args.profile)
    result = sweep(dataset)
    report = result.to_dict()
    report["wall_clock_seconds"] = round(time.time() - started, 3)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = (
        pathlib.Path(args.out)
        if args.out
        else OUT_DIR / f"counterfactual_{args.seed}_{args.events}.json"
    )
    out.write_text(json.dumps(report, indent=2) + "\n")

    print(f"\n=== RecoverOS counterfactual policy sweep: {dataset.run_id} ===")
    print(f"SYNTHETIC DATA  seed={args.seed}  events={args.events}")
    print("only the policy varies; planner, dataset, world and seed are fixed")
    print(f"wall clock: {report['wall_clock_seconds']}s\n")

    row = "{:<20} {:>14} {:>10} {:>9} {:>11} {:>11}"
    print(
        row.format(
            "variant", "recovered Rs", "contacts", "viol.", "dRs", "dRs/contact"
        )
    )
    print("-" * 80)
    for variant in report["variants"]:
        marginal = variant["marginal_revenue_per_contact_rupees"]
        print(
            row.format(
                variant["variant"][:20],
                variant["recovered_revenue_rupees"],
                str(variant["contacts_made"]),
                str(variant["policy_violations"]),
                f"{variant['revenue_delta_rupees']:+.2f}"
                if not variant["is_baseline"]
                else "-",
                "-" if marginal is None else f"{marginal:.2f}",
            )
        )
    print("-" * 80)

    print("\nverdicts:")
    for variant in report["variants"]:
        flag = "" if variant["legal"] else "  [NOT LEGALLY AVAILABLE]"
        if variant["defence_in_depth"]:
            flag += "  [enforced outside policy too]"
        print(f"  {variant['variant']}{flag}")
        print(f"      Q: {variant['question']}")
        print(f"      -> {variant['verdict']}")

    print(f"\nartifact: {out}")

    # --- self-checks on the sweep itself ---------------------------------
    #
    # A table of clean rows proves nothing unless the auditor can detect a dirty
    # one. These three checks make the sweep falsifiable rather than decorative.

    baseline = next((v for v in report["variants"] if v["is_baseline"]), None)
    if baseline is not None and baseline["policy_violations"] != 0:
        print("\nFAIL: the governed baseline violated its own policy.")
        return 1

    # 1. The invariant auditor must be awake. At least one deliberately loosened
    #    variant has to come back dirty, or every "zero violations" claim in
    #    this repository is unfalsifiable.
    loosened = [
        v
        for v in report["variants"]
        if not v["is_baseline"] and not v["defence_in_depth"]
    ]
    if loosened and not any(v["policy_violations"] > 0 for v in loosened):
        print(
            "\nFAIL: no loosened variant produced a single violation. The "
            "invariant auditor is not detecting breaches, so the clean rows "
            "above are meaningless."
        )
        return 1

    # 2. Defence-in-depth constraints must hold when their policy rule alone is
    #    disabled. If one starts moving contacts, redundant enforcement has
    #    collapsed to a single boolean.
    for variant in report["variants"]:
        if variant["defence_in_depth"] and variant["contacts_delta"] != 0:
            print(
                f"\nFAIL: {variant['variant']} is supposed to be enforced in "
                f"more than one place, but disabling its policy rule moved "
                f"{variant['contacts_delta']:+d} customer contacts."
            )
            return 1

    print(
        "\nPASS: governed baseline clean; auditor demonstrably live on loosened "
        "variants; defence-in-depth constraints held."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
