import { useEffect, useState } from "react"
import { api } from "../api"
import type { AuditRecord, Case } from "../types"
import { AuditTrail } from "./AuditTrail"
import { StateBadge } from "./StateBadge"

export function CaseDetail({ caseId, onClose }: { caseId: string; onClose: () => void }) {
  const [detail, setDetail] = useState<{ case: Case; audit_trail: AuditRecord[] } | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.caseDetail(caseId).then(setDetail).catch((e) => setError(e.message))
  }, [caseId])

  if (error) return <div className="drawer error">{error}</div>
  if (!detail) return <div className="drawer">Loading…</div>

  const c = detail.case
  const diagnosis = c.diagnosis
  const plan = c.plan

  return (
    <div className="drawer">
      <div className="drawer-header">
        <div><h2>{c.revenue_at_risk.display} at risk</h2><div className="mono dim">{c.id}</div></div>
        <div><StateBadge state={c.state} /><button onClick={onClose}>Close</button></div>
      </div>

      <section>
        <div className="section-kicker">01 / DIAGNOSE</div>
        <h3>Why this revenue is at risk</h3>
        {diagnosis ? <>
          <p>{diagnosis.rationale}</p>
          <div className="decision-meta">cause <strong>{diagnosis.cause}</strong> · prior <strong>{(diagnosis.recovery_probability * 100).toFixed(0)}%</strong> · confidence <strong>{(diagnosis.confidence * 100).toFixed(0)}%</strong></div>
          <div className="evidence-list">{diagnosis.evidence.map((item) => <span key={item}>{item}</span>)}</div>
          {diagnosis.risk_factors.length > 0 && <div className="risk-list"><span className="risk-label">Risk signals</span>{diagnosis.risk_factors.map((item) => <span key={item}>{item}</span>)}</div>}
          <div className="dim mono">by {diagnosis.produced_by} · {diagnosis.is_llm_output ? "model-generated" : "deterministic fallback"}</div>
        </> : <p className="dim">Not yet diagnosed.</p>}
      </section>

      <section>
        <div className="section-kicker">02 / PROPOSE</div>
        <h3>What the agent chose</h3>
        {plan ? <>
          <p><strong>{plan.intervention}</strong> — {plan.rationale}</p>
          <div className="decision-meta">expected recoverable value <strong>{plan.expected_recovery_value?.display ?? "—"}</strong> · confidence <strong>{(plan.confidence * 100).toFixed(0)}%</strong> · discount <strong>{plan.discount_percentage}%</strong></div>
          <div className="evidence-list">{plan.evidence.map((item) => <span key={item}>{item}</span>)}</div>
          <div className="alternatives"><span className="risk-label">Alternatives considered</span>{plan.alternatives_considered.map((item) => <span key={item}>{item}</span>)}</div>
          <div className="dim mono">proposed by {plan.produced_by} · {plan.is_llm_output ? "validated model output" : "evidence-backed planner"} · proposal only, not authorization</div>
        </> : <p className="dim">No plan proposed.</p>}
      </section>

      <section>
        <div className="section-kicker">03 / VERIFY</div>
        <h3>Proof of recovery</h3>
        {c.evidence ? <div className="evidence"><div><strong>{c.evidence.amount.display}</strong> captured</div><div className="mono dim">payment {c.evidence.payment_id} · via {c.evidence.event_type} · verified {new Date(c.evidence.verified_at).toLocaleString()}</div></div> : <p className="dim">No verified payment. This case is not counted as recovered.</p>}
      </section>

      <section><h3>Audit trail ({detail.audit_trail.length} records)</h3><AuditTrail records={detail.audit_trail} /></section>
    </div>
  )
}
