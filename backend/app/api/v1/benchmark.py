"""Reviewer-facing, labelled synthetic evaluation endpoint."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import get_container
from app.evaluation.generator import generate
from app.evaluation.harness import compare

router = APIRouter(prefix="/benchmark", tags=["benchmark"])


@router.get("")
def benchmark(
    events: int = Query(default=200, ge=40, le=2_000),
    seed: int = Query(default=42, ge=0, le=999_999),
) -> dict:
    """Run an explicitly synthetic benchmark with adaptive and baseline arms."""
    if get_container().settings.is_production:
        raise HTTPException(404, "not found")
    dataset = generate(n_events=events, seed=seed, profile="dashboard_benchmark")
    report = compare(dataset)
    report["headline"] = {
        "label": "SYNTHETIC EVALUATION DATA",
        "message": "Adaptive planning is compared with a fixed payment-link baseline under the same policy.",
        "not_production_claim": True,
    }
    return report
