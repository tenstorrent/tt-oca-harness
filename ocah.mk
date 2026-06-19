# SPDX-License-Identifier: Apache-2.0
# (c) 2026 Tenstorrent USA Inc

ifndef ocah_mk
ocah_mk := 1

OCAH_ROOT ?= $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
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
OCAH_NONFREE_COMMIT ?= main
OCAH_NONFREE_DIR ?= $(OCAH_ROOT)/nonfree
OCAH_ADOPTER_OVERLAY_MK ?=

## @section Optional nonfree components

## Clone the optional nonfree repository with resources that are not open-sourced.
## This step is optional and not required for normal OCAH use.
.PHONY: ocah-nonfree-init
ocah-nonfree-init:
	@test -n "$(OCAH_NONFREE_REMOTE)" || { echo "error: OCAH_NONFREE_REMOTE is not set"; exit 1; }
	@[ -d "$(OCAH_NONFREE_DIR)/.git" ] && echo "nonfree repo already cloned at $(OCAH_NONFREE_DIR)" || git clone "$(OCAH_NONFREE_REMOTE)" "$(OCAH_NONFREE_DIR)"
	@test -z "$(OCAH_NONFREE_COMMIT)" || git -C "$(OCAH_NONFREE_DIR)" checkout "$(OCAH_NONFREE_COMMIT)"

-include $(OCAH_ROOT)/nonfree/nonfree.mk
-include $(OCAH_ADOPTER_OVERLAY_MK)

OCAH_PHONY += ocah-nonfree-init

## Core hardware collateral and DV firmware build targets.
include $(OCAH_ROOT)/hw/common/regs/regs.mk
include $(OCAH_ROOT)/hw/common/dv/fw/fw.mk
## Yosys synthesis flow targets.
include $(OCAH_ROOT)/flows/synth/yosys/yosys.mk

HELP_TITLE = "OCAH Make Targets"
HELP_DESCRIPTION = "Regeneration and helper targets for the OCA Harness repository"
include $(OCAH_ROOT)/help.mk

endif
