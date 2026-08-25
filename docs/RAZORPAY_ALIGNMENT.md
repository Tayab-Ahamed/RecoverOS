# Razorpay alignment

How RecoverOS maps onto Razorpay's actual products, API shapes, webhook
events and regulatory constraints — and the one place where reading their
docs changed the design rather than just the labels.

Everything here is sourced from Razorpay's public documentation. Where a
claim is not verified against a live account, it says so.

---

## 1. Intervention to product mapping

`InterventionType` used to be an abstract label. Each one now names a real
product, endpoint and proof-of-success event, defined as data in
`app/integrations/razorpay_catalog.py`.

| Intervention | Razorpay product | Endpoint | Proves recovery |
| --- | --- | --- | --- |
| `PAYMENT_LINK` | Payment Links (Standard) | `POST /v1/payment_links` | `payment_link.paid`, `payment.captured`, `order.paid` |
| `REMINDER` | Payment Link reminders | `POST /v1/payment_links/{id}/notify_by/{medium}` | `payment_link.paid`, `payment.captured` |
| `SUBSCRIPTION_RECOVERY` | Subscriptions / UPI AutoPay mandate charge | `POST /v1/invoices/{id}/issue` | `subscription.charged`, `payment.captured` |
| `ESCALATION` | none — internal human queue | — | — |
| `STOP` | none | — | — |

Two consequences fall out of this table:

**Proof is per-product.** The Outcome Verifier now derives its accepted
events from this catalogue rather than a hand-written list, so adding a
product cannot silently leave its capture event unrecognised. Cross-product
proof is rejected: a paid payment link says nothing about whether a mandate
debit succeeded.

**Some interventions are impossible, not just unwise.** Subscription
recovery requires an authorised mandate. Without one the API call would
fail, so the strategist must not be able to select it.

---

## 2. The design change: Razorpay already retries

This is the substantive thing learned from their docs, and it is a
correctness issue.

Per [Payment Retries](https://razorpay.com/docs/payments/subscriptions/payment-retries/),
when a Subscriptions auto-charge fails:

```
T+0   charge fails      -> subscription moves to `pending`
T+1   Razorpay auto-retries
T+2   Razorpay auto-retries
T+3   Razorpay auto-retries
then  subscription moves to `halted`
```

So for three days the gateway is already retrying, **for free, at zero
contact cost to us**. An agent that dunned the customer on day one would be
spending one of only two permitted contacts to chase a charge the provider
was about to attempt anyway — and would then take credit for the gateway's
recovery.

That inverts a core assumption. Waiting inside the gateway window is not
passivity, it is the correct action. `subscription.halted` is the real
start of agent-led recovery, because it is the point where the provider
stops charging.

Modelled in `app/integrations/razorpay_gateway_window.py`, enforced as the
`gateway_owns_retry_window` policy rule.

---

## 3. Decline classification

A real `payment.failed` carries four fields, and the recovery decision
depends on all of them:

```
error_code     BAD_REQUEST_ERROR | GATEWAY_ERROR | SERVER_ERROR
error_source   customer | business | bank | gateway | issuer
error_step     payment_authentication | payment_authorization | ...
error_reason   incorrect_otp | insufficient_funds | card_expired | ...
```

`app/integrations/razorpay_errors.py` maps these onto our eight-value
`FailureReason`, but the more important output is the **decline class**:

| Class | Meaning | Retry same instrument? |
| --- | --- | --- |
| `SOFT` | may succeed after customer action (insufficient funds, failed OTP) | yes |
| `TRANSIENT` | infrastructure (gateway/issuer down, timeout) | yes, no contact needed |
| `HARD` | instrument is dead (expired, blocked, invalid) | no |
| `UNKNOWN` | unrecognised fields | **no** |

Three deliberate choices:

- **`UNKNOWN` is not retryable.** An optimistic default would manufacture
  retries the evidence does not support.
- **`error_source=business` never contacts the customer.** That is our own
  malformed request; dunning someone over our integration bug is harmful.
- **A hard decline on an unchanged instrument is denied.** Retrying a dead
  card four times is the classic dunning failure mode: it annoys the
  customer and recovers nothing.

---

## 4. Regulatory constraint: pre-debit notification

RBI's e-mandate framework requires a pre-debit notification at least **24
hours** before any mandate debit, for both cards and UPI AutoPay. A debit
proposed inside that window is non-compliant, not merely impolite, so the
`rbi_pre_debit_notification` rule **denies** rather than escalates.

A missing notification record is treated as a violation, not as an unknown:
absence of evidence of notice is absence of notice.

---

## 5. Honest scope: what these rules do NOT do

All four Razorpay-derived rules read from `case.event.metadata`, which is
where provider facts land when a real webhook is ingested. **Synthetic
benchmark events carry none of those keys, so every rule here is inert on
synthetic data.**

This is deliberate and worth stating plainly:

- These guards protect a live deployment.
- They do not move the benchmark numbers, and they should not. The 2,000-event
  run after this work is byte-identical to before it: ₹39,79,999.60
  recovered, 69.51% recovery rate, 0 policy violations.
- `tests/test_razorpay_policy.py::TestSyntheticDataIsUnaffected` asserts this
  directly, so if the headline numbers ever move, it will not be because
  this layer quietly started firing.

Anyone claiming these rules improved the benchmark would be
misrepresenting them.

---

## 6. Verification status

| Item | Status |
| --- | --- |
| Payment Links request/response shape | Verified against public API reference |
| Payment Links statuses (`created`, `partially_paid`, `expired`, `cancelled`, `paid`) | Verified against docs |
| Payments webhook events | Verified against docs |
| Subscriptions webhook events and retry ladder | Verified against docs |
| Payment error fields | Verified against docs |
| RBI 24h pre-debit notification | Verified against RBI/NPCI guidance |
| Reminder endpoint path | **UNVERIFIED** against a live account |
| Mandate charge via invoice issue | **UNVERIFIED** against a live account |
| `payment.failed` -> case linkage via `notes.reference_id` | **UNVERIFIED** against a live account |

The unverified rows need one test-mode account to confirm. They are listed
rather than quietly assumed.

---

## 7. Also worth knowing

- **Webhook retries.** Razorpay retries webhook delivery on an exponential
  backoff over 24 hours. Idempotency by provider event id is therefore
  mandatory, not defensive; it is enforced in `app/webhooks/handler.py`
  before any domain logic runs.
- **Payment link default validity is six months.** We set `expire_by` far
  shorter so an unpaid link produces a terminal signal instead of hanging.
- **`reminder_enable=true` means Razorpay sends its own reminders.** Those
  are real customer contacts and must be counted against the contact
  budget, or the system under-reports how often it touches people.
- **Manual charge of a domestic card is not supported.** For card mandates,
  subscription recovery degrades to asking the customer to update the card.
- **Optimizer** is Razorpay's own ML routing product. It optimises which
  gateway a transaction takes; RecoverOS optimises whether and how to
  re-approach a customer after failure. Different layers, not competitors.
