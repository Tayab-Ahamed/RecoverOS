import { useEffect, useState } from "react"
import { api } from "../api"
import type { Case } from "../types"

export function ApprovalQueue({ onChange }: { onChange: () => void }) {
  const [pending, setPending] = useState<Case[]>([])
  const [busy, setBusy] = useState<string | null>(null)

  const load = () => api.pendingApprovals().then((r) => setPending(r.results))
  useEffect(() => {
    load()
  }, [])

  const act = async (id: string, approve: boolean) => {
    setBusy(id)
    try {
      if (approve) await api.approve(id, "operator")
      else await api.deny(id, "operator", "declined in review")
      await load()
      onChange()
    } finally {
      setBusy(null)
    }
  }

  if (pending.length === 0) return null

  return (
    <div className="approvals">
      <h3>Awaiting human approval ({pending.length})</h3>
      <p className="dim">
        These cases are above the manual review threshold. The system will not
        act on them until a person decides.
      </p>
      {pending.map((c) => (
        <div key={c.id} className="approval-row">
          <span>
            <strong>{c.revenue_at_risk.display}</strong>{" "}
            <span className="mono dim">{c.event.reason}</span>
          </span>
          <span>
            <button disabled={busy === c.id} onClick={() => act(c.id, true)}>
              Approve
            </button>
            <button
              className="danger"
              disabled={busy === c.id}
              onClick={() => act(c.id, false)}
            >
              Deny
            </button>
          </span>
        </div>
      ))}
    </div>
  )
}
