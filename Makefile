.PHONY: install test run smoke compose-up compose-down

install:
	python3 -m pip install -e ".[dev]"

test:
	pytest

run:
	python3 -m civic_alert_relay

# Start the process, hit /healthz, then exit.
smoke:
	@./scripts/smoke.sh

compose-up:
	docker compose up --build -d

compose-down:
	docker compose down
