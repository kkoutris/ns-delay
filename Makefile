.DEFAULT_GOAL := help
.PHONY: help install lint format test check hooks clean download process

help:  ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

install:  ## Create .venv, install package + dev deps, install git hooks
	uv sync
	uv run pre-commit install

lint:  ## Check code with ruff (no changes)
	uv run ruff check .
	uv run ruff format --check .

format:  ## Auto-fix lint issues and format code
	uv run ruff check --fix .
	uv run ruff format .

test:  ## Run the test suite
	uv run pytest

check:  ## Run every pre-commit hook on every file
	uv run pre-commit run --all-files

download:  ## Download Rijden de Treinen monthly services into data/raw (skips existing)
	uv run python -m ns_delay.download

process:  ## Convert raw monthly CSVs in data/raw to Parquet in data/processed (overwrites)
	uv run python -m ns_delay.process

clean:  ## Remove caches
	rm -rf .ruff_cache .pytest_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
