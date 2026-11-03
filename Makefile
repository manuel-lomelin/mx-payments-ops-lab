PY ?= python3.11
VENV := .venv
BIN := $(VENV)/bin

.PHONY: setup run test cov lint fmt seed clean

setup:
	$(PY) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -e ".[dev,llm]"

run:
	$(BIN)/streamlit run Home.py

test:
	$(BIN)/pytest

cov:
	$(BIN)/pytest --cov=core --cov-report=term-missing

lint:
	$(BIN)/ruff check .
	$(BIN)/ruff format --check .

fmt:
	$(BIN)/ruff check --fix .
	$(BIN)/ruff format .

seed:
	$(BIN)/python scripts/seed.py

clean:
	rm -rf $(VENV) .pytest_cache .ruff_cache .coverage htmlcov *.egg-info
