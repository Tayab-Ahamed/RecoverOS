# Results

Every number quoted anywhere in this repository is listed here, with the
artifact it comes from and the command that regenerates it. If a figure appears
in `README.md`, `docs/SUBMISSION.md` or a pitch script and is not in this file,
treat it as unsourced.

Freshness is machine-enforced. `python -m scripts.check_artifacts` re-derives
every committed artifact from its own recorded seed and diffs the metrics below;
it runs in CI and fails the build on drift.

---

## Provenance and limits

These are **seeded synthetic** results from a simulation whose conversion priors
were chosen by the author. They demonstrate that the control system behaves
correctly and measurably at batch scale. They are **not** a forecast of
production recovery rates, and no live Razorpay Test Mode run is included yet.

All arms share the same cases, the same policy gate, and the same hidden world,
with **common random numbers**: identical cases face identical luck, so a
difference between arms is attributable to the decision rather than to variance.

The reasoning layer provably cannot read the answer key.
`scripts/static_check.py` fails the build if anything under `app.agents`,
`app.detection` or `app.policies` imports `app.evaluation.ground_truth`.

---

## Primary run — 10,000 events, seed 42

Artifact: `evaluation/runs/run_benchmark_42_10000.json`

```bash
cd backend && python -m scripts.run_benchmark --events 10000 --seed 42
```

### Action quality — the headline claim

| Arm | Optimal action | Total regret | Contacts | Policy violations |
| --- | ---: | ---: | ---: | ---: |
| Learning planner | **86.73%** | **₹11,73,939.11** | 12,458 | 0 |
| Hand-written rulebook | 69.65% | ₹16,73,979.19 | 13,605 | 0 |
| Fixed payment-link baseline | 61.61% | ₹20,42,304.81 | 13,613 | 0 |
| Oracle (unachievable bound) | 100% | ₹0.00 | 13,017 | 0 |
| Ungoverned risk demo | 37.92% | ₹22,46,280.78 | 86,065 | **4,281** |

### Revenue — supporting evidence

| Arm | Recovered revenue | Recovery rate | Cases recovered | Share of attainable |
| --- | ---: | ---: | ---: | ---: |
| Learning planner | ₹2,01,93,421.40 | 70.58% | 7,007 | 97.09% |
| Hand-written rulebook | ₹2,00,44,270.35 | 70.06% | 7,147 | 96.37% |
| Fixed payment-link baseline | ₹1,97,81,644.00 | 69.14% | 7,103 | 95.11% |
| Oracle (unachievable bound) | ₹2,07,98,709.70 | 72.70% | 7,451 | 100% |
| Ungoverned risk demo | ₹2,58,47,718.00 | 90.35% | 8,928 | — |

### Derived deltas quoted in the README

| Claim | Value | Derivation |
| --- | --- | --- |
| Optimal-action gain vs baseline | +25.12 points | 86.73% − 61.61% |
| Regret reduction vs baseline | −42.5% | 1 − (11,73,939.11 / 20,42,304.81) |
| Fewer contacts vs baseline | −1,155 | 12,458 − 13,613 |
| Revenue gain vs baseline | +₹4,11,777.40 | 2,01,93,421.40 − 1,97,81,644.00 |
| Fewer contacts vs rulebook | −1,147 | 12,458 − 13,605 |
| Governed policy violations | 0 across 10,000 cases | all governed arms |

---

## Secondary run — 2,000 events, seed 42

Artifact: `evaluation/runs/run_benchmark_42_2000.json`

| Metric | Learning | Rulebook | Fixed baseline | Oracle |
| --- | ---: | ---: | ---: | ---: |
| Recovered revenue | ₹38,83,557.30 | ₹40,08,638.80 | ₹39,21,912.00 | ₹41,66,425.85 |
| Recovery rate | 67.83% | 70.01% | 68.50% | 72.77% |
| Optimal action | **78.66%** | 70.04% | 63.14% | 100% |
| Total regret | ₹4,26,063.16 | ₹3,25,738.42 | ₹3,95,756.11 | ₹0.00 |
| Contacts | 2,605 | 2,744 | 2,751 | 2,611 |
| Policy violations | 0 | 0 | 0 | 0 |

This is the run used by `scripts.verify --quick` and quoted in
`docs/AI_ARCHITECTURE.md` and `docs/RAZORPAY_ALIGNMENT.md`.

