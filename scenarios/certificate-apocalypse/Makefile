SHELL := bash
.DEFAULT_GOAL := help
PY ?= $(shell command -v python3 || command -v python)
COMPOSE = docker compose -p vantage-ca --env-file .state/scenario.env -f docker-compose.yml

.PHONY: help up break status probe hint assert score down clean load fix ci

help: ## list targets
	@grep -hE '^[a-z]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-8s %s\n", $$1, $$2}'

up: ## per-user mutation + healthy PKI + start stack
	@bash scripts/init.sh
	@$(COMPOSE) up -d --wait
	@bash -c 'source scripts/lib.sh; require_state; timeline up'

break: ## start the incident (clock starts)
	@bash scripts/break.sh

status: ## containers + last 10 probes
	@$(COMPOSE) ps --format 'table {{.Service}}\t{{.State}}\t{{.Status}}'
	@tail -n 10 .state/evidence/probes.jsonl 2>/dev/null || true

probe: ## inspect edge TLS (make probe MESH=1 for the mTLS hop)
	@bash scripts/probe_tls.sh $(if $(MESH),mesh,)

hint: ## next hint (time-gated, -5 pts each)
	@bash scripts/hints.sh

assert: ## run public + hidden assertions
	@bash ci/assertions.sh

score: assert ## assertions + score + signed report
	@$(PY) ci/score.py

load: ## optional k6 load against the gateway (needs grafana/k6 image)
	@source .state/scenario.env && docker run --rm -i --network vantage-ca_mesh \
	  -e TARGET=https://$$VANTAGE_HOST:8443/healthz grafana/k6 run - < load/k6_load.js

fix: ## SPOILER: reference solution
	@bash solution/fix.sh

ci: ## full self-test: up, break, fix, assert, score, down
	@bash ci/run_scenario.sh

down: ## stop the stack (keeps .state for the debrief)
	@[ -f .state/scenario.env ] && $(COMPOSE) down -t 2 --remove-orphans || true
	@rm -f .state/broken

clean: down ## remove all state, PKI and evidence
	@rm -rf .state
