# Local dev recipe for the AeyeOps fork of google_workspace_mcp.
# Run `make` (no args) to list supported targets.
#
# Fail-fast semantics: every recipe runs under `bash -euo pipefail` so any
# unchecked failure aborts the target immediately instead of silently
# continuing. Chained targets (e.g. build-and-install) inherit this: the
# first failing prerequisite stops the whole chain.

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
MAKEFLAGS += --warn-undefined-variables --no-builtin-rules
.DEFAULT_GOAL := help

VENV_BIN := $(CURDIR)/.venv/bin
WORKSPACE_MCP := $(VENV_BIN)/workspace-mcp

.PHONY: help clean install test lint format \
        mcp-path mcp-register mcp-unregister \
        run run-http build-and-install

help: ## Show this help (default target)
	@awk 'BEGIN {FS = ":.*##"; printf "\nTargets:\n\n"} \
	  /^[a-zA-Z_-]+:.*##/ {printf "  \033[1m%-20s\033[0m %s\n", $$1, $$2} \
	  END {printf "\n"}' $(MAKEFILE_LIST)

clean: ## Remove .venv, build artifacts, and egg-info
	rm -rf .venv dist build workspace_mcp.egg-info

install: ## uv sync --group dev (editable install + dev deps)
	uv sync --group dev

test: ## Run pytest suite (fail-fast: -x)
	uv run pytest tests/ -x

lint: ## Run ruff linter
	uv run ruff check .

format: ## Run ruff formatter
	uv run ruff format .

mcp-path: ## Print absolute path to the local workspace-mcp binary
	@test -x "$(WORKSPACE_MCP)" || { \
	  echo "error: $(WORKSPACE_MCP) not found — run 'make install' first" >&2; \
	  exit 1; }
	@echo "$(WORKSPACE_MCP)"

mcp-register: install ## Point Claude Code's workspace-mm MCP at the local fork
	python3 scripts/make_mcp_register.py "$(WORKSPACE_MCP)"

mcp-unregister: ## Remove the workspace-mm MCP registration from Claude Code
	claude mcp remove workspace-mm

run: install ## Run workspace-mcp locally (stdio, ctrl-C to stop)
	"$(WORKSPACE_MCP)" --tool-tier complete

run-http: install ## Run workspace-mcp locally (streamable HTTP on :8000)
	"$(WORKSPACE_MCP)" --transport streamable-http --tool-tier complete

build-and-install: clean install test mcp-path ## Clean → sync → test → print MCP path
	@echo ""
	@echo "Clean build complete. To wire into Claude Code:"
	@echo "  make mcp-register"
