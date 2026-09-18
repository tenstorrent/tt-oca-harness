# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# Decides what each block gets generated: the hand-maintained policy lists (which
# blocks skip SV RTL, omit bitfields, etc.), whether a block is a composite top,
# and the per-block sub-block lists. The one place to edit when policy changes.

# C header omits bitfield structs (peakrdl can't represent >64-bit registers);
# address/mask defines only.
OCAH_REG_NO_BITFIELDS ?= key_manager oca_i3c_wrap smc smc_efuse_map sep_efuse_map

# The Python header has its own list because the reason above is a peakrdl
# c-header limitation, not a general one: rdlpyhdr.py drops just the registers it
# cannot express and keeps the ctypes classes for the rest, so a block that has to
# turn bitfields off in C can still have them in Python. The cocotb tests need
# those classes (they build register values through <REG>_reg_u), so the default
# is on and this list stays empty until some block proves otherwise.
OCAH_REG_NO_BITFIELDS_PY ?=

# Python field-access metadata is opt-in because generic register walkers are
# its only consumers. It carries sw/onwrite/onread/singlepulse from the RDL.
OCAH_REG_PY_FIELD_ACCESS_BLOCKS ?= hw/ip/entropy_source

# A top is composite when its resolved RDL sits next to a regs/blocks/ dir: each
# sub-block is generated on its own, the top keeps only its address view. Reading
# the resolved RDL means an overlay variant reusing a canonical top inherits this.
ocah_reg_is_composite = $(wildcard $(dir $(OCAH_REG_RDL_$(call ocah_reg_key,$(1))))blocks)

# Register RTL authored outside regblock: excluded from SV only, still docs + C header.
# The vendored OpenTitan blocks (aes/hmac/kmac/otbn/csrng/edn/secure_dma/
# spi_controller/aon_timer) get their reg RTL from upstream reggen, not peakrdl.
# pll_wrap/pvt_wrap are free-tree DV register models (hw/sys/smc/dv/models/regs)
# whose real RTL is the vendor PLL/PVT IP, not regblock: only their addrmap_pkg is
# committed. The nonfree overlay also lists them (EXTRA below), but they must be in
# the free base too so the peakrdl-only regen-diff gate -- which never reads nonfree
# -- is self-consistent and does not emit uncommitted <blk>_reg[_pkg].sv.
# oca_i3c_wrap describes the same map as the SMC top sees it (HCI fields
# expanded), while its register RTL comes from the vendored i3c-core.
OCAH_REG_NO_RTL_BLOCKS ?= \
  aes hmac kmac otbn \
  csrng edn secure_dma spi_controller sep_external \
  smc_efuse_map sep_efuse_map \
  clint plic debug_module wdt bus_error_unit misc_wrap \
  el2_pic aon_timer dfd smc_cla dma_ctrl \
  pll_wrap pvt_wrap oca_i3c_wrap cross_trigger_network key_manager
# Overlay append hook (e.g. the nonfree DV-shim sub-blocks whose RTL is the
# vendor's, not regblock's): set before this file so the open default is kept.
OCAH_REG_NO_RTL_BLOCKS += $(OCAH_REG_NO_RTL_BLOCKS_EXTRA)

# UVM RAL models are opt-in: only a DV environment that drives registers through
# a uvm_reg_block needs one (today just the SEP TB), and every extra block is
# another peakrdl invocation on a full regen.
#
# Composite sub-blocks are named (they are not blocks in their own right); leaves
# are listed by block id, because a name is not unique -- efuse_shim_ctrl is both
# the open DV placeholder and the Samsung shim that shadows it, and only the
# latter gets a RAL.
#
# aes/hmac/kmac/otbn/aon_timer/secure_dma and efuse_mmr are RAL leaves, not
# sub-blocks: they are homed at the vendored overlay (or hw/ip/efuse), not in the
# SEP blocks/ tree, so the composite glob does not see them. As leaves they emit
# their RAL at that home -- as csrng/edn do -- and the SEP DV testbench includes
# each by bare name via a +incdir on it. Sub-blocks below have no other home.
#
# spi_controller is a composite sub-block homed in blocks/: its vendored overlay
# RDL describes a different, newer spi_host layout than the spi_controller_reg_pkg.sv
# the SEP DUT instantiates, so the DUT-matching blocks/ copy is the generated one.
OCAH_REG_RAL_SUB_BLOCKS ?= \
  sep_efuse_map spi_controller \
  sep_cpu_ctrl sep_reset_ctrl sep_scratch sep_lifecycle_ctrl el2_pic
