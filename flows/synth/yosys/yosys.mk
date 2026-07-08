# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_synth_yosys_mk
ocah_synth_yosys_mk := 1

# Self-path first: must be resolved before the include below appends to
# MAKEFILE_LIST, or $(lastword $(MAKEFILE_LIST)) would start resolving to
# common.mk instead of this file.
OCAH_YOSYS_DIR := $(patsubst %/,%,$(dir $(lastword $(MAKEFILE_LIST))))
include $(OCAH_YOSYS_DIR)/../../common.mk

# Open-source synthesis via yosys + yosys-slang, PDK-parametrized by TECH (see
# flows/synth/yosys/README.md). Included both by ocah.mk (defines the
# ocah-synth dispatcher) and by each hw/sys/<block>/flow.mk (defines the
# ocah-synth-one per-block worker, once FLOW_DESIGN/FLOW_BENDER_TARGETS are
# set).

# Default PDK, independent of BLOCK so adding one later never touches an
# existing one (see flows/synth/yosys/tech/). Forwarded into the container as
# PDK=$(TECH) - the same env var hpretl/iic-osic-tools itself uses to select
# /foss/pdks/<TECH>; flows/synth/yosys/scripts/init_tech.tcl reads it back out.
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

# TECH-scoped so re-running with a different TECH never clobbers a previous
# PDK's results.
OCAH_SYNTH_DIR := build/synth/$(TECH)
OCAH_SYNTH_FLIST := $(OCAH_SYNTH_DIR)/$(FLOW_DESIGN).f

.PHONY: ocah-synth-one
ocah-synth-one:
	@mkdir -p $(OCAH_SYNTH_DIR)
	$(call ocah_eda_flist,$(FLOW_BENDER_TARGETS),$(OCAH_SYNTH_FLIST))
	$(call ocah_eda_docker_run, env PDK=$(TECH) PROJ_NAME=$(FLOW_DESIGN) TOP_DESIGN=$(FLOW_DESIGN) SV_FLIST=$(OCAH_SYNTH_FLIST) OUT_DIR=$(OCAH_SYNTH_DIR) TIMESCALE=$(OCAH_FLOW_TIMESCALE) yosys -c $(OCAH_YOSYS_SYNTH_TCL))

endif

endif
