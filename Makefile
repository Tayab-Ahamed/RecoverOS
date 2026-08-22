.PHONY: help test bench demo lint typecheck contracts up down logs migrate scan verify verify-sql

help:
	@echo "test       run the test suite (standard library only, no install needed)"
	@echo "bench      run the 10,000 event benchmark"
	@echo "demo       run the narrated offline demo"
	@echo "verify     test + bench + demo, the full offline proof"
	@echo "lint       ruff"
	@echo "typecheck  mypy"
	@echo "contracts  import-linter architectural contracts"
	@echo "up/down    docker compose"
	@echo "scan       secret scan"

test:
	cd backend && python3 -m unittest discover -s tests -t . -v

bench:
	cd backend && python3 -m scripts.run_benchmark --events 10000 --seed 42

demo:
	cd backend && python3 -m scripts.demo

verify: test bench demo
	@echo ""
	@echo "All offline verification passed."

lint:
	cd backend && ruff check . && ruff format --check .

typecheck:
	cd backend && mypy app

contracts:
	cd backend && lint-imports

up:
	docker compose up --build

down:
	docker compose down -v

logs:
	docker compose logs -f backend

migrate:
	docker compose run --rm migrate

scan:
	./scripts/secret_scan.sh

static:	## Parse every module and check imports, boundaries and money hygiene
	cd backend && python3 -m scripts.static_check

verify-all:	## Everything provable without a network: static, tests, demo, benchmark
	cd backend && python3 -m scripts.verify

verify-quick:	## Same, with a 2,000-event benchmark instead of 10,000
	cd backend && python3 -m scripts.verify --quick

verify-sql:	## Verify migrations and API state survives restart on SQLite
	cd backend && python3 -m scripts.verify_sql
