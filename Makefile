PYTHON ?= .venv/bin/python
COVERAGE ?= .venv/bin/coverage
LINT_IMPORTS ?= .venv/bin/lint-imports
QUALITY_PATHS := app evaluation tests scripts
STRICT_MYPY_MODULES := app/workflow_support/filtering.py app/workflow_support/identifiers.py app/lexical_tokens.py app/chroma_collections.py app/retrieval_errors.py app/source_policy.py

.PHONY: check lint format-check type-check imports test

check: lint format-check type-check imports test

lint:
	$(PYTHON) scripts/check_ruff_lint_ratchet.py

format-check:
	$(PYTHON) scripts/check_ruff_format_ratchet.py

type-check:
	$(PYTHON) -m mypy --strict $(STRICT_MYPY_MODULES)
	$(PYTHON) scripts/check_mypy_ratchet.py

imports:
	$(LINT_IMPORTS) --no-cache

test:
	$(COVERAGE) erase
	$(COVERAGE) run -m pytest tests -q
	$(COVERAGE) report
	$(COVERAGE) xml
