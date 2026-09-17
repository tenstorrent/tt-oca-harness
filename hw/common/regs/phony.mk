# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# The user-facing `make regen-regs*` targets. The ## help and .PHONY lines are
# kept literal (the make help generator parses them from $(MAKEFILE_LIST));
# prerequisites come from the out.mk regen aggregates.

## @section Register Regeneration

## A target suffix selects the output class (or clean); TARGET=<block> scopes to a
## single register block. With no TARGET, every block is regenerated.

## Regenerate non-documentation register collateral for all OCAH register blocks.
## @param OCAH_REG_BLOCKS Registered block roots to regenerate
## @param TARGET=smc Optional register block basename to regenerate
## @param OCAH_REG_RDL_PARAMS_<block>=NAME=VALUE Optional PeakRDL addrmap overrides for that block
.PHONY: ocah-regen-regs
ocah-regen-regs: $(OCAH_REGEN_ALL) $(OCAH_REGEN_REG_STAMPS)

## Regenerate SystemVerilog register RTL for OCAH register blocks.
## @param TARGET=smc Optional register block basename to regenerate
.PHONY: ocah-regen-regs-sv
ocah-regen-regs-sv: $(OCAH_REGEN_REG_SV)

## Regenerate firmware C headers and raw C address headers for OCAH register blocks.
## @param TARGET=smc Optional register block basename to regenerate
.PHONY: ocah-regen-regs-h
ocah-regen-regs-h: $(OCAH_REGEN_REG_H)

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
## Refresh the DFD RDLs from the vendored tt_hw_debug MMR spec yaml.
## On-demand like ocah-regen-vendor-rdl: the RDLs are committed, so a clean
## checkout needs no regen. Run after bumping the tt-hw-debug vendor drop.
## @param CHECK=1 Report drift and fail instead of rewriting (for CI).
.PHONY: ocah-regen-dfd-rdl
ocah-regen-dfd-rdl: | $(OCAH_REG_UV_PREREQ)
	cd "$(OCAH_ROOT)" && "$(OCAH_REG_PYTHON)" tools/regs/dfd_yaml_rdl.py \
		$(if $(CHECK),--check,--write)

.PHONY: ocah-regen-vendor-rdl
ocah-regen-vendor-rdl: | $(OCAH_REG_UV_PREREQ)
	@$(foreach e,$(OCAH_SELECTED_VENDOR_HJSON_RDLS),\
		echo "Exporting HJSON register description to RDL: $(call ocah_vhr_rdl,$(e))"; \
		$(call ocah_vendor_hjson_rdl_regen,$(e)); )

OCAH_PHONY += \
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
  ocah-regen-dfd-rdl \
  ocah-regen-vendor-rdl
