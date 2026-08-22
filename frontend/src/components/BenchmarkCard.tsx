import type { BenchmarkReport } from "../types"

function pct(value: number) {
  return `${(value * 100).toFixed(1)}%`
}

function rupeesFromPaise(value: number) {
  return `Rs ${(value / 100).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`
}

export function BenchmarkCard({ report, loading, onRun }: { report: BenchmarkReport | null; loading: boolean; onRun: () => void }) {
  return (
    <section className="panel benchmark-card">
      <div className="benchmark-head">
        <div>
          <div className="section-kicker">PROOF OF AI VALUE</div>
          <h2>Adaptive recovery, measured</h2>
          <p className="panel-copy">Same synthetic batch. Same policy gate. The only difference is how the intervention is proposed.</p>
        </div>
        <button className="secondary" disabled={loading} onClick={onRun}>{loading ? "Evaluating…" : "Run evaluation"}</button>
      </div>
      {!report ? (
        <div className="benchmark-empty">Run the evaluation to compare the adaptive agent with a fixed payment-link baseline.</div>
      ) : (
        <>
          <div className="proof-banner"><strong>{report.headline.label}</strong><span>{report.headline.message}</span><em>Seed {report.dataset.seed} · {report.dataset.events.toLocaleString()} cases</em></div>
          <div className="benchmark-grid">
            <div className="benchmark-stat"><span>Adaptive recovery</span><strong>{pct(report.adaptive_agent.recovery_rate)}</strong><small>{report.adaptive_agent.recovered_revenue_rupees} recovered</small></div>
            <div className="benchmark-stat accent"><span>Adaptive lift</span><strong>{report.ai_lift.recovery_rate_delta >= 0 ? "+" : ""}{pct(report.ai_lift.recovery_rate_delta)}</strong><small>{rupeesFromPaise(report.ai_lift.recovered_revenue_delta_paise)} vs baseline</small></div>
            <div className="benchmark-stat"><span>Recovery per contact</span><strong>{rupeesFromPaise(report.adaptive_agent.recovery_per_contact_paise)}</strong><small>adaptive agent</small></div>
            <div className="benchmark-stat safe"><span>Policy violations</span><strong>{report.adaptive_agent.policy_violations}</strong><small>adaptive + baseline both gated</small></div>
          </div>
          <div className="comparison-table">
            <div className="comparison-row comparison-labels"><span>ARM</span><span>RECOVERED</span><span>RATE</span><span>CONTACTS</span><span>VIOLATIONS</span></div>
            <div className="comparison-row"><strong>Adaptive agent</strong><span>{report.adaptive_agent.recovered_revenue_rupees}</span><span>{pct(report.adaptive_agent.recovery_rate)}</span><span>{report.adaptive_agent.contacts_made}</span><span className="green">{report.adaptive_agent.policy_violations}</span></div>
            <div className="comparison-row"><strong>Fixed baseline</strong><span>{report.fixed_baseline.recovered_revenue_rupees}</span><span>{pct(report.fixed_baseline.recovery_rate)}</span><span>{report.fixed_baseline.contacts_made}</span><span className="green">{report.fixed_baseline.policy_violations}</span></div>
            <div className="comparison-row muted"><strong>Ungoverned (risk demo)</strong><span>{report.ungoverned.recovered_revenue_rupees}</span><span>{pct(report.ungoverned.recovery_rate)}</span><span>{report.ungoverned.contacts_made}</span><span className="red">{report.ungoverned.policy_violations}</span></div>
          </div>
          <p className="benchmark-footnote">This is a reproducible control-system evaluation, not a production recovery-rate claim. Live data and synthetic data are never mixed.</p>
        </>
      )}
    </section>
  )
}
