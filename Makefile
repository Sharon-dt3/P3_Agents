install:
	uv sync

seed:
	uv run python scripts/seed.py

run:
	uv run python scripts/run_daily.py

walkthrough:
	uv run python scripts/run_walkthrough.py

test:
	uv run pytest

lint:
	uv run ruff check .

.PHONY: install seed run walkthrough test lint