OCAH_REG_RAL_LEAF_BLOCKS ?= \
  hw/ip/axi_alias_remap/regs/alias_remap \
  hw/ip/axi_filter/regs/filter_ctrl \
  hw/ip/output_remap \
  hw/ip/axi_lite_mailbox_unit/regs/axil_mailbox_sep_wrap \
  hw/ip/efuse/regs/efuse_interface_ctrl \
  hw/ip/efuse/regs/efuse_mmr \
  hw/ip/entropy_source \
  hw/ip/key_manager/regs/km_mailbox_sep \
  vendor/lowRISC/opentitan/overlay/regs/aes \
  vendor/lowRISC/opentitan/overlay/regs/aon_timer \
  vendor/lowRISC/opentitan/overlay/regs/csrng \
  vendor/lowRISC/opentitan/overlay/regs/edn \
  vendor/lowRISC/opentitan/overlay/regs/hmac \
  vendor/lowRISC/opentitan/overlay/regs/kmac \
  vendor/lowRISC/opentitan/overlay/regs/otbn \
  vendor/lowRISC/opentitan/overlay/regs/secure_dma
# Overlay append hooks (the nonfree vendor shim blocks the SEP TB drives).
OCAH_REG_RAL_SUB_BLOCKS += $(OCAH_REG_RAL_SUB_BLOCKS_EXTRA)
OCAH_REG_RAL_LEAF_BLOCKS += $(OCAH_REG_RAL_LEAF_BLOCKS_EXTRA)

# JSON register models are opt-in for the same reason as RAL: only a testbench
# that walks the register space generically needs one (the SMC/SMU cocotb
# register_test). Listed by block id, like the RAL leaves.
OCAH_REG_JSON_BLOCKS ?= hw/sys/smc
OCAH_REG_JSON_BLOCKS += $(OCAH_REG_JSON_BLOCKS_EXTRA)

# Address-space tables (rdlmap) are opt-in and distinct from the per-block
# register tables that rdladoc already emits for every RDL. List a block here
# only when it needs a composed window or aperture view. Leaf IPs keep
# including their existing regs/gen/adoc/<block>.adoc tables and do not belong
# here. Each entry reads presentation directives from doc/memmap.toml and
# emits regs/gen/adoc/memory_map.adoc.
OCAH_REG_MEMORY_MAP_BLOCKS ?= \
  hw/sys/sep \
  hw/sys/smc \
  hw/ip/key_manager \
  hw/ip/cross_trigger/cross_trigger_network \
  hw/ip/efuse/regs/efuse_interface_ctrl \
  hw/ip/axi_lite_mailbox_unit/regs/axil_mailbox
OCAH_REG_MEMORY_MAP_BLOCKS += $(OCAH_REG_MEMORY_MAP_BLOCKS_EXTRA)
OCAH_REG_MEMORY_MAP_DEPS_hw_sys_sep := \
  $(OCAH_ROOT)/hw/sys/sep/regs/include/sep_cpu_logical.rdl
OCAH_REG_MEMORY_MAP_DEPS_hw_ip_axi_lite_mailbox_unit_regs_axil_mailbox := \
  $(OCAH_ROOT)/hw/ip/axi_lite_mailbox_unit/regs/axil_mailbox_smc_wrap.rdl \
  $(OCAH_ROOT)/hw/ip/axi_lite_mailbox_unit/regs/axil_mailbox_sep_wrap.rdl
# The eFuse view composes three subsystem roots. Keep all catalogued RDL sources
# as prerequisites so a change in any included leaf cannot leave this cross-root
# documentation stale.
OCAH_REG_MEMORY_MAP_DEPS_hw_ip_efuse_regs_efuse_interface_ctrl := \
  $(foreach dir,$(OCAH_REG_CATALOG_DIRS),$(wildcard $(dir)/*.rdl))

# Blocks whose regblock RTL answers a bad address or a write to a read-only
# register with an error response, rather than silently accepting it. Listed by
# name; the overlay appends its own.
OCAH_REG_ERR_CHECK_BLOCKS ?= \
  abr_wrapper_key \
  aes_wrapper_key \
  hmac_wrapper_key \
  km_csr \
  km_drbg_sampler \
  km_kpv \
  km_mailbox_km \
  km_mailbox_sep \
  kmac_wrapper_key \
  otbn_wrapper_key
OCAH_REG_ERR_CHECK_BLOCKS += $(OCAH_REG_ERR_CHECK_BLOCKS_EXTRA)

ocah_reg_has_json = $(filter $(1),$(OCAH_REG_JSON_BLOCKS))
ocah_reg_has_py_field_access = $(filter $(1),$(OCAH_REG_PY_FIELD_ACCESS_BLOCKS))
ocah_reg_leaf_has_ral = $(filter $(1),$(OCAH_REG_RAL_LEAF_BLOCKS))
ocah_reg_ral_blocks = $(filter $(OCAH_REG_RAL_SUB_BLOCKS),$(call ocah_reg_ch_blocks,$(1)))

# The model name drives both the emitted file (<model>_ral_pkg.sv) and its include
# guard; the rename drives the top instance, and so the generated class prefix.
# They are separate because the two reasons to override are unrelated: a wrapper
# RDL whose model is known by a shorter name than its top addrmap (axil_mailbox),
# versus a vendor block that must stay distinguishable from the open block it
# shadows (the Samsung eFuse shim, whose addrmap is deliberately named
# efuse_shim_ctrl so the canonical top instantiates it unchanged).
OCAH_REG_RAL_MODEL_hw_ip_axi_lite_mailbox_unit_regs_axil_mailbox_sep_wrap ?= axil_mailbox

# Local sub-blocks of a composite top: the regs/blocks/<sub>/ basenames (a pure
# glob, no addrmap scan). C and docs take them all; SV drops the RTL-elsewhere
# blocks (applied at materialization below).
ocah_reg_ch_blocks_scan = $(notdir $(patsubst %/,%,$(wildcard $(call ocah_reg_root,$(1))/regs/blocks/*/)))

