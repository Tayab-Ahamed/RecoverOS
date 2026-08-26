"""HTTP contract tests for the demonstrable local API surface."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("PAYMENT_PROVIDER", "mock")
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("ENABLE_LOCAL_WEBHOOK_REPLAY", "true")

from tests.factories import fixed_clock  # noqa: E402
from tests.optional_deps import HAS_FASTAPI, REQUIRES_FASTAPI  # noqa: E402

if HAS_FASTAPI:  # pragma: no branch - import guard
    from fastapi.testclient import TestClient  # noqa: E402

    from app.api.deps import set_clock  # noqa: E402
    from app.main import app  # noqa: E402


@unittest.skipUnless(HAS_FASTAPI, REQUIRES_FASTAPI)
class ApiContractTests(unittest.TestCase):
    def setUp(self) -> None:
        set_clock(fixed_clock)
        self.client = TestClient(app)
        self.client.post("/api/v1/demo/reset")

    def tearDown(self) -> None:
        set_clock(None)

    def test_demo_loop_and_metrics(self) -> None:
        health = self.client.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["payment_provider"], "mock")

        seeded = self.client.post("/api/v1/demo/seed")
        self.assertEqual(seeded.status_code, 200)
        self.assertEqual(seeded.json()["cases_detected"], 40)

        run = self.client.post("/api/v1/demo/run")
        self.assertEqual(run.status_code, 200)
        self.assertEqual(run.json()["advanced"], 25)

        metrics = self.client.get("/api/v1/metrics")
        self.assertEqual(metrics.status_code, 200)
        self.assertEqual(metrics.json()["cases"], 40)
        self.assertIn("SYNTHETIC", metrics.json()["data_provenance"])

    def test_benchmark_reports_adaptive_lift_and_zero_governed_violations(self) -> None:
        response = self.client.get("/api/v1/benchmark?events=40&seed=42")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["headline"]["label"], "SYNTHETIC EVALUATION DATA")
        self.assertIn("adaptive_agent", body)
        self.assertIn("fixed_baseline", body)
        self.assertEqual(body["adaptive_agent"]["policy_violations"], 0)
        self.assertEqual(body["fixed_baseline"]["policy_violations"], 0)
        self.assertIn("recovery_rate_delta", body["ai_lift"])

    def test_live_test_launcher_refuses_mock_provider(self) -> None:
        response = self.client.post("/api/v1/demo/live-test-case")
        self.assertEqual(response.status_code, 409)
        self.assertIn("PAYMENT_PROVIDER=razorpay", response.json()["detail"])

    def test_signed_recovery_and_replay_are_idempotent(self) -> None:
        self.client.post("/api/v1/demo/seed")
        self.client.post("/api/v1/demo/run")
        cases = self.client.get("/api/v1/cases").json()["results"]
        awaiting = next(case for case in cases if case["state"] == "AWAITING_PAYMENT")

        recovered = self.client.post(
            "/api/v1/demo/replay-webhook",
            json={"case_id": awaiting["id"], "paid": True},
        )
        self.assertEqual(recovered.status_code, 200)
        self.assertEqual(recovered.json()["case"]["state"], "RECOVERED")

        replay = self.client.post(
            "/api/v1/demo/replay-webhook",
            json={"case_id": awaiting["id"], "paid": True},
        )
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.json()["reason"], "duplicate event ignored")


if __name__ == "__main__":
    unittest.main()
