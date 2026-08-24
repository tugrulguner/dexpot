.PHONY: lint typecheck test format check build clean

lint:
	uv run ruff check src tests
	uv run ruff format --check src tests

typecheck:
	uv run pyright

test:
	uv run pytest -q

format:
	uv run ruff check --fix src tests
	uv run ruff format src tests

check: lint test

build:
	uv build

clean:
	rm -rf dist .pytest_cache .ruff_cache .coverage
