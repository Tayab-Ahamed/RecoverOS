# RecoverOS five-minute submission video

Record at 1920x1080, 30 fps, with browser zoom at 100%. Keep the browser
chrome hidden if possible. Do not show `.env`, API keys, webhook secrets,
customer contact details, or personal account information.

## Local setup

From the repository root:

```bash
docker compose up --build
```

If Docker is unavailable, follow `LOCAL_RUN.md`. Open the frontend and keep
the backend terminal hidden from the recording. Use the mock provider for the
synthetic dashboard proof. The confirmed Razorpay Test Mode proof is shown
from the Test Mode dashboard/webhook evidence, never mixed into synthetic
metrics.

## Five-minute shot map

| Time | Screen and action | Hold | Narration cue |
| --- | --- | ---: | --- |
| 0:00–0:20 | Title/dashboard opening. Show RecoverOS name, mission statement, and the permanent `SYNTHETIC EVALUATION DATA` banner. | 5s on banner | “Failed payments are not just a detection problem. The hard problem is recovering revenue without spending customer trust.” |
| 0:20–0:45 | Click **Run the proof**. Let the metrics and case feed populate. | 8s on completed metrics | “RecoverOS detects revenue at risk, chooses a bounded intervention, and measures the result. This dataset is synthetic, reproducible, seed 42—not merchant revenue.” |
| 0:45–1:15 | Open one recovered case. Show state badge, amount, diagnosis, evidence, selected plan, and audit trail. | 3–4s per section | “The agent explains the failure, proposes an action, and records the evidence behind it. The agent cannot declare success by itself.” |
| 1:15–1:40 | Scroll to the audit trail and final evidence. Pause on `OUTCOME_VERIFIER`, captured=true, and webhook event ID. | 8s | “Only signature-verified captured payment evidence can transition a case to RECOVERED. Authorization alone is not counted as money recovered.” |
| 1:40–2:05 | Open an opted-out/ineligible case. Show no provider action and zero contacts. | 7s | “Governance also means knowing when not to act. Consent and policy boundaries stop the workflow before customer contact.” |
| 2:05–2:30 | Open a high-value case awaiting approval. Show approval queue and policy explanation. | 7s | “High-value actions wait for a human. AI proposes; deterministic policy authorizes; the operator identity is recorded in the audit trail.” |
| 2:30–3:05 | Return to benchmark card. Show adaptive, fixed baseline, and ungoverned risk rows. Show contacts and violations. | 10s | “On the seeded 10,000-event benchmark, the learner reaches 86.73% optimal action versus 61.61% for the fixed baseline, with zero governed violations.” |
| 3:05–3:25 | Hold on the ungoverned row and policy-violation count. | 8s | “The unsafe agent recovers more by contacting more people, but commits policy violations. RecoverOS optimizes recovery under governance, not recovery at any cost.” |
| 3:25–3:45 | Show the architecture/pipeline view: detection → agents → policy → executor → Razorpay → webhook verifier. | 8s | “The trust boundary is explicit: AI proposes, policy authorizes, the provider executes, and webhooks prove.” |
| 3:45–4:20 | Show Razorpay Test Mode evidence: successful test payment, corrected webhook endpoint ending in `/api/webhooks/razorpay`, and received `payment.captured` plus `payment_link.paid`. Redact IDs and contacts. | 5s each | “This is a separate Razorpay Test Mode proof. The payment succeeded, the signed events arrived after the webhook path was corrected, and the case moved from AWAITING_PAYMENT to RECOVERED.” |
| 4:20–4:45 | Return to the case audit screen. Show provenance `LIVE_TEST_MODE`, captured evidence, and recovered state. | 10s | “Live Test Mode evidence is never blended with the synthetic benchmark. Provenance is visible in the product and in the audit record.” |
| 4:45–5:00 | Final architecture/title frame with the four-part statement. | 10s | “RecoverOS is a governed revenue-recovery control plane: measurable economics, bounded autonomy, verified payment capture, and an audit trail.” |

## Recording rules

- Keep every important screen visible for at least 5 seconds.
- Move the mouse slowly and pause after each click.
- Avoid fast scrolling; use deliberate section-by-section movement.
- If a request or dashboard load takes time, keep the screen still and let it
  breathe rather than cutting immediately.
- Use one continuous synthetic demo run. Do not run the benchmark repeatedly
  on camera unless the UI needs a reset.
- Show `SYNTHETIC` and `LIVE TEST MODE` as separate scenes with an obvious cut.
- Never describe synthetic rupee totals as real recovered merchant revenue.

## Subtitle/voice production

Use the narration cues above as the source for AI voice generation. Generate
one audio segment per timestamp block, then align each segment to the listed
time range. Add subtitles as short two-line captions; do not transcribe long
paragraphs over the UI. Keep the final export at 1080p H.264 with burned-in
subtitles and a separate clean master if the editor supports it.
