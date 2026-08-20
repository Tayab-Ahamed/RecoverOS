# RecoverOS

**A governed autonomous revenue recovery system for failed payments.**

When a payment fails, revenue is at risk and someone has to decide what to do
about it. RecoverOS decides and acts on its own — but every action it takes must
be authorized by deterministic policy first, and no recovery is ever recorded as
successful unless the payment provider independently confirms the money arrived.

> **AI proposes. Deterministic software authorizes. The provider executes.
> Webhooks verify.**

The interesting engineering problem here is not making an agent act. It is
making an agent that acts on money **provably unable** to act outside its
mandate.

---

## Prove it in 60 seconds

No installs. No Docker. No network. No API keys. The entire recovery loop is
standard-library Python.

```bash
cd backend
python3 -m scripts.verify --quick
```

That runs static verification, 100 tests, a narrated 4-scenario demo, and a
2,000-case benchmark with a full invariant audit. Drop `--quick` for the real
10,000-case run.

Or run the pieces individually:

```bash
python3 -m scripts.static_check                            # imports, boundaries, money hygiene
python3 -m unittest discover -s tests -t . -q              # 100 tests
python3 -m scripts.demo                                    # narrated walkthrough
python3 -m scripts.run_benchmark --events 10000 --seed 42  # governed vs ungoverned
```

Requires Python 3.12 or 3.13. Both are covered in CI.

---

## What governance actually costs

The benchmark runs the same 10,000 synthetic at-risk payments twice: once
through the full policy engine, once with governance removed and everything
else identical.

| | Governed | Ungoverned |
| --- | --- | --- |
| Revenue at risk | Rs 2,97,16,216 | Rs 2,97,16,216 |
| Recovered | Rs 2,34,10,077 | Rs 2,82,39,080 |
| Recovery rate | 81.83% | 98.71% |
| Customer contacts | 13,796 | 21,540 |
| Stopped by policy | 115 | 0 |
| Escalated to a human | 2,132 | 0 |
| Audit records | 168,028 | 224,242 |
| **Policy violations** | **0** | **4,490** |

Removing the policy engine recovers about **Rs 48 lakh more** — by contacting
customers who opted out, exceeding attempt ceilings, and making 7,744 extra
contacts. It also commits 4,490 violations that would be indefensible in an
audit or a regulatory conversation.

Governance costs roughly 17 percentage points of recovery rate. That is the
price of a system you can actually deploy against real customers, and RecoverOS
treats it as the product rather than as overhead.

> **On reading these numbers correctly:** this is a deterministic synthetic
> benchmark against a mock provider, seeded and reproducible. It is **not a
> prediction of production recovery rate**, and it must not be quoted as one.
> What it demonstrates is that the control system holds at batch scale: zero
> invariant violations across 168,028 audit records. Same seed, same numbers,
> byte for byte — asserted by a test.

---

## The loop

```
DETECT  -> DIAGNOSE -> DECIDE -> GOVERN -> ACT -> VERIFY -> RECOVER
                                    |                 |
                                 refuse           STOP / RETRY / ESCALATE
```

| Stage | Component | Deterministic? |
| --- | --- | --- |
| Detect | `app/detection` | Yes |
| Diagnose | Diagnosis agent | Reasoning |
| Decide | Strategist agent | Reasoning |
| Govern | Policy engine | **Yes** |
| Act | Executor | Yes |
| Verify | Outcome verifier | Yes |

The two reasoning agents produce *proposals*. They cannot reach a payment
provider and they cannot mark their own work successful.

## Three structural guarantees

Not conventions — each is enforced in code and covered by tests.

**1. Reasoning cannot reach a provider.** `app.agents`, `app.detection` and
`app.policies` are forbidden from importing any provider module. Only the
executor may call one. Enforced by `import-linter` in CI *and* by
`scripts/static_check.py`, which parses the AST and needs nothing installed —
because a safety claim you can only check when the network is up is not a safety
claim.

**2. The executor refuses unauthorized work.** `RecoveryExecutor.execute()`
refuses unless the policy decision allows it *and* the case is in state
`APPROVED`. There is no path from proposal to provider call that skips the
policy engine. `PLANNED -> EXECUTING` and `POLICY_CHECK -> EXECUTING` are
tested as forbidden transitions.

**3. The actor cannot declare its own success.** `CaseState.RECOVERED` is
writable only by `Actor.OUTCOME_VERIFIER`, which transitions only on a
signature-verified webhook carrying a **captured** payment. `payment.authorized`
is explicitly not recovery — authorized money is not captured money. A database
CHECK constraint mirrors this: a `RECOVERED` row with no payment evidence cannot
exist.

## Five invariants

1. No case reaches `RECOVERED` without verified captured payment evidence.
2. No action executes without policy authorization.
3. No case exceeds its attempt or contact ceiling.
4. No opted-out customer is ever contacted.
5. Every financial or state transition has an audit record.

