SHELL := bash
.DEFAULT_GOAL := help
PY ?= $(shell command -v python3 || command -v python)
# MODE=docker (default) | k3d.  Fixed per run in .state/scenario.env by `make up`.
export MODE ?= docker
export KUBE_CONTEXT ?= k3d-vantage

.PHONY: help cluster up break status logs call time apply hint assert score down clean fix ci

help: ## list targets
	@grep -hE '^[a-z]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-8s %s\n", $$1, $$2}'

cluster: ## k3d only: create the local cluster (install.ps1 does this on Windows)
	@k3d cluster list vantage >/dev/null 2>&1 || k3d cluster create vantage --agents 1 --wait

up: ## per-user mutation + healthy state + start (MODE=docker|k3d)
	@bash scripts/ctl.sh up

break: ## start the incident (clock starts)
	@bash scripts/break.sh

status: ## workloads + last 10 probes
	@bash scripts/ctl.sh status

logs: ## service logs: make logs S=auth|api|prober
	@bash scripts/ctl.sh logs $(or $(S),api)

call: ## fetch a token and call the api, like a client would
	@bash scripts/call.sh

time: ## clock offset of auth and api (chronyc tracking)
	@bash scripts/ctl.sh time

apply: ## load edited .state/{keys,config,clock} into the services
	@bash scripts/ctl.sh apply

hint: ## next hint (time-gated, -5 pts each)
	@bash ../../framework/hints.sh .

assert: ## run public + hidden assertions
	@bash ci/assertions.sh

score: assert ## assertions + score + signed report
	@$(PY) ../../framework/score.py .

fix: ## SPOILER: reference solution
	@bash solution/fix.sh

ci: ## full self-test: up, break, fix, assert, score, down
	@bash ci/run_scenario.sh

down: ## stop (keeps .state for the debrief)
	@bash scripts/ctl.sh down

clean: down ## remove all state and evidence
	@rm -rf .state
