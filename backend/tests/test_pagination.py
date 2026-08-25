"""Tests for the cases list endpoint pagination and filtering."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("PAYMENT_PROVIDER", "mock")
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("ENABLE_LOCAL_WEBHOOK_REPLAY", "true")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


class PaginationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        # Reset and seed demo data (40 cases)
        self.client.post("/api/v1/demo/reset")
        self.client.post("/api/v1/demo/seed")
        self.client.post("/api/v1/demo/run")

    # ------------------------------------------------------------------ #
    # 1. Default pagination returns page 1 with page_size 50
    # ------------------------------------------------------------------ #

    def test_cases_default_pagination(self) -> None:
        resp = self.client.get("/api/v1/cases")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()

        # All four pagination keys must be present
        self.assertIn("results", body)
        self.assertIn("total", body)
        self.assertIn("page", body)
        self.assertIn("page_size", body)
        self.assertIn("pages", body)

        # Default values
        self.assertEqual(body["page"], 1)
        self.assertEqual(body["page_size"], 50)

        # 40 demo cases seeded; all fit on page 1
        self.assertEqual(body["total"], 40)
        self.assertEqual(len(body["results"]), 40)

        # Each result must look like a full case object
        first = body["results"][0]
        self.assertIn("id", first)
        self.assertIn("state", first)
        self.assertIn("revenue_at_risk", first)

    # ------------------------------------------------------------------ #
    # 2. Filter by state=RECOVERED returns only recovered cases
    # ------------------------------------------------------------------ #

    def test_cases_filter_by_state(self) -> None:
        # First check how many RECOVERED cases exist
        all_resp = self.client.get("/api/v1/cases")
        all_cases = all_resp.json()["results"]
        expected_recovered = [c for c in all_cases if c["state"] == "RECOVERED"]

        resp = self.client.get("/api/v1/cases?state=RECOVERED")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()

        self.assertEqual(body["total"], len(expected_recovered))
        for case in body["results"]:
            self.assertEqual(case["state"], "RECOVERED")

    # ------------------------------------------------------------------ #
    # 3. Page 2 with small page_size works correctly
    # ------------------------------------------------------------------ #

    def test_cases_page_2(self) -> None:
        page_size = 10
        # Page 1
        resp1 = self.client.get(f"/api/v1/cases?page=1&page_size={page_size}")
        self.assertEqual(resp1.status_code, 200)
        body1 = resp1.json()

        # Page 2
        resp2 = self.client.get(f"/api/v1/cases?page=2&page_size={page_size}")
        self.assertEqual(resp2.status_code, 200)
        body2 = resp2.json()

        self.assertEqual(body1["total"], body2["total"])   # same total
        self.assertEqual(body2["page"], 2)
        self.assertEqual(body2["page_size"], page_size)

        # Results on page 2 should not overlap with page 1
        ids_page1 = {c["id"] for c in body1["results"]}
        ids_page2 = {c["id"] for c in body2["results"]}
        self.assertEqual(len(ids_page1 & ids_page2), 0, "Pages must not overlap")

        # Page 2 should have items
        self.assertGreater(len(body2["results"]), 0)

        # pages count is correct
        import math
        expected_pages = math.ceil(body1["total"] / page_size)
        self.assertEqual(body1["pages"], expected_pages)


if __name__ == "__main__":
    unittest.main()
