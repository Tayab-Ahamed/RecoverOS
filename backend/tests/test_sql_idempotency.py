from __future__ import annotations

import unittest

from tests.optional_deps import HAS_SQLALCHEMY, REQUIRES_SQLALCHEMY

if HAS_SQLALCHEMY:  # pragma: no branch - import guard
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.integrations.idempotency import SqlIdempotencyStore
    from app.models.sql import Base


@unittest.skipUnless(HAS_SQLALCHEMY, REQUIRES_SQLALCHEMY)
class SqlIdempotencyTests(unittest.TestCase):
    def test_claim_survives_a_new_store_instance(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        first = Session(engine)
        try:
            self.assertTrue(SqlIdempotencyStore(first).claim("evt_1"))
            first.commit()
        finally:
            first.close()

        second = Session(engine)
        try:
            store = SqlIdempotencyStore(second)
            self.assertTrue(store.seen("evt_1"))
            self.assertFalse(store.claim("evt_1"))
        finally:
            second.close()
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
