const BASE = import.meta.env.VITE_API_BASE ?? ""
const V1 = `${BASE}/api/v1`

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  })
  if (!response.ok) {
    // The backend returns a safe shaped error; surface its code, not a stack.
    const body = await response.json().catch(() => null)
    throw new Error(body?.error?.message ?? `Request failed (${response.status})`)
  }
  return response.json() as Promise<T>
}

export const api = {
  metrics: () => request<import("./types").Metrics>(`${V1}/metrics`),

  benchmark: (events = 200, seed = 42) =>
    request<import("./types").BenchmarkReport>(`${V1}/benchmark?events=${events}&seed=${seed}`),

  agents: () => request<import("./types").AgentState>(`${V1}/agents`),

  shadowEval: (events = 120, seed = 42) =>
    request<import("./types").ShadowReport>(`${V1}/agents/shadow-eval?events=${events}&seed=${seed}`),

  cases: (state?: string) =>
    request<{ total: number; results: import("./types").Case[] }>(
      `${V1}/cases${state ? `?state=${encodeURIComponent(state)}` : ""}`,
    ),

  caseDetail: (id: string) =>
    request<{
      case: import("./types").Case
      audit_trail: import("./types").AuditRecord[]
    }>(`${V1}/cases/${id}`),

  pendingApprovals: () =>
    request<{
      total: number
      total_value_paise: number
      results: import("./types").Case[]
    }>(`${V1}/approvals`),

  approve: (id: string, approver: string) =>
    request(`${V1}/approvals/${id}/approve`, {
      method: "POST",
      body: JSON.stringify({ approver }),
    }),

  deny: (id: string, approver: string, reason: string) =>
    request(`${V1}/approvals/${id}/deny`, {
      method: "POST",
      body: JSON.stringify({ approver, reason }),
    }),

  seed: (events = 40, seed = 7) =>
    request(`${V1}/demo/seed`, {
      method: "POST",
      body: JSON.stringify({ events, seed }),
    }),

  run: (limit = 25) =>
    request(`${V1}/demo/run`, {
      method: "POST",
      body: JSON.stringify({ limit }),
    }),

  replayWebhook: (caseId: string, paid: boolean | null = null) =>
    request(`${V1}/demo/replay-webhook`, {
      method: "POST",
      body: JSON.stringify({ case_id: caseId, paid }),
    }),

  reset: () => request(`${V1}/demo/reset`, { method: "POST" }),
}
