# sdk-kit development: the generator (Python, stdlib only at runtime) and its tests.
#   make test        unit tests + coverage gate (>= 90 % lines and >= 90 % branches)
#   make lint        ruff + mypy --strict
#   make demo        render the demo repository into build/demo
#   make render-all  render every service of spec/services.json into build/<key>
#   make check-all   render-all, then "sdk-kit check" on every rendered repository

PYTHON ?= python3
VENV ?= .venv
BUILD ?= build
COVER_MIN ?= 90
BIN := $(VENV)/bin
STAMP := $(VENV)/.sdk-kit-dev

.PHONY: all venv test coverage lint format demo render-all check-all clean

all: lint test

$(STAMP): pyproject.toml
	$(PYTHON) -m venv $(VENV)
	$(BIN)/python -m pip install --quiet --upgrade pip
	$(BIN)/python -m pip install --quiet pytest pytest-cov ruff mypy
	touch $(STAMP)

venv: $(STAMP)

test: $(STAMP)
	@mkdir -p $(BUILD)
	$(BIN)/python -m pytest --cov=sdk_kit --cov-branch --cov-report=term --cov-report=json:$(BUILD)/coverage.json
	@$(BIN)/python -c 'import json,sys; t=json.load(open("$(BUILD)/coverage.json"))["totals"]; \
	l=100*t["covered_lines"]/max(t["num_statements"],1); b=100*t["covered_branches"]/max(t["num_branches"],1); \
	print(f"coverage: lines {l:.2f}% branches {b:.2f}% (gate $(COVER_MIN)%)"); \
	sys.exit(0 if l>=$(COVER_MIN) and b>=$(COVER_MIN) else 1)'

coverage: test

lint: $(STAMP)
	$(BIN)/ruff check sdk_kit tests
	$(BIN)/ruff format --check sdk_kit tests
	$(BIN)/mypy

format: $(STAMP)
	$(BIN)/ruff format sdk_kit tests
	$(BIN)/ruff check --fix sdk_kit tests

demo:
	bin/sdk-kit new demo --dest $(BUILD)/demo --force

render-all:
	@set -e; for key in $$(bin/sdk-kit list | awk 'NR>1 {print $$1}'); do \
	  bin/sdk-kit new $$key --dest $(BUILD)/$$key --force >/dev/null; \
	  echo "rendered $(BUILD)/$$key"; \
	done

check-all: render-all
	@status=0; for key in $$(bin/sdk-kit list | awk 'NR>1 {print $$1}'); do \
	  echo "==> $$key"; bin/sdk-kit check --dest $(BUILD)/$$key || status=1; \
	done; exit $$status

clean:
	rm -rf -- "$(BUILD)" .pytest_cache .ruff_cache .mypy_cache .coverage
	find sdk_kit tests -name __pycache__ -type d -prune -exec rm -rf {} +
