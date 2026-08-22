# Internship portfolio brief

## Project headline

Built RecoverOS, a governed autonomous payment-recovery platform where AI
proposes actions but deterministic policy, signed provider webhooks, and human
approval gates control every financial transition.

## Resume bullets

- Designed a multi-agent payment-recovery loop with strict trust boundaries:
  reasoning agents can propose, but only an authorized executor can call the
  provider and only a verifier can declare recovery.
- Implemented policy enforcement for opt-out protection, attempt/contact
  ceilings, value-based human approval, exact paise arithmetic, and append-only
  audit trails.
- Built a reproducible evaluation harness comparing an adaptive recovery
  planner, a fixed payment-link baseline, and an ungoverned risk arm across
  synthetic batches; the governed arms maintain zero invariant violations while
  reporting recovery efficiency and customer-contact cost.
- Added signed Razorpay webhook verification, durable event-id replay
  protection, SQL persistence, migration support, a provenance-safe live Test Mode
  launcher, and restart-tested API state recovery.

## Interview explanation

The most important design decision was treating AI output as an untrusted
proposal rather than an authorization. The agents never import provider code;
the policy engine is deterministic; the executor checks authorization again;
and the outcome verifier requires captured-payment evidence from a signed
webhook. This makes the system explainable under failure and audit pressure.

## Honest caveat

The benchmark uses synthetic data and a mock provider. It demonstrates control
behavior, not a production recovery-rate forecast. A live Razorpay Test Mode
run still requires merchant credentials and a public HTTPS webhook endpoint.
