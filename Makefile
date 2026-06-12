.PHONY: test test-unit test-integration lint typecheck format check clean silver

test: test-unit
	@echo "All unit tests passed."

test-unit:
	uv run pytest --cov=src/omc_analytics --cov-report=term-missing -m "not integration"

test-integration:
	uv run pytest tests/integration/ -v

lint:
	uv run ruff check src/ tests/

typecheck:
	uv run mypy src/omc_analytics

format:
	uv run black src/ tests/

check: lint typecheck test

silver:  ## Run dbt build for the Silver layer
	uv run dbt build --project-dir dbt_project