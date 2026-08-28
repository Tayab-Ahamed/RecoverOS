# HTTP API

All application endpoints are under `/api/v1`. Unversioned application paths
return 404. Health checks are the deliberate exception and are served at both
the root and the versioned prefix, because probes should not have to know about
API versioning.

This surface is executed by the local TestClient contract suite and the SQL
restart check. The live Razorpay path has been confirmed in Test Mode; see
`docs/RAZORPAY_TESTMODE.md` for the redacted verification record.


## Health

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/health` | Liveness, plus version and git SHA |
| GET | `/health/db` | Real `SELECT 1` |
| GET | `/health/redis` | Real `PING` |
| GET | `/health/razorpay` | 200 or structured 503; must never fail boot |

A dependency being down returns 503 with a shaped body, not a stack trace, and
never prevents the process from starting.

## Authentication

In production, `/api/v1/*` business endpoints require an
`Authorization: Bearer <JWT>` header. Tokens use HS256 and `JWT_SECRET`, and
must include a non-empty `sub` claim. Approval audit entries use that subject
as the operator identity. Razorpay webhooks use their signature instead of a
bearer token; local demo mode remains unauthenticated.

## Cases

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/api/v1/cases` | List cases with state, amounts, attempts |
| GET | `/api/v1/cases/{id}` | One case with diagnosis, plan, evidence and PTP |
| GET | `/api/v1/cases/{id}/audit` | Full audit trail, oldest first |
| GET | `/api/v1/cases/{id}/audit.csv` | Export case audit trail as CSV |
| POST | `/api/v1/cases/{id}/ptp` | Record customer Promise-to-Pay (amount + timezone-aware due date) |
| GET | `/api/v1/cases/{id}/ptp` | Current Promise-to-Pay commitment status |

Every audit entry carries the actor, the transition, and the
`policy_version_id` and `decision_id` that authorized it. An audit line that
cannot say which policy version permitted an action is not an audit line.

## Approvals

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/api/v1/approvals` | Cases held at `AWAITING_APPROVAL` |
| POST | `/api/v1/approvals/{id}/approve` | Re-authorizes, then executes |
| POST | `/api/v1/approvals/{id}/deny` | Records the denial and reason |

Approval **re-runs the policy engine** rather than trusting the earlier
decision. Time passes between a human opening the queue and clicking approve;
ceilings and opt-out status can change in that window.

## Metrics and proof

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/api/v1/metrics` | Current dataset metrics and provenance |
| GET | `/api/v1/benchmark?events=200&seed=42` | Synthetic proof with fixed baseline, rulebook, learning, oracle, and ungoverned arms |
| GET | `/api/v1/agents` | Current agent, learning, and model telemetry snapshot |
| GET | `/api/v1/agents/shadow-eval?events=120&seed=42` | Paired synthetic LLM influence and guardrail evaluation |

Revenue at risk, recovered revenue, recovery rate, contacts, escalations and
policy violations are reported for the current dataset. The benchmark endpoint runs a fixed payment-link baseline, the original rulebook, the outcome-aware learning strategist, an oracle upper-bound policy, and an ungoverned comparison over the same labelled synthetic batch. It reports recovery per contact, optimal-action rate, regret, calibration, and the learning lift relative to the rulebook; the results are synthetic and the endpoint is unavailable in production. The agent snapshot exposes the contextual learner's posterior cells, verified-outcome memory, propensity calibration, critic statistics, and LLM telemetry. The shadow evaluator pairs a learning run with a model-in-loop run over the same dataset and reports action influence, rationale quality, and catch rate against known scripted faults; it is also unavailable in production.

## Webhooks

| Method | Path |
| --- | --- |
| POST | `/api/webhooks/razorpay` |

Processing order, all of which must pass:

1. HMAC-SHA256 over the **raw request body** against
   `X-Razorpay-Signature`. Parsing before verifying would mean acting on
   unauthenticated input.
2. Replay protection keyed on the provider event id. In production a missing id
   is rejected as malformed; outside production a `body:sha256:...` digest may
   be derived for the local replay path (see D11).
3. Case resolution via `reference_id`, falling back to `payment.notes`.
4. Outcome verification. `payment_link.paid` and `payment.captured` are
   recovery. `payment.authorized` is not.

Unknown event types are acknowledged and ignored rather than erroring, so
Razorpay does not retry something we deliberately do not handle.

## Demo

| Method | Path | Notes |
| --- | --- | --- |
| POST | `/api/v1/demo/reset` | Clear in-memory state |
| POST | `/api/v1/demo/seed` | Load the synthetic demo dataset |
| POST | `/api/v1/demo/run` | Advance all cases through the loop |
| POST | `/api/v1/demo/replay-webhook` | Locally signed webhook replay |
| POST | `/api/v1/demo/live-test-case` | One labelled Razorpay Test Mode case; refuses mock mode |

`RECOVERY_STRATEGY=learning` enables the outcome-aware contextual strategist in the main API; `RECOVERY_STRATEGY=rules` selects the original rulebook baseline. The default local strategy is `learning`, while all model and learning state remains bounded and proposal-only.

Replay is gated behind `ENABLE_LOCAL_WEBHOOK_REPLAY` and the production config
guard refuses to boot with it enabled.

## Errors

```json
{ "error": { "code": "policy_violation", "message": "...", "request_id": "..." } }
```

Domain exceptions map to status codes centrally in `app/core/errors.py`.
Messages are drawn from a fixed safe set; exception text is never echoed to a
client. `request_id` propagates from the request through every JSON log line.
