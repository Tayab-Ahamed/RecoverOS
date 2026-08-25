import { useEffect, useState } from "react"
import { api } from "../api"
import type { AuditRecord, Case } from "../types"
import { StateBadge } from "./StateBadge"

/**
 * Maps actor names to a short 2-letter initials and a colour tone,
 * used in the timeline circle.
 */
function actorMeta(actor: string): { initials: string; tone: string } {
  if (actor.includes('VERIF')) return { initials: 'OV', tone: 'mint' }
  if (actor.includes('STRAT')) return { initials: 'SA', tone: 'amber' }
  if (actor.includes('DIAGN')) return { initials: 'DA', tone: 'violet' }
  if (actor.includes('SENTINEL') || actor.includes('REVENUE')) return { initials: 'RS', tone: 'blue' }
  if (actor.includes('POLICY')) return { initials: 'PG', tone: 'coral' }
  if (actor.includes('HUMAN') || actor.includes('OPERATOR')) return { initials: 'OP', tone: 'amber' }
  if (actor.includes('WEBHOOK') || actor.includes('PROVIDER')) return { initials: 'WH', tone: 'mint' }
  const words = actor.split(/[\s_]+/)
  return { initials: words.slice(0, 2).map(w => w[0]).join('').toUpperCase(), tone: 'blue' }
}

/**
 * Formats a raw evidence string (e.g. key=val) into a clean structured chip
 */
function formatEvidenceTag(item: string) {
  if (item.includes('=')) {
    const [k, ...rest] = item.split('=')
    const v = rest.join('=')
    return (
      <span key={item} className="meta-tag">
        <b className="tag-key">{k}</b>
        <span className="tag-val">{v}</span>
      </span>
    )
  }
  return <span key={item} className="meta-tag plain">{item}</span>
}

/**
 * Timeline-style audit trail. Each step has a coloured actor circle, the
 * action name, a state-transition arrow, and a policy version badge.
 */
