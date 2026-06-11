ifndef ocah_mk
ocah_mk := 1

OCAH_ROOT ?= $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
UV ?= uv

OCAH_PHONY ?=

## @section Environment

## Sync the uv-managed Python environment used by OCAH generation flows.
.PHONY: uv-sync
uv-sync:
	@command -v "$(UV)" >/dev/null 2>&1 || { \
		echo "error: uv is required for OCAH register regeneration."; \
		echo "install instructions: https://docs.astral.sh/uv/getting-started/installation/"; \
		exit 1; \
	}
	@cd "$(OCAH_ROOT)" && "$(UV)" sync

OCAH_PHONY += uv-sync

OCAH_AGENTS_REMOTE ?=
OCAH_AGENTS_COMMIT ?=
OCAH_AGENTS_DIR ?= $(OCAH_ROOT)/agents

## @section Optional AI assistant configuration

## Clone the optional tt-oca-agents repository into a staging directory.
## This step is optional and not required for normal OCAH use.
.PHONY: ocah-agents-init
ocah-agents-init:
	@if [ -z "$(OCAH_AGENTS_REMOTE)" ]; then \
		echo "error: OCAH_AGENTS_REMOTE is not set (placeholder until tt-oca-agents repo exists)"; \
		exit 1; \
	fi
	@if [ -d "$(OCAH_AGENTS_DIR)/.git" ]; then \
		echo "agents repo already cloned at $(OCAH_AGENTS_DIR)"; \
	else \
		git clone "$(OCAH_AGENTS_REMOTE)" "$(OCAH_AGENTS_DIR)"; \
	fi
	@if [ -n "$(OCAH_AGENTS_COMMIT)" ]; then \
		git -C "$(OCAH_AGENTS_DIR)" checkout "$(OCAH_AGENTS_COMMIT)"; \
	fi
# TODO: distribute files from $(OCAH_AGENTS_DIR) once tt-oca-agents layout is defined.

OCAH_PHONY += ocah-agents-init

OCAH_NONFREE_REMOTE ?=
OCAH_NONFREE_COMMIT ?=
OCAH_NONFREE_DIR ?= $(OCAH_ROOT)/nonfree

## @section Optional nonfree components

## Clone the optional nonfree repository with resources that are not open-sourced.
## This step is optional and not required for normal OCAH use.
.PHONY: ocah-nonfree-init
ocah-nonfree-init:
	@if [ -z "$(OCAH_NONFREE_REMOTE)" ]; then \
		echo "error: OCAH_NONFREE_REMOTE is not set (placeholder until nonfree repo exists)"; \
		exit 1; \
	fi
	@if [ -d "$(OCAH_NONFREE_DIR)/.git" ]; then \
		echo "nonfree repo already cloned at $(OCAH_NONFREE_DIR)"; \
	else \
		git clone "$(OCAH_NONFREE_REMOTE)" "$(OCAH_NONFREE_DIR)"; \
	fi
	@if [ -n "$(OCAH_NONFREE_COMMIT)" ]; then \
		git -C "$(OCAH_NONFREE_DIR)" checkout "$(OCAH_NONFREE_COMMIT)"; \
	fi

-include $(OCAH_ROOT)/nonfree/nonfree.mk

OCAH_PHONY += ocah-nonfree-init

include $(OCAH_ROOT)/hw/regs.mk
include $(OCAH_ROOT)/hw/common/dv/fw.mk

HELP_TITLE = "OCAH Make Targets"
HELP_DESCRIPTION = "Regeneration and helper targets for the OCA Harness repository"
include $(OCAH_ROOT)/help.mk

endif