Recorded honestly: at this dataset size the learning planner picks the **best
action** most often (78.66% against the rulebook's 70.04%) but recovers **less
money** than the rulebook, because it spends 139 fewer contacts. Optimal-action
rate and recovered revenue are different objectives, and at 2,000 events the
gap between them is wide enough to be visible. Read the 10,000-event run for
revenue: the bandit needs volume before its posteriors sharpen.

---

## Model-in-the-loop shadow evaluation — 120 events, seed 42

Artifact: `evaluation/runs/shadow_eval_42_120.json`

```bash
cd backend && python -m scripts.run_shadow_eval --events 120 --seed 42
```

| Metric | Value |
| --- | ---: |
| Paired decisions compared | 113 |
| Model agreement with base strategy | 89.38% |
| Model influence rate | 10.62% |
| Guardrail catch rate on injected faults | **100%** |
| Injected faults | 26 (16 malformed JSON, 6 unsafe output, 4 injection compliance) |
| Parse failure rate | 4.41% |

Recorded honestly: in this run the narrated arm produced **slightly lower** raw
recovered revenue than the non-narrated arm while reducing regret. The LLM earns
its place through explanation and a tested safety envelope, not through a claim
that narration recovers more money.

---

## Test and verification counts

| Claim | Value | Command |
| --- | --- | --- |
| Test suite | 207 tests | `python -m unittest discover -s tests -t . -q` |
| Skipped on a bare interpreter | 13 (HTTP + SQL suites) | as above, no packages installed |
| Architectural boundary checks | pass, zero dependencies | `python -m scripts.static_check` |
| Clock hermeticity | pass at all 24 hours | included in the suite above |
| Harness run isolation | pass | included in the suite above |
| Committed artifact freshness | pass | `python -m scripts.check_artifacts` |

The suite passes at **any hour of the day**. That is asserted rather than
assumed: `tests/test_clock_hermeticity.py` re-authorizes a case under all 24
injected hours and fails if any rule other than `contact_time_window` changes
its verdict.

---

## Why recovery rate is not the headline

Recovery rate is inflated by contacting more people. The ungoverned arm posts the
best recovery rate on the scoreboard — 90.35% — using 86,065 contacts and
committing 4,281 policy violations, roughly 6.9× the contact volume of the
learner for 19.8 points of recovery rate bought with consent violations.

---

## Counterfactual policy sweep — 2,000 events, seed 42

Artifact: `evaluation/runs/counterfactual_42_2000.json`

```bash
cd backend && python -m scripts.run_counterfactual --events 2000 --seed 42
```

The benchmark shows the planner chooses well *under one fixed ruleset*. It cannot
answer the question an operator actually asks, which is never "is the agent
good" but "we allow two customer contacts — what would a third one buy, and what
would it cost?" This sweep answers that by experiment: same dataset, same hidden
world, same seed, same planner, and the **only** thing that varies is the policy.

Every variant is audited against `GOVERNED_RULES`, not against its own loosened
ruleset, so a variant cannot become compliant by lowering its own bar.

| Variant | Recovered | Contacts | Violations | Δ revenue | Δ/contact | Verdict |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `governed_default` | ₹38,83,557.30 | 2,605 | 0 | — | — | baseline |
| `three_contacts` | ₹43,05,937.20 | 2,958 | **427** | +₹4,22,379.90 | ₹1,196.54 | reject |
| `four_attempts` | ₹38,83,557.30 | 2,605 | 0 | ₹0.00 | — | reject |
| `no_economic_floor` | ₹38,83,903.30 | 2,611 | 4 | +₹346.00 | ₹57.67 | reject |
| `deeper_discount` | ₹38,83,557.30 | 2,605 | 0 | ₹0.00 | — | reject |
| `ignore_opt_out` | ₹38,83,557.30 | 2,605 | 0 | ₹0.00 | — | held |

What the sweep establishes:

- **A third contact is not free.** It recovers ₹4.22L more, and commits 427
  violations of the governed contact ceiling to do it. The revenue is real and
  it is not ours to take.
- **Two constraints cost nothing at all.** A fourth retry attempt and a deeper
  discount ceiling both move revenue by exactly ₹0.00, so those bounds are free
  to keep. A constraint that costs nothing is the easiest governance argument
  there is.
- **The economic floor is doing real work.** Removing it earns ₹346 across 2,000
  events, at ₹57.67 per additional contact — far below what the average contact
  earns — while breaching the floor 4 times.
- **Consent cannot be defeated by loosening policy alone.** Disabling
  `stop_after_opt_out` changes nothing measurable, because opt-out is enforced
  independently in four places: `detection/rules.py` refuses to open the case,
  both strategists propose `STOP`, and the orchestrator terminates at
  `INELIGIBLE` before the policy engine is ever consulted. This row is the
  evidence for that claim rather than an assertion of it.

The script exits non-zero if the governed baseline violates its own policy, if
**no** loosened variant trips the invariant auditor (which would mean the auditor
is asleep and every "zero violations" claim here is unfalsifiable), or if a
defence-in-depth constraint stops holding. It runs in CI.

Optimal-action rate and regret are defined per decision against the hidden world
model and cannot be improved by contacting more people, only by choosing better.
That is why they lead.

---

## Note on Promise-to-Pay (PTP) constraint evaluation

Promise-to-Pay is an **inbound deterministic denial constraint**: when a customer commits to pay by date $T$, the `ptp_active_grace_period` rule pauses outbound dunning until $T$. It is not an agent action in the contextual bandit, and the synthetic benchmark generator intentionally emits no PTP events to keep the primary benchmark numbers bit-identical and reproducible.

Consequently, the counterfactual policy sweep does not price PTP: evaluating an `ignore_promise_to_pay` variant on a synthetic dataset without inbound customer commitments would yield ₹0.00 delta, which would misleadingly imply the safety rule has zero value rather than reflecting that it was not exercised. PTP is instead verified deterministically via unit test suites (`tests/test_promise_to_pay.py`) and live demo walkthroughs (`Scenario E` in `docs/DEMO.md`).

