from __future__ import annotations

import unittest

from app.domain.entities import DataProvenance, Diagnosis, FailureReason
from app.domain.states import Actor
from tests.factories import case, customer, event, evidence
from tests.optional_deps import HAS_SQLALCHEMY, REQUIRES_SQLALCHEMY

if HAS_SQLALCHEMY:  # pragma: no branch - import guard
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.models.sql import Base
    from app.repositories.sql import SqlCaseRepository, SqlCustomerRepository


@unittest.skipUnless(HAS_SQLALCHEMY, REQUIRES_SQLALCHEMY)
class SqlRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def test_customer_and_case_round_trip(self) -> None:
        customer_repo = SqlCustomerRepository(self.session)
        case_repo = SqlCaseRepository(self.session)
        person = customer(provenance=DataProvenance.LIVE_TEST_MODE)
        ev = event(metadata={"source": "test"}, provenance=DataProvenance.LIVE_TEST_MODE)
        item = case(ev=ev, provenance=DataProvenance.LIVE_TEST_MODE)
        item.diagnosis = Diagnosis(
            cause=FailureReason.CARD_EXPIRED,
            recovery_probability=0.84,
            rationale="test rationale",
            produced_by=Actor.DIAGNOSIS_AGENT,
            is_llm_output=False,
            confidence=0.9,
        )

        customer_repo.add(person)
        case_repo.add(item)
        self.session.commit()

        loaded = SqlCaseRepository(self.session).get(item.id)
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.event.metadata, {"source": "test"})
        self.assertEqual(loaded.event.amount, item.event.amount)
        self.assertEqual(loaded.diagnosis, item.diagnosis)
        self.assertEqual(SqlCustomerRepository(self.session).get(person.id), person)

    def test_recovered_case_round_trip_persists_payment_evidence(self) -> None:
        customer_repo = SqlCustomerRepository(self.session)
        case_repo = SqlCaseRepository(self.session)
        person = customer()
        item = case()
        item.evidence = evidence()
        item.recovered_amount = item.evidence.amount
        customer_repo.add(person)
        case_repo.add(item)
        self.session.commit()

        loaded = case_repo.get(item.id)
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.evidence, item.evidence)
        self.assertEqual(loaded.recovered_amount, item.recovered_amount)


if __name__ == "__main__":
    unittest.main()
