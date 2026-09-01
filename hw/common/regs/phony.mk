# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# The user-facing `make regen-regs*` targets. The ## help and .PHONY lines are
# kept literal (the make help generator parses them from $(MAKEFILE_LIST));
# prerequisites come from the out.mk regen aggregates.

## @section Register Regeneration

## A target suffix selects the output class (or clean); TARGET=<block> scopes to a
## single register block. With no TARGET, every block is regenerated.

# Open-tree paths, not ocah_reg_block_by_name: TARGET=sep and the companion's
# nonfree/hw/sys/sep share the notdir "sep", so discovery would concatenate both.
OCAH_KM_ADDR_H  := $(OCAH_ROOT)/hw/ip/key_manager/regs/gen/c/key_manager_addr.h
OCAH_SEP_ADDR_H := $(OCAH_ROOT)/hw/sys/sep/regs/gen/c/sep_addr.h
OCAH_KM_SEP_EFUSE_MAP_CHECK = python3 "$(OCAH_ROOT)/tools/regs/check_km_sep_efuse_map.py" \
  --km "$(OCAH_KM_ADDR_H)" --sep "$(OCAH_SEP_ADDR_H)"

## Regenerate non-documentation register collateral for all OCAH register blocks.
## @param OCAH_REG_BLOCKS Registered block roots to regenerate
## @param TARGET=smc Optional register block basename to regenerate
.PHONY: ocah-regen-regs
ocah-regen-regs: $(OCAH_REGEN_ALL) $(OCAH_REGEN_REG_STAMPS)
	@$(OCAH_KM_SEP_EFUSE_MAP_CHECK)

## Regenerate SystemVerilog register RTL for OCAH register blocks.
## @param TARGET=smc Optional register block basename to regenerate
.PHONY: ocah-regen-regs-sv
ocah-regen-regs-sv: $(OCAH_REGEN_REG_SV)

## Regenerate firmware C headers and raw C address headers for OCAH register blocks.
## @param TARGET=smc Optional register block basename to regenerate
.PHONY: ocah-regen-regs-h
ocah-regen-regs-h: $(OCAH_REGEN_REG_H)
	@$(OCAH_KM_SEP_EFUSE_MAP_CHECK)

## Regenerate SystemVerilog address packages for OCAH register blocks.
## @param TARGET=smc Optional register block basename to regenerate
.PHONY: ocah-regen-regs-addrpkg
ocah-regen-regs-addrpkg: $(OCAH_REGEN_REG_ADDRPKG)

## Regenerate flattened SV headers for OCAH register blocks.
## @param TARGET=smc Optional register block basename to regenerate
.PHONY: ocah-regen-regs-svh
ocah-regen-regs-svh: $(OCAH_REGEN_REG_SVH)

## Regenerate Python register headers for OCAH register blocks.
## @param TARGET=smc Optional register block basename to regenerate
.PHONY: ocah-regen-regs-py
ocah-regen-regs-py: $(OCAH_REGEN_REG_PY)

## Regenerate JSON register models for the OCAH register blocks that opt in.
## @param TARGET=smc Optional register block basename to regenerate
.PHONY: ocah-regen-regs-json
ocah-regen-regs-json: $(OCAH_REGEN_REG_JSON)

## Regenerate IP-XACT component descriptions for OCAH register blocks.
## @param TARGET=smc Optional register block basename to regenerate
.PHONY: ocah-regen-regs-ipxact
ocah-regen-regs-ipxact: $(OCAH_REGEN_REG_IPXACT)

## Regenerate UVM RAL register models for the OCAH register blocks that opt in.
## @param TARGET=smc Optional register block basename to regenerate
.PHONY: ocah-regen-regs-ral
ocah-regen-regs-ral: $(OCAH_REGEN_REG_RAL)

## Regenerate AsciiDoc register documentation for OCAH register blocks.
## @param TARGET=smc Optional register block basename to regenerate
.PHONY: ocah-regen-regs-adoc
ocah-regen-regs-adoc: $(OCAH_REGEN_REG_ADOC)

## Regenerate HTML register documentation for OCAH register blocks.
## @param TARGET=smc Optional register block basename to regenerate
.PHONY: ocah-regen-regs-html
ocah-regen-regs-html: $(OCAH_REGEN_REG_HTML)

## Remove generated register collateral and transient register-generation stamps.
## One `rm` per block so the recipe stays under ARG_MAX when the process
## environment is large (GitLab sources the site setup script before this target).
## @param TARGET=smc Optional register block basename to clean
define ocah_reg_clean_one
	@rm -rf $(foreach path,$(call ocah_reg_clean_paths,$(1)),"$(path)")

endef
.PHONY: ocah-regen-regs-clean
ocah-regen-regs-clean:
	$(foreach block,$(OCAH_SELECTED_REG_BLOCKS),$(call ocah_reg_clean_one,$(block)))

## Refresh the committed vendored register RDLs from their upstream OpenTitan hjson.
## On-demand only: a clean checkout already has the RDLs and regen-regs never runs
## this (the committed RDL is never a make prerequisite of the hjson). Re-serializes
## with tt-oca's reggen, so expect a format diff vs the checked-in RDL.
## @param RDL=aes Optional vendored RDL basename to refresh (default: all). A
## separate selector from TARGET, which classify.mk validates against top blocks.
ocah_vhr_name = $(notdir $(basename $(call ocah_vhr_rdl,$(1))))
OCAH_SELECTED_VENDOR_HJSON_RDLS = $(if $(RDL),$(foreach e,$(OCAH_VENDOR_HJSON_RDLS),$(if $(filter $(RDL),$(call ocah_vhr_name,$(e))),$(e))),$(OCAH_VENDOR_HJSON_RDLS))
.PHONY: ocah-regen-vendor-rdl
ocah-regen-vendor-rdl: | uv-sync
	@$(foreach e,$(OCAH_SELECTED_VENDOR_HJSON_RDLS),\
		echo "Exporting HJSON register description to RDL: $(call ocah_vhr_rdl,$(e))"; \
		$(call ocah_vendor_hjson_rdl_regen,$(e)); )

## Fail if KM and SEP generated eFuse-map [11:0] offsets disagree. Hardware
## remaps KM-local 0x0001_1xxx to SEP 0x1093_0xxx by replacing [31:12]; a LOCKS_*
## insertion that updates only the SEP copy leaves KM FW reading the wrong field.
.PHONY: ocah-check-km-sep-efuse-map
ocah-check-km-sep-efuse-map:
	@$(OCAH_KM_SEP_EFUSE_MAP_CHECK)

OCAH_PHONY += \
  ocah-check-km-sep-efuse-map \
  ocah-regen-regs \
  ocah-regen-regs-sv \
  ocah-regen-regs-h \
  ocah-regen-regs-addrpkg \
  ocah-regen-regs-svh \
  ocah-regen-regs-py \
  ocah-regen-regs-ral \
  ocah-regen-regs-json \
  ocah-regen-regs-ipxact \
  ocah-regen-regs-adoc \
  ocah-regen-regs-html \
  ocah-regen-regs-clean \
  ocah-regen-vendor-rdl
