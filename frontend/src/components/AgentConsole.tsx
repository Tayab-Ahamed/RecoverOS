import type { Case } from "../types"

function compactState(state: string) { return state.replaceAll("_", " ") }

export function AgentConsole({ selected, onInspect }: { selected: Case | null; onInspect: () => void }) {
  if (!selected) return <aside className="agent-console empty-console"><div className="section-kicker">DECISION THEATRE</div><div className="console-orb">?</div><h2>Select a signal</h2><p>The Focus Capsule will show the agent's evidence, proposed move, and policy boundary here.</p></aside>
  const diagnosis = selected.diagnosis
  const plan = selected.plan
  const isVerified = selected.state === "RECOVERED"
  const isStopped = selected.state === "INELIGIBLE" || selected.state === "ESCALATED"
  return <aside className={`agent-console ${isVerified ? "verified-console" : isStopped ? "stopped-console" : ""}`}>
    <div className="console-top"><div><div className="section-kicker">FOCUS CAPSULE / {selected.id.slice(-8)}</div><h2>{selected.revenue_at_risk.display} <span>at risk</span></h2></div><div className={`console-state ${isVerified ? "mint" : isStopped ? "coral" : "blue"}`}>{compactState(selected.state)}</div></div>
    <div className="console-reason"><span>TRIGGER</span><strong>{selected.event.reason.replaceAll("_", " ")}</strong><small>{selected.event.type.replaceAll("_", " ")}</small></div>
    <div className="agent-voice"><div className="voice-mark">AI</div><div><div className="voice-label">AGENT READOUT</div><p>{diagnosis?.rationale ?? "The agent is waiting for enough evidence to make a bounded proposal."}</p></div></div>
    <div className="console-stat-grid"><div><span>prior probability</span><strong>{Math.round((diagnosis?.recovery_probability ?? 0) * 100)}%</strong></div><div><span>expected value</span><strong>{plan?.expected_recovery_value?.display ?? "—"}</strong></div><div><span>contact budget</span><strong>{selected.contacts_made}/3</strong></div></div>
    <div className="decision-theatre"><div className="theatre-title"><span>DECISION THEATRE</span><small>evidence → restraint → proof</small></div><div className="theatre-step done"><i>01</i><div><strong>Diagnose</strong><span>{diagnosis?.cause?.replaceAll("_", " ") ?? "pending"}</span></div><b>sealed</b></div><div className="theatre-step active"><i>02</i><div><strong>Propose</strong><span>{plan?.intervention?.replaceAll("_", " ") ?? "no plan"}</span></div><b>{plan?.is_llm_output ? "model" : "planner"}</b></div><div className={`theatre-step ${isVerified ? "done" : "active"}`}><i>03</i><div><strong>{isStopped ? "Restraint" : "Authorize"}</strong><span>{isStopped ? (selected.state === "INELIGIBLE" ? "no contact" : "human handoff") : "policy gate"}</span></div><b>{isStopped ? "blocked" : "allowed"}</b></div><div className={`theatre-step ${isVerified ? "done" : ""}`}><i>04</i><div><strong>Verify</strong><span>{selected.evidence?.captured ? "signed capture" : "awaiting proof"}</span></div><b>{isVerified ? "proven" : "open"}</b></div></div>
    <div className="console-bottom"><span>{plan ? `why this move: ${plan.rationale}` : "why no move: consent or recovery probability blocked the path"}</span><button className="console-inspect" onClick={onInspect}>Open full ledger ↗</button></div>
  </aside>
}
