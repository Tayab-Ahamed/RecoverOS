import type { Case } from "../types"

const stateClass: Record<string, string> = {
  RECOVERED: "reclaimed",
  ESCALATED: "handoff",
  INELIGIBLE: "silent",
  AWAITING_PAYMENT: "inflight",
  AWAITING_APPROVAL: "hold",
}

const stageFor = (item: Case) => {
  if (item.state === "RECOVERED") return 5
  if (item.state === "ESCALATED") return 4
  if (item.state === "INELIGIBLE") return 2
  if (item.state === "AWAITING_APPROVAL") return 3
  return Math.min(3, Math.max(1, item.attempts + 1))
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
        <div className="river-labels"><span>SIGNAL</span><span>DIAGNOSIS</span><span>PROPOSAL</span><span>POLICY</span><span>PROOF</span></div>
        <div className="river-grid" />
        <div className="river-spine"><span /><span /><span /><span /><span /></div>
        <div className="river-current" />
        {visible.map((item, index) => {
          const lane = index < 5 ? 0 : 1
          const top = 15 + (index % 5) * 18
          const left = lane === 0 ? 4 : 47
          const stage = stageFor(item)
          const selected = selectedId === item.id
          return <button key={item.id} className={`river-case ${stateClass[item.state] ?? "inflight"} ${selected ? "selected" : ""}`} style={{ top: `${top}%`, left: `${left}%` }} onClick={() => onSelect(item.id)} aria-label={`Focus ${item.revenue_at_risk.display} ${item.state} signal`}><span className="river-connector" style={{ width: `${stage * 17}%` }} /><span className="river-node"><i /></span><strong>{item.revenue_at_risk.display}</strong><small>{item.event.reason.replaceAll("_", " ")}</small><em>{item.state.replaceAll("_", " ")}</em></button>
        })}
        <div className="river-core"><span>VERIFIED</span><strong>{cases.filter((item) => item.state === "RECOVERED").length}</strong><small>signals closed</small></div>
      </div>
      <div className="river-footer"><span><i className="legend-dot mint" />verified capture</span><span><i className="legend-dot blue" />active recovery</span><span><i className="legend-dot amber" />human hold</span><span><i className="legend-dot coral" />stop / handoff</span><strong>click any capsule to focus</strong></div>
    </section>
  )
}
