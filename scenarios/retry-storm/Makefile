SHELL := bash
.DEFAULT_GOAL := help
PY ?= $(shell command -v python3 || command -v python)
# MODE=docker (default) | k3d.  Fixed per run in .state/scenario.env by `make up`.
export MODE ?= docker
export KUBE_CONTEXT ?= k3d-vantage

.PHONY: help cluster up break status logs call metrics apply hint assert score submit down clean fix ci

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

logs: ## service logs: make logs S=api|inventory|loadgen|prober
	@bash scripts/ctl.sh logs $(or $(S),api)

call: ## one checkout through the api, with its latency
	@bash scripts/ctl.sh call

metrics: ## inventory + api metrics over the last W seconds: make metrics W=30
	@bash scripts/ctl.sh metrics $(or $(W),30)

apply: ## load edited .state/config into the services (k3d: ConfigMap + rollout)
	@bash scripts/ctl.sh apply

hint: ## next hint (time-gated, -5 pts each)
	@bash ../../framework/hints.sh .

assert: ## run public + hidden assertions
	@bash ci/assertions.sh

score: assert ## assertions + score + signed report
	@$(PY) ../../framework/score.py .

submit: assert ## graded run (GRADER_URL set): server scores and signs
	@bash ../../framework/submit.sh .

fix: ## SPOILER: reference solution
	@bash solution/fix.sh

ci: ## full self-test: up, break, fix, assert, score, down
	@bash ci/run_scenario.sh

down: ## stop (keeps .state for the debrief)
	@bash scripts/ctl.sh down

clean: down ## remove all state and evidence
	@rm -rf .state
