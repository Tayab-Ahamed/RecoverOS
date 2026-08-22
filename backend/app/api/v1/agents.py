"""Reviewer-facing introspection for the agentic recovery layer."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import get_container
from app.evaluation.llm_eval import run_shadow_eval

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("")
def agent_state() -> dict:
    """Return the current process-local agent and model telemetry."""
    container = get_container()
    strategist = container.strategist
    snapshot = strategist.snapshot() if hasattr(strategist, "snapshot") else {}
    return {
        "strategy": container.settings.recovery_strategy,
        "llm_provider": getattr(container.llm, "name", "unknown"),
        "learning_enabled": container.settings.recovery_strategy == "learning",
        "data_provenance": "PROCESS_LOCAL_STATE",
        "snapshot": snapshot,
    }


@router.get("/shadow-eval")
def shadow_eval(
    events: int = Query(default=120, ge=40, le=800),
    seed: int = Query(default=42, ge=0, le=999_999),
) -> dict:
    """Measure model influence and guardrail behavior in paired synthetic shadow mode."""
    if get_container().settings.is_production:
        raise HTTPException(404, "not found")
    report = run_shadow_eval(events=events, seed="api-shadow", dataset_seed=seed)
    result = report.to_dict()
    result["headline"] = {
        "label": "SYNTHETIC SHADOW EVALUATION",
        "message": "Paired learning runs isolate what the language model changed, what it explained, and what guardrails blocked.",
        "not_production_claim": True,
    }
    return result
