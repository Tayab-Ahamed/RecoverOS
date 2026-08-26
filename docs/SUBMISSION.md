# RecoverOS submission playbook

## Track

**AI Revenue Recovery**

RecoverOS detects revenue at risk, uses an evidence-backed agent to choose a proportionate intervention, passes that proposal through deterministic policy, executes through a payment provider, and declares recovery only after a verified captured-payment webhook.

## One-line pitch

> RecoverOS is the governed recovery agent for failed payments: it chooses the next best intervention, but deterministic policy controls consent, limits, and approvals, while Razorpay webhooks provide the evidence that money actually arrived.

## What makes it competitive

The project is not only a failure detector. It closes the loop across detection, diagnosis, intervention selection, execution, verification, escalation, and audit. The learning planner is evaluated against both a fixed payment-link baseline and a hand-written rulebook on the same synthetic batch, under the same policy gate, against a hidden world model the agents provably cannot read. The benchmark also includes an ungoverned risk arm to make the cost of unsafe autonomy visible, and an oracle arm to bound the scoreboard.

The headline claim is deliberately **not** recovery rate. Recovery rate can be raised by contacting more people, which is why the ungoverned arm reaches 90.35% while committing 4,281 policy violations. The defensible claim is action quality: on the 10,000-event run the learner selects the value-maximising action **86.73%** of the time versus **61.61%** for the fixed baseline, cuts total regret by **42.5%**, and does it with **1,155 fewer customer contacts**. Same money, less trust spent.

The central trust boundary is deliberately simple:

> **AI proposes. Deterministic software authorizes. The provider executes. Webhooks verify.**

## Five-minute pitch script

### 0:00–0:35 — Start with the money

Open the dashboard and click **Run the proof**. Say: “This batch contains revenue at risk. RecoverOS does not optimize for a flashy recovery percentage at any cost. It optimizes for money recovered per compliant customer contact, with zero policy violations.”

Point to the recovered revenue, recovery rate, escalations, and provenance banner. State clearly that the demo dataset is synthetic and reproducible.

### 0:35–1:25 — Show the adaptive decision

Open a recovered case. Show the diagnosis evidence, risk signals, selected intervention, alternatives considered, expected recoverable value, confidence, and the audit trail. Explain that the agent chooses among a payment link, reminder, subscription recovery, escalation, or stop; the policy engine still has final authority.

### 1:25–2:05 — Show the system proving the capture

Point to the final state transition and the captured-payment webhook evidence. Explain that an authorization is not counted as revenue. Only a signature-verified captured event can write `RECOVERED`.

### 2:05–2:45 — Show the boundaries

Open the opted-out case. Show `INELIGIBLE`, zero contacts, and no provider action. Then show the high-value case held at `AWAITING_APPROVAL`. Say: “The agent knows when not to act, and it knows when a human must decide.”

### 2:45–3:35 — Show measured agent value

Open **Adaptive recovery, measured**. Explain that every arm sees the same cases, the same policy, and the same hidden world, with common random numbers so identical cases face identical luck.

Lead with **optimal-action rate and regret**, not recovery rate: 86.73% versus 61.61%, regret down 42.5%, on 1,155 fewer contacts, capturing 97.45% of what the oracle proves was attainable. Say plainly that recovery rate is the wrong headline because the ungoverned arm wins it (90.35%) by committing 4,281 violations. The ungoverned arm exists to demonstrate why governance matters; it is not a production recommendation.

### 3:35–4:20 — Explain implementation depth

Show the architecture: deterministic detection, diagnosis agent, strategist agent, policy engine, executor, provider adapter, signed webhook handler, verifier, and audit log. Mention paise-safe money representation, replay protection, state-transition enforcement, and provenance labels.

### 4:20–5:00 — Close with the product claim

Close with: “RecoverOS is not an AI that sends messages until someone pays. It is a revenue-recovery control plane that makes every intervention explainable, bounded, reversible where possible, and provable after the fact.”

## What is real versus simulated

The state machine, policy engine, executor, verifier, signature validation, replay protection, audit trail, benchmark harness, and dashboard are executable locally. The default demo uses labelled synthetic data and a deterministic mock provider. Synthetic results must never be presented as production recovery performance.

Razorpay Test Mode support is implemented through the Payment Links adapter and webhook path. A final live-test-mode run still requires merchant credentials, a public HTTPS endpoint, and a webhook configured in Razorpay Test Mode. Never use Live Mode credentials for the buildathon demo.

## Reviewer proof commands

```bash
cd backend
python -m scripts.verify --quick
python -m scripts.verify_sql
python -m scripts.run_benchmark --events 10000 --seed 42
python -m scripts.check_artifacts   # every published number reproduces
```

```bash
cd frontend
npm run build
```

For the local product demo, follow [LOCAL_RUN.md](LOCAL_RUN.md). For the Test Mode checklist, follow [RAZORPAY_TESTMODE.md](RAZORPAY_TESTMODE.md).

## Honest evidence statement

Every report carries a seed, dataset run ID, profile, and `SYNTHETIC` provenance label. The adaptive-versus-baseline comparison measures control-system behavior and strategy efficiency on generated data; it is evidence that the implementation can be evaluated and audited, not a forecast of production recovery rates.
