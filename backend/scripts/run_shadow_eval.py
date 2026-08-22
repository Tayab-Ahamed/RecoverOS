"""Run the paired learning-versus-model shadow evaluation.

Usage:
    python -m scripts.run_shadow_eval --events 120 --seed 42

The default scripted client is a deterministic fault injector, not a language
model. Its purpose is to measure guardrail behavior against known injected
faults without making claims about model quality.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.evaluation.llm_eval import run_shadow_eval  # noqa: E402


OUT_DIR = pathlib.Path(__file__).resolve().parents[2] / "evaluation" / "runs"


def main() -> int:
    parser = argparse.ArgumentParser(description="RecoverOS LLM shadow evaluation")
    parser.add_argument("--events", type=int, default=120)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    started = time.time()
    report = run_shadow_eval(
        events=args.events,
        seed="cli-shadow",
        dataset_seed=args.seed,
    )
    payload = report.to_dict()
    payload["wall_clock_seconds"] = round(time.time() - started, 3)
    payload["data_label"] = "SYNTHETIC SHADOW EVALUATION"

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = pathlib.Path(args.out) if args.out else OUT_DIR / f"shadow_eval_{args.seed}_{args.events}.json"
    out.write_text(json.dumps(payload, indent=2) + "\n")

    print(f"=== RecoverOS shadow evaluation: {args.events} events, seed {args.seed} ===")
    print(f"paired decisions: {payload['decisions_compared']}")
    print(f"model agreement: {payload['agreement_rate']:.1%}")
    print(f"model influence: {payload['influence_rate']:.1%}")
    print(f"guardrail catch rate: {payload['guardrail_catch_rate']}")
    print(f"artifact: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
