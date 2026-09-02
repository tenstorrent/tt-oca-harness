# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_synth_yosys_mk
ocah_synth_yosys_mk := 1

# Resolve self-path before including common.mk, which appends to MAKEFILE_LIST.
OCAH_YOSYS_DIR := $(patsubst %/,%,$(dir $(lastword $(MAKEFILE_LIST))))
include $(OCAH_YOSYS_DIR)/../../common.mk

# Synthesis via yosys + yosys-slang, PDK-parametrized by TECH. Included by
# ocah.mk (ocah-synth-all dispatcher) and each flow.mk (ocah-synth worker).

# Default PDK, forwarded into the container as PDK=$(TECH) (see
# flows/synth/yosys/tech/ and scripts/init_tech.tcl).
TECH ?= ihp-sg13g2

OCAH_YOSYS_SYNTH_TCL := $(OCAH_YOSYS_DIR)/scripts/synth.tcl

## @section Synthesis (yosys)

## Synthesize all (or BLOCK=-selected) hw/sys blocks with yosys + yosys-slang.
## For a single block, prefer `ocah-synth` directly from that block's flow.mk.
## @param BLOCK=smu Optional block(s) to synthesize; omit for all
## @param TECH=ihp-sg13g2 Optional PDK (default ihp-sg13g2)
.PHONY: ocah-synth-all
ocah-synth-all:
	$(call ocah_flow_run,ocah-synth,TECH="$(TECH)")

OCAH_PHONY += ocah-synth-all

ifeq ($(origin OCAH_EDA_USE_CONTAINER_PDKS),undefined)
PDK_SENTINEL = $(PDK_ROOT)/ciel/$(TECH)/versions/$($(TECH)_HASH)
PDK_ROOT ?= $(OCAH_ROOT)/local/pdks
else
PDK_SENTINEL =
PDK_ROOT ?= /foss/pdks
endif

sky130_HASH ?= d400e26845538beaeb7cc5fdb9bfc06c30ea27cb
ihp-sg13g2_HASH ?= a2bf8ea81aee7d0fcdd6d62168edca0d7d0bcb08
gf180mcuD_HASH ?= 8f2d1529c86235d726979eb9ecb7e9628108590b

## Install all pdks to PDK_ROOT, for use on an offline system. Single pdks
## will be installed on demand by Make
## @param PDK_ROOT=local/offline_pdks Install location for pdks (default local/pdks)
## @param _HASH Override version of installed pdk (note, actually ihp-sg13g2_HASH/gf180mcuD_HASH/sky130_HASH)
ocah-synth-pdks: ${PDK_ROOT}/ihp-sg13g2 ${PDK_ROOT}/sky130 ${PDK_ROOT}/gf180mcuD

${PDK_ROOT}:
	mkdir -p $(PDK_ROOT)

${PDK_ROOT}/sky130 ${PDK_ROOT}/ihp-sg13g2 ${PDK_ROOT}/gf180mcuD: ${PDK_ROOT}
	ciel ls --pdk=$(subst ${PDK_ROOT}/,,$@) --pdk-root=$(PDK_ROOT) | grep $($(subst ${PDK_ROOT}/,,$@)_HASH) || ciel build --clear-build-artifacts --pdk=$(subst ${PDK_ROOT}/,,$@) --pdk-root=$(PDK_ROOT) $($(subst ${PDK_ROOT}/,,$@)_HASH)
	ln -srf $(PDK_ROOT)/ciel/$(subst ${PDK_ROOT}/,,$@) $(PDK_ROOT)/$(subst ${PDK_ROOT}/,,$@)



${PDK_SENTINEL}: ${PDK_ROOT}/${TECH}
	ciel enable --pdk=$(TECH) --pdk-root=$(PDK_ROOT) $($(TECH)_HASH)

## Remove all Installed PDKs
ocah-synth-pdks-clean:
	rm -rf $(PDK_ROOT)

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
.PHONY: ocah-synth
ocah-synth: ${PDK_SENTINEL}
	@mkdir -p $(OCAH_SYNTH_DIR)
	$(call ocah_eda_flist,$(FLOW_BENDER_TARGETS),$(OCAH_SYNTH_FLIST))
	@sed -i '1i +incdir+$(OCAH_YOSYS_ASSERT_INCDIR)' $(OCAH_SYNTH_FLIST)
ifeq ($(origin OCAH_EDA_SKIP_CONTAINERS),undefined)
	$(call ocah_eda_docker_run, env PDK=$(TECH) PDK_ROOT=$(PDK_ROOT) PROJ_NAME=$(FLOW_DESIGN) TOP_DESIGN=$(FLOW_DESIGN) SV_FLIST=$(OCAH_SYNTH_FLIST) OUT_DIR=$(OCAH_SYNTH_DIR) TIMESCALE=$(OCAH_FLOW_TIMESCALE) yosys -c $(OCAH_YOSYS_SYNTH_TCL))
else
	PDK=$(TECH) PDK_ROOT=$(PDK_ROOT) PROJ_NAME=$(FLOW_DESIGN) TOP_DESIGN=$(FLOW_DESIGN) SV_FLIST=$(OCAH_SYNTH_FLIST) OUT_DIR=$(OCAH_SYNTH_DIR) TIMESCALE=$(OCAH_FLOW_TIMESCALE) yosys -c $(OCAH_YOSYS_SYNTH_TCL)
endif

endif

endif
