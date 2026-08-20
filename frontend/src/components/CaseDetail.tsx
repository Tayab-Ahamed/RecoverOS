import { useEffect, useState } from "react"
import { api } from "../api"
import type { AuditRecord, Case } from "../types"
import { AuditTrail } from "./AuditTrail"
import { StateBadge } from "./StateBadge"

export function CaseDetail({ caseId, onClose }: { caseId: string; onClose: () => void }) {
  const [detail, setDetail] = useState<{
    case: Case
    audit_trail: AuditRecord[]
  } | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.caseDetail(caseId).then(setDetail).catch((e) => setError(e.message))
  }, [caseId])

  if (error) return <div className="drawer error">{error}</div>
  if (!detail) return <div className="drawer">Loading\u2026</div>

  const c = detail.case

  return (
    <div className="drawer">
      <div className="drawer-header">
        <div>
          <h2>{c.revenue_at_risk.display} at risk</h2>
          <div className="mono dim">{c.id}</div>
        </div>
        <div>
          <StateBadge state={c.state} />
          <button onClick={onClose}>Close</button>
        </div>
      </div>

      <section>
        <h3>Why it failed</h3>
        {c.diagnosis ? (
          <>
            <p>{c.diagnosis.rationale}</p>
            <div className="dim mono">
              cause {c.diagnosis.cause} \u00b7 recovery prior{" "}
              {(c.diagnosis.recovery_probability * 100).toFixed(0)}% \u00b7 by{" "}
              {c.diagnosis.produced_by} \u00b7{" "}
              {c.diagnosis.is_llm_output ? "model-generated" : "rule-based"}
            </div>
          </>
        ) : (
          <p className="dim">Not yet diagnosed.</p>
        )}
      </section>

      <section>
        <h3>What was proposed</h3>
        {c.plan ? (
          <>
            <p>
              <strong>{c.plan.intervention}</strong> \u2014 {c.plan.rationale}
            </p>
            <div className="dim mono">
              proposed by {c.plan.produced_by} \u00b7 discount{" "}
              {c.plan.discount_percentage}% \u00b7 a proposal only, not an
              authorization
            </div>
          </>
        ) : (
          <p className="dim">No plan proposed.</p>
        )}
      </section>

      <section>
        <h3>Proof of recovery</h3>
        {c.evidence ? (
          <div className="evidence">
            <div>
              <strong>{c.evidence.amount.display}</strong> captured
            </div>
            <div className="mono dim">
              payment {c.evidence.payment_id} \u00b7 via {c.evidence.event_type} \u00b7
              verified {new Date(c.evidence.verified_at).toLocaleString()}
            </div>
          </div>
        ) : (
          <p className="dim">
            No verified payment. This case is not counted as recovered.
          </p>
        )}
      </section>

      <section>
        <h3>Audit trail ({detail.audit_trail.length} records)</h3>
        <AuditTrail records={detail.audit_trail} />
      </section>
    </div>
  )
}
