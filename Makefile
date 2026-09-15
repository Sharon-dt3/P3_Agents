install:
	uv sync

seed:
	uv run python scripts/seed.py

run:
	uv run python scripts/run_daily.py

test:
	uv run pytest

lint:
	uv run ruff check .

.PHONY: install seed run test lint
