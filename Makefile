.PHONY: install test test-unit test-prop test-concurrency lint format typecheck bench run docker-up docker-down clean

PYTHON ?= .venv/bin/python
PIP ?= .venv/bin/pip
PYTEST ?= .venv/bin/pytest
RUFF ?= .venv/bin/ruff
MYPY ?= .venv/bin/mypy
UVICORN ?= .venv/bin/uvicorn

install:
	python3 -m venv .venv
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

test:
	$(PYTEST) tests -v --cov=src --cov-report=term-missing --cov-report=html:htmlcov --cov-fail-under=85

test-unit:
	$(PYTEST) tests/unit -v

test-prop:
	$(PYTEST) tests/property -v

test-concurrency:
	$(PYTEST) tests/concurrency -v

lint:
	$(RUFF) check src tests scripts

format:
	$(RUFF) format src tests scripts

typecheck:
	$(MYPY) src

bench:
	$(PYTHON) scripts/bench.py

run:
	$(UVICORN) src.main:app --host 0.0.0.0 --port 8000 --reload

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down -v

clean:
	rm -rf .pytest_cache .coverage htmlcov .mypy_cache .ruff_cache __pycache__ dist build *.egg-info
