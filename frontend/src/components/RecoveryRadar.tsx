import type { Case } from "../types"

const stateClass: Record<string, string> = {
  RECOVERED: "recovered",
  AWAITING_PAYMENT: "awaiting",
  AWAITING_APPROVAL: "approval",
  ESCALATED: "escalated",
  INELIGIBLE: "ineligible",
  STOPPED: "stopped",
}

function pointFor(item: Case, index: number) {
  const angle = ((index * 137.5) % 360) * Math.PI / 180
  const radius = 18 + ((index * 17) % 27)
  const x = 50 + Math.cos(angle) * radius
  const y = 50 + Math.sin(angle) * radius * 0.72
  const size = 12 + Math.min(12, Math.max(0, Math.log10(Math.max(item.revenue_at_risk.paise, 1)) - 4) * 4)
  return { left: `${x}%`, top: `${y}%`, size: `${size}px` }
}

export function RecoveryRadar({ cases, selectedId, onSelect }: { cases: Case[]; selectedId: string | null; onSelect: (id: string) => void }) {
  const visible = cases.slice(0, 18)
  const recovered = cases.filter((item) => item.state === "RECOVERED").length
  const liveSignals = cases.filter((item) => !["RECOVERED", "INELIGIBLE"].includes(item.state)).length

  return (
    <section className="radar-panel">
      <div className="radar-heading">
        <div>
          <div className="section-kicker">LIVE REVENUE FIELD</div>
          <h2>Recovery Radar</h2>
          <p>Every dot is money in motion. Size is value at risk. Color is the current control state.</p>
        </div>
        <div className="radar-readout"><strong>{liveSignals}</strong><span>active signals</span></div>
      </div>
      <div className="radar-stage" aria-label="Interactive recovery radar">
        <div className="radar-grid" />
        <div className="radar-orbit orbit-a" /><div className="radar-orbit orbit-b" /><div className="radar-orbit orbit-c" />
        <div className="radar-sweep" />
        <div className="radar-core"><span>RECOVEROS</span><strong>{recovered}</strong><small>verified</small></div>
        {visible.map((item, index) => {
          const point = pointFor(item, index)
          const selected = selectedId === item.id
          return <button key={item.id} className={`radar-node ${stateClass[item.state] ?? "awaiting"} ${selected ? "selected" : ""}`} style={{ left: point.left, top: point.top, width: point.size, height: point.size }} onClick={() => onSelect(item.id)} aria-label={`Open ${item.revenue_at_risk.display} ${item.state} case`}><span /></button>
        })}
        <div className="radar-axis axis-x" /><div className="radar-axis axis-y" />
        <span className="radar-label label-top">HIGH URGENCY</span><span className="radar-label label-right">HIGH VALUE</span><span className="radar-label label-bottom">LOW SIGNAL</span>
      </div>
      <div className="radar-legend"><span><i className="dot recovered" />Verified</span><span><i className="dot awaiting" />Awaiting payment</span><span><i className="dot approval" />Human decision</span><span><i className="dot escalated" />Escalated</span><span className="radar-foot">Click a signal to inspect its decision ledger</span></div>
    </section>
  )
}
