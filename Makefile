.DEFAULT_GOAL := help

.PHONY: help
help: ## Show available targets
	@awk 'BEGIN {FS = ":.*## "}; /^[a-zA-Z0-9_.-]+:.*## / {printf "  %-18s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

.PHONY: sync
sync: ## Install the locked dependencies with uv
	uv sync --locked

.PHONY: sample
sample: ## Write the built-in sample picture to output/sample.png
	@mkdir -p output
	uv run --locked paint-by-numbers sample output/sample.png

.PHONY: demo
demo: sample ## Convert the sample picture for ages 6-8 into output/
	uv run --locked paint-by-numbers convert output/sample.png --age 6-8 -o output

.PHONY: test
test: ## Run the fast test suite
	uv run --locked pytest -m "not browser"

.PHONY: test-browser
test-browser: ## Run the real-browser Pyodide test (needs network access)
	uv run --locked --group browser playwright install chromium
	RUN_BROWSER_TESTS=1 uv run --locked --group browser pytest -m browser --no-cov

.PHONY: build-pages
build-pages: ## Build the static site into _site/
	uv run --locked python scripts/build_pages.py

.PHONY: serve-pages
serve-pages: build-pages ## Serve the static site at http://localhost:8000
	uv run --locked python -m http.server 8000 --directory _site

.PHONY: formatter
formatter: ## Check code formatting
	uv run --locked black --check .

.PHONY: type-check
type-check: ## Run static type checking
	uv run --locked mypy src scripts

.PHONY: linter
linter: ## Run the linter
	uv run --locked pylint src scripts

.PHONY: code-quality
code-quality: formatter type-check linter ## Formatting, typing and linting
