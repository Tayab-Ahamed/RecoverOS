.PHONY: help test bench demo lint typecheck contracts up down logs migrate scan verify

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
