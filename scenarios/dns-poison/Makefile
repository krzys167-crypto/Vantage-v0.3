SHELL := bash
.DEFAULT_GOAL := help
PY ?= $(shell command -v python3 || command -v python)
# MODE=docker (default) | k3d.  Fixed per run in .state/scenario.env by `make up`.
export MODE ?= docker
export KUBE_CONTEXT ?= k3d-vantage

.PHONY: help cluster up break status logs call dig resolve zone reload flush apply hint assert score submit postmortem lint-postmortem debrief down clean fix ci

help: ## list targets
	@grep -hE '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-15s %s\n", $$1, $$2}'

cluster: ## k3d only: create the local cluster (install.ps1 does this on Windows)
	@k3d cluster list vantage >/dev/null 2>&1 || k3d cluster create vantage --agents 1 --wait
	@bash ../../framework/k3d_preload.sh vantage

up: ## per-user mutation + healthy state + start (MODE=docker|k3d)
	@bash scripts/ctl.sh up

break: ## start the incident (clock starts)
	@bash scripts/break.sh

status: ## workloads + last 10 probes
	@bash scripts/ctl.sh status

logs: ## service logs: make logs S=api|dns|payments|legacy|fx|prober
	@bash scripts/ctl.sh logs $(or $(S),api)

call: ## one checkout through the api, like a client would
	@bash scripts/ctl.sh call

dig: ## ask the authoritative dns: make dig N=payments.internal
	@bash scripts/ctl.sh dig $(or $(N),payments.internal)

resolve: ## what the api's resolver believes: make resolve N=fx.internal
	@bash scripts/ctl.sh resolve $(or $(N),payments.internal)

zone: ## zone currently served by the dns (serial + records)
	@bash scripts/ctl.sh zone

reload: ## ask the dns to load .state/zone/internal.zone (needs a higher $$SERIAL)
	@bash scripts/ctl.sh reload

flush: ## flush the api's resolver cache
	@bash scripts/ctl.sh flush

apply: ## load edited .state/config into the api
	@bash scripts/ctl.sh apply

hint: ## next hint (time-gated, -5 pts each)
	@bash ../../framework/hints.sh .

assert: ## run public + hidden assertions
	@bash ci/assertions.sh

score: assert ## assertions + score + signed report
	@$(PY) ../../framework/score.py .

submit: assert ## graded run (GRADER_URL set): server scores and signs
	@bash ../../framework/submit.sh .

PM ?= postmortem.md
postmortem: ## after submit: post-mortem template for this attempt (postmortem.md), cause catalog inside
	@$(PY) ../../framework/postmortem.py template . $(PM)

lint-postmortem: ## check postmortem.md against the grader's format rules (free, nothing is sent)
	@$(PY) ../../framework/postmortem.py lint . $(PM)

debrief: ## sign postmortem.md with your key and send it: checked against the evidence, once per attempt
	@$(PY) ../../framework/postmortem.py submit . $(PM)

fix: ## SPOILER: reference solution
	@bash solution/fix.sh

ci: ## full self-test: up, break, fix, assert, score, down
	@bash ci/run_scenario.sh

down: ## stop (keeps .state for the debrief)
	@bash scripts/ctl.sh down

clean: down ## remove all state and evidence
	@rm -rf .state
