import type { AgentState, Case, Metrics, ShadowReport } from "../types"

type Agent = { id: string; label: string; icon: string; tone: string; description: string; count: number; status: string; action: string }
type Props = { cases: Case[]; metrics: Metrics; running: boolean; onRun: () => void; onFocus: (id: string) => void; agentState: AgentState | null; shadowRunning: boolean; onShadowEval: () => void; shadowReport: ShadowReport | null }

export function AgentFleet({ cases, metrics, running, onRun, onFocus, agentState, shadowRunning, onShadowEval, shadowReport }: Props) {
  const verified = cases.filter((item) => item.evidence?.captured).length
  const diagnosed = cases.filter((item) => item.diagnosis).length
  const proposed = cases.filter((item) => item.plan).length
  const highSignal = cases.find((item) => item.state === "ESCALATED") ?? cases.find((item) => item.plan) ?? cases[0]
  const liveModel = cases.some((item) => item.diagnosis?.is_llm_output || item.plan?.is_llm_output)
  const bandit = agentState?.snapshot.bandit
  const memory = agentState?.snapshot.memory
  const stats = agentState?.snapshot.stats ?? {}
  const llmNarrations = typeof stats.llm_narrations === "number" ? stats.llm_narrations : 0
  const guardrailBlocks = typeof stats.llm_guardrail_blocks === "number" ? stats.llm_guardrail_blocks : 0
  const outcomesLearned = typeof stats.outcomes_learned === "number" ? stats.outcomes_learned : 0
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
    <div className="deck-heading"><div><div className="micro-label">AI & AGENTIC CONTROL PLANE / {liveModel ? "MODEL ACTIVE" : "EXPLAINABLE FALLBACK"}</div><h2>Four minds. One bounded loop.</h2><p>These are the agents actually moving the case—not a chat window pretending to be an operator.</p></div><div className="deck-actions"><button className="agent-run-button" onClick={onShadowEval} disabled={shadowRunning}><span className="run-orbit">◌</span>{shadowRunning ? "Shadow audit running…" : "Run shadow audit"}</button><button className="agent-run-button primary-agent-action" onClick={onRun} disabled={running}><span className="run-orbit">↻</span>{running ? "Agent loop running…" : "Run autonomous loop"}</button></div></div>
    <div className="agent-fleet-grid">{agents.map((agent) => <button key={agent.id} className={`agent-card ${agent.tone}`} onClick={() => highSignal && onFocus(highSignal.id)}><div className="agent-card-top"><span className="agent-index">{agent.icon}</span><span className="agent-status"><i /> {agent.status}</span></div><strong>{agent.label}</strong><p>{agent.description}</p><div className="agent-card-foot"><span>{agent.action}</span><b>{agent.count}</b></div></button>)}</div>
    <div className="agent-telemetry"><span><b>{bandit?.segments_learned ?? 0}</b> learned segments</span><span><b>{bandit?.total_observations ?? outcomesLearned}</b> verified observations</span><span><b>{bandit?.exploration_rate ? `${(bandit.exploration_rate * 100).toFixed(1)}%` : "0%"}</b> exploration</span><span><b>{memory?.outcomes ?? outcomesLearned}</b> memory records</span><span><b>{llmNarrations}</b> model narrations</span><span className={guardrailBlocks ? "telemetry-alert" : ""}><b>{guardrailBlocks}</b> guardrail blocks</span></div>
    {shadowReport && <div className="shadow-proof"><div><span className="micro-label">MODEL SHADOW AUDIT / PAIRED RUN</span><strong>{(shadowReport.influence_rate * 100).toFixed(1)}% <small>model influence</small></strong></div><span><b>{shadowReport.decisions_compared}</b> paired decisions</span><span><b>{(shadowReport.agreement_rate * 100).toFixed(1)}%</b> agreement</span><span><b>{shadowReport.guardrail_catch_rate === null ? "—" : `${(shadowReport.guardrail_catch_rate * 100).toFixed(1)}%`}</b> injected faults caught</span><span><b>{(shadowReport.parse_failure_rate * 100).toFixed(1)}%</b> parse failure</span></div>}
    <div className="agent-deck-bottom"><div className="agent-progress"><div className="progress-head"><span>AGENTIC EXECUTION TRACE</span><strong>{running ? "LIVE" : "LAST VERIFIED RUN"}</strong></div><div className="agent-progress-line"><span className="progress-fill" style={{ width: `${Math.max(12, Math.round((verified / Math.max(1, metrics.cases)) * 100))}%` }} /></div><div className="progress-steps"><span className="done">detect</span><span className="done">diagnose</span><span className="done">propose</span><span className="done">authorize</span><span className={verified ? "done" : "open"}>verify</span></div></div><div className="agent-feed"><div className="feed-head"><span>LIVE AGENT BROADCAST</span><small>derived from audit events</small></div>{feed.map(({ item, actor, message }) => <button key={item.id} onClick={() => onFocus(item.id)}><i className={item.state === "RECOVERED" ? "mint" : item.state === "ESCALATED" ? "coral" : "blue"} /><span><b>{actor}</b> {message}</span><em>{item.revenue_at_risk.display}</em></button>)}</div></div>
  </section>
}
