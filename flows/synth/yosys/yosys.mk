# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_synth_yosys_mk
ocah_synth_yosys_mk := 1

# Resolve self-path before including common.mk, which appends to MAKEFILE_LIST.
OCAH_YOSYS_DIR := $(patsubst %/,%,$(dir $(lastword $(MAKEFILE_LIST))))
include $(OCAH_YOSYS_DIR)/../../common.mk

# Synthesis via yosys + yosys-slang, PDK-parametrized by TECH. Included by
# ocah.mk (ocah-synth-yosys-all dispatcher) and each flow.mk (ocah-synth-yosys
# worker).

# Default PDK, forwarded into the container as PDK=$(TECH) (see
# flows/synth/yosys/tech/ and scripts/init_tech.tcl).
TECH ?= ihp-sg13g2

OCAH_YOSYS_SYNTH_TCL := $(OCAH_YOSYS_DIR)/scripts/synth.tcl

## @section Synthesis (yosys)

## Synthesize all (or BLOCK=-selected) hw/sys blocks with yosys + yosys-slang.
## For a single block, prefer `ocah-synth-yosys` directly from that block's flow.mk.
## @param BLOCK=smu Optional block(s) to synthesize; omit for all
## @param TECH=ihp-sg13g2 Optional PDK (default ihp-sg13g2)
.PHONY: ocah-synth-yosys-all
ocah-synth-yosys-all:
	$(call ocah_flow_run,ocah-synth-yosys,TECH="$(TECH)")

OCAH_PHONY += ocah-synth-yosys-all

ifdef FLOW_DESIGN

# TECH-scoped so different PDKs don't clobber each other's build output.
OCAH_SYNTH_DIR := build/synth/$(TECH)
OCAH_SYNTH_FLIST := $(OCAH_SYNTH_DIR)/$(FLOW_DESIGN).f

# The prim_assert.sv shim is yosys-only and must win the +incdir search against
# the vendored OpenTitan copy it delegates to, so it has to come first. It also
# has to stay off every other flow's flist: the customer IP packager flattens all
# include dirs into one directory, where the two files collide on basename.
# Bender drops an include_dirs-only source group, so prepend the dir here rather
# than gating it on a Bender target.
OCAH_YOSYS_ASSERT_INCDIR := $(OCAH_ROOT)/hw/common/assert/yosys

## Synthesize this one block with yosys + yosys-slang.
.PHONY: ocah-synth-yosys
ocah-synth-yosys:
	@mkdir -p $(OCAH_SYNTH_DIR)
	$(call ocah_eda_flist,$(FLOW_BENDER_TARGETS),$(OCAH_SYNTH_FLIST))
	@sed -i '1i +incdir+$(OCAH_YOSYS_ASSERT_INCDIR)' $(OCAH_SYNTH_FLIST)
	$(call ocah_eda_docker_run, env PDK=$(TECH) PROJ_NAME=$(FLOW_DESIGN) TOP_DESIGN=$(FLOW_DESIGN) SV_FLIST=$(OCAH_SYNTH_FLIST) OUT_DIR=$(OCAH_SYNTH_DIR) TIMESCALE=$(OCAH_FLOW_TIMESCALE) yosys -c $(OCAH_YOSYS_SYNTH_TCL))

endif

endif
