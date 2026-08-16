SHELL := /bin/bash
PY    ?= python3.12
VENV  ?= .venv
BIN   := $(VENV)/bin

ifeq ($(OS),Windows_NT)
BIN := $(VENV)/Scripts
endif

.PHONY: help setup setup-postgres migrate migrate-down seed-demo seed-demo-reset test test-cov \
        reset-db revision check check-schema doctor clean

help:
	@echo "make setup       - cria venv e instala dependencias (Python 3.12)"
	@echo "make migrate     - aplica as migrations Alembic (alembic upgrade head)"
	@echo "make seed-demo   - popula o dataset DEMO sintetico"
	@echo "make test        - roda a suite pytest"
	@echo "make check       - check-schema + migrate + seed-demo + test (gate do Sprint 1)"
	@echo "make check-schema- verifica models x migration sem instalar dependencias"
	@echo "make doctor      - diagnostico de configuracao e conectividade do banco"
	@echo "make revision m='msg' - nova revisao Alembic"
	@echo "make reset-db    - APAGA o SQLite local e remigra"

$(VENV):
	$(PY) -m venv $(VENV)

setup: $(VENV)
	$(BIN)/python -m pip install --upgrade pip
	$(BIN)/python -m pip install -e ".[dev]"
	@mkdir -p data
	@test -f .env || cp .env.example .env
	@echo "OK. Proximo passo: make migrate"

setup-postgres: $(VENV)
	$(BIN)/python -m pip install --upgrade pip
	$(BIN)/python -m pip install -e ".[dev,postgres]"

migrate:
	$(BIN)/alembic upgrade head

migrate-down:
	$(BIN)/alembic downgrade -1

revision:
	@test -n "$(m)" || (echo "uso: make revision m='mensagem'" && exit 1)
	$(BIN)/alembic revision -m "$(m)"

seed-demo:
	$(BIN)/python -m copilot.seed.demo

seed-demo-reset:
	$(BIN)/python -m copilot.seed.demo --reset

test:
	$(BIN)/pytest

test-cov:
	$(BIN)/pytest --cov=copilot --cov-report=term-missing

doctor:
	$(BIN)/python -m copilot.scripts_entry doctor

# Verificacao estatica models x migration. Roda com Python puro, sem venv.
check-schema:
	$(PY) scripts/check_schema_consistency.py

check: check-schema migrate seed-demo test
	@echo "Gate do Sprint 1: OK"

reset-db:
	rm -f data/copilot.db
	$(MAKE) migrate

clean:
	rm -rf .pytest_cache .ruff_cache **/__pycache__ .coverage
