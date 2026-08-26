<div align="center">

# RecoverOS

**A governed agentic control plane for revenue recovery.**

AI proposes. Deterministic policy authorizes. The provider executes. Webhooks verify.

[![CI](https://github.com/Tayab-Ahamed/RecoverOS/actions/workflows/ci.yml/badge.svg)](https://github.com/Tayab-Ahamed/RecoverOS/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-207%20passing-3fb950)](backend/tests)
[![Policy violations](https://img.shields.io/badge/policy%20violations-0%20%2F%2010%2C000%20cases-3fb950)](evaluation/runs/run_benchmark_42_10000.json)
[![Reproducible](https://img.shields.io/badge/artifacts-CI%20drift%20guarded-1f6feb)](backend/scripts/check_artifacts.py)
[![Track](https://img.shields.io/badge/Razorpay%20Buildathon-03%20AI%20Revenue%20Recovery-0f8fff)](https://razorpay.com/buildathon/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

<img src="docs/ui/pipeline.svg" alt="RecoverOS pipeline: detect, diagnose, decide, govern, act, verify" width="100%">

</div>

---

RecoverOS recovers revenue lost to failed payments, abandoned checkouts, failed
subscriptions and overdue receivables. It detects revenue at risk, diagnoses the
cause, proposes the smallest useful intervention, passes that proposal through a
deterministic policy gate, executes only what was authorized, and counts money
as recovered **only** after a signature-verified captured-payment webhook.

It is not a chatbot bolted onto a payments table. It is a bounded control system
for the window between **payment failure** and **verified comeback**.

> An agent that cannot be told *no* has no business touching payments.

---

## Contents

| Section | What it answers |
| --- | --- |
| [The claim](#the-claim) | What this system is measured on, and why not recovery rate |
| [Measured results](#measured-results) | The numbers, and how to reproduce them yourself |
| [Why the gateway insight matters](#the-insight-that-changed-the-design) | The one place reading Razorpay's docs changed the architecture |
| [Promise-to-Pay bounded grace](#promise-to-pay-bounded-grace-as-a-governed-pause) | Why waiting on customer commitments is an active policy choice |
| [Architecture](#architecture) | Trust boundaries, agents, and what each one may not do |
| [Prove it locally](#prove-it-locally) | One command, no network, no credentials |
| [Honest scope](#honest-scope) | What is real, what is simulated, what is unverified |

---

## The claim

Most recovery systems stop at a list of failed payments, or send a fixed retry
ladder to everyone. RecoverOS closes the loop while keeping the *cost* of
automation visible — because in dunning, the expensive resource is not compute,
it is customer patience.

**The headline metric here is deliberately not recovery rate.**

Recovery rate is trivially gamed by contacting more people. In this repository's
own benchmark, the deliberately ungoverned arm posts the best recovery rate on
the scoreboard — **90.35%** — by making **86,065** customer contacts and
committing **4,281 policy violations**. Any submission leading with recovery
rate is reporting a number that rewards harassment.

So the learner is scored on the two metrics that cannot be inflated by
contacting more people:

| Metric | Why it is honest |
| --- | --- |
| **Optimal-action rate** | Defined per decision against a hidden world model. Independent of luck. |
| **Regret** (money left on the table) | Cannot be reduced by contacting more people, only by choosing better. |

---

## Measured results

All figures below come from the committed artifact
[`evaluation/runs/run_benchmark_42_10000.json`](evaluation/runs/run_benchmark_42_10000.json)
— 10,000 events, seed 42. Every arm sees the same cases, the same policy gate,
and the same hidden world, with **common random numbers** so identical cases
face identical luck and any difference is attributable to the decision.

### Action quality — the claim being made

| Arm | Optimal action | Regret | Contacts | Violations |
| --- | ---: | ---: | ---: | ---: |
| **Learning planner** | **86.73%** | **₹11,73,939** | **12,458** | **0** |
| Hand-written rulebook | 69.65% | ₹16,73,979 | 13,605 | 0 |
| Fixed payment-link baseline | 61.61% | ₹20,42,304 | 13,613 | 0 |
| Oracle *(full knowledge, unachievable)* | 100% | ₹0 | 13,017 | 0 |
| Ungoverned risk demo | 37.92% | ₹22,46,280 | 86,065 | **4,281** |

**Learner versus the fixed baseline: +25.1 points of optimal action, 42.5% less
regret, and 1,155 fewer customer contacts.** More money, materially less trust
spent.

### Revenue — the supporting evidence

| Arm | Recovered | Recovery rate | Share of attainable |
| --- | ---: | ---: | ---: |
| **Learning planner** | **₹2,01,93,421.40** | 70.58% | **97.09%** |
| Hand-written rulebook | ₹2,00,44,270.35 | 70.06% | 96.37% |
| Fixed payment-link baseline | ₹1,97,81,644.00 | 69.14% | 95.11% |
| Oracle *(bounds the scoreboard)* | ₹2,07,98,709.70 | 72.70% | 100% |
| Ungoverned risk demo | ₹2,58,47,718.00 | 90.35% | — *(cheats)* |

The learner captures **97.09% of the revenue the oracle proves was attainable**.
The oracle exists precisely so that a score can be read as a fraction of what
was actually possible, rather than against 100% — which is unreachable by
construction, because payer quality is latent and conversion is probabilistic.

Note the honest detail: the learner's revenue lead over the rulebook is **thin**
— ₹1.49L on a ₹2 crore base, about 0.7%. Its real margin is in *how* it earns
that money: 17 points more optimal actions, ₹5L less regret, and 1,147 fewer
customer contacts. If revenue were the only scoreboard, the honest conclusion
would be that the rulebook is competitive. It is the contact budget that
separates them, which is exactly why the contact budget is measured.

### Reproduce every number above

```bash
cd backend
python3 -m scripts.run_benchmark --events 10000 --seed 42
python3 -m scripts.check_artifacts     # asserts committed artifacts still match code
```

`check_artifacts` re-derives every committed artifact from its own recorded seed
and diffs each metric quoted in this README. **It runs in CI.** A stale artifact
fails the build, so a published number cannot silently drift away from the code
that produced it.

<details>
<summary><b>Why that guard exists</b> (a real bug this repo shipped)</summary>

An earlier revision of this README quoted a 200-event artifact showing an 86.46%
recovery rate against a 71.17% baseline. The strategist was subsequently
rewritten; the artifact was not regenerated. Re-running the documented command
showed the headline arm was actually *losing*.

Nobody fabricated anything. The file simply went stale while the code moved. In
a project whose entire thesis is "count only what you can prove," that is the
most damaging class of bug available, so freshness is now machine-enforced
instead of asserted.

</details>

<details>
<summary><b>The reproducibility bug that invalidated an earlier version of this table</b></summary>

The numbers above are not the ones this README shipped previously, and the
reason is worth stating plainly.

`Customer.contacts_this_window` is a mutable counter, and the contact ceiling is
enforced by reading it. `run_strategy` was iterating the caller's `Customer`
objects directly, so **running an arm wrote to the dataset**. `compare()` hands
the same `Dataset` to all six arms in sequence, so every arm after the first
started life with the previous arm's contact counts already spent and was denied
contacts it should have been allowed.

Two consequences, both disqualifying for a benchmark:

1. The comparison was partly measuring **position in the `STRATEGIES` tuple**.
   Reordering the arms would have changed the headline. The `ungoverned` arm
   makes ~7× the contacts of any other, so whichever governed arm happened to
   run after it was starved.
2. Re-running a single arm on its own could not reproduce its own published
   figure — the exact failure `check_artifacts` exists to catch, hiding one
   level below where that script was looking.

The symptom that exposed it: the identical configuration, run five times in one
process, returned five different revenue figures.

The fix is one `deepcopy` in `run_strategy`, which makes it a pure function of
`(dataset, strategy, seed)`. The guard is
[`backend/tests/test_harness_isolation.py`](backend/tests/test_harness_isolation.py),
which asserts an arm's result is independent of what ran before it, that the
ungoverned arm cannot starve a later arm, and that **every** declared strategy is
order-independent.

Every artifact in `evaluation/runs/` was regenerated after this fix. At 200
events the correction actually **reversed the sign** of the published delta: the
adaptive arm had appeared to lose ₹11,244.85 to the fixed baseline, and once the
contamination was removed it wins by ₹5,756.90. The contamination had been
handicapping the very arm this project is arguing for.

</details>

<details>
<summary><b>Model-in-the-loop shadow evaluation</b> (paired, 120 events)</summary>

From [`evaluation/runs/shadow_eval_42_120.json`](evaluation/runs/shadow_eval_42_120.json):

| Question | Metric |
| --- | --- |
| Did the model change decisions? | 10.6% influence rate |
| Did it preserve the base strategy? | 89.4% agreement |
| Did it survive known unsafe outputs? | **100% guardrail catch rate** across 26 injected faults |

In that run, model narration **slightly reduced** raw recovered revenue while
reducing regret. That is reported as-is: the LLM earns its place through
explanation and a tested safety envelope, **not** through an unsupported claim
that narration recovers more money.

</details>

> **Provenance.** These are seeded synthetic results from a simulation whose
> conversion priors were chosen by the author. They demonstrate that the control
> system behaves correctly and measurably at batch scale. They are **not** a
> forecast of production recovery rates.

---

## What each safety rule actually costs

"Our agent is governed" is a claim anyone can make. The question a payments team
will actually ask is narrower and much harder: *we allow two customer contacts —
what would a third one buy, and what would it cost?*

```bash
cd backend && python3 -m scripts.run_counterfactual --events 2000 --seed 42
```

This re-runs the same dataset, same hidden world, same seed and same planner,
varying **only the policy**, and prices every constraint in rupees. Full table in
[`docs/RESULTS.md`](docs/RESULTS.md); the four findings:

| Constraint | What relaxing it buys | Verdict |
| --- | --- | --- |
| Two contacts → three | +₹4,22,379.90, and **427 violations** | Real money. Not ours to take. |
| Three attempts → four | ₹0.00 | Free to keep |
| Deeper discount ceiling | ₹0.00 | Free to keep |
| Economic floor removed | +₹346 at ₹57.67 per extra contact | Not worth it |

Two of the four safety rules cost **exactly nothing**, which is the easiest
governance argument available: they are not a tradeoff at all. The contact
ceiling is a genuine tradeoff, and it is now quantified rather than asserted.

Three properties make this an experiment rather than a demo:

- **Every variant is audited against the shipped ruleset**, never against its own
  loosened one. A variant cannot become compliant by lowering its own bar.
- **The auditor is proven awake.** The script exits non-zero if *no* loosened
  variant produces violations — because a silent auditor would make every "zero
  violations" badge in this README unfalsifiable.
- **Consent survives policy loosening.** Disabling `stop_after_opt_out` moves
  nothing, because opt-out is enforced in four independent places upstream of the
  policy engine. That row is *evidence* of defence in depth rather than a claim
  about it, and a test fails if it ever stops being true.

---

## The bug class this repo takes most seriously

A benchmark that cannot reproduce itself is worse than no benchmark. Two such
bugs were found and fixed, and both are now machine-guarded:

**Wall-clock leakage.** `PolicyEngine` denies contacts outside 08:00–21:00 UTC.
The test suite constructed engines without injecting a clock, so 17 tests passed
in the afternoon and failed before 13:30 IST. The suite was, in effect, reporting
the time of day. Fixed by pinning a clock in every test;
[`backend/tests/test_clock_hermeticity.py`](backend/tests/test_clock_hermeticity.py)
now AST-scans the suite and **fails the build** if any test constructs a
`PolicyEngine` without `clock=`, then sweeps all 24 hours asserting no rule other
than `contact_time_window` changes its verdict.

**Cross-arm contamination.** The benchmark harness mutated the dataset it was
handed, so each arm inherited the previous arm's spent contact budget. Details in
the collapsed section above. Fixed, and guarded by
[`backend/tests/test_harness_isolation.py`](backend/tests/test_harness_isolation.py).

The second one is the more instructive: `check_artifacts` was already running in
CI to catch stale numbers, and it did not catch this, because the artifacts were
faithfully reproducing a *deterministically wrong* computation. Reproducibility
guards are necessary and not sufficient.

---

## The insight that changed the design

Reading Razorpay's [Payment Retries](https://razorpay.com/docs/payments/subscriptions/payment-retries/)
documentation produced a correctness fix, not a cosmetic one.

When a Subscriptions auto-charge fails:

```
T+0   charge fails      → subscription moves to `pending`
T+1   Razorpay auto-retries
T+2   Razorpay auto-retries
T+3   Razorpay auto-retries
then  subscription moves to `halted`
```

For three days **the gateway is already retrying, for free, at zero contact
cost.** An agent that dunned the customer on day one would spend one of only two
permitted contacts chasing a charge the provider was about to attempt anyway —
and would then take credit for the gateway's recovery.

That inverts a core assumption: **waiting inside the gateway window is not
passivity, it is the correct action.** `subscription.halted` is the real start of
agent-led recovery, because it is the point at which the provider stops charging.

Modelled in `app/integrations/razorpay_gateway_window.py`, enforced as the
`gateway_owns_retry_window` policy rule. Three related decisions fall out of the
same reading of the docs:

- **`UNKNOWN` declines are not retryable.** An optimistic default would
  manufacture retries the evidence does not support.
- **`error_source=business` never contacts the customer.** That is our own
  malformed request; dunning someone over our integration bug is harmful.
- **RBI's 24-hour pre-debit notification rule *denies*, not escalates.** A debit
  inside that window is non-compliant, not merely impolite. A missing
  notification record is treated as a violation: absence of evidence of notice is
  absence of notice.

Full mapping, including three items explicitly marked **UNVERIFIED** against a
live account, is in [`docs/RAZORPAY_ALIGNMENT.md`](docs/RAZORPAY_ALIGNMENT.md).

---

## Promise-to-Pay: bounded grace as a governed pause

When a customer commits to pay by a specific date (e.g., "I will settle Friday after salary credit"), the right move is not to keep dunning — it is to wait.

Like the gateway retry window, **Promise-to-Pay (PTP) is a deterministic reason not to contact someone**. It is designed around four governance invariants:

- **Denial, not an action space addition.** PTP enters strictly via inbound customer commitment events, never as an agent action in the contextual bandit. Outbound dunning is paused under `ptp_active_grace_period` while unexpired, keeping the primary benchmark numbers clean and unaffected.
- **Pure authorization.** `PolicyEngine.authorize()` is a pure, non-mutating query. It never alters state or marks promises broken during authorization.
- **Bounded grace.** To prevent indefinite dunning evasion, commitments are hard-capped at a **30-day maximum horizon** (a 400-day promise is refused at creation) and **at most 2 broken promises per case** before further grace is denied.
- **Strict verification & budget discipline.** A promise is fulfilled only when verified capture evidence matches the **exact case reference AND exact amount in paise**. Partial payments before the due date remain `PENDING` (allowing top-up) rather than prematurely broken. Any customer reminder consumes the standard contact ceiling without loopholes.

---

## Architecture

```mermaid
flowchart LR
    S[Revenue Sentinel<br/>detect drift] --> D[Diagnosis Agent<br/>explain risk]
    D --> P[Strategist<br/>choose intervention]
    P --> G{Policy Engine<br/>authorize?}
    G -->|allowed| X[Executor<br/>bounded action]
    G -->|blocked| N[Ineligible / Stopped]
    G -->|threshold| H[Human Approval]
    H -->|approved| X
    X --> W[Razorpay / Mock Provider]
    W --> E[Signed Webhook]
    E --> V[Outcome Verifier<br/>prove capture]
    V --> R[[RECOVERED]]

    style G fill:#0f5132,stroke:#3fb950,color:#fff
    style V fill:#0f5132,stroke:#3fb950,color:#fff
    style R fill:#1f6feb,stroke:#1f6feb,color:#fff
    style N fill:#5c1a1a,stroke:#f85149,color:#fff
    style H fill:#5c4813,stroke:#d29922,color:#fff
```

Each component's **hard boundary** matters more than its capability:

| Component | Responsibility | Cannot |
| --- | --- | --- |
| `REVENUE_SENTINEL` | Detect revenue at risk, prioritize | Contact a customer or call a provider |
| `DIAGNOSIS_AGENT` | Failure hypothesis, evidence, risk factors | Execute, or mark a case recovered |
| `STRATEGIST_AGENT` | Compare interventions, estimate value, propose | Bypass policy, or reach the provider |
| `POLICY_ENGINE` | Consent, ceilings, thresholds, discounts, provenance | Reason freely, or call a provider |
| `EXECUTOR` | Perform exactly the authorized action | Self-authorize |
| `OUTCOME_VERIFIER` | Verify signed events and captured payments | Treat authorization as recovered money |

### Three structural guarantees

Each is enforced by code and covered by a test — not by convention.

**1. Reasoning cannot reach a provider.** `app.agents`, `app.detection` and
`app.policies` are forbidden from importing any provider adapter. Enforced twice:
by `import-linter` in CI, **and** by `scripts/static_check.py`, which parses the
AST and needs no installed packages — because a safety claim that can only be
checked when the network is up is not a safety claim.

**2. The executor refuses unauthorized work.** `RecoveryExecutor.execute()`
requires a `Decision` object with `allowed=True` *and* a case in state
`APPROVED`. There is no path from proposal to provider call that skips policy.

**3. The actor cannot declare its own success.** `CaseState.RECOVERED` is
writable only by `Actor.OUTCOME_VERIFIER`, only on a signature-verified webhook
carrying a captured payment. `payment.authorized` is explicitly **not** recovery.
A database `CHECK` constraint refuses a `RECOVERED` row with no evidence attached.

### Five invariants, re-derived from the audit log after every run

1. No case reaches `RECOVERED` without verified captured-payment evidence.
2. No provider action executes without deterministic policy authorization.
3. No case exceeds its attempt or customer-contact ceiling.
4. No opted-out customer is contacted.
5. Every financial or state transition produces an audit record.

The benchmark re-checks all five from the audit trail and **exits non-zero** on
violation. The governed run reports **zero across 10,000 cases**.

<details>
<summary><b>Layering, state machine, and money representation</b></summary>

```
app.api          HTTP surface, no business logic
app.services     orchestrator, executor, verifier, state machine, approvals
app.agents  app.detection  app.policies  app.integrations
app.repositories
app.models       SQLAlchemy tables
app.domain       pure: Money, states, entities, errors
app.core         config, logging, error shaping, db engine
```

Dependencies point downward only. `app.domain` imports nothing outward — not
FastAPI, not SQLAlchemy — which is why the entire recovery loop runs under a
bare interpreter with no packages installed.

**State machine:** 17 states with an explicit transition table.
`StateMachine.transition()` validates the transition, checks the actor is
permitted to write the target state, and appends an audit record.

```
happy      DETECTED → DIAGNOSING → ELIGIBLE → PLANNED → POLICY_CHECK
                   → APPROVED → EXECUTING → AWAITING_PAYMENT → RECOVERED
approval   POLICY_CHECK → AWAITING_APPROVAL → APPROVED | DENIED
retry      EXECUTING → FAILED → RETRY_ELIGIBLE → PLANNED
exhausted  EXECUTING → FAILED → MAX_ATTEMPTS → ESCALATED
refused    DIAGNOSING → INELIGIBLE            (opted out, zero probability)
```

Tested as *forbidden*: `DETECTED → RECOVERED`, `PLANNED → EXECUTING`,
`POLICY_CHECK → EXECUTING`, `DENIED → EXECUTING`. Each would be a way to move
money without authorization or claim recovery without evidence.

**Money:** integer paise everywhere, `BIGINT` in the database. `Money` rejects
float construction outright and scales through `Decimal` with explicit
`ROUND_HALF_UP`. No code path lets an amount become a binary float.

**Provenance:** every customer, event and case is labelled `SYNTHETIC` or
`LIVE_TEST_MODE`. `assert_single_provenance()` refuses to mix them in one run,
and the UI shows a red banner if mixed data is detected.

</details>

---

## Prove it locally

No Docker, no network, no credentials, no database:

```bash
cd backend
python3 -m scripts.verify --quick
```

That runs architectural boundary checks, the test suite, four narrated
scenarios, a 2,000-case governed-versus-ungoverned benchmark, and a paired LLM
shadow audit. Individually:

```bash
python3 -m scripts.static_check                      # AST boundary checks, zero deps
python3 -m unittest discover -s tests -t . -q        # 207 tests
python3 -m scripts.demo                              # five narrated scenarios
python3 -m scripts.run_benchmark --events 10000 --seed 42
python3 -m scripts.check_artifacts                   # published numbers still reproduce
python3 -m scripts.run_counterfactual --events 2000 --seed 42  # prices safety rules
python3 -m scripts.run_shadow_eval --events 120 --seed 42
```

On a bare interpreter the HTTP and SQL suites skip cleanly
(`OK (skipped=12)`); CI installs `backend/requirements.txt` and runs all 207.

### The five narrated scenarios, and why each exists

| Scenario | What it demonstrates |
| --- | --- |
| **A.** ₹8,499 expired card → recovered | The loop *executes* rather than recommends — and does not mark its own homework |
| **B.** ₹4,999 permanent decline → escalated | Stopping rules are real. The system gives up on purpose |
| **C.** ₹1,299 recoverable, customer opted out | Terminates at `INELIGIBLE`, **zero** provider calls. Money deliberately left on the table |
| **D.** ₹75,000 above threshold | Holds at `AWAITING_APPROVAL` indefinitely rather than self-approving |
| **E.** ₹6,499 customer promises to pay | Outbound contact paused under `ptp_active_grace_period`, **zero** calls during grace |

Scenarios C and E are the important ones: both demonstrate the system declining to act.

### Run the full stack

```bash
cp .env.example .env
docker compose up --build
```

| Service | URL |
| --- | --- |
| Frontend | `http://localhost:5173` |
| Backend health | `http://localhost:8000/health` |
| API docs | `http://localhost:8000/docs` |

Defaults use the deterministic mock provider and mock reasoning client. For real
Razorpay Test Mode, follow [`docs/RAZORPAY_TESTMODE.md`](docs/RAZORPAY_TESTMODE.md)
— it requires private Test Mode credentials and a public HTTPS webhook URL. **No
credentials are included in this repository.**

---

## API surfaces

| Endpoint | Purpose |
| --- | --- |
| `GET /api/v1/metrics` | Portfolio metrics and provenance summary |
| `GET /api/v1/cases` | Case ledger, with state filtering and pagination |
| `GET /api/v1/cases/{id}` | Case detail and full audit trail |
| `POST /api/v1/cases/{id}/ptp` | Register customer Promise-to-Pay (amount + timezone-aware due date) |
| `GET /api/v1/cases/{id}/ptp` | Inspect current Promise-to-Pay status |
| `GET /api/v1/benchmark` | Learning, rulebook, baseline, oracle and ungoverned arms |
| `GET /api/v1/agents` | Learning strategist, bandit, memory, critic, LLM telemetry |
| `GET /api/v1/agents/shadow-eval` | Paired model influence and guardrail evaluation |
| `GET /api/v1/approvals` | Human approval queue |
| `POST /api/v1/approvals/{id}/approve` · `/deny` | Explicit human decision |
| `POST /api/v1/webhooks/razorpay` | Signature-verified provider event intake |
| `POST /api/v1/demo/live-test-case` | Provenance-safe Razorpay Test Mode launcher |

Full contract in [`docs/API.md`](docs/API.md).

---

## Honest scope

| Capability | State |
| --- | --- |
| Domain model, money arithmetic, state machine | Executed and tested |
| Detection, diagnosis, strategy, policy, executor, verifier | Executed and tested |
| Promise-to-Pay (PTP) lifecycle tracker & grace periods | Executed and tested |
| Webhook signature verification and replay handling | Executed and tested |
| Learning-versus-baseline benchmark | Seeded, reproducible, CI drift-guarded |
| Architectural import boundaries | Statically verified, twice |
| FastAPI HTTP layer and SQLite persistence | Executed locally, restart-tested |
| React + TypeScript frontend | Production build passes in CI |
| Bandit posterior persistence | Implemented and tested |
| Propensity / memory / attribution persistence | **Process-local — not yet durable** |
| Razorpay Test Mode live run | **Adapter implemented; awaiting credentials + public webhook URL** |
| Production traffic, Postgres deployment | Not included |

Two limitations stated plainly, because they are the first questions a reviewer
should ask:

1. **The Razorpay-derived policy rules are inert on synthetic data.** They read
   from `case.event.metadata`, where real provider facts land. Synthetic
   benchmark events carry none of those keys, so those rules do not move the
   benchmark numbers — and
   `tests/test_razorpay_policy.py::TestSyntheticDataIsUnaffected` asserts
   exactly that, so if the headline figures ever shift, it will not be because
   this layer quietly started firing. They protect a live deployment; they do not
   flatter the scoreboard.

2. **Three integration details are unverified against a live account** — the
   reminder endpoint path, mandate charge via invoice issue, and
   `payment.failed` → case linkage via `notes.reference_id`. They are listed in
   `docs/RAZORPAY_ALIGNMENT.md` rather than quietly assumed.

---

## Documentation

| Document | Purpose |
| --- | --- |
| [`docs/RESULTS.md`](docs/RESULTS.md) | **Single source of truth for every number quoted anywhere in this repo** |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Layering, state machine, structural guarantees |
| [`docs/AI_ARCHITECTURE.md`](docs/AI_ARCHITECTURE.md) | Learning strategist, hidden-world evaluation, LLM safety envelope |
| [`docs/RAZORPAY_ALIGNMENT.md`](docs/RAZORPAY_ALIGNMENT.md) | Product mapping, decline classes, RBI constraints, verification status |
| [`docs/API.md`](docs/API.md) | API contract and endpoint reference |
| [`docs/DEMO.md`](docs/DEMO.md) | Presenter script and zero-setup path |
| [`docs/SUBMISSION.md`](docs/SUBMISSION.md) | Buildathon submission narrative and pitch script |
| [`docs/RAZORPAY_TESTMODE.md`](docs/RAZORPAY_TESTMODE.md) | Test Mode and webhook runbook |
| [`docs/IMPLEMENTATION_DECISIONS.md`](docs/IMPLEMENTATION_DECISIONS.md) | Design decisions and their trade-offs |
| [`docs/LOCAL_RUN.md`](docs/LOCAL_RUN.md) | Local product demo walkthrough |

---

## Configuration and safety defaults

All configuration arrives through environment variables and is validated at
startup. Production configuration **refuses to boot** with a mock provider,
placeholder secrets, a short JWT secret, or local webhook replay enabled.

The default policy is intentionally bounded: 3 maximum attempts, 2 maximum
customer contacts, a minimum recovery value, a maximum discount, a contact-hours
window, and a manual-review threshold for high-value cases. Policy versions are
checksummed, and every authorization records the policy version that made the
decision.

---

<div align="center">

**AI proposes. Deterministic software authorizes. The provider executes. Webhooks verify.**

MIT licensed. See [`LICENSE`](LICENSE).

</div>
