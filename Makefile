.PHONY: install test lint format typecheck check changelog-draft changelog build clean

install:
	uv sync --all-extras

test:
	uv sync --all-extras --reinstall-package dexpot
	uv run pytest tests/ -v --cov=src/dexpot --cov-report=term-missing --cov-fail-under=65

lint:
	uv run ruff check src/ tests/ examples/ scripts/
	uv run ruff format --check src/ tests/ examples/ scripts/

format:
	uv run ruff check --fix src/ tests/ examples/ scripts/
	uv run ruff format src/ tests/ examples/ scripts/

typecheck:
	uv run pyright src/ tests/ examples/ scripts/

check: lint typecheck test

changelog-draft:
	uv run towncrier build --draft --version $$(uv version --short)

changelog:
	uv run towncrier build --yes --version $$(uv version --short)

build:
	uv build

clean:
	rm -rf dist/ build/ *.egg-info .pytest_cache .ruff_cache .coverage htmlcov/
	find . -type d -name __pycache__ -exec rm -rf {} +
