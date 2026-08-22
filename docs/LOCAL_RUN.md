# Local reviewer run

This path runs the product without Docker, Postgres, Redis, payment keys, or
an external model. It is the recommended first run for a reviewer.

## Backend

Terminal 1:

```bash
cd backend
python -m pip install -r requirements.txt
$env:PAYMENT_PROVIDER="mock"       # PowerShell
$env:LLM_PROVIDER="mock"
$env:ENABLE_LOCAL_WEBHOOK_REPLAY="true"
uvicorn app.main:app --reload --port 8000
```

On macOS/Linux, use `export` instead of `$env:`.

## Frontend

Terminal 2:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`, click **Seed and run**, and follow the 90-second
script in `docs/SUBMISSION.md`.

## Proof commands

```bash
cd backend
python -m scripts.verify --quick
python -m scripts.verify_sql
```

The first command proves the governed control loop and invariants. The second
proves that the database-backed API path restores its 40-case dataset and audit
trail after a container reset using SQLite.
