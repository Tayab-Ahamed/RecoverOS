import { useCallback, useEffect, useMemo, useState } from "react"
import { api } from "./api"
import { AgentConsole } from "./components/AgentConsole"
import { AgentFleet } from "./components/AgentFleet"
import { ApprovalQueue } from "./components/ApprovalQueue"
import { BenchmarkCard } from "./components/BenchmarkCard"
import { CaseDetail } from "./components/CaseDetail"
import { MissionCanvas } from "./components/MissionCanvas"
import { ProvenanceBanner } from "./components/ProvenanceBanner"
import { StateBadge } from "./components/StateBadge"
import type { BenchmarkReport, Case, Metrics } from "./types"

type View = "mission" | "proof" | "ledger"

export function App() {
  const [metrics, setMetrics] = useState<Metrics | null>(null)
  const [cases, setCases] = useState<Case[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [benchmark, setBenchmark] = useState<BenchmarkReport | null>(null)
  const [view, setView] = useState<View>("mission")
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [benchmarkBusy, setBenchmarkBusy] = useState(false)

  const refresh = useCallback(async () => {
    try {
      const [m, c] = await Promise.all([api.metrics(), api.cases()])
      setMetrics(m)
      setCases(c.results)
      setError(null)
    } catch (e) { setError((e as Error).message) }
  }, [])

  useEffect(() => { refresh() }, [refresh])

  const runBenchmark = async () => {
    setBenchmarkBusy(true)
    try { setBenchmark(await api.benchmark(200, 42)); setError(null) }
    catch (e) { setError((e as Error).message) }
    finally { setBenchmarkBusy(false) }
  }

  const runDemo = async () => {
    setBusy(true)
    try {
      await api.reset(); await api.seed()
      for (let cycle = 0; cycle < 4; cycle += 1) {
        await api.run(40)
        const current = await api.cases()
        const awaiting = current.results.filter((item) => item.state === "AWAITING_PAYMENT")
        if (awaiting.length === 0) break
        for (const item of awaiting) await api.replayWebhook(item.id)
      }
      await refresh(); await runBenchmark()
    } catch (e) { setError((e as Error).message) }
    finally { setBusy(false) }
  }

  const selectedCase = useMemo(() => cases.find((item) => item.id === selected) ?? cases[0] ?? null, [cases, selected])
  const drawerCase = selected ? cases.find((item) => item.id === selected) ?? null : null
  const nextSignal = cases.find((item) => item.state === "AWAITING_PAYMENT") ?? cases.find((item) => item.state === "AWAITING_APPROVAL") ?? cases.find((item) => item.state === "ESCALATED")

  const openCase = (id: string) => setSelected(id)
  const navItems: Array<[View, string, string]> = [["mission", "01", "Mission control"], ["proof", "02", "Proof lab"], ["ledger", "03", "Case ledger"]]

  return <div className="mission-shell">
    <aside className="mission-rail">
      <button className="mission-logo" onClick={() => setView("mission")} aria-label="RecoverOS mission control">R<span>↗</span></button>
      <div className="rail-spine" />
      {navItems.map(([key, number, label]) => <button key={key} className={`rail-nav ${view === key ? "active" : ""}`} onClick={() => setView(key)} aria-label={label}><span>{number}</span><i>{key === "mission" ? "◉" : key === "proof" ? "⌁" : "≡"}</i></button>)}
      <div className="rail-footer"><span className="rail-live" /><small>LOCAL<br />MOCK</small></div>
    </aside>

    <main className="mission-app">
      <header className="mission-topbar">
        <div className="brand-lockup"><div className="micro-label"><span className="live-pip" /> RECOVEROS / MERCHANT COMMAND CENTER</div><h1>Recover<span>OS</span></h1><p>The recovery layer between a failed payment and a verified comeback.</p></div>
        <div className="operator-lockup"><div className="operator-line"><span className="operator-avatar">◎</span><span>OPERATOR</span><strong>GUARDED MODE</strong></div><div className="operator-actions"><button className="ghost-button" onClick={refresh}>Sync field</button><button className="primary-button" disabled={busy} onClick={runDemo}>{busy ? "Running field…" : "Start recovery run"}</button></div></div>
      </header>

      <div className="command-nav"><div className="command-tabs">{navItems.map(([key, number, label]) => <button key={key} className={view === key ? "command-tab active" : "command-tab"} onClick={() => setView(key)}><span>{number}</span>{label}</button>)}</div><div className="command-meta">POLICY v1 <span>•</span> MOCK RAZORPAY <span>•</span> SIGNED WEBHOOKS</div></div>

      {metrics && <ProvenanceBanner provenance={metrics.data_provenance} />}
      {error && <div className="command-error">{error}</div>}
      {!metrics && !error && <section className="launch-screen"><div className="launch-orbit" /><div className="micro-label">RECOVEROS / INITIALIZING MISSION CONTROL</div><h2>Revenue does not disappear.<br /><em>It drifts.</em></h2><p>RecoverOS tracks the drift, chooses the smallest useful intervention, and counts the comeback only when the payment provider proves it.</p><button className="primary-button" disabled={busy} onClick={runDemo}>{busy ? "Initializing…" : "Initialize the field →"}</button><div className="launch-doctrine"><span>AI proposes</span><i>→</i><span>Policy decides</span><i>→</i><span>Money proves</span></div></section>}

      {metrics && <section className="revenue-pulse"><div className="pulse-stat lead"><span>RECOVERY PULSE</span><strong>{metrics.recovered_revenue.display}</strong><small>verified revenue returned to orbit</small></div><div className="pulse-stat"><span>FLOATING VALUE</span><strong>{metrics.revenue_at_risk.display}</strong><small>{metrics.cases} signals in this batch</small></div><div className="pulse-stat"><span>FIELD CONVERSION</span><strong>{(metrics.recovery_rate * 100).toFixed(1)}%</strong><small>capture-backed recovery rate</small></div><div className="pulse-stat pulse-status"><span>CONTROL STATUS</span><strong><i /> NOMINAL</strong><small>0 policy violations observed</small></div></section>}

      {metrics && view === "mission" && <>
        <div className="mission-intro"><div><div className="micro-label">BATCH 07 / LIVE RECOVERY WINDOW</div><h2>Keep the good money moving.</h2></div><div className="mission-intro-copy">A case is not a row. It is a journey with a cost, a consent boundary, and a proof state.</div></div>
        <AgentFleet cases={cases} metrics={metrics} running={busy} onRun={runDemo} onFocus={openCase} />
        <section className="mission-layout"><MissionCanvas cases={cases} selectedId={selectedCase?.id ?? null} onSelect={openCase} /><AgentConsole selected={selectedCase} onInspect={() => selectedCase && setSelected(selectedCase.id)} /></section>
        <section className="mission-bottom-grid"><div className="mission-rule"><span className="micro-label">SYSTEM PROMISE</span><h3>Never spend trust to chase a rupee.</h3><p>RecoverOS may leave money unrecovered. It will not contact an opted-out customer, exceed a retry ceiling, or claim recovery before a signed capture event.</p><div className="rule-tags"><span>consent-first</span><span>paise-safe</span><span>audit-complete</span></div></div><div className="mission-next"><span className="micro-label">NEXT OBSERVATION</span><strong>{nextSignal ? nextSignal.revenue_at_risk.display : "FIELD CLEAR"}</strong><p>{nextSignal ? `${nextSignal.state.replaceAll("_", " ")} / ${nextSignal.event.reason.replaceAll("_", " ")}` : "All current signals have reached a terminal state."}</p><button className="text-action" onClick={() => nextSignal && setSelected(nextSignal.id)}>Focus signal ↗</button></div></section>
      </>}

      {metrics && view === "proof" && <><section className="proof-hero"><div className="micro-label">PROOF LAB / CONTROLLED EXPERIMENT</div><h2>Can the agent recover more<br /><em>without becoming reckless?</em></h2><p>The same labelled cases. The same policy gate. The only variable is how the intervention is proposed.</p></section><BenchmarkCard report={benchmark} loading={benchmarkBusy} onRun={runBenchmark} /></>}

      {metrics && view === "ledger" && <><section className="ledger-hero"><div><div className="micro-label">CASE LEDGER / AUDIT SURFACE</div><h2>Every decision leaves a trace.</h2></div><p>Searchable recovery history for operators, reviewers, and the person who will ask “why did we contact them?”</p></section><ApprovalQueue onChange={refresh} /><div className="ledger-table-wrap"><table className="cases mission-cases"><thead><tr><th>Signal</th><th>Recovered</th><th>State</th><th>Cause</th><th>Attempts</th><th>Contacts</th><th /></tr></thead><tbody>{cases.map((c) => <tr key={c.id} className={selectedCase?.id === c.id ? "row-selected" : ""} onClick={() => openCase(c.id)}><td><strong>{c.revenue_at_risk.display}</strong><small className="row-id">{c.id.slice(-8)}</small></td><td className={c.recovered_amount ? "green" : "dim"}>{c.recovered_amount?.display ?? "—"}</td><td><StateBadge state={c.state} /></td><td className="mono dim">{c.event.reason}</td><td>{c.attempts}</td><td>{c.contacts_made}</td><td><button onClick={(event) => { event.stopPropagation(); openCase(c.id) }}>Inspect</button></td></tr>)}</tbody></table></div></>}

      {metrics && view !== "ledger" && <section className="ledger-preview"><div><div className="micro-label">AUDIT SURFACE</div><h3>Need the paper trail?</h3><p>Open the Case Ledger to inspect every transition, actor, policy decision, and provider event.</p></div><button className="text-action" onClick={() => setView("ledger")}>Open case ledger ↗</button></section>}
      {drawerCase && <CaseDetail caseId={drawerCase.id} onClose={() => setSelected(null)} />}
    </main>
  </div>
}
