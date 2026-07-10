# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_lint_slang_mk
ocah_lint_slang_mk := 1

# Semantic lint via slang (elaborating frontend, not a style linter). Included
# by ocah.mk (ocah-lint-slang-all dispatcher) and each flow.mk (ocah-lint-slang worker).
include $(patsubst %/,%,$(dir $(lastword $(MAKEFILE_LIST))))/../common.mk

## @section Lint (slang)

## Lint all (or BLOCK=-selected) hw/sys blocks with slang. For a single
## block, prefer `ocah-lint-slang` directly from that block's own flow.mk.
## @param BLOCK=smu Optional block(s) to lint (space-separated); omit for all
.PHONY: ocah-lint-slang-all
ocah-lint-slang-all:
	$(call ocah_flow_run,ocah-lint-slang)

OCAH_PHONY += ocah-lint-slang-all

ifdef FLOW_DESIGN

OCAH_LINT_SLANG_DIR := build/lint
OCAH_LINT_SLANG_FLIST := $(OCAH_LINT_SLANG_DIR)/$(FLOW_DESIGN).f

## Generate this block's bender filelist for lint, without running slang.
## Reused by the CI lint job.
.PHONY: ocah-lint-slang-flist
ocah-lint-slang-flist:
	@mkdir -p $(OCAH_LINT_SLANG_DIR)
	$(call ocah_eda_flist,$(FLOW_BENDER_TARGETS),$(OCAH_LINT_SLANG_FLIST))

## Lint this one block with slang.
.PHONY: ocah-lint-slang
ocah-lint-slang: ocah-lint-slang-flist
	# --single-unit: slang defaults to one compilation unit per file in -f,
	# so macros `include`d in one file aren't visible when used in another.
	$(call ocah_require_host_tool,slang,./scripts/docker-run.sh eda-run make lint-slang)
	slang --lint-only --top $(FLOW_DESIGN) --timescale=$(OCAH_FLOW_TIMESCALE) --error-limit=0 --single-unit -f $(OCAH_LINT_SLANG_FLIST)

endif

endif
