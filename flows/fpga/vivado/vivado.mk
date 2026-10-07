# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_fpga_vivado_mk
ocah_fpga_vivado_mk := 1

# Resolve self-path before including common.mk, which appends to MAKEFILE_LIST.
OCAH_VIVADO_DIR := $(patsubst %/,%,$(dir $(lastword $(MAKEFILE_LIST))))
include $(OCAH_VIVADO_DIR)/../../common.mk

# Vivado RTL elaboration of the emulation view. Included by ocah.mk
# (ocah-fpga-vivado-all dispatcher) and each flow.mk (ocah-fpga-vivado worker).

OCAH_VIVADO_TCL ?= $(OCAH_VIVADO_DIR)/scripts/readiness.tcl
OCAH_VIVADO_PART ?= xczu15eg-ffvb1156-2-i
OCAH_VIVADO_INPUT ?= flist

ifeq ($(filter /%, $(OCAH_VIVADO_TCL)),)
OCAH_VIVADO_TCL := $(abspath $(OCAH_VIVADO_TCL))
endif

## @section FPGA (Vivado)

## Elaborate all (or BLOCK=-selected) hw/sys blocks with Vivado.
## @param BLOCK=smu Optional block(s) to elaborate; omit for all
## @param OCAH_VIVADO_INPUT=flist Read the Bender file list (flist) or Bender's Vivado script (script)
## @param OCAH_VIVADO_PART=xczu15eg-ffvb1156-2-i Optional Vivado part
.PHONY: ocah-fpga-vivado-all
ocah-fpga-vivado-all:
	$(call ocah_flow_run,ocah-fpga-vivado,OCAH_VIVADO_INPUT="$(OCAH_VIVADO_INPUT)" OCAH_VIVADO_PART="$(OCAH_VIVADO_PART)")

OCAH_PHONY += ocah-fpga-vivado-all

ifdef FLOW_DESIGN

OCAH_VIVADO_BUILD_DIR := $(abspath build/fpga/vivado)
OCAH_VIVADO_FLIST := $(OCAH_VIVADO_BUILD_DIR)/$(FLOW_DESIGN).f
OCAH_VIVADO_SCRIPT := $(OCAH_VIVADO_BUILD_DIR)/$(FLOW_DESIGN).tcl

## Elaborate this one block with Vivado.
.PHONY: ocah-fpga-vivado
ocah-fpga-vivado:
	@command -v vivado >/dev/null 2>&1 || { echo "error: vivado not found on PATH." >&2; exit 1; }
	@mkdir -p $(OCAH_VIVADO_BUILD_DIR)
	cd $(OCAH_ROOT) && $(call ocah_bender_flist,$(OCAH_EMUL_BENDER_TARGETS),$(FLOW_BENDER_TARGETS)) \
		> $(OCAH_VIVADO_FLIST)
	cd $(OCAH_ROOT) && $(OCAH_BENDER) script vivado $(OCAH_EMUL_BENDER_TARGETS) \
		$(OCAH_FLOW_COMMON_BENDER_TARGETS) $(FLOW_BENDER_TARGETS) > $(OCAH_VIVADO_SCRIPT)
	cd $(OCAH_VIVADO_BUILD_DIR) && TOP_DESIGN=$(FLOW_DESIGN) SV_FLIST=$(OCAH_VIVADO_FLIST) \
		VIVADO_SCRIPT=$(OCAH_VIVADO_SCRIPT) VIVADO_INPUT=$(OCAH_VIVADO_INPUT) \
		PART=$(OCAH_VIVADO_PART) OUT_DIR=$(OCAH_VIVADO_BUILD_DIR) \
		vivado -mode batch -notrace -nojournal -log $(FLOW_DESIGN).log \
		-source $(OCAH_VIVADO_TCL)

endif

endif
