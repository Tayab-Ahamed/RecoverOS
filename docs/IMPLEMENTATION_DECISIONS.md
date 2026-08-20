# Implementation decisions and deviations

Every deviation from the approved specification is recorded here with its
reason, as required by the kickoff instruction.

## D1. The core recovery loop has zero third-party dependencies

**Specified:** FastAPI, SQLAlchemy, Pydantic, Redis throughout.

**Built:** the domain, detection, policy engine, state machine, executor,
verifier, webhook handler, agents, orchestrator and evaluation harness import
nothing outside the Python standard library. FastAPI, SQLAlchemy, Alembic and
Redis are present as adapters at the edges.

**Why:** this was originally forced by a build environment with no package
index, but it is kept because it is better architecture and it produces a
stronger deliverable. The consequence is that the entire recovery loop, the
full test suite and the 10,000-event benchmark can be executed by a reviewer
with nothing but `python3` — no database, no Redis, no credentials, no network.
The safety claims are therefore verifiable rather than merely asserted.

**Cost:** honest and worth stating. Pydantic request/response validation is not
used; responses are shaped by hand in `app/api/schemas.py`. Configuration is a
validated dataclass rather than `BaseSettings`.

## D2. `unittest` rather than `pytest`

**Specified:** pytest.

**Built:** tests are `unittest.TestCase` classes.

**Why:** they run with no installation step, which keeps D1's guarantee intact.
They remain fully compatible with `pytest`, which is configured in
`pyproject.toml`, so `pytest` works for anyone who installs it.

## D3. `/health` is mounted twice

The versioning rule says every route lives under `/api/v1`. Health routes are
mounted at both the root and the versioned prefix, because load balancers and
container orchestrators need a stable probe that does not move when the API is
versioned. Deliberate, narrow exception.

## D4. Provider abstraction with a deterministic mock as the default

`PAYMENT_PROVIDER=mock` is the default. The mock derives customer payment
behaviour from a seeded hash, so the same dataset produces identical results on
every run. Live Razorpay is a drop-in adapter behind the same port.

## D5. A denial after an attempt escalates rather than stopping

When policy refuses further action on a case that has already been attempted,
real money is still outstanding, so the case moves to `ESCALATED` and reaches a
human. A denial before any attempt (opt-out, below the economic floor) is a
clean `STOPPED`. This distinction is not in the original specification; without
it, recoverable revenue could be silently dropped.

## D6. Approval is a separate service

Human approval lives in `app/services/approval.py` rather than as a branch in
the orchestrator, because it is a distinct trust boundary. Policy is
re-evaluated at approval time, so a stale approval cannot authorize an action
that policy would now refuse.

## D7. Architectural contracts are enforced by a build step

`backend/.importlinter` forbids `app.agents`, `app.detection` and `app.policies`
from importing any payment provider. "The AI cannot move money" is checked by
`lint-imports` in CI rather than trusted from a comment.

## D8. Invariant 1 is also a database constraint

`recovery_cases` carries CHECK constraints so a row cannot be in state
`RECOVERED`, or carry a recovered amount, without linked payment evidence. The
application enforces this too; putting it in the schema means a bug in
application code cannot corrupt the ledger.

## D9. Deterministic reasoning is the default, and is labelled

With `LLM_PROVIDER=mock` the diagnosis narrative comes from a rule table.
Every diagnosis records `is_llm_output`, so a reviewer can always tell whether
a model produced the text. When a live model fails or returns malformed JSON,
the system falls back to the deterministic narrative and records that no model
output was used, rather than guessing or crashing.

## D10. The numeric recovery prior is deterministic, not model-generated

The probability that drives prioritisation comes from
`app/detection/rules.py`. The agent contributes explanation, not arithmetic.
This keeps prioritisation reproducible and auditable.

## D11. A provider event with no event id is malformed, not recoverable

**Was:** the webhook route fell back to `f"body:{hash(raw)}"` when the provider
event id header was absent.

**Defect:** `hash()` of a bytes object is randomised per interpreter process
unless `PYTHONHASHSEED` is pinned. Replay protection keyed on that value does
not survive a restart, so an already-processed `payment_link.paid` event could
be accepted a second time and a case could be credited twice. This was a real
bug found in review, not a hypothetical.

**Now:** identity resolution lives in `app/webhooks/event_id.py`:

- A provider-supplied id always wins. A whitespace-only header counts as
  absent.
- Outside production, an id may be derived as `body:sha256:<hex>` for the
  signed local replay path. A digest is deterministic across processes,
  machines and interpreter versions.
- **In production, a missing id raises `MissingProviderEventId` and the request
  is rejected with HTTP 400.** Manufacturing a deduplication key from content
  the sender controls is worse than refusing: two distinct events with
  identical bodies would collapse into one, and one event redelivered with a
  byte-level difference would be processed twice.
- `is_derived()` lets audit consumers distinguish a real provider id from a
  manufactured one, and the webhook log line records it.

The logic sits in a standard-library module rather than in the FastAPI route so
it is covered by tests, including a regression test that runs `derive_event_id`
in two separate interpreter subprocesses and asserts the results match. That
assertion is precisely what the previous implementation would have failed.

## Standing verification items

These are **UNVERIFIED** and must be resolved before any submission or
production use. They are deliberately isolated so no unverified claim leaks
into the README.

1. **Buildathon track requirements.** `razorpay.com/buildathon/` returned an
   error page on every attempt. Track numbering, wording, deadlines, team size
   and submission format are unverified. No compliance claim is made anywhere
   in this repository.
2. **Failed-attempt linkage.** Whether a failed attempt on a Payment Link emits
   `payment.failed` with a resolvable link association is unverified against a
   live account. The handler reads `notes.reference_id` as the fallback path.
3. **Subscription events.** The existence and exact semantics of
   `subscription.pending` and `subscription.halted` on a fresh test account are
   unverified.
4. **Rate limits.** Razorpay documents that a rate limiter exists but does not
   publish thresholds. Batch execution has no throttle tuned to a real limit.
5. **Test-mode capability.** Whether Subscriptions are enabled by default on a
   fresh test account is unverified.
