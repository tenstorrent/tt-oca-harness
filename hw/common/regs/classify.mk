# SPDX-License-Identifier: Apache-2.0
# (c) 2026 Tenstorrent USA Inc

# Decides what each block gets generated: the hand-maintained policy lists (which
# blocks skip SV RTL, omit bitfields, etc.), whether a block is a composite top,
# and the per-block sub-block lists. The one place to edit when policy changes.

# C header omits bitfield structs (peakrdl can't represent >64-bit registers);
# address/mask defines only.
OCAH_REG_NO_BITFIELDS ?= smc_efuse_map sep_efuse_map

# A top is composite when its resolved RDL sits next to a regs/blocks/ dir: each
# sub-block is generated on its own, the top keeps only its address view. Reading
# the resolved RDL means an overlay variant reusing a canonical top inherits this.
ocah_reg_is_composite = $(wildcard $(dir $(OCAH_REG_RDL_$(call ocah_reg_key,$(1))))blocks)

# Reserve an address window only: C header, but no SV RTL and no docs.
OCAH_REG_PLACEHOLDER_BLOCKS ?= oca_i3c_wrap
# Register RTL authored outside regblock: excluded from SV only, still docs + C header.
OCAH_REG_NO_RTL_BLOCKS ?= \
  aes hmac kmac otbn \
  smc_efuse_map sep_efuse_map \
  clint plic debug_module wdt bus_error_unit misc_wrap \
  el2_pic aon_timer efuse_mmr dfd

# Local sub-blocks of a composite top: the regs/blocks/<sub>/ basenames (a pure
# glob, no addrmap scan). C keeps placeholders; docs drop them; SV also drops
# RTL-elsewhere blocks (applied at materialization below).
ocah_reg_ch_blocks_scan = $(notdir $(patsubst %/,%,$(wildcard $(call ocah_reg_root,$(1))/regs/blocks/*/)))

# Composite tops vs plain leaves (the lists the rules in rules.mk loop over).
OCAH_REG_COMPOSITE_BLOCK_IDS := $(foreach block,$(OCAH_REG_BLOCKS),$(if $(call ocah_reg_is_composite,$(block)),$(block)))
OCAH_REG_PLAIN_BLOCK_IDS     := $(filter-out $(OCAH_REG_COMPOSITE_BLOCK_IDS),$(OCAH_REG_BLOCKS))

# Tops that get the shared catalog on their -I path: the composite tops, by name
# (so open and overlay variants of a subsystem both qualify).
OCAH_REG_INCDIR_BLOCKS ?= $(sort $(foreach b,$(OCAH_REG_COMPOSITE_BLOCK_IDS),$(call ocah_reg_name,$(b))))

# Blocks in scope: TARGET=<name> selects one, else all.
ocah_reg_block_by_name = $(strip $(foreach block,$(OCAH_REG_BLOCKS),$(if $(filter $(1),$(notdir $(block))),$(block))))
OCAH_SELECTED_REG_BLOCKS := $(if $(TARGET),$(call ocah_reg_block_by_name,$(TARGET)),$(OCAH_REG_BLOCKS))

ifeq ($(strip $(OCAH_SELECTED_REG_BLOCKS)),)
  $(error Unknown OCAH register block '$(TARGET)'; known blocks: $(foreach block,$(OCAH_REG_BLOCKS),$(notdir $(block))))
endif

# Set the per-block policy vars (search/svmode/bitfields/html) for every block.
define ocah_reg_classify_vars
OCAH_REG_SEARCH_$(call ocah_reg_key,$(1)) := $(call ocah_reg_incdirs_resolve,$(1))
OCAH_REG_SVMODE_$(call ocah_reg_key,$(1)) := $(if $(filter $(call ocah_reg_name,$(1)),$(OCAH_REG_NO_RTL_BLOCKS)),skip,regblock)
OCAH_REG_BITFIELDS_$(call ocah_reg_key,$(1)) := $(if $(filter $(call ocah_reg_name,$(1)),$(OCAH_REG_NO_BITFIELDS)),none,ltoh)
OCAH_REG_HTML_$(call ocah_reg_key,$(1)) := $(or $(OCAH_REG_HTML_OUTPUT_OVERRIDE_$(call ocah_reg_key,$(1))),$(OCAH_REG_GEN_$(call ocah_reg_key,$(1)))/html/index.html)
endef
$(foreach block,$(OCAH_REG_BLOCKS),$(eval $(call ocah_reg_classify_vars,$(block))))

# Per-output-class sub-block lists for composite tops. SUBDOC/SUBSV reference the
# prior line's var, escaped ($$) so they expand at eval time (after it is assigned).
define ocah_reg_classify_composite_vars
OCAH_REG_SUBCH_$(call ocah_reg_key,$(1)) := $(call ocah_reg_ch_blocks_scan,$(1))
OCAH_REG_SUBDOC_$(call ocah_reg_key,$(1)) := $$(filter-out $$(OCAH_REG_PLACEHOLDER_BLOCKS),$$(OCAH_REG_SUBCH_$(call ocah_reg_key,$(1))))
OCAH_REG_SUBSV_$(call ocah_reg_key,$(1)) := $$(filter-out $$(OCAH_REG_NO_RTL_BLOCKS),$$(OCAH_REG_SUBDOC_$(call ocah_reg_key,$(1))))
endef
$(foreach block,$(OCAH_REG_COMPOSITE_BLOCK_IDS),$(eval $(call ocah_reg_classify_composite_vars,$(block))))
