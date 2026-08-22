import type { Case, Metrics } from "../types"

type Agent = { id: string; label: string; icon: string; tone: string; description: string; count: number; status: string; action: string }

export function AgentFleet({ cases, metrics, running, onRun, onFocus }: { cases: Case[]; metrics: Metrics; running: boolean; onRun: () => void; onFocus: (id: string) => void }) {
  const verified = cases.filter((item) => item.evidence?.captured).length
  const diagnosed = cases.filter((item) => item.diagnosis).length
  const proposed = cases.filter((item) => item.plan).length
  const highSignal = cases.find((item) => item.state === "ESCALATED") ?? cases.find((item) => item.plan) ?? cases[0]
  const liveModel = cases.some((item) => item.diagnosis?.is_llm_output || item.plan?.is_llm_output)
  const agents: Agent[] = [
    { id: "sentinel", label: "REVENUE_SENTINEL", icon: "01", tone: "blue", description: "Detects drift before it becomes a missed invoice.", count: cases.length, status: running ? "scanning" : "watching", action: `${cases.length} signals in field` },
    { id: "diagnosis", label: "DIAGNOSIS_AGENT", icon: "02", tone: "violet", description: "Turns payment failure into a calibrated hypothesis.", count: diagnosed, status: running ? "reasoning" : liveModel ? "model active" : "fallback sealed", action: `${diagnosed} hypotheses sealed` },
    { id: "strategist", label: "STRATEGIST_AGENT", icon: "03", tone: "amber", description: "Chooses the smallest useful recovery intervention.", count: proposed, status: running ? "planning" : liveModel ? "model active" : "planner sealed", action: `${proposed} bounded proposals` },
    { id: "verifier", label: "OUTCOME_VERIFIER", icon: "04", tone: "mint", description: "Refuses to call it recovered without provider proof.", count: verified, status: running ? "verifying" : "sealed", action: `${verified} captures verified` },
  ]
  const feed = cases.slice(0, 5).map((item) => {
    const actor = item.state === "RECOVERED" ? "OUTCOME_VERIFIER" : item.state === "ESCALATED" ? "STRATEGIST_AGENT" : item.state === "INELIGIBLE" ? "DIAGNOSIS_AGENT" : "REVENUE_SENTINEL"
    const message = item.state === "RECOVERED" ? `sealed ${item.recovered_amount?.display ?? item.revenue_at_risk.display} capture proof` : item.state === "ESCALATED" ? "selected human handoff at attempt ceiling" : item.state === "INELIGIBLE" ? "stopped before contact on consent boundary" : `flagged ${item.event.reason.replaceAll("_", " ").toLowerCase()} drift`
    return { item, actor, message }
  })
  return <section className="agent-command-deck">
    <div className="deck-heading"><div><div className="micro-label">AI & AGENTIC CONTROL PLANE / {liveModel ? "MODEL ACTIVE" : "EXPLAINABLE FALLBACK"}</div><h2>Four minds. One bounded loop.</h2><p>These are the agents actually moving the case—not a chat window pretending to be an operator.</p></div><button className="agent-run-button" onClick={onRun} disabled={running}><span className="run-orbit">↻</span>{running ? "Agent loop running…" : "Run autonomous loop"}</button></div>
    <div className="agent-fleet-grid">{agents.map((agent) => <button key={agent.id} className={`agent-card ${agent.tone}`} onClick={() => highSignal && onFocus(highSignal.id)}><div className="agent-card-top"><span className="agent-index">{agent.icon}</span><span className="agent-status"><i /> {agent.status}</span></div><strong>{agent.label}</strong><p>{agent.description}</p><div className="agent-card-foot"><span>{agent.action}</span><b>{agent.count}</b></div></button>)}</div>
    <div className="agent-deck-bottom"><div className="agent-progress"><div className="progress-head"><span>AGENTIC EXECUTION TRACE</span><strong>{running ? "LIVE" : "LAST RUN / 12:10:16"}</strong></div><div className="agent-progress-line"><span className="progress-fill" style={{ width: `${Math.max(12, Math.round((verified / Math.max(1, metrics.cases)) * 100))}%` }} /></div><div className="progress-steps"><span className="done">detect</span><span className="done">diagnose</span><span className="done">propose</span><span className="done">authorize</span><span className={verified ? "done" : "open"}>verify</span></div></div><div className="agent-feed"><div className="feed-head"><span>LIVE AGENT BROADCAST</span><small>derived from audit events</small></div>{feed.map(({ item, actor, message }) => <button key={item.id} onClick={() => onFocus(item.id)}><i className={item.state === "RECOVERED" ? "mint" : item.state === "ESCALATED" ? "coral" : "blue"} /><span><b>{actor}</b> {message}</span><em>{item.revenue_at_risk.display}</em></button>)}</div></div>
  </section>
}
