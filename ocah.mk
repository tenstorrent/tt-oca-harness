# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_mk
ocah_mk := 1

ifndef OCAH_ROOT
OCAH_ROOT := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
endif
UV ?= uv

OCAH_PHONY ?=

## @section Environment

## Sync the uv-managed Python environment used by OCAH generation flows.
.PHONY: uv-sync
uv-sync:
	@command -v "$(UV)" >/dev/null 2>&1 || { echo "error: uv is required; see https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }
	@"$(UV)" --directory "$(OCAH_ROOT)" sync

OCAH_PHONY += uv-sync

OCAH_NONFREE_REMOTE ?= git@github.com:tenstorrent/tt-oca-harness-nonfree.git
OCAH_NONFREE_DIR ?= $(OCAH_ROOT)/nonfree
OCAH_ADOPTER_OVERLAY_MK ?=

## @section Optional nonfree components

## Clone the optional nonfree repository with resources that are not open-sourced.
## This step is optional and not required for normal OCAH use.
.PHONY: ocah-nonfree-init
ocah-nonfree-init:
	@test -n "$(OCAH_NONFREE_REMOTE)" || { echo "error: OCAH_NONFREE_REMOTE is not set"; exit 1; }
	@[ -d "$(OCAH_NONFREE_DIR)/.git" ] && echo "nonfree repo already cloned at $(OCAH_NONFREE_DIR)" || git clone "$(OCAH_NONFREE_REMOTE)" "$(OCAH_NONFREE_DIR)"

-include $(OCAH_ROOT)/nonfree/nonfree.mk
-include $(OCAH_ADOPTER_OVERLAY_MK)
## SEP virtual-platform (sep-vp) build and pytest harness targets (optional,
## skipped silently when virtual_platform/ is absent).
-include $(OCAH_ROOT)/virtual_platform/vp.mk

OCAH_PHONY += ocah-nonfree-init

## @section Submodules

OCAH_SUBMODULES ?= hw/sys/sep/bootrom/prod/tools/tt-oca-manifest virtual_platform/tt-oca-harness-model

## Check out the OCA manifest tooling and the VP model submodules.
.PHONY: ocah-submodules-init
ocah-submodules-init:
	@set -e; \
	for d in $(OCAH_SUBMODULES); do \
	  git -C "$(OCAH_ROOT)" submodule update --init --recursive "$$d"; \
	  test -n "$$(ls -A "$(OCAH_ROOT)/$$d" 2>/dev/null)" || { \
	    echo "error: $$d checked out but is empty"; exit 1; }; \
	done

OCAH_PHONY += ocah-submodules-init

## @section Integration filelists

## Regenerate the simulation, synthesis, and emulation filelists in integration/filelists/.
## @param CHECK=1 Report stale filelists and fail instead of rewriting.
.PHONY: ocah-update-integration-filelists
ocah-update-integration-filelists:
	@cd "$(OCAH_ROOT)" && python3 scripts/update_integration_filelists.py $(if $(filter 1,$(CHECK)),--check)

OCAH_PHONY += ocah-update-integration-filelists

## Core hardware collateral and DV firmware build targets.
include $(OCAH_ROOT)/hw/common/regs/regs.mk
include $(OCAH_ROOT)/hw/common/dv/fw/fw.mk

## Documentation build targets (after regs.mk so the register accessors exist).
include $(OCAH_ROOT)/doc/doc.mk
## Open-source lint/synth/format flow targets (slang/verible native-or-fail;
## yosys Docker-by-default; see tools/docker/README.md and
## flows/synth/yosys/README.md).
include $(OCAH_ROOT)/flows/lint/slang.mk
include $(OCAH_ROOT)/flows/lint/verilator.mk
include $(OCAH_ROOT)/flows/lint/verible.mk
include $(OCAH_ROOT)/flows/lint/sv-comments.mk
include $(OCAH_ROOT)/flows/lint/sv-enums.mk
include $(OCAH_ROOT)/flows/lint/bender-sources.mk
include $(OCAH_ROOT)/flows/lint/clang-format.mk
include $(OCAH_ROOT)/flows/lint/ruff.mk
include $(OCAH_ROOT)/flows/lint/mypy.mk
include $(OCAH_ROOT)/flows/lint/codespell.mk
include $(OCAH_ROOT)/flows/lint/markdownlint.mk
include $(OCAH_ROOT)/flows/lint/vale.mk
include $(OCAH_ROOT)/flows/lint/yamllint.mk
include $(OCAH_ROOT)/flows/lint/tomllint.mk
include $(OCAH_ROOT)/flows/lint/checkmake.mk
include $(OCAH_ROOT)/flows/lint/shell.mk
include $(OCAH_ROOT)/flows/lint/pre-commit.mk
include $(OCAH_ROOT)/flows/lint/tclint.mk
include $(OCAH_ROOT)/flows/lint/nix-fmt.mk
include $(OCAH_ROOT)/flows/synth/yosys/yosys.mk
include $(OCAH_ROOT)/flows/emul/vivado/vivado.mk

HELP_TITLE = "OCAH Make Targets"
HELP_DESCRIPTION = "Regeneration and helper targets for the OCA Harness repository"
include $(OCAH_ROOT)/help.mk

endif
