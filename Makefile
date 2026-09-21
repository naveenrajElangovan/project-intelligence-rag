PYTHON ?= .venv/bin/python
COVERAGE ?= .venv/bin/coverage
LINT_IMPORTS ?= .venv/bin/lint-imports
DEPTRY ?= .venv/bin/deptry
.DEFAULT_GOAL := help
QUALITY_PATHS := app evaluation tests scripts
WORKSPACE_ROOT ?= $(abspath $(CURDIR)/..)
BACKEND_DIR ?= $(WORKSPACE_ROOT)/project-intelligence-backend
COMPOSE_FILE ?= $(BACKEND_DIR)/docker-compose.yml
COMPOSE := docker compose --project-directory $(BACKEND_DIR) --file $(COMPOSE_FILE)
CORE_SERVICES := chroma mongodb rag ingestion api atlassian

.PHONY: check lint format-check type-check imports dependencies test help up down stop restart status logs \
	services-up services-down services-stop services-restart services-status services-logs \
	all-up all-down all-stop all-restart all-status all-logs \
	chroma-up chroma-down mongodb-up mongodb-down rag-up rag-down \
	ingestion-up ingestion-down api-up api-down atlassian-up atlassian-down

help:
	@echo "Combined service targets:"
	@echo "  make up                Alias for services-up"
	@echo "  make down              Alias for services-down"
	@echo "  make services-up       Build missing images and start every long-running service"
	@echo "  make services-down     Stop and remove the complete Compose stack"
	@echo "  make services-stop     Stop the stack without removing containers"
	@echo "  make services-restart  Restart every long-running service"
	@echo "  make services-status   Show service state and published ports"
	@echo "  make services-logs     Follow logs for all long-running services"
	@echo ""
	@echo "Per-service targets (SERVICE: $(CORE_SERVICES)):"
	@echo "  make up-SERVICE        Start one service and its dependencies"
	@echo "  make down-SERVICE      Stop and remove one service container"
	@echo "  make stop-SERVICE      Stop one service without removing it"
	@echo "  make restart-SERVICE   Restart one service"
	@echo "  make status-SERVICE    Show one service's state"
	@echo "  make logs-SERVICE      Follow one service's logs"

up: services-up
down: services-down
stop: services-stop
restart: services-restart
status: services-status
logs: services-logs

services-up:
	$(COMPOSE) up -d $(CORE_SERVICES)

services-down:
	$(COMPOSE) down

services-stop:
	$(COMPOSE) stop $(CORE_SERVICES)

services-restart:
	$(COMPOSE) restart $(CORE_SERVICES)

services-status:
	$(COMPOSE) ps -a

services-logs:
	$(COMPOSE) logs --follow $(CORE_SERVICES)

all-up: services-up
all-down: services-down
all-stop: services-stop
all-restart: services-restart
all-status: services-status
all-logs: services-logs

up-%:
	$(COMPOSE) up -d $*

down-%:
	$(COMPOSE) rm --stop --force $*

stop-%:
	$(COMPOSE) stop $*

restart-%:
	$(COMPOSE) restart $*

status-%:
	$(COMPOSE) ps -a $*

logs-%:
	$(COMPOSE) logs --follow $*

chroma-up: up-chroma
chroma-down: down-chroma
mongodb-up: up-mongodb
mongodb-down: down-mongodb
rag-up: up-rag
rag-down: down-rag
ingestion-up: up-ingestion
ingestion-down: down-ingestion
api-up: up-api
api-down: down-api
atlassian-up: up-atlassian
atlassian-down: down-atlassian

check: lint format-check type-check imports dependencies test

lint:
	$(PYTHON) -m ruff check $(QUALITY_PATHS) tools labs

format-check:
	$(PYTHON) -m ruff format --check $(QUALITY_PATHS) tools labs

type-check:
	$(PYTHON) -m mypy app

imports:
	$(LINT_IMPORTS) --no-cache

dependencies:
	$(DEPTRY) . --exclude '.venv|\.git|\.quality-runs|corpora' --optional-dependencies-dev-groups dev --per-rule-ignores 'DEP001=run_retrieval_eval|build_gold_suites|phoenix_client|score|starter,DEP002=uvicorn|coverage|deptry|import-linter|mypy|pre-commit|ruff|langchain-community,DEP004=pytest'

test:
	$(COVERAGE) erase
	$(COVERAGE) run -m pytest tests -q
	$(COVERAGE) report
	$(COVERAGE) xml
