# RecoverOS

Autonomous revenue recovery with deterministic governance.

> **AI proposes. Deterministic software authorizes. The payment provider
> executes. Webhooks verify.**

Most "AI agent" systems in payments stop at a recommendation. RecoverOS closes
the loop: it detects revenue at risk, diagnoses why it failed, plans an
intervention, submits that plan to a deterministic policy engine, executes the
authorized action against a payment provider, and marks money recovered **only**
after a verified captured-payment webhook.

The interesting engineering is not the autonomy. It is the brakes.

---

## Run it in thirty seconds

No database, no Redis, no credentials, no network, no `pip install`:

```bash
cd backend
python3 -m scripts.demo                                    # four narrated scenarios
python3 -m unittest discover -s tests -t . -v               # 89 tests
python3 -m scripts.run_benchmark --events 10000 --seed 42   # measured batch run
```

The entire recovery loop is standard-library Python. That is deliberate: the
safety claims below are verifiable by a reviewer in one command, not merely
asserted in a README. See `docs/IMPLEMENTATION_DECISIONS.md`, D1.

Full stack, when you want the API, database and UI:

```bash
cp .env.example .env
docker compose up --build
```

---

## Measured results

**SYNTHETIC EVALUATION DATA.** 10,000 events, seed 42, mock provider, run in
this repository. Reproduce with the command above; identical seed produces
identical output, and a test asserts that.

| Metric | Governed | Ungoverned |
| --- | --- | --- |
| Cases | 10,000 | 10,000 |
| Revenue at risk | Rs 2,97,16,216 | Rs 2,97,16,216 |
| Recovered (verified captures only) | **Rs 2,34,10,077** | Rs 2,82,39,080 |
| Recovery rate | 81.8% | 98.7% |
| Cases recovered | 7,371 | 9,618 |
| Customer contacts made | 13,796 | 21,540 |
| Stopped by policy | 115 | 0 |
| Escalated to a human | 2,132 | 0 |
| Audit records written | 168,028 | 224,242 |
| **Policy violations** | **0** | **4,490** |

The second column is the point of the whole project. Removing the policy engine
recovers about Rs 48 lakh more — by contacting 7,744 more customers, ignoring
opt-outs, exceeding attempt ceilings, and committing 4,490 policy violations. It
is a system you could not deploy. The governed run leaves that money on the
table on purpose and can prove, per case, why.

### Honest reading of these numbers

The recovery percentages come from a seeded simulation whose conversion priors
were chosen by the authors, settled through a mock provider. **They are not a
prediction of real-world recovery rates and should not be quoted as one.** What
this benchmark demonstrates is narrower and more defensible: the control system
behaves correctly at batch scale, and the invariant auditor finds zero
violations across 10,000 cases and 168,028 audit records. The benchmark script
exits non-zero if a single violation appears.

---

## Architecture

```
DETECT -> DIAGNOSE -> DECIDE -> GOVERN -> ACT -> VERIFY -> RECOVER
                                   |                  |
                                   v                  v
                              STOP / RETRY / ESCALATE  audit trail
```

| Component | Deterministic? | Can it move money? |
| --- | --- | --- |
| Revenue Sentinel (`detection/`) | Yes | No |
| Diagnosis Agent (`agents/`) | No (LLM, optional) | No |
| Strategist Agent (`agents/`) | No (LLM, optional) | No |
| **Policy Guard** (`policies/`) | **Yes** | No — it only authorizes |
| Executor (`services/executor.py`) | Yes | **Yes, and only with a decision** |
| Outcome Verifier (`services/verifier.py`) | Yes | No — it only confirms |

Two agents reason. Neither can act. The executor is the only component that can
reach a payment provider, and it refuses to run without an `allowed=True`
decision object and a case in state `APPROVED`.

This is enforced as a build step, not a convention:
`backend/.importlinter` forbids `app.agents`, `app.detection` and `app.policies`
from importing any provider module. CI fails if that boundary is crossed.

### The five invariants

1. No case reaches `RECOVERED` without a verified captured payment.
2. No outbound action occurs without Policy Guard authorization.
3. No case exceeds its attempt or contact ceiling.
4. No opted-out customer is ever contacted.
5. Every financial and recovery transition has an audit record.

