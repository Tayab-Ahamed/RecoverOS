import unittest

from app.domain.states import (
    ALLOWED_TRANSITIONS,
    TERMINAL_STATES,
    Actor,
    CaseState,
    is_transition_allowed,
    may_actor_write,
)


class TestStateGraph(unittest.TestCase):
    def test_every_state_has_a_table_entry(self):
        for state in CaseState:
            self.assertIn(state, ALLOWED_TRANSITIONS, f"{state} missing")

    def test_terminal_states_have_no_exits(self):
        for state in TERMINAL_STATES:
            self.assertEqual(ALLOWED_TRANSITIONS[state], frozenset())

    def test_non_terminal_states_are_never_stuck(self):
        for state in CaseState:
            if state not in TERMINAL_STATES:
                self.assertTrue(ALLOWED_TRANSITIONS[state], f"{state} is a dead end")

    def test_happy_path_is_reachable(self):
        path = [
            CaseState.DETECTED,
            CaseState.DIAGNOSING,
            CaseState.ELIGIBLE,
            CaseState.PLANNED,
            CaseState.POLICY_CHECK,
            CaseState.APPROVED,
            CaseState.EXECUTING,
            CaseState.AWAITING_PAYMENT,
            CaseState.RECOVERED,
        ]
        for src, dst in zip(path, path[1:]):
            self.assertTrue(is_transition_allowed(src, dst), f"{src} -> {dst}")

    def test_approval_and_retry_paths_exist(self):
        self.assertTrue(
            is_transition_allowed(CaseState.POLICY_CHECK, CaseState.AWAITING_APPROVAL)
        )
        self.assertTrue(
            is_transition_allowed(CaseState.AWAITING_APPROVAL, CaseState.APPROVED)
        )
        self.assertTrue(is_transition_allowed(CaseState.FAILED, CaseState.RETRY_ELIGIBLE))
        self.assertTrue(is_transition_allowed(CaseState.RETRY_ELIGIBLE, CaseState.PLANNED))
        self.assertTrue(is_transition_allowed(CaseState.MAX_ATTEMPTS, CaseState.ESCALATED))

    def test_recovered_is_writable_only_by_the_verifier(self):
        self.assertTrue(may_actor_write(CaseState.RECOVERED, Actor.OUTCOME_VERIFIER))
        for actor in Actor:
            if actor is Actor.OUTCOME_VERIFIER:
                continue
            self.assertFalse(
                may_actor_write(CaseState.RECOVERED, actor),
                f"{actor} must not declare recovery",
            )

    def test_agents_cannot_approve(self):
        for actor in (Actor.STRATEGIST_AGENT, Actor.DIAGNOSIS_AGENT, Actor.EXECUTOR):
            self.assertFalse(may_actor_write(CaseState.APPROVED, actor))

    def test_governance_cannot_be_skipped(self):
        self.assertFalse(is_transition_allowed(CaseState.DETECTED, CaseState.RECOVERED))
        self.assertFalse(is_transition_allowed(CaseState.PLANNED, CaseState.EXECUTING))
        self.assertFalse(is_transition_allowed(CaseState.POLICY_CHECK, CaseState.EXECUTING))
        self.assertFalse(is_transition_allowed(CaseState.DENIED, CaseState.EXECUTING))
