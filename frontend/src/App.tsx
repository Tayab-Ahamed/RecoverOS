import { useCallback, useEffect, useState } from "react"
import { api } from "./api"
import { ApprovalQueue } from "./components/ApprovalQueue"
import { CaseDetail } from "./components/CaseDetail"
import { MetricsBar } from "./components/MetricsBar"
import { ProvenanceBanner } from "./components/ProvenanceBanner"
import { StateBadge } from "./components/StateBadge"
import type { Case, Metrics } from "./types"

export function App() {
  const [metrics, setMetrics] = useState<Metrics | null>(null)
  const [cases, setCases] = useState<Case[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async () => {
    try {
      const [m, c] = await Promise.all([api.metrics(), api.cases()])
      setMetrics(m)
      setCases(c.results)
      setError(null)
    } catch (e) {
      setError((e as Error).message)
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const runDemo = async () => {
    setBusy(true)
    try {
      await api.seed()
      await api.run()
      await refresh()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="app">
      <header>
        <div>
          <h1>RecoverOS</h1>
          <p className="dim">
            AI proposes. Deterministic software authorizes. The provider
            executes. Webhooks verify.
          </p>
        </div>
        <div className="actions">
          <button disabled={busy} onClick={runDemo}>
            {busy ? "Running\u2026" : "Seed and run"}
          </button>
          <button onClick={refresh}>Refresh</button>
        </div>
      </header>

      {metrics && <ProvenanceBanner provenance={metrics.data_provenance} />}
      {error && <div className="error">{error}</div>}
      {metrics && <MetricsBar metrics={metrics} />}

      <ApprovalQueue onChange={refresh} />

      <table className="cases">
        <thead>
          <tr>
            <th>At risk</th>
            <th>Recovered</th>
            <th>State</th>
            <th>Reason</th>
            <th>Attempts</th>
            <th>Contacts</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {cases.map((c) => (
            <tr key={c.id}>
              <td>{c.revenue_at_risk.display}</td>
              <td className={c.recovered_amount ? "green" : "dim"}>
                {c.recovered_amount?.display ?? "\u2014"}
              </td>
              <td>
                <StateBadge state={c.state} />
              </td>
              <td className="mono dim">{c.event.reason}</td>
              <td>{c.attempts}</td>
              <td>{c.contacts_made}</td>
              <td>
                <button onClick={() => setSelected(c.id)}>Audit</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {cases.length === 0 && (
        <p className="dim">
          No cases yet. Use \u201cSeed and run\u201d to load a labelled synthetic
          dataset.
        </p>
      )}

      {selected && (
        <CaseDetail caseId={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  )
}
