install:
	uv sync

seed:
	uv run python scripts/seed.py

run:
	uv run python scripts/run_daily.py

walkthrough:
	uv run python scripts/run_walkthrough.py

copilot-api:
	PYTHONPATH=src uv run uvicorn p1.api.copilot_studio_api:app --reload --reload-dir src

test:
	uv run pytest

lint:
	uv run ruff check .

.PHONY: install seed run walkthrough copilot-api test lint
