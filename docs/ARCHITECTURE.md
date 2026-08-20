# Architecture

One sentence: **AI proposes, deterministic software authorizes, the provider
executes, webhooks verify.**

Everything below is a consequence of taking that sentence literally.

## The loop

```
DETECT     deterministic rules over risk events        app/detection
   |
DIAGNOSE   reasoning agent, explains the failure       app/agents/diagnosis_agent.py
   |
DECIDE     reasoning agent, proposes an intervention   app/agents/strategist_agent.py
   |
GOVERN     policy engine, authorizes or refuses        app/policies/engine.py
   |
ACT        executor, the only caller of a provider     app/services/executor.py
   |
VERIFY     outcome verifier, reads signed webhooks     app/services/verifier.py
   |
RECOVER / STOP / RETRY / ESCALATE
```

The agents produce *proposals*. They cannot move money, and they cannot mark
their own work successful.

## Three structural guarantees

These are not conventions. Each one is enforced by code and covered by a test.

### 1. Reasoning cannot reach a provider

`app.agents`, `app.detection` and `app.policies` are forbidden from importing
`app.integrations.razorpay` or `app.integrations.mock_razorpay`. Only
`app.services.executor` may call a provider.

Enforced twice: by `import-linter` in CI, and by `scripts/static_check.py`,
which parses the AST and needs no installed packages. The second exists because
a safety claim that can only be checked when the network is up is not a safety
claim.

### 2. The executor refuses unauthorized work

`RecoveryExecutor.execute()` refuses unless the policy decision allows the
action *and* the case is in state `APPROVED`. There is no path from a proposal
to a provider call that skips the policy engine.

### 3. The actor cannot declare its own success

`CaseState.RECOVERED` is writable only by `Actor.OUTCOME_VERIFIER`, and the
verifier only transitions on a signature-verified webhook carrying a captured
payment. `payment.authorized` is explicitly **not** recovery: authorized money
is not captured money.

The database mirrors this: a CHECK constraint refuses a `RECOVERED` row with no
payment evidence attached.

## Layering

```
app.api          HTTP surface, no business logic
app.services     orchestrator, executor, verifier, state machine, approvals
app.agents  app.detection  app.policies  app.integrations
app.repositories
app.models       SQLAlchemy tables
app.domain       pure: Money, states, entities, errors
app.core         config, logging, error shaping, db engine
```

Dependencies point downward only. `app.domain` imports nothing outward, not
even FastAPI or SQLAlchemy, which is why the entire recovery loop runs under a
bare interpreter with no packages installed.

## State machine

17 states, explicit transition table in `app/domain/states.py`. Transitions go
through `StateMachine.transition()`, which validates the transition, checks the
actor is permitted to write the target state, and appends an audit record.

```
happy      DETECTED -> DIAGNOSING -> ELIGIBLE -> PLANNED -> POLICY_CHECK
                    -> APPROVED -> EXECUTING -> AWAITING_PAYMENT -> RECOVERED
approval   POLICY_CHECK -> AWAITING_APPROVAL -> APPROVED | DENIED
retry      EXECUTING -> FAILED -> RETRY_ELIGIBLE -> PLANNED
exhausted  EXECUTING -> FAILED -> MAX_ATTEMPTS -> ESCALATED
refused    DIAGNOSING -> INELIGIBLE          (opted out, zero probability)
```

Tested as forbidden: `DETECTED -> RECOVERED`, `PLANNED -> EXECUTING`,
`POLICY_CHECK -> EXECUTING`, `DENIED -> EXECUTING`. Each would be a way to move
money without authorization or to claim recovery without evidence.

## Money

Integer paise everywhere, `BIGINT` in the database. `Money` rejects float
construction outright and scales through `Decimal` with explicit
`ROUND_HALF_UP`. There is no code path where an amount becomes a binary float.

## Provenance

Every customer, event and case is labelled `SYNTHETIC` or `LIVE_TEST_MODE`.
`assert_single_provenance()` refuses to mix them in one run, and the UI shows a
red banner if mixed data is ever detected. Simulated results must never be
readable as real ones.

## Five invariants

1. No case reaches `RECOVERED` without verified captured payment evidence.
2. No action executes without policy authorization.
3. No case exceeds its attempt or contact ceiling.
4. No opted-out customer is contacted.
5. Every financial or state transition has an audit record.

The benchmark harness re-derives all five from the audit log after each run and
fails loudly on violation. The governed run reports zero across 10,000 cases.
