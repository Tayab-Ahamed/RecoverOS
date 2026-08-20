import type { AuditRecord } from "../types"

/**
 * The audit trail is a first-class product surface, not a debug view. Each row
 * shows who acted, what changed, and which policy version and decision
 * authorized it.
 */
export function AuditTrail({ records }: { records: AuditRecord[] }) {
  return (
    <table className="audit">
      <thead>
        <tr>
          <th>When</th>
          <th>Actor</th>
          <th>Action</th>
          <th>Transition</th>
          <th>Detail</th>
          <th>Authorization</th>
        </tr>
      </thead>
      <tbody>
        {records.map((r) => (
          <tr key={r.id}>
            <td className="mono dim">{new Date(r.at).toLocaleTimeString()}</td>
            <td>
              <span className="actor">{r.actor}</span>
            </td>
            <td className="mono">{r.action}</td>
            <td className="mono dim">
              {r.from_state && r.to_state ? `${r.from_state} \u2192 ${r.to_state}` : "\u2014"}
            </td>
            <td>{r.detail}</td>
            <td className="mono dim">
              {r.policy_version_id ? `policy ${r.policy_version_id}` : ""}
              {r.decision_id ? ` / ${r.decision_id}` : ""}
              {r.external_event_id ? ` / event ${r.external_event_id}` : ""}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
