# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_lint_verilator_mk
ocah_lint_verilator_mk := 1

# Structural lint via verilator --lint-only. Included by ocah.mk
# (ocah-lint-verilator-all dispatcher) and each flow.mk (ocah-lint-verilator worker).
include $(patsubst %/,%,$(dir $(lastword $(MAKEFILE_LIST))))/../common.mk

## @section Lint (verilator)

## Lint all (or BLOCK=-selected) hw/sys blocks with verilator --lint-only.
## For a single block, prefer `ocah-lint-verilator` from that block's own flow.mk.
## @param BLOCK=smu Optional block(s) to lint (space-separated); omit for all
## @param VERILATOR_LINT_PATH=hw/sys/sep/rtl/efuse Optionally suppress (most) warnings outside
## a given directory
.PHONY: ocah-lint-verilator-all
ocah-lint-verilator-all:
	$(call ocah_flow_run,ocah-lint-verilator)

OCAH_PHONY += ocah-lint-verilator-all

## Build every package in each (or BLOCK=-selected) block's filelist into a
## Verilator model under --public-flat-rw, the flag cocotb's runner forces.
## @param BLOCK=smu Optional block(s) to check (space-separated); omit for all
.PHONY: ocah-lint-verilator-public-all
ocah-lint-verilator-public-all:
	$(call ocah_flow_run,ocah-lint-verilator-public)

OCAH_PHONY += ocah-lint-verilator-public-all

ifdef FLOW_DESIGN

OCAH_LINT_VERILATOR_DIR := build/lint
OCAH_LINT_VERILATOR_FLIST    := $(OCAH_LINT_VERILATOR_DIR)/$(FLOW_DESIGN)_verilator.f
OCAH_LINT_VERILATOR_FILTER_PATHS  := $(OCAH_LINT_VERILATOR_DIR)/$(FLOW_DESIGN)_verilator_filter_paths.vlt
OCAH_LINT_VERILATOR_COMMON_WAIVERS ?= hw/common/regs/lint/peakrdl.verilator.vlt
OCAH_LINT_VERILATOR_WAIVER_FILES := $(addprefix $(OCAH_ROOT)/, \
	$(OCAH_LINT_VERILATOR_COMMON_WAIVERS) $(FLOW_VERILATOR_WAIVERS))
OCAH_LINT_VERILATOR_TOP ?= $(FLOW_DESIGN)

# Verilator requires +define+FOO=1 syntax; the shared OCAH_FLOW_COMMON_DEFINES
# uses "-D FOO=1" (space-separated) which slang and bender accept but verilator
# does not. State the same defines explicitly in verilator's native form rather
# than trying to reformat the shared variable.
OCAH_LINT_VERILATOR_DEFINES := +define+SYNTHESIS=1

OCAH_LINT_VERILATOR_FLAGS = -sv --language 1800-2023 \
	--timing \
	--timescale $(OCAH_FLOW_TIMESCALE) \
	$(OCAH_LINT_VERILATOR_DEFINES) \
	-Wno-fatal \
	+define+ASSERTS_OFF

## Generate this block's bender filelist for verilator lint, without running verilator.
.PHONY: ocah-lint-verilator-flist
ocah-lint-verilator-flist:
	@mkdir -p $(OCAH_LINT_VERILATOR_DIR)
	$(call ocah_eda_flist,$(FLOW_BENDER_TARGETS),$(OCAH_LINT_VERILATOR_FLIST))
	@if [ -n '$(VERILATOR_LINT_PATH)' ]; then \
	    { echo '`verilator_config'; \
	      grep '^/' $(OCAH_LINT_VERILATOR_FLIST) \
	      | grep -v '^$(OCAH_ROOT)/$(patsubst %/,%,$(VERILATOR_LINT_PATH))' \
	      | sed 's|.*|lint_off -file "&"|'; \
	    } > $(OCAH_LINT_VERILATOR_FILTER_PATHS); \
	fi

## Lint this one block with verilator --lint-only.
## @param OCAH_LINT_VERILATOR_TOP=<module> Override the top within this block's filelist
.PHONY: ocah-lint-verilator
ocah-lint-verilator: ocah-lint-verilator-flist
	$(call ocah_require_host_tool,verilator,./scripts/docker-run.sh run-here make ocah-lint-verilator)
	verilator --lint-only $(OCAH_LINT_VERILATOR_FLAGS) \
		--top-module $(OCAH_LINT_VERILATOR_TOP) \
		-FI $(OCAH_VENDOR_DEFINES_SVH) \
		$(OCAH_LINT_VERILATOR_EXTRA_FLAGS) \
		$(OCAH_LINT_VERILATOR_WAIVER_FILES) \
		$(if $(VERILATOR_LINT_PATH),$(OCAH_LINT_VERILATOR_FILTER_PATHS)) \
		-f $(OCAH_LINT_VERILATOR_FLIST)

OCAH_LINT_VERILATOR_PUBLIC_DIR := $(OCAH_LINT_VERILATOR_DIR)/$(FLOW_DESIGN)_public_flat_rw

# --public-flat-rw registers every package parameter by name, so an empty top
# over the block's filelist builds each package registration the cocotb
# benches compile while Verilator drops the uninstantiated modules. The
# registrations fail in the C++ compile, hence --build.
## Build this block's packages into a Verilator model under --public-flat-rw.
.PHONY: ocah-lint-verilator-public
ocah-lint-verilator-public: ocah-lint-verilator-flist
	$(call ocah_require_host_tool,verilator,./scripts/docker-run.sh run-here make ocah-lint-verilator-public)
	@mkdir -p $(OCAH_LINT_VERILATOR_PUBLIC_DIR)
	@printf 'module ocah_public_flat_rw_top;\nendmodule\n' > $(OCAH_LINT_VERILATOR_PUBLIC_DIR)/top.sv
	verilator --cc --build -j 0 --public-flat-rw $(OCAH_LINT_VERILATOR_FLAGS) \
		--top-module ocah_public_flat_rw_top \
		-Wno-lint -Wno-style \
		-f $(OCAH_LINT_VERILATOR_FLIST) \
		$(OCAH_LINT_VERILATOR_PUBLIC_DIR)/top.sv \
		-Mdir $(OCAH_LINT_VERILATOR_PUBLIC_DIR)/obj

endif

endif
