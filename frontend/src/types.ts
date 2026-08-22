export type Money = { paise: number; display: string; currency: string }

export type Diagnosis = {
  cause: string
  recovery_probability: number
  rationale: string
  produced_by: string
  is_llm_output: boolean
  confidence: number
  evidence: string[]
  risk_factors: string[]
}

export type Plan = {
  intervention: string
  discount_percentage: number
  rationale: string
  produced_by: string
  is_llm_output: boolean
  confidence: number
  evidence: string[]
  alternatives_considered: string[]
  expected_recovery_value: Money | null
}

export type Evidence = {
  payment_id: string
  event_id: string
  amount: Money
  captured: boolean
  verified_at: string
  event_type: string
}

export type Case = {
  id: string
  customer_id: string
  state: string
  provenance: string
  revenue_at_risk: Money
  recovered_amount: Money | null
  attempts: number
  contacts_made: number
  external_link_id: string | null
  event: {
    id: string
    type: string
    reason: string
    amount: Money
    occurred_at: string
  }
  diagnosis: Diagnosis | null
  plan: Plan | null
  evidence: Evidence | null
}

export type AuditRecord = {
  id: string
  case_id: string
  actor: string
  action: string
  from_state: string | null
  to_state: string | null
  detail: string
  at: string
  policy_version_id: string | null
  decision_id: string | null
  external_event_id: string | null
}

export type Metrics = {
  cases: number
  revenue_at_risk: Money
  eligible_revenue: Money
  recovered_revenue: Money
  recovery_rate: number
  cases_by_state: Record<string, number>
  data_provenance: Record<string, number>
  audit_records: number
  policy_version: string
  policy_checksum: string
}

export type BenchmarkArm = {
  strategy: string
  cases: number
  recovered_revenue_rupees: string
  recovery_rate: number
  recovered_cases: number
  contacts_made: number
  recovery_per_contact_paise: number
  policy_violations: number
  strategy_mix: Record<string, number>
  adaptive_explanations: number
}

export type ShadowReport = {
  events: number
  seed: string
  decisions_compared: number
  agreement_rate: number
  model_changed_action: number
  influence_rate: number
  guardrail_catch_rate: number | null
  parse_failure_rate: number
  headline?: { label: string; message: string; not_production_claim: boolean }
}

export type AgentState = {
  strategy: string
  llm_provider: string
  learning_enabled: boolean
  data_provenance: string
  snapshot: {
    agent?: string
    llm_provider?: string
    stats?: Record<string, number | Record<string, number>>
    bandit?: { decisions?: number; explorations?: number; exploration_rate?: number; segments_learned?: number; total_observations?: number }
    propensity?: { updates?: number; mean_correction?: number; max_correction?: number }
    memory?: { outcomes?: number; segments?: number }
    critic?: { reviews?: number; interventions?: number }
  }
}

export type BenchmarkReport = {
  dataset: {
    run_id: string
    seed: number
    events: number
    customers: number
    provenance: string
    profile: string
  }
  adaptive_agent: BenchmarkArm
  fixed_baseline: BenchmarkArm
  ungoverned: BenchmarkArm
  learning?: BenchmarkArm
  oracle?: BenchmarkArm
  learning_llm?: BenchmarkArm
  learning_lift?: {
    recovered_revenue_delta_paise: number
    recovery_rate_delta: number
    contacts_delta: number
    recovery_per_contact_delta_paise: number
    optimal_action_rate_delta?: number
    mean_regret_delta_paise?: number
    brier_skill_score_vs_rules?: number
    interpretation: string
  }
  ai_lift: {
    recovered_revenue_delta_paise: number
    recovery_rate_delta: number
    contacts_delta: number
    recovery_per_contact_delta_paise: number
    interpretation: string
  }
  headline: {
    label: string
    message: string
    not_production_claim: boolean
  }
}
