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
| Learning planner | **86.74%** | **₹9,85,715.11** | 12,390 | 0 |
| Hand-written rulebook | 65.69% | ₹21,43,705.45 | 13,700 | 0 |
| Fixed payment-link baseline | 61.61% | ₹20,42,304.81 | 13,613 | 0 |
| Oracle (unachievable bound) | 100% | ₹7.15 | 13,017 | 0 |
| Ungoverned risk demo | 37.92% | ₹22,46,280.78 | 86,065 | **4,281** |

### Revenue — supporting evidence

| Arm | Recovered revenue | Recovery rate | Cases recovered | Share of attainable |
| --- | ---: | ---: | ---: | ---: |
| Learning planner | ₹2,02,68,522.95 | 70.85% | 6,982 | 97.45% |
| Hand-written rulebook | ₹1,97,53,242.45 | 69.05% | 7,097 | 94.97% |
| Fixed payment-link baseline | ₹1,97,81,644.00 | 69.14% | 7,103 | 95.11% |
| Oracle (unachievable bound) | ₹2,07,98,675.05 | 72.70% | 7,451 | 100% |
| Ungoverned risk demo | ₹2,58,47,718.00 | 90.35% | 8,928 | — |

### Derived deltas quoted in the README

| Claim | Value | Derivation |
| --- | --- | --- |
| Optimal-action gain vs baseline | +25.13 points | 86.74% − 61.61% |
| Regret reduction vs baseline | −51.7% | 1 − (9,85,715.11 / 20,42,304.81) |
| Fewer contacts vs baseline | −1,223 | 12,390 − 13,613 |
| Revenue gain vs baseline | +₹4,86,878.95 | 2,02,68,522.95 − 1,97,81,644.00 |
| Fewer contacts vs rulebook | −1,310 | 12,390 − 13,700 |
| Governed policy violations | 0 across 10,000 cases | all governed arms |

---

## Secondary run — 2,000 events, seed 42

Artifact: `evaluation/runs/run_benchmark_42_2000.json`

| Metric | Learning | Rulebook | Fixed baseline |
| --- | ---: | ---: | ---: |
| Recovered revenue | ₹39,38,301.85 | ₹39,79,999.60 | ₹39,21,912.00 |
| Recovery rate | 68.79% | 69.51% | 68.50% |
| Optimal action | **81.05%** | 65.84% | 63.14% |
| Total regret | ₹3,72,369.07 | ₹4,26,788.73 | ₹3,95,756.11 |
| Contacts | 2,528 | 2,755 | 2,751 |
| Policy violations | 0 | 0 | 0 |

This is the run used by `scripts.verify --quick` and quoted in
`docs/AI_ARCHITECTURE.md` and `docs/RAZORPAY_ALIGNMENT.md`.

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
| Test suite | 166 tests | `python -m unittest discover -s tests -t . -q` |
| Skipped on a bare interpreter | 12 (HTTP + SQL suites) | as above, no packages installed |
| Architectural boundary checks | pass, zero dependencies | `python -m scripts.static_check` |
| Committed artifact freshness | pass | `python -m scripts.check_artifacts` |

---

## Why recovery rate is not the headline

Recovery rate is inflated by contacting more people. The ungoverned arm posts the
best recovery rate on the scoreboard — 90.35% — using 86,065 contacts and
committing 4,281 policy violations, roughly 6.9× the contact volume of the
learner for 19.5 points of recovery rate bought with consent violations.

Optimal-action rate and regret are defined per decision against the hidden world
model and cannot be improved by contacting more people, only by choosing better.
That is why they lead.
