# Demo script

## Zero-setup path

No database, no Redis, no credentials, no network:

```bash
cd backend
python3 -m scripts.demo                                   # four narrated scenarios
python3 -m unittest discover -s tests -t . -q              # 166 tests
python3 -m scripts.run_benchmark --events 10000 --seed 42  # measured batch
python3 -m scripts.check_artifacts                         # published numbers still reproduce
```

## The four scenarios, and why each exists

### A. Recoverable failure, money actually recovered

Rs 8,499 expired card. The loop runs: detect, diagnose, plan, authorize,
execute, verify. The case reaches `RECOVERED` only after a captured payment
event, and the transition is attributed to the Outcome Verifier.

**Point:** the system executes rather than recommends, and it does not mark its
own homework.

### B. Unrecoverable, stopped and escalated

Rs 4,999 declined card that never succeeds. Attempts stay inside the ceiling,
contacts stay inside the ceiling, then the case escalates to a human.

**Point:** stopping rules are real. The system gives up on purpose.

### C. Policy refusal (the most important scenario)

Rs 1,299 recoverable, from a customer who opted out. The case terminates at
`INELIGIBLE` before any plan is even proposed, and zero provider calls are made.
The money is deliberately left on the table.

**Point:** an AI that cannot be told no has no business touching payments. Show
the provider call count: zero.

### D. High value, held for human approval

Rs 75,000 above the review threshold. The case stops at `AWAITING_APPROVAL`
and waits. With no approver configured it waits indefinitely rather than
self-approving.

**Point:** autonomy is bounded by value.

## The batch result

Run the benchmark live. It reports the governed run beside an ungoverned run
over the same dataset, so the audience can see what governance costs and what
it prevents. The governed run must report zero policy violations; the script
exits non-zero if it does not.

## Closing line

> AI proposes. Deterministic software authorizes. The provider executes.
> Webhooks verify.

And the honest caveat, said out loud: the recovery percentages come from a
seeded simulation, not from production traffic. What is proven here is that the
control system behaves correctly at batch scale.
