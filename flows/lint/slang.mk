# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_lint_slang_mk
ocah_lint_slang_mk := 1

# Semantic lint via slang (elaborating frontend, not a style linter). Included
# by ocah.mk (ocah-lint dispatcher) and each flow.mk (ocah-lint-one worker).
include $(patsubst %/,%,$(dir $(lastword $(MAKEFILE_LIST))))/../common.mk

## @section Lint (slang)

## Lint one or all hw/sys blocks with slang (open-source SystemVerilog frontend).
## @param BLOCK=smu Optional block to lint (see flows/synth/yosys/README.md); omit to lint all
.PHONY: ocah-lint
ocah-lint:
	$(call ocah_flow_run,ocah-lint-one)

OCAH_PHONY += ocah-lint

ifdef FLOW_DESIGN

OCAH_LINT_DIR := build/lint
OCAH_LINT_FLIST := $(OCAH_LINT_DIR)/$(FLOW_DESIGN).f

.PHONY: ocah-lint-one
ocah-lint-one:
	@mkdir -p $(OCAH_LINT_DIR)
	$(call ocah_eda_flist,$(FLOW_BENDER_TARGETS),$(OCAH_LINT_FLIST))
	$(call ocah_eda_docker_run, slang --lint-only --top $(FLOW_DESIGN) --timescale=$(OCAH_FLOW_TIMESCALE) --error-limit=0 -f $(OCAH_LINT_FLIST))

endif

endif
