# Phase 3b runbook: first real Razorpay Test Mode recovery

This is the gate that turns RecoverOS from a well-tested simulation into a
payment-recovery prototype. Nothing in this repository has ever made a network
call to Razorpay.

**Goal:** one case, one real Payment Link, one real signed webhook, one
`RECOVERED` state reached only because Razorpay said the money arrived.

## Prerequisites

- A Razorpay account in **Test Mode**. Test keys do not require completed KYC.
- A public HTTPS URL for webhook delivery. `ngrok http 8000` or a Cloudflare
  tunnel is fine. Razorpay cannot reach `localhost`.

## 1. Bring the stack up

```bash
cp .env.example .env
docker compose up --build
```

The backend, Postgres, Redis and the frontend start. `alembic upgrade head`
runs on boot. Confirm:

```bash
curl localhost:8000/health
curl localhost:8000/health/db
curl localhost:8000/health/redis
```

This is the first time this path has ever been executed. Expect to fix
something here.

## 2. Switch off the mock

In `.env`:

```
PAYMENT_PROVIDER=razorpay
RAZORPAY_KEY_ID=rzp_test_xxxxxxxxxxxx
RAZORPAY_KEY_SECRET=xxxxxxxxxxxxxxxx
RAZORPAY_WEBHOOK_SECRET=<the secret you set in the dashboard>
```

`RAZORPAY_WEBHOOK_SECRET` is **not** your API secret. It is the string you type
into the dashboard when creating the webhook. Signature verification fails
silently-looking if you confuse them, so check this first when a webhook is
rejected.

Restart the backend. `/health/razorpay` should return 200.

## 3. Register the webhook

Dashboard -> Settings -> Webhooks -> Add New Webhook.

- URL: `https://<your-tunnel>/api/webhooks/razorpay`
- Secret: the value of `RAZORPAY_WEBHOOK_SECRET`
- Events: `payment_link.paid`, `payment.captured`, `payment.failed`,
  `payment_link.expired`

Test and Live modes have separate webhook configurations. Register in Test.

## 4. Run one case

```bash
curl -X POST localhost:8000/api/v1/demo/seed
curl -X POST localhost:8000/api/v1/demo/run
curl localhost:8000/api/v1/cases | jq
```

Take the `short_url` from the executing case and open it in a browser. Pay with
a test card; on the mock bank page choose **Success**.

## 5. Watch the loop close

```bash
curl localhost:8000/api/v1/cases/<case_id>/audit | jq
```

What must be true:

- the case is `RECOVERED`
- the transition's actor is `OUTCOME_VERIFIER`, not the executor
- the audit record carries the real Razorpay `external_event_id`
- provenance on the case is `LIVE_TEST_MODE`, not `SYNTHETIC`
- replaying the same webhook body is rejected as a duplicate

If the state changed to `RECOVERED` without a signed webhook, something is
wrong and it matters more than any other bug in the system.

## Known unknowns to resolve here

These are documented as standing verification items and can only be settled
against a real account:

1. Whether a failed Payment Link attempt emits `payment.failed` carrying a
   resolvable link association. Scenario B and the notes-based fallback in
   `WebhookHandler._extract` depend on it.
2. Whether `subscription.pending` and `subscription.halted` behave as assumed,
   and whether Subscriptions are enabled on a fresh test account.
3. Published rate limits. A limiter exists; thresholds are not documented.

## What not to do

- Do not create thousands of real Payment Links to reproduce the benchmark. The
  10,000-event run is synthetic on purpose.
- Do not add cancellation, retry or subscription APIs to reach parity with the
  spec. Create and fetch are sufficient to prove the loop. Razorpay has no
  merchant-callable retry API in any case; it auto-retries and then halts.
- Do not point this at Live keys. Production config refuses a mock provider and
  weak secrets, but it cannot protect you from real customers.
