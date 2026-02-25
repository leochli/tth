.PHONY: dev install test lint fmt demo phase phase-live test-interactive demo-interactive

install:
	uv sync --extra dev

dev:
	uv run uvicorn src.tth.api.main:app --reload --port 8000

test:
	uv run pytest tests/ -v

lint:
	uv run ruff check src/ tests/
	uv run mypy src/

fmt:
	uv run ruff format src/ tests/

demo:
	uv run python scripts/demo.py

phase:
	.venv/bin/python scripts/run_phased_tests.py

phase-live:
	.venv/bin/python scripts/run_phased_tests.py --live

test-interactive:
	uv run python scripts/interactive_test.py "$(MESSAGE)"

demo-interactive:
	uv run python scripts/interactive_demo.py
