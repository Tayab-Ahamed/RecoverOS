# Implementation plan

## Approved sequence

`0 -> 1 -> 2 -> 3a -> 4 -> 5 -> 6 -> 7 -> 8 -> 3b -> 9 -> 10 -> 11 -> 12 -> 13 -> 14 -> 15 -> 16`

Phase 3a is the provider interface, the adapter, the webhook path, signature
verification and idempotency, all built against the mock provider. Phase 3b is
live credentials and one real end-to-end payment; it is a floating gate that
must close before Phase 9.

## Status

| Phase | Scope | Status |
| --- | --- | --- |
| 0 | Reconnaissance, contradiction resolution | Complete |
| 1 | Foundation, configuration, logging, error shaping, health | Complete (API unexecuted) |
| 2 | Domain model, money, state machine, audit log | Complete and tested |
| 3a | Provider port, mock adapter, signatures, idempotency | Complete and tested |
| 4 | Detection and prioritisation | Complete and tested |
| 5 | Diagnosis and strategy agents | Complete and tested |
| 6 | Policy Guard | Complete and tested |
| 7 | Executor | Complete and tested |
| 8 | Outcome Verifier and webhook ingestion | Complete and tested |
| 3b | Live Razorpay end-to-end payment | **Blocked**: needs credentials |
| 9 | Evaluation harness and benchmark | Complete and executed |
| 10 | API surface | Written, not executed |
| 11 | Frontend | Written, not executed |
| 12 | Persistence and migrations | Written, not executed |
| 13 | Workflow automation (n8n) | Not started, non-blocking |
| 14 | Production hardening | Config guard in place; rest pending |
| 15 | Deployment | Compose and Dockerfiles written, not executed |
| 16 | Buildathon compliance audit | Blocked on unverified requirements |

## What "complete and tested" means here

Executed in a sandbox with no network: 89 tests pass, a 10,000-event benchmark
runs to completion, and the invariant auditor reports zero policy violations.

"Written, not executed" means exactly that. The FastAPI, SQLAlchemy, Alembic,
Docker and frontend layers have never been run, because the build environment
had no package index. They are unverified by execution and should be treated as
such until `docker compose up` succeeds.

## Next actions, in order

1. `docker compose up --build` and fix whatever the untested layers get wrong.
2. Close Phase 3b: real test-mode credentials, one real payment, one real
   signed webhook.
3. Verify the five standing items in `IMPLEMENTATION_DECISIONS.md`.
4. Wire the SQL repositories behind the same interfaces the in-memory ones
   already satisfy, then re-run the full suite against Postgres.
