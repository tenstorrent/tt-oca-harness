# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# Finds the register blocks and works out each one's input/output paths: the
# source RDL, gen/build dirs, source HJSON, and include search dirs. classify.mk
# then fills in the per-block policy (which outputs each block gets).

# First-party tops: dirs holding the dir-name RDL
# (hw/{ip,sys}/<name>/regs/<name>.rdl). System-level register sources
# are normalized into hw/sys/<name>/regs (for example SMC and SEP); AXI network
# and monitor elements live under hw/ip/<name>/regs; legacy per-RTL
# data/registers trees are intentionally not discovered here. Role == location
# (see doc/user_guide/regs.adoc), so discovery is a pure glob. IPs may also be
# grouped one level deeper by family (hw/ip/<family>/<ip>/regs, e.g. jtag, uart,
# cross_trigger), so both hw/ip/*/regs and hw/ip/*/*/regs are globbed. The block
# NAME is notdir(id), so nesting changes the path only, never the block name. The
# vendor overlay glob picks up checked-in RDLs for vendored IPs (e.g. the relocated
# OpenTitan reg blocks under vendor/<org>/<pkg>/overlay/regs/<ip>/regs/<ip>.rdl), so
# they behave exactly like a hw/ip block.
ocah_reg_dirs := $(wildcard \
  $(OCAH_ROOT)/hw/ip/*/regs \
  $(OCAH_ROOT)/hw/ip/*/*/regs \
  $(OCAH_ROOT)/hw/sys/*/regs \
  $(OCAH_ROOT)/vendor/*/*/overlay/regs/*/regs)
ocah_reg_root_if_rdl = $(if $(wildcard $(1)/$(notdir $(patsubst %/regs,%,$(1))).rdl),$(patsubst $(OCAH_ROOT)/%,%,$(patsubst %/regs,%,$(1))))
OCAH_RDL_REG_BLOCKS := $(sort $(foreach d,$(ocah_reg_dirs),$(call ocah_reg_root_if_rdl,$(d))))

# Standalone siblings: regs/*.rdl minus the dir-name top (fragments live in
# regs/include/, sub-blocks in regs/blocks/). Emit flat via the file-backed path.
ocah_reg_sibling_rdls = $(filter-out $(1)/$(notdir $(patsubst %/regs,%,$(1))).rdl,$(wildcard $(1)/*.rdl))
OCAH_REG_SIBLING_RDL_FILES := $(foreach d,$(ocah_reg_dirs),$(call ocah_reg_sibling_rdls,$(d)))

# Extra RDL files exported as standalone blocks: DV shims, vendored overlay RDLs
# (e.g. pulp-platform idma's dma_ctrl, which lives in overlay/rdl/ rather than the
# overlay/regs/<ip>/regs layout the block globs above discover), plus the regs-root
# siblings.
OCAH_REG_STANDALONE_RDL_FILES ?= \
  $(wildcard $(OCAH_ROOT)/hw/sys/*/dv/models/regs/*.rdl) \
  $(wildcard $(OCAH_ROOT)/hw/ip/*/dv/models/regs/*.rdl) \
  $(wildcard $(OCAH_ROOT)/hw/ip/*/*/dv/models/regs/*.rdl) \
  $(wildcard $(OCAH_ROOT)/vendor/*/*/overlay/rdl/*.rdl) \
  $(OCAH_REG_SIBLING_RDL_FILES)
# efuse_bank is a hand-maintained DV model; its RDL lives under dv/models/regs/
# for reference only. Exclude it from regen so PeakRDL never overwrites the
# hand-edited storage process.
OCAH_REG_STANDALONE_RDL_FILES := $(filter-out \
  $(OCAH_ROOT)/hw/ip/efuse/dv/models/regs/efuse_bank.rdl, \
  $(OCAH_REG_STANDALONE_RDL_FILES))
OCAH_EXTRA_REG_RDL_FILES ?=

ocah_reg_file_block_id = $(patsubst $(OCAH_ROOT)/%,%,$(basename $(1)))
OCAH_RDL_FILE_REG_FILES := $(sort $(OCAH_REG_STANDALONE_RDL_FILES) $(OCAH_EXTRA_REG_RDL_FILES))
OCAH_RDL_FILE_REG_BLOCKS := $(foreach f,$(OCAH_RDL_FILE_REG_FILES),$(call ocah_reg_file_block_id,$(f)))

ocah_relpath = $(patsubst $(OCAH_ROOT)/%,%,$(1))

# Per-id accessors: name, source root, make-safe key (ids may contain '/').
ocah_reg_name = $(notdir $(1))
ocah_reg_root = $(OCAH_ROOT)/$(1)
ocah_reg_key = $(subst /,_,$(1))

# Vendored register RDLs refreshable from upstream OpenTitan hjson. The RDL is
# committed (a clean checkout needs no regen), so these are NOT discovered here as
# blocks - the committed RDL is found by the globs above. This is purely the
# regen source map for the on-demand `regen-vendor-rdl` target (see phony.mk).
# Entry: <committed-rdl-relpath>:<opentitan-relative-hjson>[:<addrmap-name>].
# The optional 3rd field overrides the emitted addrmap name for IPs vendored under
# their upstream name but renamed in tt-oca (dma -> secure_dma, spi_host ->
# spi_controller); reggen reproduces the same registers, only the top name differs.
OCAH_VENDOR_HJSON_RDLS ?= \
  vendor/lowRISC/opentitan/overlay/regs/aes/regs/aes.rdl:upstream/hw/ip/aes/data/aes.hjson \
  vendor/lowRISC/opentitan/overlay/regs/hmac/regs/hmac.rdl:upstream/hw/ip/hmac/data/hmac.hjson \
  vendor/lowRISC/opentitan/overlay/regs/kmac/regs/kmac.rdl:upstream/hw/ip/kmac/data/kmac.hjson \
  vendor/lowRISC/opentitan/overlay/regs/otbn/regs/otbn.rdl:upstream/hw/ip/otbn/data/otbn.hjson \
  vendor/lowRISC/opentitan/overlay/regs/aon_timer/regs/aon_timer.rdl:upstream/hw/ip/aon_timer/data/aon_timer.hjson \
  vendor/lowRISC/opentitan/overlay/regs/csrng/regs/csrng.rdl:upstream/hw/ip/csrng/data/csrng.hjson \
  vendor/lowRISC/opentitan/overlay/regs/edn/regs/edn.rdl:upstream/hw/ip/edn/data/edn.hjson \
  vendor/lowRISC/opentitan/overlay/regs/secure_dma/regs/secure_dma.rdl:upstream/hw/ip/dma/data/dma.hjson:secure_dma \
  vendor/lowRISC/opentitan/overlay/regs/spi_controller/regs/spi_controller.rdl:upstream/hw/ip/spi_host/data/spi_host.hjson:spi_controller

ocah_vhr_rdl     = $(word 1,$(subst :, ,$(1)))
ocah_vhr_hjson   = $(OCAH_ROOT)/vendor/lowRISC/opentitan/$(word 2,$(subst :, ,$(1)))
ocah_vhr_nameopt = $(if $(word 3,$(subst :, ,$(1))),--name $(word 3,$(subst :, ,$(1))))
ocah_vhr_name    = $(basename $(notdir $(call ocah_vhr_rdl,$(1))))

# Preserve each checked-in RDL's compatibility-sensitive serializer dialect.
OCAH_VHR_UPPERCASE_FIELDS := aes csrng secure_dma spi_controller
OCAH_VHR_FIRST_REPLICA_MULTIREGS := secure_dma
OCAH_VHR_BASE_MULTIREG_FIELDS := aes
OCAH_VHR_FLATTEN_MULTIREGS := csrng
OCAH_VHR_ARRAYED_WINDOWS := spi_controller
# Emit the addrmap name/desc from the upstream hjson human_name/one_line_desc so
# the register pages head with a friendly title, matching the other vendored IPs.
OCAH_VHR_NO_METADATA :=
OCAH_VHR_NO_GUARD := aes csrng secure_dma spi_controller
OCAH_VHR_NO_UDP_INCLUDE := secure_dma spi_controller

# Overlay hook: extra block ids, usually variants reusing a top RDL.
OCAH_EXTRA_REG_BLOCKS ?=

OCAH_REG_BLOCKS ?= \
  $(OCAH_RDL_REG_BLOCKS) \
  $(OCAH_RDL_FILE_REG_BLOCKS) \
  $(OCAH_EXTRA_REG_BLOCKS)

# Shared -I dirs for tops that pull sub-block/fragment RDLs by bare include:
# IP regs roots, regs/include, regs/blocks/<sub>, and the DV shim trees.
OCAH_REG_CATALOG_DIRS := \
  $(wildcard $(OCAH_ROOT)/hw/ip/*/regs) \
  $(wildcard $(OCAH_ROOT)/hw/ip/*/*/regs) \
  $(wildcard $(OCAH_ROOT)/hw/ip/*/regs/include) \
  $(wildcard $(OCAH_ROOT)/hw/ip/*/*/regs/include) \
  $(wildcard $(OCAH_ROOT)/hw/ip/*/regs/blocks/*) \
  $(wildcard $(OCAH_ROOT)/hw/ip/*/*/regs/blocks/*) \
  $(wildcard $(OCAH_ROOT)/hw/sys/*/regs) \
  $(wildcard $(OCAH_ROOT)/hw/sys/*/regs/include) \
  $(wildcard $(OCAH_ROOT)/hw/sys/*/regs/blocks/*) \
  $(wildcard $(OCAH_ROOT)/hw/sys/*/dv/models/regs) \
  $(wildcard $(OCAH_ROOT)/hw/ip/*/dv/models/regs) \
  $(wildcard $(OCAH_ROOT)/hw/ip/*/*/dv/models/regs) \
  $(wildcard $(OCAH_ROOT)/vendor/*/*/overlay/regs/*/regs) \
  $(wildcard $(OCAH_ROOT)/vendor/*/*/overlay/regs/*/regs/include) \
  $(wildcard $(OCAH_ROOT)/vendor/*/*/overlay/rdl) \
  $(wildcard $(OCAH_ROOT)/vendor/chipsalliance/i3c-core/upstream/src/rdl/tt_rdl) \
  $(wildcard $(OCAH_ROOT)/vendor/chipsalliance/i3c-core/upstream/src/rdl) \
  $(wildcard $(OCAH_ROOT)/vendor/chipsalliance/adams-bridge/upstream/src/abr_top/rtl)