Each is enforced in code, asserted in tests, audited across the full benchmark,
and — for invariant 1 — additionally enforced by database CHECK constraints, so
a bug in application code cannot corrupt the ledger.

### Design decisions worth defending

- **Money is integer paise everywhere.** `Money.from_rupees` rejects floats
  outright. There is no `DECIMAL`, no `float`, and no rounding near an amount.
- **`RECOVERED` is writable by exactly one actor**, the Outcome Verifier. The
  component that acts cannot declare its own success.
- **`payment.authorized` is explicitly not recovery.** Authorized is not
  captured. Treating them as equivalent is the most common way this class of
  system overstates results.
- **Webhook signatures are verified over raw bytes.** Parsing and
  re-serialising the JSON changes the bytes and breaks the digest.
- **Idempotency is enforced by provider event id.** In the benchmark every one
  of 13,796 delivered events was replayed; all were correctly ignored.
- **Policy versions are content-addressed.** Every decision records the policy
  checksum that produced it, so a historical decision stays explainable after
  the rules change.
- **Denial after an attempt escalates rather than stops.** Money is still
  outstanding, so a human sees it (D5).

---

## The four demo scenarios

| | Scenario | Outcome | Why it matters |
| --- | --- | --- | --- |
| A | Rs 8,499 expired card | `RECOVERED` | The loop executes, and only verified capture counts |
| B | Rs 4,999 declined, never pays | `ESCALATED` | Bounded attempts, then a compliant handover |
| C | Rs 1,299, customer opted out | `STOPPED`, **zero provider calls** | An AI that cannot be told no does not belong in payments |
| D | Rs 75,000 above threshold | `AWAITING_APPROVAL` | Autonomy is bounded by value |

Scenario C is the one to watch. Recoverable revenue is deliberately abandoned.

---

## What is verified, and what is not

I would rather be trusted than impressive, so:

**Executed and passing in this repository**

- The full recovery loop, end to end, over 10,000 events.
- 89 tests, including reproducibility, invariant, and governance-cost tests.
- The benchmark, the invariant auditor, and the narrated demo.

**Written but never executed** — no package index was available in the build
environment, so these layers are unverified by execution:

- The FastAPI application, routers and middleware.
- SQLAlchemy models and the Alembic migration.
- Docker Compose, both Dockerfiles, the CI workflow.
- The React frontend.

Treat them as unreviewed until `docker compose up` succeeds.

**Never exercised against Razorpay.** No live or test-mode API call has been
made from this repository. The Razorpay adapter is written against documented
behaviour; Phase 3b in `docs/IMPLEMENTATION_PLAN.md` is the gate that closes
this, and five specific unverified items are listed in
`docs/IMPLEMENTATION_DECISIONS.md`.

The default configuration (`PAYMENT_PROVIDER=mock`, `LLM_PROVIDER=mock`) is
fully offline and deterministic.

---

## Layout

```
backend/
  app/
    domain/        money, states, entities, errors   (no outward dependencies)
    detection/     risk detection and prioritisation
    agents/        diagnosis and strategy (propose only)
    policies/      the Policy Guard and versioned rules
    services/      state machine, executor, verifier, orchestrator, approval, audit
    integrations/  provider port, mock adapter, Razorpay adapter, signatures
    webhooks/      signed ingestion with replay protection
    evaluation/    dataset generator and benchmark harness
    api/           FastAPI surface
    models/        SQLAlchemy schema
  tests/           89 tests, standard library only
  scripts/         demo, benchmark
frontend/          React + TypeScript dashboard with audit drawer
docs/              plan, decisions and deviations, demo script
evaluation/runs/   labelled benchmark artifacts
```

## Configuration

Every variable is documented in `.env.example`. `.env` is gitignored in the
first commit. Configuration is validated at boot, and production boot fails on
a weak `JWT_SECRET`, a mock provider, or an enabled local webhook replay.

```bash
./scripts/secret_scan.sh   # run over full git history in CI
```

## License

MIT.