The benchmark re-derives all five from the audit log after every run and fails
loudly on violation.

---

## The demo, in three beats

`python3 -m scripts.demo`

| | Scenario | Outcome |
| --- | --- | --- |
| **A** | Rs 8,499, card expired | Payment link, payment confirmed by webhook → `RECOVERED` |
| **B** | Rs 4,999, card declined | Attempt ceiling reached → `ESCALATED`, not abandoned |
| **C** | Rs 1,299, customer opted out | `INELIGIBLE`, **zero provider calls** |
| **D** | Rs 75,000, high value | Holds at `AWAITING_APPROVAL`, no self-approval |

Scenario C is the one that matters. Recoverable revenue is deliberately left on
the table, before a plan is even proposed, and the audit trail proves no contact
was attempted. **An AI that cannot be told no is not deployable in payments.**

Together: it can act, it knows when not to act, and it knows when a human must
decide.

---

## Verification status

Honesty about what has actually been run matters more than a green badge.

| Area | Status |
| --- | --- |
| Domain, money, state machine | Executed, tested |
| Detection, policy engine | Executed, tested |
| Executor, verifier, orchestrator | Executed, tested |
| Webhook signature and replay handling | Executed, tested |
| 10,000-case benchmark and invariant audit | Executed, reproducible |
| Architectural boundaries | Statically verified |
| FastAPI HTTP layer | **Written, never executed** |
| SQLAlchemy models, Alembic migration | **Written, never executed** |
| Redis, Docker Compose, React UI | **Written, never executed** |
| Razorpay Test Mode, live calls | **Never exercised** |

The build environment had no package index, so anything requiring a third-party
dependency could not be run. That is a real limitation, and one of those
unexecuted modules did ship with a defect that no test could have caught — which
is exactly why `scripts/static_check.py` now parses every module and verifies
that every import resolves, without importing anything.

**Expect to fix something on first `docker compose up`.** The verified core is
the part that decides and moves money.

---

## Full stack

```bash
cp .env.example .env
docker compose up --build
```

Backend on `:8000`, frontend on `:5173`, Postgres, Redis, migrations on boot.
Defaults use the deterministic mock provider and mock reasoning client, so this
runs with no credentials at all.

For a real Razorpay Test Mode recovery, follow **[docs/RAZORPAY_TESTMODE.md](docs/RAZORPAY_TESTMODE.md)**.

## Layout

```
backend/app/
  domain/         Money, 17-state machine, entities — pure, zero dependencies
  detection/      deterministic risk scoring
  agents/         diagnosis + strategist (propose only)
  policies/       policy engine, versioned and checksummed
  services/       orchestrator, executor, verifier, state machine, approvals
  integrations/   provider protocol, Razorpay adapter, deterministic mock
  webhooks/       signature verification, durable event identity
  evaluation/     dataset generator + governed vs ungoverned harness
  api/            FastAPI surface (unexecuted)
  models/         SQLAlchemy tables (unexecuted)
backend/tests/    100 tests, standard library only
backend/scripts/  verify, static_check, demo, run_benchmark
frontend/         React + TypeScript + Vite
docs/             architecture, API, decisions, plan, demo, Razorpay runbook
```

## Docs

| | |
| --- | --- |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Layering, guarantees, state machine |
| [API.md](docs/API.md) | Endpoint reference |
| [RAZORPAY_TESTMODE.md](docs/RAZORPAY_TESTMODE.md) | Phase 3b runbook |
| [IMPLEMENTATION_DECISIONS.md](docs/IMPLEMENTATION_DECISIONS.md) | D1–D13, including every bug found in review |
| [IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) | Phase status |
| [DEMO.md](docs/DEMO.md) | Presenter script |

`IMPLEMENTATION_DECISIONS.md` records deviations and defects rather than hiding
them — including a reproducibility bug where payment outcomes were seeded on
random case IDs, a silent revenue loss where policy denial dropped outstanding
money without escalation, and a webhook replay key derived from `hash()`, which
is randomized per process and so would not have survived a restart.

## Configuration

All configuration is environment variables, validated at startup with fail-fast
errors. See `.env.example`. Production config **refuses to boot** with a mock
provider, a JWT secret under 32 characters, a placeholder secret, or local
webhook replay enabled.

Policy defaults: 3 attempts max, 2 contacts max, Rs 100 minimum recovery value,
10% maximum discount, Rs 50,000 manual review threshold. Policy versions are
checksummed and every decision records the version that authorized it.

## Data provenance

Every record is labelled `SYNTHETIC` or `LIVE_TEST_MODE`, the two are never
mixed in one run, and the UI shows a red banner if mixing is ever detected.
Simulated results must never be readable as real ones.

---

## License

MIT. See [LICENSE](LICENSE).
