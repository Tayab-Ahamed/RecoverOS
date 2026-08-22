"""Verify migrations and API state survival using a temporary SQLite database."""

from __future__ import annotations

import os
import uuid
from pathlib import Path


def main() -> None:
    db = Path.cwd() / f".recoveros-sql-{uuid.uuid4().hex}.db"
    try:
        os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{db.as_posix()}"
        os.environ["PAYMENT_PROVIDER"] = "mock"
        os.environ["LLM_PROVIDER"] = "mock"
        os.environ["ENABLE_LOCAL_WEBHOOK_REPLAY"] = "true"

        from alembic import command
        from alembic.config import Config

        config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
        command.upgrade(config, "head")

        from fastapi.testclient import TestClient
        from app.api.deps import reset_container, restart_container
        from app.main import app

        client = TestClient(app)
        assert client.post("/api/v1/demo/seed").status_code == 200
        assert client.post("/api/v1/demo/run").status_code == 200
        before = client.get("/api/v1/cases").json()["total"]
        case_id = client.get("/api/v1/cases").json()["results"][0]["id"]
        audit_before = len(client.get(f"/api/v1/cases/{case_id}/audit").json()["results"])
        restart_container()
        after = client.get("/api/v1/cases").json()["total"]
        audit_after = len(client.get(f"/api/v1/cases/{case_id}/audit").json()["results"])
        assert before == 40 and after == 40 and audit_after == audit_before and audit_after > 0
        print(f"SQL API restart check passed: {before} -> {after} cases, {audit_before} -> {audit_after} audit records")
    finally:
        reset_container()
        from app.core.db import get_engine, get_session_factory

        get_session_factory.cache_clear()
        engine = get_engine()
        engine.dispose()
        get_engine.cache_clear()
        if db.exists():
            db.unlink()


if __name__ == "__main__":
    main()
