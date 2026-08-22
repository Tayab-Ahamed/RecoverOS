# Razorpay Test Mode verification runbook

This is the final gate that turns RecoverOS from a reproducible simulation into a payment-recovery prototype: one case, one real Payment Link, one real signed webhook, and one `RECOVERED` state reached only because Razorpay confirmed captured money.

Razorpay documents that webhooks are asynchronous server-to-server notifications, that Test Mode has its own webhook configuration, that webhook URLs must be publicly reachable on ports 80 or 443, and that signatures use HMAC-SHA256 over the raw request body. Razorpay also recommends identifying duplicate deliveries with `x-razorpay-event-id` and not assuming webhook order. See [About Webhooks](https://razorpay.com/docs/webhooks/), [Validate and Test Webhooks](https://razorpay.com/docs/webhooks/validate-test/), [Payment Webhook Events](https://razorpay.com/docs/webhooks/payments/), and [Payment Link Webhook Events](https://razorpay.com/docs/webhooks/payment-links/).

## Prerequisites

Use a Razorpay account in **Test Mode**, never Live Mode. You need a public HTTPS staging URL or a supported tunnel such as zrok. Razorpay cannot deliver directly to `localhost`, and its documentation lists several common relay domains as blocked.

## 1. Start the stack

```bash
cp .env.example .env
docker compose up --build
```

Confirm the health endpoints:

```bash
curl localhost:8000/health
curl localhost:8000/health/db
curl localhost:8000/health/redis
```

For a no-Docker local review, follow [LOCAL_RUN.md](LOCAL_RUN.md) and use the mock provider first.

## 2. Configure Test Mode credentials

Set these values in `.env` without committing them:

```dotenv
PAYMENT_PROVIDER=razorpay
RAZORPAY_KEY_ID=<test-key-id>
RAZORPAY_KEY_SECRET=<test-key-secret>
RAZORPAY_WEBHOOK_SECRET=<webhook-secret-created-in-dashboard>
```

The webhook secret is not the API secret. It is the value entered when the webhook is created in the Razorpay Dashboard. Restart the backend and confirm `/health/razorpay` is healthy.

## 3. Expose the webhook endpoint

If using zrok:

```bash
zrok share public http://localhost:8000
```

Keep the process running. Use the generated HTTPS hostname as the webhook base URL.

## 4. Register the Test Mode webhook

In the Razorpay Dashboard, switch to **Test Mode**, open **Account & Settings → Webhooks**, and add:

```text
https://<public-host>/api/webhooks/razorpay
```

Use the exact value of `RAZORPAY_WEBHOOK_SECRET`. Subscribe to at least:

```text
payment_link.paid
payment.captured
payment.failed
payment_link.expired
```

Test and Live modes have separate webhook configurations. Do not configure this endpoint in Live Mode for the buildathon demonstration.

## 5. Generate one recovery action

For the synthetic local proof, use:

```bash
curl -X POST localhost:8000/api/v1/demo/seed
curl -X POST localhost:8000/api/v1/demo/run
curl localhost:8000/api/v1/cases
```

For a real Test Mode proof, use the dedicated live-labelled launcher:

```bash
curl -X POST localhost:8000/api/v1/demo/live-test-case \
  -H 'Content-Type: application/json' \
  -d '{"amount_rupees":4999,"reason":"CARD_EXPIRED"}'
```

The endpoint refuses to run unless `PAYMENT_PROVIDER=razorpay`, resets the demo store to prevent provenance mixing, creates one `LIVE_TEST_MODE` case, and sends the bounded plan through the real Razorpay Payment Links adapter. Open the returned Payment Link and complete it with Razorpay Test Mode credentials.

## 6. Verify the state transition

```bash
curl localhost:8000/api/v1/cases/<case_id>
curl localhost:8000/api/v1/cases/<case_id>/audit
```

The following must all be true:

| Check | Expected result |
| --- | --- |
| Case state | `RECOVERED` only after captured evidence |
| Recovery actor | `OUTCOME_VERIFIER`, never the executor or agent |
| Evidence | Real Razorpay payment and webhook event identifiers |
| Provenance | `LIVE_TEST_MODE`, never `SYNTHETIC` |
| Signature | Validated against the raw request body and webhook secret |
| Replay | Same event ID is rejected or ignored without double-counting |
| Ordering | `payment.authorized` cannot be treated as captured recovery |

If the state changes to `RECOVERED` without a signed captured webhook, stop the demonstration and fix it before submission.

## 7. Capture evidence for the submission

Record the Test Mode dashboard view, the generated Payment Link, the webhook delivery, the case detail drawer, and the audit trail. Redact all secrets, customer contact details, and API credentials. Keep the synthetic benchmark and the live Test Mode evidence in separate labelled sections.

## Known verification items

A real account is still required to settle the exact failed Payment Link payload shape and any account-specific webhook behavior. The implementation handles the documented Payment Link and payment events, validates signatures before parsing, uses durable event identity for idempotency, and treats provider event order as non-authoritative.

## Safety rules

Do not create thousands of real Payment Links to reproduce the benchmark. Do not paste credentials into documentation or source control. Do not use Live Mode credentials. Do not claim synthetic recovery percentages as production performance.
