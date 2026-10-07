# Agent runtime x harness test bed. Harnesses and model aliases are defined in harnesses.toml / models.toml.
#
# Native (no Docker, lowest memory)
#   make native-up                     litellm :4000 + mock LLM :14000 as local processes (pid files in .run/)
#   make test-native HARNESS=strands   conformance suite for one harness (MODEL=mock by default)
#   make qa                            full QA run -> runs/<id>/run.json + report.html
#   make native-down
# Docker / k8s
#   make up HARNESS=strands [MODEL=anthropic] [TRACING=1]    compose: litellm + mock + harness (+ Langfuse)
#   make test HARNESS=strands [RUNTIME=local|k3d|openshell]
#   make k3d-up / k3d-deploy HARNESS=x / k3d-forward HARNESS=x / k3d-down
# Registry
#   make gen | gen-check               regenerate (or verify) litellm.yaml, compose harness services, k8s overlays
#   make new-harness NAME=foo LANG=python|node

-include .env

HARNESS ?= strands
RUNTIME ?= local
MODEL   ?= mock
REG     := python3 scripts/registry.py
HARNESSES = $(shell $(REG) names)

COMPOSE := docker compose -f runtimes/docker-local/docker-compose.yml \
	-f runtimes/docker-local/docker-compose.harnesses.yml --env-file .env $(if $(TRACING),--profile tracing)
export LANGFUSE_BASIC_AUTH := $(shell printf '%s:%s' "$(LANGFUSE_PUBLIC_KEY)" "$(LANGFUSE_SECRET_KEY)" | base64)
export MODEL
ifdef TRACING
export LANGFUSE_HOST ?= http://localhost:3000
export LANGFUSE_PUBLIC_KEY LANGFUSE_SECRET_KEY
export OTEL_ENDPOINT := http://langfuse-web:3000/api/public/otel
endif

PURPOSE_local := docker_local
PURPOSE_k3d := k3d
PURPOSE_openshell := openshell
TARGET_URL ?= http://localhost:$(shell $(REG) port $(HARNESS) $(PURPOSE_$(RUNTIME)))

.PHONY: help gen gen-check new-harness native-up native-down test-native infra up down build logs test \
	k3d-up k3d-down k3d-deploy k3d-forward qa qa-report qa-compare qa-open

help:
	@sed -n '1,/^$$/p' Makefile | sed 's/^# \{0,1\}//'

# ---------------------------------------------------------------- registry
gen:
	$(REG) gen

gen-check:   # CI: fails if generated files are out of date
	$(REG) gen --check

new-harness:
	@test -n "$(NAME)" -a -n "$(LANG)" || (echo "usage: make new-harness NAME=foo LANG=python|node" && exit 2)
	$(REG) new-harness $(NAME) $(LANG)

# ---------------------------------------------------------------- native (no Docker)
native-up:
	scripts/native.sh up

native-down:
	scripts/native.sh down

test-native:   # one harness, natively, conformance suite only
	python3 qa/run.py --models $(MODEL) --suites conformance --harnesses $(HARNESS) --no-report

# ---------------------------------------------------------------- docker compose
infra:
	$(COMPOSE) up -d --wait

up: infra
	$(COMPOSE) --profile $(HARNESS) up -d --build --wait

down:
	$(COMPOSE) --profile all --profile tracing down

build:
	$(COMPOSE) --profile $(HARNESS) build

logs:
	$(COMPOSE) --profile all logs -f $(if $(SVC),$(SVC),$(HARNESS))

test:
	cd tests && TARGET_URL=$(TARGET_URL) uv run pytest

# ---------------------------------------------------------------- k3d (dedicated cluster; never touches other kube contexts)
K3D_CLUSTER := agentrt
KCTX := --context k3d-$(K3D_CLUSTER)
KUSTOMIZE := kubectl kustomize --load-restrictor LoadRestrictionsNone

k3d-up:
	k3d cluster list $(K3D_CLUSTER) >/dev/null 2>&1 || k3d cluster create $(K3D_CLUSTER) --servers 1 --agents 0 \
		--k3s-arg '--disable=traefik@server:0' --kubeconfig-switch-context=false
	$(COMPOSE) build mock-llm
	k3d image import -c $(K3D_CLUSTER) agentrt/mock-llm:dev
	$(KUSTOMIZE) runtimes/k8s/base | kubectl $(KCTX) apply -f -
	kubectl $(KCTX) -n agentrt rollout status deploy/litellm deploy/mock-llm --timeout=300s

k3d-deploy:
	$(COMPOSE) --profile $(HARNESS) build $(HARNESS)
	k3d image import -c $(K3D_CLUSTER) agentrt/$(HARNESS):dev
	$(KUSTOMIZE) runtimes/k8s/overlays/$(HARNESS) | kubectl $(KCTX) apply -f -
	kubectl $(KCTX) -n agentrt rollout restart deploy/$(HARNESS)-agent
	kubectl $(KCTX) -n agentrt rollout status deploy/$(HARNESS)-agent --timeout=300s

k3d-forward:   # foreground; second terminal: make test RUNTIME=k3d HARNESS=...
	kubectl $(KCTX) -n agentrt port-forward svc/$(HARNESS)-agent $(shell $(REG) port $(HARNESS) k3d):8080

k3d-down:
	k3d cluster delete $(K3D_CLUSTER)

# ---------------------------------------------------------------- QA (runs/<id>/run.json + report.html)
# Needs `make native-up` (litellm :4000 + mock :14000). Default models: default_qa = true in models.toml.
QA_MODELS ?= $(shell $(REG) models --qa --configured)
QA_SUITES ?= conformance,audit,inspect,supply,safety
QA_EPOCHS ?= 3

qa:
	python3 qa/run.py --models $(QA_MODELS) --suites $(QA_SUITES) --epochs $(QA_EPOCHS) $(QA_ARGS)

qa-report:   # re-render RUN=runs/<id> (default: latest run)
	python3 qa/report.py $(RUN)

qa-compare:  # OLD=runs/<a> NEW=runs/<b> (default: previous vs latest); exit 1 on regression
	python3 qa/compare.py $(OLD) $(NEW)

qa-open:
	open runs/index.html
