import type { Case } from "../types"

const stateClass: Record<string, string> = {
  RECOVERED: "reclaimed",
  ESCALATED: "handoff",
  INELIGIBLE: "silent",
  AWAITING_PAYMENT: "inflight",
  AWAITING_APPROVAL: "hold",
}



export function MissionCanvas({ cases, selectedId, onSelect }: { cases: Case[]; selectedId: string | null; onSelect: (id: string) => void }) {
  const visible = cases.slice(0, 10)
  return (
    <section className="mission-panel">
      <div className="mission-heading">
        <div><div className="section-kicker">RECOVERY WINDOW / BATCH 07</div><h2>Revenue River</h2><p>Watch money move from a weak signal to a verified outcome.</p></div>
        <div className="window-clock"><span className="clock-dot" /><strong>08:47</strong><small>window remaining</small></div>
      </div>
      <div className="river-stage">
        <div className="river-labels">
          <span>SIGNAL</span>
          <span>DIAGNOSIS</span>
          <span>PROPOSAL</span>
          <span>POLICY</span>
          <span>PROOF</span>
        </div>
        <div className="river-list">
          {visible.map((item) => {
            const selected = selectedId === item.id
            const proposalText = item.plan?.intervention ? item.plan.intervention.replaceAll("_", " ") : (item.diagnosis ? "PLANNED" : "DETECTED")
            const policyText = item.state === "INELIGIBLE" ? "OPT-OUT" : (item.state === "AWAITING_APPROVAL" ? "HOLD / REVIEW" : "ALLOWED (v1)")
            return (
              <button
                key={item.id}
                type="button"
                className={`river-case ${stateClass[item.state] ?? "inflight"} ${selected ? "selected" : ""}`}
                onClick={() => onSelect(item.id)}
                aria-label={`Focus ${item.revenue_at_risk.display} ${item.state} signal`}
              >
                <span className="col-signal">
                  <strong>{item.revenue_at_risk.display}</strong>
                  <small className="col-case-id">{item.id.slice(-8)}</small>
                </span>
                <span className="col-diag">{item.event.reason.replaceAll("_", " ")}</span>
                <span className="col-prop">{proposalText}</span>
                <span className="col-policy">{policyText}</span>
                <span className="col-proof">
                  <em className={`stage-badge ${stateClass[item.state] ?? "inflight"}`}>{item.state.replaceAll("_", " ")}</em>
                </span>
              </button>
            )
          })}
        </div>
      </div>
      <div className="river-footer"><span><i className="legend-dot mint" />verified capture</span><span><i className="legend-dot blue" />active recovery</span><span><i className="legend-dot amber" />human hold</span><span><i className="legend-dot coral" />stop / handoff</span><strong>click any capsule to focus</strong></div>
    </section>
  )
}
