# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_synth_yosys_mk
ocah_synth_yosys_mk := 1

# Resolve self-path before including common.mk, which appends to MAKEFILE_LIST.
OCAH_YOSYS_DIR := $(patsubst %/,%,$(dir $(lastword $(MAKEFILE_LIST))))
include $(OCAH_YOSYS_DIR)/../../common.mk

# Synthesis via yosys + yosys-slang, PDK-parametrized by TECH. Included by
# ocah.mk (ocah-synth dispatcher) and each flow.mk (ocah-synth-one worker).

# Default PDK, forwarded into the container as PDK=$(TECH) (see
# flows/synth/yosys/tech/ and scripts/init_tech.tcl).
TECH ?= ihp-sg13g2

OCAH_YOSYS_SYNTH_TCL := $(OCAH_YOSYS_DIR)/scripts/synth.tcl

## @section Synthesis (yosys)

## Synthesize one or all hw/sys blocks with yosys + yosys-slang.
## @param BLOCK=smu Optional block to synthesize (see flows/synth/yosys/README.md); omit for all
## @param TECH=ihp-sg13g2 Optional PDK, see flows/synth/yosys/tech/ (default ihp-sg13g2)
.PHONY: ocah-synth
ocah-synth:
	$(call ocah_flow_run,ocah-synth-one,TECH="$(TECH)")

OCAH_PHONY += ocah-synth

ifdef FLOW_DESIGN

# TECH-scoped so different PDKs don't clobber each other's build output.
OCAH_SYNTH_DIR := build/synth/$(TECH)
OCAH_SYNTH_FLIST := $(OCAH_SYNTH_DIR)/$(FLOW_DESIGN).f

.PHONY: ocah-synth-one
ocah-synth-one:
	@mkdir -p $(OCAH_SYNTH_DIR)
	$(call ocah_eda_flist,$(FLOW_BENDER_TARGETS),$(OCAH_SYNTH_FLIST))
	$(call ocah_eda_docker_run, env PDK=$(TECH) PROJ_NAME=$(FLOW_DESIGN) TOP_DESIGN=$(FLOW_DESIGN) SV_FLIST=$(OCAH_SYNTH_FLIST) OUT_DIR=$(OCAH_SYNTH_DIR) TIMESCALE=$(OCAH_FLOW_TIMESCALE) yosys -c $(OCAH_YOSYS_SYNTH_TCL))

endif

endif
