import json
import unittest

from app.domain.entities import InterventionType
from app.domain.states import Actor, CaseState
from app.integrations.signature import compute_signature
from tests import factories as f


class OrchestratorCase(unittest.TestCase):
    def drive(self, sys_, case, customer, outcomes):
        """Advance a case, feeding a scripted list of pay/fail outcomes."""
        sys_.orchestrator.advance(case, customer)
        for will_pay in outcomes:
            if case.state is not CaseState.AWAITING_PAYMENT:
                break
            event = (
                sys_.provider.paid_event(case.external_link_id)
                if will_pay
                else sys_.provider.failed_event(case.external_link_id)
            )
            raw = json.dumps(event).encode()
            sys_.handler.handle(
                raw,
                compute_signature(raw, f.SECRET),
                f"evt_{case.id}_{case.attempts}",
            )
            if case.state is CaseState.FAILED:
                sys_.orchestrator.handle_failure(case, customer)
        return case


class TestHappyPath(OrchestratorCase):
    def test_successful_recovery(self):
        sys_ = f.System()
        customer = f.customer()
        case = sys_.register(f.case())
        self.drive(sys_, case, customer, [True])

        self.assertEqual(case.state, CaseState.RECOVERED)
        self.assertEqual(case.attempts, 1)
        self.assertEqual(case.recovered_amount.paise, 849900)
        self.assertIsNotNone(case.diagnosis)
        self.assertIsNotNone(case.evidence)

    def test_the_full_loop_is_visible_in_the_audit_trail(self):
        sys_ = f.System()
        case = sys_.register(f.case())
        self.drive(sys_, case, f.customer(), [True])
        actions = [r.action for r in sys_.audit.for_case(case.id)]
        for expected in (
            "DIAGNOSED",
            "POLICY_DECISION",
            "PAYMENT_LINK_CREATED",
            "STATE_TRANSITION",
        ):
            self.assertIn(expected, actions, f"{expected} missing from audit trail")

    def test_recovery_transition_is_attributed_to_the_verifier(self):
        sys_ = f.System()
        case = sys_.register(f.case())
        self.drive(sys_, case, f.customer(), [True])
        recovered = [
            r
            for r in sys_.audit.for_case(case.id)
            if r.to_state is CaseState.RECOVERED
        ]
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0].actor, Actor.OUTCOME_VERIFIER)


class TestStoppingRules(OrchestratorCase):
    def test_attempts_are_bounded_then_escalated(self):
        sys_ = f.System()
        customer = f.customer()
        case = sys_.register(f.case())
        # Fail more times than the policy permits.
        self.drive(sys_, case, customer, [False] * 10)

        self.assertEqual(case.state, CaseState.ESCALATED)
        self.assertLessEqual(case.attempts, sys_.policy.rules.max_recovery_attempts)
        self.assertLessEqual(case.contacts_made, sys_.policy.rules.max_customer_contacts)

    def test_opted_out_customer_is_never_contacted(self):
        sys_ = f.System()
        case = sys_.register(f.case())
        sys_.orchestrator.advance(case, f.customer(opted_out=True))
        self.assertEqual(case.state, CaseState.INELIGIBLE)
        self.assertEqual(sys_.provider.create_calls, 0)

    def test_below_floor_case_is_denied_and_stopped(self):
        sys_ = f.System()
        case = sys_.register(f.case(f.event(rupees=49)))
        sys_.orchestrator.advance(case, f.customer())
        self.assertEqual(case.state, CaseState.STOPPED)
        self.assertEqual(sys_.provider.create_calls, 0)
        reasons = [r.detail for r in sys_.audit.for_case(case.id)]
        self.assertTrue(any("min_recovery_value" in d for d in reasons))

    def test_denial_is_recorded_with_a_reason(self):
        sys_ = f.System()
        case = sys_.register(f.case(f.event(rupees=49)))
        sys_.orchestrator.advance(case, f.customer())
        decisions = [
            r for r in sys_.audit.for_case(case.id) if r.action == "POLICY_DECISION"
        ]
        self.assertEqual(len(decisions), 1)
        self.assertIn("DENY", decisions[0].detail)
        self.assertTrue(decisions[0].policy_version_id)


