# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_synth_pdk_mk
ocah_synth_pdk_mk := 1

PDKS = sky130 ihp-sg13g2 gf180mcuD

# Default PDK, forwarded into yosys as PDK=$(TECH) (see
# flows/synth/yosys/tech/ and scripts/init_tech.tcl).
TECH ?= ihp-sg13g2

# Warn if unsupported PDK
ifeq ($(filter $(TECH),$(PDKS)),)
$(error Unknown PDK '$(TECH)' — supported PDKs are: $(PDKS))
endif

# PDK installation location and install check
PDK_ROOT ?= $(OCAH_ROOT)/local/pdks
PDK_SENTINEL = $(PDK_ROOT)/ciel/$(TECH)/versions/$($(TECH)_HASH)

# Hashes for PDKs to install - currently matching prior EDA container
sky130_HASH ?= d400e26845538beaeb7cc5fdb9bfc06c30ea27cb
ihp-sg13g2_HASH ?= a2bf8ea81aee7d0fcdd6d62168edca0d7d0bcb08
gf180mcuD_HASH ?= 8f2d1529c86235d726979eb9ecb7e9628108590b

## @section Synthesis (PDK Installation)

## Install all pdks to PDK_ROOT, for use on an offline system. Single pdks
## will be installed on demand using `ocah-synth-pdk`
## @param PDK_ROOT=local/offline_pdks Install location for pdks (default local/pdks)
## @param _HASH Override version of installed pdk (note, actually ihp-sg13g2_HASH/gf180mcuD_HASH/sky130_HASH)
.PHONY: ocah-synth-pdks
ocah-synth-pdks: ${PDK_ROOT}/ihp-sg13g2 ${PDK_ROOT}/sky130 ${PDK_ROOT}/gf180mcuD

## Install selected pdk to PDK_ROOT
## @param PDK_ROOT=local/offline_pdks Install location for pdks (default local/pdks)
## @param _HASH Override version of installed pdk (note, actually ihp-sg13g2_HASH/gf180mcuD_HASH/sky130_HASH)
## @param TECH=ihp-sg13g2 Optional PDK (default ihp-sg13g2)
.PHONY: ocah-synth-pdk
ocah-synth-pdk: ${PDK_ROOT}/${TECH}

${PDK_ROOT}:
	mkdir -p $(PDK_ROOT)

$(foreach pdk,$(PDKS),${PDK_ROOT}/$(pdk)) : ${PDK_ROOT}
	ciel ls --pdk=$(subst ${PDK_ROOT}/,,$@) --pdk-root=$(PDK_ROOT) | grep $($(subst ${PDK_ROOT}/,,$@)_HASH) || ciel build --clear-build-artifacts --pdk=$(subst ${PDK_ROOT}/,,$@) --pdk-root=$(PDK_ROOT) $($(subst ${PDK_ROOT}/,,$@)_HASH)
	ln -srf $(PDK_ROOT)/ciel/$(subst ${PDK_ROOT}/,,$@) $(PDK_ROOT)/$(subst ${PDK_ROOT}/,,$@)

${PDK_SENTINEL}: ocah-synth-pdk
	ciel enable --pdk=$(TECH) --pdk-root=$(PDK_ROOT) $($(TECH)_HASH)

## Remove all Installed PDKs
.PHONY: ocah-synth-pdks-clean
ocah-synth-pdks-clean:
	rm -rf $(PDK_ROOT)

OCAH_PHONY += ocah-synth-pdks-all ocah-synth-pdk ocah-synth-pdks-clean

endif