# A block's own includes (regs/include + regs/blocks/<sub>), always on its -I path.
ocah_reg_own_search_dirs = \
  $(wildcard $(call ocah_reg_root,$(1))/regs/include) \
  $(wildcard $(call ocah_reg_root,$(1))/regs/blocks/*)

# -I order: overlay extras (win by precedence), own includes, then the shared
# catalog for composite tops (OCAH_REG_INCDIR_BLOCKS, set by classify.mk).
ocah_reg_search_dirs = $(OCAH_REG_EXTRA_SEARCH_$(call ocah_reg_key,$(1))) $(call ocah_reg_own_search_dirs,$(1)) $(if $(filter $(call ocah_reg_name,$(1)),$(OCAH_REG_INCDIR_BLOCKS)),$(OCAH_REG_CATALOG_DIRS))
ocah_reg_incdirs_resolve = $(addprefix -I ,$(call ocah_reg_search_dirs,$(1)))

# File-backed block metadata: shared regs/gen/ dir, per-entry build dir (no clash).
define ocah_reg_file_block_vars
OCAH_REG_RDL_OVERRIDE_$(call ocah_reg_key,$(call ocah_reg_file_block_id,$(1))) := $(1)
OCAH_REG_GEN_OVERRIDE_$(call ocah_reg_key,$(call ocah_reg_file_block_id,$(1))) := $(patsubst %/,%,$(dir $(1)))/gen
OCAH_REG_BUILD_OVERRIDE_$(call ocah_reg_key,$(call ocah_reg_file_block_id,$(1))) := $(patsubst %/,%,$(dir $(1)))/build/$(notdir $(basename $(1)))
OCAH_REG_HTML_OUTPUT_OVERRIDE_$(call ocah_reg_key,$(call ocah_reg_file_block_id,$(1))) := $(patsubst %/,%,$(dir $(1)))/gen/html/$(notdir $(basename $(1))).html
OCAH_REG_EXTRA_SEARCH_$(call ocah_reg_key,$(call ocah_reg_file_block_id,$(1))) ?= $(patsubst %/,%,$(dir $(1)))
endef
$(foreach f,$(OCAH_RDL_FILE_REG_FILES),$(eval $(call ocah_reg_file_block_vars,$(f))))

# Source-path resolvers. RDL is overridable (OCAH_REG_RDL_OVERRIDE_<key>) so an
# overlay variant reuses a canonical RDL while emitting under its own gen/ dir.
ocah_reg_rdl_resolve = $(or $(OCAH_REG_RDL_OVERRIDE_$(call ocah_reg_key,$(1))),$(call ocah_reg_root,$(1))/regs/$(call ocah_reg_name,$(1)).rdl)
ocah_reg_hjson_resolve = $(call ocah_reg_root,$(1))/data/$(call ocah_reg_name,$(1)).hjson
ocah_reg_gen_resolve = $(or $(OCAH_REG_GEN_OVERRIDE_$(call ocah_reg_key,$(1))),$(call ocah_reg_root,$(1))/regs/gen)
ocah_reg_build_resolve = $(or $(OCAH_REG_BUILD_OVERRIDE_$(call ocah_reg_key,$(1))),$(call ocah_reg_root,$(1))/regs/build)

# Set the per-block path vars (RDL/GEN/BUILD/HJSON); SEARCH is set in classify.mk.
define ocah_reg_discover_vars
OCAH_REG_RDL_$(call ocah_reg_key,$(1)) := $(call ocah_reg_rdl_resolve,$(1))
OCAH_REG_GEN_$(call ocah_reg_key,$(1)) := $(call ocah_reg_gen_resolve,$(1))
OCAH_REG_BUILD_$(call ocah_reg_key,$(1)) := $(call ocah_reg_build_resolve,$(1))
OCAH_REG_HJSON_$(call ocah_reg_key,$(1)) := $(call ocah_reg_hjson_resolve,$(1))
endef
$(foreach block,$(OCAH_REG_BLOCKS),$(eval $(call ocah_reg_discover_vars,$(block))))
