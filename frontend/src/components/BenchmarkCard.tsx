import type { BenchmarkReport } from "../types"

function pct(value: number) {
  return `${(value * 100).toFixed(1)}%`
}

function rupeesFromPaise(value: number) {
  return `Rs ${(value / 100).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`
}

/**
 * Visual bar comparing recovery rates for the three arms.
 * The widths are relative to the max rate so one bar always fills the width.
 */
function RecoveryRateBars({ report }: { report: BenchmarkReport }) {
  const arms = [
    { label: 'Adaptive agent', rate: report.adaptive_agent.recovery_rate, color: '#16a34a', revenue: report.adaptive_agent.recovered_revenue_rupees, violations: report.adaptive_agent.policy_violations },
    { label: 'Fixed baseline', rate: report.fixed_baseline.recovery_rate, color: '#3395ff', revenue: report.fixed_baseline.recovered_revenue_rupees, violations: report.fixed_baseline.policy_violations },
    { label: 'Ungoverned (risk)', rate: report.ungoverned.recovery_rate, color: '#dc2626', revenue: report.ungoverned.recovered_revenue_rupees, violations: report.ungoverned.policy_violations },
  ]
  const maxRate = Math.max(...arms.map(a => a.rate))
  return (
    <div className="recovery-bar-chart">
      <div className="bar-chart-title">Recovery rate by arm</div>
      {arms.map(arm => (
        <div key={arm.label} className="bar-chart-row">
          <div className="bar-chart-label">{arm.label}</div>
          <div className="bar-chart-track">
            <div
              className="bar-chart-fill"
              style={{
                width: `${maxRate > 0 ? (arm.rate / maxRate) * 100 : 0}%`,
                background: arm.color,
                boxShadow: `0 0 12px ${arm.color}55`,
              }}
            />
          </div>
          <div className="bar-chart-value" style={{ color: arm.color }}>{pct(arm.rate)}</div>
          <div className="bar-chart-meta">{arm.revenue} · {arm.violations === 0 ? <span className="bc-safe">0 violations</span> : <span className="bc-risk">{arm.violations} violations</span>}</div>
        </div>
      ))}
    </div>
  )
}

export function BenchmarkCard({
  report,
  loading,
  onRun,
  events = 200,
  seed = 42,
  onEventsChange,
  onSeedChange,
}: {
  report: BenchmarkReport | null
  loading: boolean
  onRun: () => void
  events?: number
  seed?: number
  onEventsChange?: (v: number) => void
  onSeedChange?: (v: number) => void
}) {
  return (
    <section className="panel benchmark-card">
      <div className="benchmark-head">
        <div>
          <div className="section-kicker">PROOF OF AI VALUE</div>
          <h2>Adaptive recovery, measured</h2>
          <p className="panel-copy">Same synthetic batch. Same policy gate. The only difference is how the intervention is proposed.</p>
        </div>
        <div className="benchmark-controls">
          <div className="benchmark-param-row">
            <label htmlFor="bm-events" className="benchmark-param-label">Events</label>
            <input
              id="bm-events"
              type="number"
              className="benchmark-param-input"
              value={events}
              min={10}
              max={2000}
              onChange={e => onEventsChange?.(Number(e.target.value))}
              disabled={loading}
            />
          </div>
          <div className="benchmark-param-row">
            <label htmlFor="bm-seed" className="benchmark-param-label">Seed</label>
            <input
              id="bm-seed"
              type="number"
              className="benchmark-param-input"
              value={seed}
              min={0}
              max={9999}
              onChange={e => onSeedChange?.(Number(e.target.value))}
              disabled={loading}
            />
          </div>
          <button className="secondary" disabled={loading} onClick={onRun}>{loading ? "Evaluating…" : "Run evaluation"}</button>
        </div>
      </div>
      {!report ? (
        <div className="benchmark-empty">Run the evaluation to compare the adaptive agent with a fixed payment-link baseline. Configure events and seed above to control the synthetic dataset.</div>
      ) : (
        <>
          <div className="proof-banner"><strong>{report.headline.label}</strong><span>{report.headline.message}</span><em>Seed {report.dataset.seed} · {report.dataset.events.toLocaleString()} cases</em></div>
          <div className="benchmark-grid">
            <div className="benchmark-stat"><span>Adaptive recovery</span><strong>{pct(report.adaptive_agent.recovery_rate)}</strong><small>{report.adaptive_agent.recovered_revenue_rupees} recovered</small></div>
            <div className="benchmark-stat accent"><span>Adaptive lift</span><strong>{report.ai_lift.recovery_rate_delta >= 0 ? "+" : ""}{pct(report.ai_lift.recovery_rate_delta)}</strong><small>{rupeesFromPaise(report.ai_lift.recovered_revenue_delta_paise)} vs baseline</small></div>
            <div className="benchmark-stat"><span>Recovery per contact</span><strong>{rupeesFromPaise(report.adaptive_agent.recovery_per_contact_paise)}</strong><small>adaptive agent</small></div>
            <div className="benchmark-stat safe"><span>Policy violations</span><strong>{report.adaptive_agent.policy_violations}</strong><small>adaptive + baseline both gated</small></div>
          </div>

          {/* Visual bar chart comparing the 3 arms */}
          <RecoveryRateBars report={report} />

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
