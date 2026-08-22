from __future__ import annotations

import os
import unittest

from fastapi.testclient import TestClient

os.environ.setdefault("APP_ENV", "local")
os.environ.setdefault("PAYMENT_PROVIDER", "mock")
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("ENABLE_LOCAL_WEBHOOK_REPLAY", "true")

from app.main import app  # noqa: E402


class AgentApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.client.post("/api/v1/demo/reset")

    def test_agent_snapshot_exposes_learning_state(self) -> None:
        response = self.client.get("/api/v1/agents")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["learning_enabled"])
        self.assertEqual(body["strategy"], "learning")
        self.assertIn("bandit", body["snapshot"])
        self.assertIn("propensity", body["snapshot"])
        self.assertIn("memory", body["snapshot"])

    def test_shadow_eval_reports_model_influence_and_guardrail_result(self) -> None:
        response = self.client.get("/api/v1/agents/shadow-eval?events=40&seed=42")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertGreater(body["decisions_compared"], 0)
        self.assertGreaterEqual(body["agreement_rate"], 0.0)
        self.assertLessEqual(body["agreement_rate"], 1.0)
        self.assertGreaterEqual(body["influence_rate"], 0.0)
        self.assertLessEqual(body["influence_rate"], 1.0)
        self.assertIsNotNone(body["guardrail_catch_rate"])
        self.assertEqual(body["headline"]["label"], "SYNTHETIC SHADOW EVALUATION")


if __name__ == "__main__":
    unittest.main()