function AuditTimeline({ records }: { records: AuditRecord[] }) {
  if (records.length === 0) {
    return <p className="dim">No audit records yet.</p>
  }
  return (
    <div className="audit-timeline">
      {records.map((r, idx) => {
        const { initials, tone } = actorMeta(r.actor)
        const isLast = idx === records.length - 1
        return (
          <div key={r.id} className={`audit-step ${isLast ? 'audit-step-last' : ''}`}>
            {!isLast && <div className="audit-step-line" />}
            <div className={`audit-actor-circle tone-${tone}`}>{initials}</div>
            <div className="audit-step-body">
              <div className="audit-step-header">
                <span className="audit-action mono">{r.action}</span>
                {r.from_state && r.to_state && (
                  <span className="audit-transition">
                    <span className="audit-state-from">{r.from_state.replaceAll('_', ' ')}</span>
                    <span className="audit-arrow">→</span>
                    <span className="audit-state-to">{r.to_state.replaceAll('_', ' ')}</span>
                  </span>
                )}
                {r.policy_version_id && (
                  <span className="audit-policy-badge">policy {r.policy_version_id}</span>
                )}
              </div>
              <div className="audit-step-detail">{r.detail}</div>
              <div className="audit-step-meta">
                <span className="audit-actor-name">{r.actor}</span>
                <span className="audit-timestamp mono dim">{new Date(r.at).toLocaleTimeString()}</span>
                {r.decision_id && <span className="audit-decision-id mono dim">decision/{r.decision_id.slice(-8)}</span>}
                {r.external_event_id && <span className="audit-event-id mono dim">event/{r.external_event_id.slice(-8)}</span>}
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}

export function CaseDetail({ caseId, onClose }: { caseId: string; onClose: () => void }) {
  const [detail, setDetail] = useState<{ case: Case; audit_trail: AuditRecord[] } | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.caseDetail(caseId).then(setDetail).catch((e) => setError(e.message))
  }, [caseId])

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <div className="drawer" onClick={(e) => e.stopPropagation()}>
        {error && (
          <div className="drawer-error">
            <div className="error-icon">⚠</div>
            <h3>Failed to load case</h3>
            <p>{error}</p>
            <button className="ghost-button" onClick={onClose}>Close</button>
          </div>
        )}

        {!detail && !error && (
          <div className="drawer-loading">
            <div className="drawer-spinner" />
            <span>Loading case details…</span>
          </div>
        )}

        {detail && (
          <>
            <div className="drawer-header">
              <div className="drawer-header-title">
                <div className="section-kicker">CASE INSPECTION / {detail.case.id.slice(-8)}</div>
                <h2>{detail.case.revenue_at_risk.display} <span className="dim-sub">at risk</span></h2>
                <div className="drawer-case-hash mono dim">{detail.case.id}</div>
              </div>
              <div className="drawer-header-actions">
                <StateBadge state={detail.case.state} />
                <button className="drawer-close-btn" onClick={onClose} aria-label="Close drawer">✕</button>
              </div>
            </div>

            <div className="drawer-content">
              {/* Section 1: Diagnose */}
              <section className="drawer-card">
                <div className="drawer-card-head">
                  <span className="section-kicker">01 / DIAGNOSE</span>
                  <h3>Why this revenue is at risk</h3>
                </div>
                {detail.case.diagnosis ? (
                  <div className="drawer-card-body">
                    <p className="drawer-rationale">{detail.case.diagnosis.rationale}</p>
                    
                    <div className="drawer-meta-bar">
                      <div className="meta-pill">
                        <span className="meta-pill-label">CAUSE</span>
                        <strong className="meta-pill-val">{detail.case.diagnosis.cause.replaceAll('_', ' ')}</strong>
                      </div>
                      <div className="meta-pill">
                        <span className="meta-pill-label">PRIOR PROBABILITY</span>
                        <strong className="meta-pill-val">{(detail.case.diagnosis.recovery_probability * 100).toFixed(0)}%</strong>
                      </div>
                      <div className="meta-pill">
                        <span className="meta-pill-label">CONFIDENCE</span>
                        <strong className="meta-pill-val">{(detail.case.diagnosis.confidence * 100).toFixed(0)}%</strong>
                      </div>
                    </div>

                    <div className="drawer-tags-group">
                      <div className="tags-title">EVIDENCE SIGNALS</div>
                      <div className="meta-tags-cloud">
                        {detail.case.diagnosis.evidence.map(formatEvidenceTag)}
                      </div>
                    </div>

                    {detail.case.diagnosis.risk_factors.length > 0 && (
                      <div className="drawer-tags-group">
                        <div className="tags-title">RISK SIGNALS</div>
                        <div className="meta-tags-cloud">
                          {detail.case.diagnosis.risk_factors.map((item) => (
                            <span key={item} className="meta-tag risk">{item}</span>
                          ))}
                        </div>
                      </div>
                    )}

                    <div className="drawer-attribution mono dim">
                      sealed by <strong>{detail.case.diagnosis.produced_by}</strong> · {detail.case.diagnosis.is_llm_output ? "model-generated" : "deterministic fallback"}
                    </div>
                  </div>
                ) : (
                  <p className="dim">Not yet diagnosed.</p>
                )}
              </section>

              {/* Section 2: Propose */}
              <section className="drawer-card">
                <div className="drawer-card-head">
                  <span className="section-kicker">02 / PROPOSE</span>
                  <h3>What the agent chose</h3>
                </div>
                {detail.case.plan ? (
                  <div className="drawer-card-body">
                    <div className="drawer-intervention-badge">
                      <strong>{detail.case.plan.intervention.replaceAll('_', ' ')}</strong>
                      <span>— {detail.case.plan.rationale}</span>
                    </div>

                    <div className="drawer-meta-bar">
                      <div className="meta-pill">
                        <span className="meta-pill-label">EXPECTED VALUE</span>
                        <strong className="meta-pill-val">{detail.case.plan.expected_recovery_value?.display ?? "—"}</strong>
                      </div>
                      <div className="meta-pill">
                        <span className="meta-pill-label">CONFIDENCE</span>
                        <strong className="meta-pill-val">{(detail.case.plan.confidence * 100).toFixed(0)}%</strong>
                      </div>
                      <div className="meta-pill">
                        <span className="meta-pill-label">DISCOUNT</span>
                        <strong className="meta-pill-val">{detail.case.plan.discount_percentage}%</strong>
                      </div>
                    </div>

                    <div className="drawer-tags-group">
                      <div className="tags-title">BANDIT & POLICY EVIDENCE</div>
                      <div className="meta-tags-cloud">
                        {detail.case.plan.evidence.map(formatEvidenceTag)}
                      </div>
                    </div>

                    {detail.case.plan.alternatives_considered.length > 0 && (
                      <div className="drawer-tags-group">
                        <div className="tags-title">ALTERNATIVES CONSIDERED</div>
                        <div className="meta-tags-cloud">
                          {detail.case.plan.alternatives_considered.map((item) => (
                            <span key={item} className="meta-tag alt">{item}</span>
                          ))}
                        </div>
                      </div>
                    )}

                    <div className="drawer-attribution mono dim">
                      proposed by <strong>{detail.case.plan.produced_by}</strong> · {detail.case.plan.is_llm_output ? "validated model output" : "evidence-backed planner"} · proposal only, not authorization
                    </div>
                  </div>
                ) : (
                  <p className="dim">No plan proposed.</p>
                )}
              </section>

              {/* Section 3: Verify */}
              <section className="drawer-card">
                <div className="drawer-card-head">
                  <span className="section-kicker">03 / VERIFY</span>
                  <h3>Proof of recovery</h3>
                </div>
                <div className="drawer-card-body">
                  {detail.case.evidence ? (
                    <div className="drawer-proof-box verified">
                      <div className="proof-status-row">
                        <div className="proof-icon">✓</div>
                        <div>
                          <strong>{detail.case.evidence.amount.display} captured</strong>
                          <div className="mono dim">Verified via Razorpay webhook signature</div>
                        </div>
                      </div>
                      <div className="proof-meta-grid">
                        <div><span>PAYMENT ID</span><strong className="mono">{detail.case.evidence.payment_id}</strong></div>
                        <div><span>EVENT TYPE</span><strong className="mono">{detail.case.evidence.event_type}</strong></div>
                        <div><span>VERIFIED AT</span><strong className="mono">{new Date(detail.case.evidence.verified_at).toLocaleString()}</strong></div>
                      </div>
                    </div>
                  ) : (
                    <div className="drawer-proof-box unverified">
                      <div className="proof-status-row">
                        <div className="proof-icon dim">⏳</div>
                        <div>
                          <strong>No verified payment proof</strong>
                          <div className="dim">This case is not counted as recovered without a signed provider event.</div>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              </section>

              {/* Section 4: Audit Trail */}
              <section className="drawer-card">
                <div className="drawer-card-head">
                  <span className="section-kicker">IMMUTABLE LOG</span>
                  <h3>Audit trail ({detail.audit_trail.length} records)</h3>
                </div>
                <div className="drawer-card-body">
                  <AuditTimeline records={detail.audit_trail} />
                </div>
              </section>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
