import type { Metrics } from "../types"

export function MetricsBar({ metrics }: { metrics: Metrics }) {
  return (
    <div className="metrics">
      <Metric label="Revenue at risk" value={metrics.revenue_at_risk.display} />
      <Metric
        label="Recovered (verified)"
        value={metrics.recovered_revenue.display}
        accent
      />
      <Metric
        label="Recovery rate"
        value={`${(metrics.recovery_rate * 100).toFixed(1)}%`}
      />
      <Metric label="Cases" value={String(metrics.cases)} />
      <Metric label="Audit records" value={String(metrics.audit_records)} />
      <Metric label="Policy" value={metrics.policy_version} />
    </div>
  )
}

function Metric({
  label,
  value,
  accent,
}: {
  label: string
  value: string
  accent?: boolean
}) {
  return (
    <div className={`metric ${accent ? "accent" : ""}`}>
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
    </div>
  )
}