class TestHumanApproval(OrchestratorCase):
    def test_high_value_halts_without_an_approver(self):
        sys_ = f.System(approver=None)
        case = sys_.register(f.case(f.event(rupees=75000)))
        sys_.orchestrator.advance(case, f.customer())
        self.assertEqual(case.state, CaseState.AWAITING_APPROVAL)
        self.assertEqual(sys_.provider.create_calls, 0)

    def test_human_approval_releases_the_action(self):
        sys_ = f.System(approver=lambda c, d: True)
        case = sys_.register(f.case(f.event(rupees=75000)))
        sys_.orchestrator.advance(case, f.customer())
        self.assertEqual(case.state, CaseState.AWAITING_PAYMENT)
        self.assertEqual(sys_.provider.create_calls, 1)

    def test_human_rejection_stops_the_case(self):
        sys_ = f.System(approver=lambda c, d: False)
        case = sys_.register(f.case(f.event(rupees=75000)))
        sys_.orchestrator.advance(case, f.customer())
        self.assertEqual(case.state, CaseState.STOPPED)
        self.assertEqual(sys_.provider.create_calls, 0)


class TestSubscriptionRecovery(OrchestratorCase):
    def test_halted_subscription_uses_a_payment_link(self):
        # Razorpay exposes no merchant-callable retry API, so the only honest
        # recovery path is a payment link for the unpaid invoice.
        from app.domain.entities import RiskEventType

        sys_ = f.System()
        case = sys_.register(
            f.case(f.event(event_type=RiskEventType.SUBSCRIPTION_HALTED))
        )
        sys_.orchestrator.advance(case, f.customer())
        self.assertEqual(case.plan.intervention, InterventionType.SUBSCRIPTION_RECOVERY)
        self.assertEqual(case.state, CaseState.AWAITING_PAYMENT)


class TestAgentsCannotAct(unittest.TestCase):
    def test_agents_never_touch_the_provider(self):
        """The strategist produces a proposal object and nothing else."""
        sys_ = f.System()
        case = f.case()
        case.diagnosis = sys_.orchestrator.diagnosis_agent.diagnose(
            case.event, f.customer()
        )
        plan = sys_.orchestrator.strategist.plan(case, case.diagnosis, f.customer())
        self.assertEqual(sys_.provider.create_calls, 0)
        self.assertEqual(case.state, CaseState.DETECTED)
        self.assertIn(plan.intervention, list(InterventionType))

    def test_strategist_refuses_to_propose_contacting_an_opted_out_customer(self):
        sys_ = f.System()
        case = f.case()
        diagnosis = sys_.orchestrator.diagnosis_agent.diagnose(case.event, f.customer())
        plan = sys_.orchestrator.strategist.plan(
            case, diagnosis, f.customer(opted_out=True)
        )
        self.assertEqual(plan.intervention, InterventionType.STOP)
        self.assertFalse(plan.contact_customer)


class TestLlmFailureDegradesSafely(unittest.TestCase):
    def test_diagnosis_falls_back_when_the_model_fails(self):
        from app.agents.diagnosis_agent import DiagnosisAgent
        from app.agents.llm import LLMError

        class BrokenLLM:
            name = "broken"

            def complete_json(self, system, prompt, schema_hint):
                raise LLMError("model unavailable")

        diagnosis = DiagnosisAgent(BrokenLLM()).diagnose(f.event(), f.customer())
        self.assertFalse(diagnosis.is_llm_output)
        self.assertTrue(diagnosis.rationale)
        self.assertGreater(diagnosis.recovery_probability, 0.0)

    def test_malformed_model_output_is_refused_not_guessed(self):
        from app.agents.llm import LLMError, parse_strict_json

        self.assertEqual(parse_strict_json('{"a": 1}'), {"a": 1})
        with self.assertRaises(LLMError):
            parse_strict_json("not json at all")
        with self.assertRaises(LLMError):
            parse_strict_json("[1, 2, 3]")
