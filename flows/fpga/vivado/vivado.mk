# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_synth_vivado_mk
ocah_synth_vivado_mk := 1

# Resolve self-path before including common.mk, which appends to MAKEFILE_LIST.
OCAH_VIVADO_DIR := $(patsubst %/,%,$(dir $(lastword $(MAKEFILE_LIST))))
include $(OCAH_VIVADO_DIR)/../../common.mk

# Vivado RTL elaboration. Included by ocah.mk (ocah-synth-vivado-all dispatcher)
# and each flow.mk (ocah-synth-vivado worker).

OCAH_VIVADO_SYNTH_TCL ?= $(OCAH_VIVADO_DIR)/scripts/readiness.tcl
OCAH_VIVADO_PART ?= xczu15eg-ffvb1156-2-i
OCAH_VIVADO_INPUT ?= flist

ifeq ($(filter /%, $(OCAH_VIVADO_SYNTH_TCL)),)
OCAH_VIVADO_SYNTH_TCL := $(abspath $(OCAH_VIVADO_SYNTH_TCL))
endif

## @section Synthesis (Vivado)

## Elaborate all (or BLOCK=-selected) hw/sys blocks with Vivado.
## @param BLOCK=smu Optional block(s) to elaborate; omit for all
## @param OCAH_VIVADO_INPUT=flist Read the Bender file list (flist) or Bender's Vivado script (script)
## @param OCAH_VIVADO_PART=xczu15eg-ffvb1156-2-i Optional Vivado part
.PHONY: ocah-synth-vivado-all
ocah-synth-vivado-all:
	$(call ocah_flow_run,ocah-synth-vivado,OCAH_VIVADO_INPUT="$(OCAH_VIVADO_INPUT)" OCAH_VIVADO_PART="$(OCAH_VIVADO_PART)")

OCAH_PHONY += ocah-synth-vivado-all

ifdef FLOW_DESIGN

OCAH_VIVADO_BUILD_DIR := $(abspath build/synth/vivado)
OCAH_VIVADO_FLIST := $(OCAH_VIVADO_BUILD_DIR)/$(FLOW_DESIGN).f
OCAH_VIVADO_SCRIPT := $(OCAH_VIVADO_BUILD_DIR)/$(FLOW_DESIGN).tcl

## Elaborate this one block with Vivado.
.PHONY: ocah-synth-vivado
ocah-synth-vivado:
	@command -v vivado >/dev/null 2>&1 || { echo "error: vivado not found on PATH." >&2; exit 1; }
	@mkdir -p $(OCAH_VIVADO_BUILD_DIR)
	$(call ocah_eda_flist,$(FLOW_BENDER_TARGETS),$(OCAH_VIVADO_FLIST))
	$(OCAH_BENDER) script vivado $(OCAH_FLOW_COMMON_DEFINES) $(OCAH_FLOW_COMMON_BENDER_TARGETS) \
		$(FLOW_BENDER_TARGETS) > $(OCAH_VIVADO_SCRIPT)
	cd $(OCAH_VIVADO_BUILD_DIR) && TOP_DESIGN=$(FLOW_DESIGN) SV_FLIST=$(OCAH_VIVADO_FLIST) \
		VIVADO_SCRIPT=$(OCAH_VIVADO_SCRIPT) VIVADO_INPUT=$(OCAH_VIVADO_INPUT) \
		PART=$(OCAH_VIVADO_PART) OUT_DIR=$(OCAH_VIVADO_BUILD_DIR) \
		vivado -mode batch -notrace -nojournal -log $(FLOW_DESIGN).log \
		-source $(OCAH_VIVADO_SYNTH_TCL)

endif

endif