# Composite tops vs plain leaves (the lists the rules in rules.mk loop over).
OCAH_REG_COMPOSITE_BLOCK_IDS := $(foreach block,$(OCAH_REG_BLOCKS),$(if $(call ocah_reg_is_composite,$(block)),$(block)))
OCAH_REG_PLAIN_BLOCK_IDS     := $(filter-out $(OCAH_REG_COMPOSITE_BLOCK_IDS),$(OCAH_REG_BLOCKS))

# Tops that get the shared catalog on their -I path: composite tops, plus plain
# wrapper/top RDLs that include sibling blocks by bare filename. The relocated
# OpenTitan overlay blocks hmac/kmac/otbn (like edn) pull the shared
# opentitan_udps.rdl fragment by bare include, so they need the catalog too.
# smc_cla is a leaf but composes the six generated dfd_<blk> RDLs, which live in
# the tt-hw-debug overlay include dir the catalog already globs.
OCAH_REG_CATALOG_SEARCH_BLOCKS ?= \
  edn \
  efuse_interface_ctrl \
  hmac \
  i2c_wrap \
  key_manager \
  kmac \
  oca_i3c_wrap \
  otbn \
  sep_external \
  smc \
  smc_cla \
  telemetry_receiver_wrap \
  uart_log_engine_wrap \
  uart_wrap
OCAH_REG_INCDIR_BLOCKS ?= $(sort $(OCAH_REG_CATALOG_SEARCH_BLOCKS) $(foreach b,$(OCAH_REG_COMPOSITE_BLOCK_IDS),$(call ocah_reg_name,$(b))))

# Per-block -I addition for the vendored i3c-core MIPI HCI map.
# oca_i3c_wrap `include "registers.rdl"`; put the vendor dir first on its path
# (file-backed EXTRA_SEARCH defaults to the local regs/ dir, which has no
# registers.rdl of its own).
OCAH_REG_EXTRA_SEARCH_hw_ip_i3ccore_wrap_regs_oca_i3c_wrap += \
  $(OCAH_ROOT)/vendor/chipsalliance/i3c-core/upstream/src/rdl

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
OCAH_REG_BITFIELDS_PY_$(call ocah_reg_key,$(1)) := $(if $(filter $(call ocah_reg_name,$(1)),$(OCAH_REG_NO_BITFIELDS_PY)),none,ltoh)
OCAH_REG_HTML_$(call ocah_reg_key,$(1)) := $(or $(OCAH_REG_HTML_OUTPUT_OVERRIDE_$(call ocah_reg_key,$(1))),$(OCAH_REG_GEN_$(call ocah_reg_key,$(1)))/html/$(call ocah_reg_name,$(1)).html)
endef
$(foreach block,$(OCAH_REG_BLOCKS),$(eval $(call ocah_reg_classify_vars,$(block))))

# Per-output-class sub-block lists for composite tops. SUBDOC/SUBSV reference the
# prior line's var, escaped ($$) so they expand at eval time (after it is assigned).
# SUBDOC currently mirrors SUBCH; it stays a separate var so a doc-only exclusion
# has a place to go without threading a new list through out.mk.
define ocah_reg_classify_composite_vars
OCAH_REG_SUBCH_$(call ocah_reg_key,$(1)) := $(call ocah_reg_ch_blocks_scan,$(1))
OCAH_REG_SUBDOC_$(call ocah_reg_key,$(1)) := $$(OCAH_REG_SUBCH_$(call ocah_reg_key,$(1)))
OCAH_REG_SUBSV_$(call ocah_reg_key,$(1)) := $$(filter-out $$(OCAH_REG_NO_RTL_BLOCKS),$$(OCAH_REG_SUBDOC_$(call ocah_reg_key,$(1))))
endef
$(foreach block,$(OCAH_REG_COMPOSITE_BLOCK_IDS),$(eval $(call ocah_reg_classify_composite_vars,$(block))))
