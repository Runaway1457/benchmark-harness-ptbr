.PHONY: install lint type security test check run site clean

UV ?= uv

install:
	$(UV) sync --extra dev

lint:
	$(UV) run ruff format --check ptbr_benchmark tests
	$(UV) run ruff check ptbr_benchmark tests

type:
	$(UV) run mypy

security:
	$(UV) run bandit -q -r ptbr_benchmark -c pyproject.toml
	@audit_file=$$(mktemp); \
	trap 'rm -f "$$audit_file"' EXIT; \
	$(UV) export --frozen --no-dev --no-emit-project --format requirements.txt \
		--output-file "$$audit_file"; \
	$(UV) run pip-audit --strict --requirement "$$audit_file"

test:
	$(UV) run pytest

check: lint type security test

run:
	$(UV) run ptbr-benchmark validate
	$(UV) run ptbr-benchmark run --provider baseline --prompt minimal --repetitions 3
	$(UV) run ptbr-benchmark run --provider baseline --prompt optimized --repetitions 3
	$(UV) run ptbr-benchmark report

site:
	$(UV) run ptbr-benchmark report

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov dist build
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
