.PHONY: install test lint format typecheck rust-check check build

install:
	uv sync --group dev --locked
	VIRTUAL_ENV=$$(pwd)/.venv uvx maturin==1.15.0 develop --locked --release

test:
	uv run pytest tests/ -q

lint:
	uv run ruff check python/ tests/ scripts/
	uv run ruff format --check python/ tests/ scripts/

format:
	uv run ruff check --fix python/ tests/ scripts/
	uv run ruff format python/ tests/ scripts/
	cargo fmt

typecheck:
	uv run pyright python/ tests/ scripts/

rust-check:
	cargo fmt --check
	cargo clippy --locked --all-targets --all-features -- -D warnings

check: lint typecheck rust-check test

build:
	uv build
