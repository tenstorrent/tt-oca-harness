# SPDX-License-Identifier: Apache-2.0
# (c) 2026 Tenstorrent USA Inc

ifndef ocah_regs_mk
ocah_regs_mk := 1

# Auto-discover first-party RDL blocks at hw/{ip,sys}/<name>/regs/<name>.rdl.
# Additional standalone RDL entry points are registered below by file path.
ocah_reg_dirs := $(wildcard $(OCAH_ROOT)/hw/ip/*/regs $(OCAH_ROOT)/hw/sys/*/regs)
ocah_reg_root_if_rdl = $(if $(wildcard $(1)/$(notdir $(patsubst %/regs,%,$(1))).rdl),$(patsubst $(OCAH_ROOT)/%,%,$(patsubst %/regs,%,$(1))))
OCAH_RDL_REG_BLOCKS := $(sort $(foreach d,$(ocah_reg_dirs),$(call ocah_reg_root_if_rdl,$(d))))

# Standalone RDL files generated as normal blocks even though their name is not
# a hw/{ip,sys}/<name>/ root basename: DV shims and IP sub-blocks pulled by the
# firmware umbrellas (hw/common/dv/fw/*.h).
OCAH_REG_UMBRELLA_IP_RDL_NAMES ?= \
  efuse_interface_ctrl \
  axil_mailbox_smc_wrap \
  axil_mailbox_sep_wrap \
  km_mailbox_sep
OCAH_REG_STANDALONE_RDL_FILES ?= \
  $(wildcard $(OCAH_ROOT)/hw/sys/*/dv/shims/regs/*.rdl) \
  $(wildcard $(OCAH_ROOT)/hw/ip/*/dv/shims/regs/*.rdl) \
  $(foreach n,$(OCAH_REG_UMBRELLA_IP_RDL_NAMES),$(wildcard $(OCAH_ROOT)/hw/ip/*/regs/$(n).rdl))
OCAH_EXTRA_REG_RDL_FILES ?=

ocah_reg_file_block_id = $(patsubst $(OCAH_ROOT)/%,%,$(basename $(1)))
OCAH_RDL_FILE_REG_FILES := $(sort $(OCAH_REG_STANDALONE_RDL_FILES) $(OCAH_EXTRA_REG_RDL_FILES))
OCAH_RDL_FILE_REG_BLOCKS := $(foreach f,$(OCAH_RDL_FILE_REG_FILES),$(call ocah_reg_file_block_id,$(f)))

OCAH_BENDER ?= bender
ocah_bender_path = $(strip $(shell $(OCAH_BENDER) path $(1) 2>/dev/null))
ocah_relpath = $(patsubst $(OCAH_ROOT)/%,%,$(1))

# HJSON-backed vendor blocks, each "<bender-package>:<package-relative-hjson>".
# The block name is the HJSON basename; the package root is resolved with
# `bender path`. Collateral lands under <package-root>/gen/<block-name>, leaving
# the vendored upstream/ tree untouched.
OCAH_VENDOR_HJSON_REG_BLOCKS ?= \
  opentitan:upstream/hw/ip/otbn/data/otbn.hjson \
  idma:upstream/target/rtl/idma_reg64_2d.hjson

ocah_vendor_pkg = $(word 1,$(subst :, ,$(1)))
ocah_vendor_hjson_rel = $(word 2,$(subst :, ,$(1)))
ocah_vendor_name = $(basename $(notdir $(call ocah_vendor_hjson_rel,$(1))))
ocah_vendor_root = $(call ocah_bender_path,$(call ocah_vendor_pkg,$(1)))
ocah_vendor_reg_block = $(call ocah_relpath,$(call ocah_vendor_root,$(1)))/gen/$(call ocah_vendor_name,$(1))
ocah_vendor_reg_hjson = $(call ocah_vendor_root,$(1))/$(call ocah_vendor_hjson_rel,$(1))

OCAH_HJSON_REG_BLOCKS ?= $(foreach e,$(OCAH_VENDOR_HJSON_REG_BLOCKS),$(call ocah_vendor_reg_block,$(e)))

# OCAH_EXTRA_REG_BLOCKS lets an optional overlay (e.g. nonfree/nonfree.mk, which
# is included before this file) register additional block ids - typically
# variant builds that reuse a canonical top RDL with overlay includes swapped in.
OCAH_EXTRA_REG_BLOCKS ?=

OCAH_REG_BLOCKS ?= \
  $(OCAH_RDL_REG_BLOCKS) \
  $(OCAH_RDL_FILE_REG_BLOCKS) \
  $(OCAH_HJSON_REG_BLOCKS) \
  $(OCAH_EXTRA_REG_BLOCKS)

OCAH_REGBLOCK_UDP ?= $(OCAH_ROOT)/hw/common/regs/regblock_udps.rdl
OCAH_REG_CPU_IF ?= axi4-lite-flat
OCAH_REG_DEFAULT_RESET ?= arst_n
OCAH_PANDOC ?= pandoc
OCAH_REGGEN_WRAPPER ?= $(OCAH_ROOT)/tools/regs/reggen_wrapper.py
OCAH_REGEN_REG_JOBS ?= 8

# Register generation is embarrassingly parallel across blocks and sub-blocks.
# Default those goals to -j8 unless the user already supplied a jobs flag.
ocah_reg_make_goals := $(filter regen-regs% ocah-regen-regs%,$(MAKECMDGOALS))
ifneq ($(ocah_reg_make_goals),)
ifeq ($(filter -j% --jobs%,$(MAKEFLAGS)),)
MAKEFLAGS += -j$(OCAH_REGEN_REG_JOBS)
endif
endif

# Run a tool from the repo root, mirroring output into a log; used as
# `@$(ocah_sh) '<cmd> 2>&1 | tee "<log>"'`. A plain constant (not a $(call)
# function) so commands carrying their own commas stay intact.
ocah_sh := cd "$(OCAH_ROOT)" && bash -o pipefail -c

# Shared catalog of bare search dirs for tops that pull sub-block RDLs from
# elsewhere via bare `include lines; self-contained blocks need none. Covers the
# hw/ip register catalog plus the DV shim trees.
OCAH_REG_CATALOG_DIRS := \
  $(wildcard $(OCAH_ROOT)/hw/ip/*/regs) \
  $(wildcard $(OCAH_ROOT)/hw/sys/*/dv/shims/regs) \
  $(wildcard $(OCAH_ROOT)/hw/ip/*/dv/shims/regs)
OCAH_REG_INCDIR_BLOCKS ?= $(OCAH_REG_COMPOSITE_BLOCKS)

# Ordered bare search dirs for a block: per-block overlay extras first
# (OCAH_REG_EXTRA_SEARCH_<key>), then the shared catalog for incdir tops, so
# same-named overlay RDLs win by include-path precedence. Emitted as peakrdl -I
# flags for consistent `include resolution across exporter runs.
ocah_reg_search_dirs = $(OCAH_REG_EXTRA_SEARCH_$(call ocah_reg_key,$(1))) $(if $(filter $(call ocah_reg_name,$(1)),$(OCAH_REG_INCDIR_BLOCKS)),$(OCAH_REG_CATALOG_DIRS))
ocah_reg_incdirs = $(addprefix -I ,$(call ocah_reg_search_dirs,$(1)))

# Blocks whose C header is emitted without bitfield structs (peakrdl c-header
# cannot represent registers wider than 64 bits, so these fall back to address +
# field mask/position defines only).
OCAH_REG_NO_BITFIELDS ?= smc_efuse_map sep_efuse_map
ocah_reg_c_bitfields = $(if $(filter $(call ocah_reg_name,$(1)),$(OCAH_REG_NO_BITFIELDS)),none,ltoh)

# Composite tops aggregate sub-blocks at addresses peakrdl exporters cannot run
# as one top, so each local sub-block is generated on its own and the top keeps
# only its address view. The firmware umbrella is hand-maintained outside gen/
# (see hw/common/dv/fw/<top>.h).
OCAH_REG_COMPOSITE_BLOCKS ?= sep smc
ocah_reg_is_composite = $(filter $(call ocah_reg_name,$(1)),$(OCAH_REG_COMPOSITE_BLOCKS))

# Placeholder blocks reserve an address window only; they get a C header but no
# SV RTL and no docs.
OCAH_REG_PLACEHOLDER_BLOCKS ?= oca_i3c_wrap
# Blocks whose register RTL is authored outside peakrdl regblock; excluded from
# SV RTL only, still documented and still get a C header.
OCAH_REG_NO_RTL_BLOCKS ?= \
  aes hmac kmac otbn \
  smc_efuse_map sep_efuse_map \
  clint plic debug_module wdt bus_error_unit misc_wrap \
  el2_pic aon_timer efuse_mmr dfd

# Local sub-block sets for a composite top, derived by globbing its regs/ dir.
# Memories (no addrmap) yield no collateral and drop out structurally; C headers
# keep placeholders; docs drop placeholders; SV additionally drops RTL-elsewhere.
ocah_reg_local_rdls = $(filter-out %/$(call ocah_reg_name,$(1)).rdl,$(wildcard $(call ocah_reg_root,$(1))/regs/*.rdl))
ocah_reg_ch_blocks = $(basename $(notdir $(shell grep -lE '\baddrmap\b' $(call ocah_reg_local_rdls,$(1)) /dev/null)))
ocah_reg_doc_blocks = $(filter-out $(OCAH_REG_PLACEHOLDER_BLOCKS),$(call ocah_reg_ch_blocks,$(1)))
ocah_reg_sv_blocks = $(filter-out $(OCAH_REG_NO_RTL_BLOCKS),$(call ocah_reg_doc_blocks,$(1)))
# A plain (leaf) block whose own name is RTL-elsewhere is header-only: no
# regblock run, just the address exporters.
ocah_reg_sv_skipped = $(filter $(call ocah_reg_name,$(1)),$(OCAH_REG_NO_RTL_BLOCKS))

ocah_reg_block_by_name = $(strip $(foreach block,$(OCAH_REG_BLOCKS),$(if $(filter $(1),$(notdir $(block))),$(block))))
OCAH_SELECTED_REG_BLOCKS := $(if $(TARGET),$(call ocah_reg_block_by_name,$(TARGET)),$(OCAH_REG_BLOCKS))

ifeq ($(strip $(OCAH_SELECTED_REG_BLOCKS)),)
  $(error Unknown OCAH register block '$(TARGET)'; known blocks: $(foreach block,$(OCAH_REG_BLOCKS),$(notdir $(block))))
endif

ocah_reg_name = $(notdir $(1))
ocah_reg_root = $(OCAH_ROOT)/$(1)
# Make-safe per-block key (block ids may contain '/', e.g. overlay variants).
ocah_reg_key = $(subst /,_,$(1))

# Standalone file-backed block metadata. These blocks share generated headers
# with their containing regs/ dir (e.g. hw/sys/smc/dv/shims/regs/gen/c) but get a
# per-entry build dir so their .generated stamps do not collide.
define ocah_reg_file_block_vars
OCAH_REG_RDL_OVERRIDE_$(call ocah_reg_key,$(call ocah_reg_file_block_id,$(1))) := $(1)
OCAH_REG_GEN_OVERRIDE_$(call ocah_reg_key,$(call ocah_reg_file_block_id,$(1))) := $(patsubst %/,%,$(dir $(1)))/gen
OCAH_REG_BUILD_OVERRIDE_$(call ocah_reg_key,$(call ocah_reg_file_block_id,$(1))) := $(patsubst %/,%,$(dir $(1)))/build/regs/$(notdir $(basename $(1)))
OCAH_REG_HTML_OUTPUT_OVERRIDE_$(call ocah_reg_key,$(call ocah_reg_file_block_id,$(1))) := $(patsubst %/,%,$(dir $(1)))/gen/html/$(notdir $(basename $(1)))/index.html
OCAH_REG_EXTRA_SEARCH_$(call ocah_reg_key,$(call ocah_reg_file_block_id,$(1))) ?= $(patsubst %/,%,$(dir $(1)))
endef
$(foreach f,$(OCAH_RDL_FILE_REG_FILES),$(eval $(call ocah_reg_file_block_vars,$(f))))

# Source RDL, overridable via OCAH_REG_RDL_OVERRIDE_<key> so an overlay variant
# can reuse a canonical RDL elsewhere while emitting under its own gen/ dir.
ocah_reg_rdl = $(or $(OCAH_REG_RDL_OVERRIDE_$(call ocah_reg_key,$(1))),$(call ocah_reg_root,$(1))/regs/$(call ocah_reg_name,$(1)).rdl)
ocah_reg_hjson_vendor = $(strip $(foreach e,$(OCAH_VENDOR_HJSON_REG_BLOCKS),$(if $(filter $(call ocah_vendor_reg_block,$(e)),$(1)),$(call ocah_vendor_reg_hjson,$(e)))))
ocah_reg_hjson_default = $(call ocah_reg_root,$(1))/data/$(call ocah_reg_name,$(1)).hjson
ocah_reg_hjson = $(or $(call ocah_reg_hjson_vendor,$(1)),$(call ocah_reg_hjson_default,$(1)))
ocah_reg_gen = $(or $(OCAH_REG_GEN_OVERRIDE_$(call ocah_reg_key,$(1))),$(call ocah_reg_root,$(1))/regs/gen)
ocah_reg_build = $(or $(OCAH_REG_BUILD_OVERRIDE_$(call ocah_reg_key,$(1))),$(call ocah_reg_root,$(1))/build/regs)

ocah_reg_sv_stamp = $(call ocah_reg_build,$(1))/sv.generated
ocah_reg_sv_outputs = \
  $(call ocah_reg_gen,$(1))/sv/$(call ocah_reg_name,$(1))_reg.sv \
  $(call ocah_reg_gen,$(1))/sv/$(call ocah_reg_name,$(1))_reg_pkg.sv
# Composite tops emit per-sub-block collateral under blocks/ dirs; plain (leaf)
# blocks use the single-file outputs below.
ocah_reg_sv_block_dir = $(call ocah_reg_gen,$(1))/sv/blocks
ocah_reg_c_block_dir = $(call ocah_reg_gen,$(1))/c/blocks
ocah_reg_adoc_block_dir = $(call ocah_reg_gen,$(1))/adoc/blocks
ocah_reg_html_block_dir = $(call ocah_reg_gen,$(1))/html/blocks
ocah_reg_c_output = $(call ocah_reg_gen,$(1))/c/$(call ocah_reg_name,$(1)).h
ocah_reg_svpkg_output = $(call ocah_reg_gen,$(1))/svh/$(call ocah_reg_name,$(1))_reg.svh
ocah_reg_raw_c_output = $(call ocah_reg_gen,$(1))/c/$(call ocah_reg_name,$(1))_addr.h
ocah_reg_py_output = $(call ocah_reg_gen,$(1))/py/$(call ocah_reg_name,$(1))_addr.py
ocah_reg_md_output = $(call ocah_reg_gen,$(1))/adoc/$(call ocah_reg_name,$(1)).md
ocah_reg_adoc_output = $(call ocah_reg_gen,$(1))/adoc/$(call ocah_reg_name,$(1)).adoc
ocah_reg_html_output = $(or $(OCAH_REG_HTML_OUTPUT_OVERRIDE_$(call ocah_reg_key,$(1))),$(call ocah_reg_gen,$(1))/html/index.html)

# Per-sub-block output file lists for a composite top (one file per sub-block, so
# make tracks each independently - only the changed RDL rebuilds).
ocah_reg_sv_block_outputs = $(foreach b,$(call ocah_reg_sv_blocks,$(1)),$(call ocah_reg_sv_block_dir,$(1))/$(b)_reg.sv)
ocah_reg_c_block_outputs = $(foreach b,$(call ocah_reg_ch_blocks,$(1)),$(call ocah_reg_c_block_dir,$(1))/$(b).h)
ocah_reg_adoc_block_outputs = $(foreach b,$(call ocah_reg_doc_blocks,$(1)),$(call ocah_reg_adoc_block_dir,$(1))/$(b).adoc)
ocah_reg_html_block_outputs = $(foreach b,$(call ocah_reg_doc_blocks,$(1)),$(call ocah_reg_html_block_dir,$(1))/$(b)/index.html)

# Output selectors feeding the regen-regs-* aggregates and the .generated deps:
# composite -> per-sub-block lists; RTL-elsewhere leaf -> empty SV stamp; plain
# leaf -> single-file outputs.
ocah_reg_sv_target = $(if $(call ocah_reg_is_composite,$(1)),$(call ocah_reg_sv_block_outputs,$(1)),$(if $(call ocah_reg_sv_skipped,$(1)),$(call ocah_reg_sv_stamp,$(1)),$(call ocah_reg_sv_outputs,$(1))))
ocah_reg_h_target = $(if $(call ocah_reg_is_composite,$(1)),$(call ocah_reg_c_block_outputs,$(1)),$(call ocah_reg_c_output,$(1)))
ocah_reg_adoc_target = $(if $(call ocah_reg_is_composite,$(1)),$(call ocah_reg_adoc_block_outputs,$(1)),$(call ocah_reg_adoc_output,$(1)))
ocah_reg_html_target = $(if $(call ocah_reg_is_composite,$(1)),$(call ocah_reg_html_block_outputs,$(1)),$(call ocah_reg_html_output,$(1)))
ocah_reg_html_dir = $(patsubst %/,%,$(dir $(call ocah_reg_html_output,$(1))))
ocah_reg_is_file_backed = $(OCAH_REG_GEN_OVERRIDE_$(call ocah_reg_key,$(1)))
ocah_reg_file_clean_outputs = \
  $(call ocah_reg_sv_outputs,$(1)) \
  $(call ocah_reg_svpkg_output,$(1)) \
  $(call ocah_reg_c_output,$(1)) \
  $(call ocah_reg_raw_c_output,$(1)) \
  $(call ocah_reg_py_output,$(1)) \
  $(call ocah_reg_md_output,$(1)) \
  $(call ocah_reg_adoc_output,$(1)) \
  $(call ocah_reg_html_dir,$(1))
ocah_reg_clean_paths = $(if $(call ocah_reg_is_file_backed,$(1)),$(call ocah_reg_file_clean_outputs,$(1)) $(call ocah_reg_build,$(1)),$(call ocah_reg_gen,$(1)) $(call ocah_reg_build,$(1)))

OCAH_REGEN_REG_SV := $(foreach block,$(OCAH_SELECTED_REG_BLOCKS),$(call ocah_reg_sv_target,$(block)))
OCAH_REGEN_REG_H := $(foreach block,$(OCAH_SELECTED_REG_BLOCKS),$(call ocah_reg_h_target,$(block)) $(call ocah_reg_raw_c_output,$(block)))
OCAH_REGEN_REG_SVH := $(foreach block,$(OCAH_SELECTED_REG_BLOCKS),$(call ocah_reg_svpkg_output,$(block)))
OCAH_REGEN_REG_PY := $(foreach block,$(OCAH_SELECTED_REG_BLOCKS),$(call ocah_reg_py_output,$(block)))
OCAH_REGEN_REG_ADOC := $(foreach block,$(OCAH_SELECTED_REG_BLOCKS),$(call ocah_reg_adoc_target,$(block)))
OCAH_REGEN_REG_HTML := $(foreach block,$(OCAH_SELECTED_REG_BLOCKS),$(call ocah_reg_html_target,$(block)))
OCAH_REGEN_REG_STAMPS := $(foreach block,$(OCAH_SELECTED_REG_BLOCKS),$(call ocah_reg_build,$(block))/.generated)
# Default regen-regs skips documentation. Documentation is generated explicitly
# by regen-regs-adoc and regen-regs-html (or by the doc build flow).
OCAH_REGEN_ALL := \
  $(OCAH_REGEN_REG_SV) \
  $(OCAH_REGEN_REG_H) \
  $(OCAH_REGEN_REG_SVH) \
  $(OCAH_REGEN_REG_PY)

define ocah_hjson_reg_block_rules
$(call ocah_reg_rdl,$(1)): $(call ocah_reg_hjson,$(1)) $(OCAH_REGGEN_WRAPPER) | uv-sync
	@mkdir -p "$(call ocah_reg_root,$(1))/regs" "$(call ocah_reg_build,$(1))"
	@echo "Exporting HJSON register description to RDL for $(1)"
	@cd "$(OCAH_ROOT)" && "$(UV)" run python tools/regs/reggen_wrapper.py \
		--systemrdl \
		-o "$(1)/regs/$(call ocah_reg_name,$(1)).rdl" \
		"$(call ocah_reg_hjson,$(1))"
endef

define ocah_reg_block_rules
$(call ocah_reg_raw_c_output,$(1)): $(call ocah_reg_rdl,$(1)) $(OCAH_REGBLOCK_UDP) | uv-sync
	@mkdir -p "$(call ocah_reg_gen,$(1))/c" "$(call ocah_reg_build,$(1))"
	@echo "Regenerating raw C address header for $(1)"
	@$(ocah_sh) '"$(UV)" run peakrdl raw-header $(call ocah_reg_incdirs,$(1)) "$(OCAH_REGBLOCK_UDP)" "$(call ocah_reg_rdl,$(1))" --format c --base-name "$(shell echo $(call ocah_reg_name,$(1))_addr | tr a-z A-Z)" -o "$(call ocah_reg_raw_c_output,$(1))" 2>&1 | tee "$(call ocah_reg_build,$(1))/raw_c_header.log"'

$(call ocah_reg_svpkg_output,$(1)): $(call ocah_reg_rdl,$(1)) $(OCAH_REGBLOCK_UDP) | uv-sync
	@mkdir -p "$(call ocah_reg_gen,$(1))/svh" "$(call ocah_reg_build,$(1))"
	@echo "Regenerating SystemVerilog address package include for $(1)"
	@$(ocah_sh) '"$(UV)" run peakrdl raw-header $(call ocah_reg_incdirs,$(1)) "$(OCAH_REGBLOCK_UDP)" "$(call ocah_reg_rdl,$(1))" --format svpkg -o "$(call ocah_reg_svpkg_output,$(1))" 2>&1 | tee "$(call ocah_reg_build,$(1))/raw_svpkg.log"'

$(call ocah_reg_py_output,$(1)): $(call ocah_reg_raw_c_output,$(1)) $(OCAH_ROOT)/tools/regs/pyhdr.py
	@mkdir -p "$(call ocah_reg_gen,$(1))/py" "$(call ocah_reg_build,$(1))"
	@echo "Regenerating Python address constants for $(1)"
	@cd "$(OCAH_ROOT)" && "$(UV)" run python tools/regs/pyhdr.py \
		"$(call ocah_reg_raw_c_output,$(1))" \
		"$(call ocah_reg_py_output,$(1))"

$(call ocah_reg_build,$(1))/.generated: $(call ocah_reg_sv_target,$(1)) $(call ocah_reg_h_target,$(1)) $(call ocah_reg_raw_c_output,$(1)) $(call ocah_reg_svpkg_output,$(1)) $(call ocah_reg_py_output,$(1))
	@mkdir -p "$(call ocah_reg_build,$(1))"
	@touch "$$@"
endef

# Register RTL for plain (leaf) blocks: one regblock run on the block's own RDL.
define ocah_reg_sv_plain_rule
$(call ocah_reg_sv_stamp,$(1)): $(call ocah_reg_rdl,$(1)) $(OCAH_REGBLOCK_UDP) | uv-sync
	@mkdir -p "$(call ocah_reg_gen,$(1))/sv" "$(call ocah_reg_build,$(1))"
	@echo "Regenerating register SV for $(1)"
	@$(ocah_sh) '"$(UV)" run peakrdl regblock $(call ocah_reg_incdirs,$(1)) "$(OCAH_REGBLOCK_UDP)" "$(call ocah_reg_rdl,$(1))" -o "$(call ocah_reg_gen,$(1))/sv" --cpuif "$(OCAH_REG_CPU_IF)" --default-reset "$(OCAH_REG_DEFAULT_RESET)" --module-name "$(call ocah_reg_name,$(1))_reg" --package-name "$(call ocah_reg_name,$(1))_reg_pkg" 2>&1 | tee "$(call ocah_reg_build,$(1))/peakrdl_sv.log"'
	@touch "$$@"

$(call ocah_reg_sv_outputs,$(1)): $(call ocah_reg_sv_stamp,$(1))
	@test -f "$$@" || { echo "error: expected generated file missing: $$@"; exit 1; }
endef

# Per-sub-block collateral for composite tops: pattern rules running the matching
# peakrdl exporter on each local sub-block RDL (one output per sub-block). The top
# keeps only its address view (see ocah_reg_block_rules).
define ocah_reg_composite_rules
$(call ocah_reg_sv_block_dir,$(1))/%_reg.sv: $(call ocah_reg_root,$(1))/regs/%.rdl $(OCAH_REGBLOCK_UDP) | uv-sync
	@mkdir -p "$$(@D)" "$(call ocah_reg_build,$(1))"
	@echo "Regenerating register SV for $(1) sub-block $$*"
	@$(ocah_sh) '"$(UV)" run peakrdl regblock $(call ocah_reg_incdirs,$(1)) "$(OCAH_REGBLOCK_UDP)" "$$<" -o "$$(@D)" --cpuif "$(OCAH_REG_CPU_IF)" --default-reset "$(OCAH_REG_DEFAULT_RESET)" --module-name "$$*_reg" --package-name "$$*_reg_pkg" 2>&1 | tee "$(1)/build/regs/peakrdl_sv_$$*.log"'

$(call ocah_reg_c_block_dir,$(1))/%.h: $(call ocah_reg_root,$(1))/regs/%.rdl $(OCAH_REGBLOCK_UDP) | uv-sync
	@mkdir -p "$$(@D)" "$(call ocah_reg_build,$(1))"
	@echo "Regenerating firmware C header for $(1) sub-block $$*"
	@$(ocah_sh) '"$(UV)" run peakrdl c-header $(call ocah_reg_incdirs,$(1)) "$(OCAH_REGBLOCK_UDP)" "$$<" -o "$$@" --bitfields $$(if $$(filter $$*,$(OCAH_REG_NO_BITFIELDS)),none,ltoh) --type-style lexical 2>&1 | tee "$(1)/build/regs/c_header_$$*.log"'

$(call ocah_reg_adoc_block_dir,$(1))/%.md: $(call ocah_reg_root,$(1))/regs/%.rdl $(OCAH_REGBLOCK_UDP) | uv-sync
	@mkdir -p "$$(@D)" "$(call ocah_reg_build,$(1))"
	@echo "Regenerating Markdown register docs for $(1) sub-block $$*"
	@$(ocah_sh) '"$(UV)" run peakrdl markdown $(call ocah_reg_incdirs,$(1)) "$(OCAH_REGBLOCK_UDP)" "$$<" -o "$$@" 2>&1 | tee "$(1)/build/regs/markdown_$$*.log"'

$(call ocah_reg_adoc_block_dir,$(1))/%.adoc: $(call ocah_reg_adoc_block_dir,$(1))/%.md
	@command -v "$(OCAH_PANDOC)" >/dev/null 2>&1 || { echo "error: pandoc is required to convert Markdown register docs to AsciiDoc"; exit 1; }
	@echo "Converting Markdown register docs to AsciiDoc for $(1) sub-block $$*"
	@cd "$(OCAH_ROOT)" && "$(OCAH_PANDOC)" -f markdown -t asciidoc "$$<" -o "$$@"

$(call ocah_reg_html_block_dir,$(1))/%/index.html: $(call ocah_reg_root,$(1))/regs/%.rdl $(OCAH_REGBLOCK_UDP) | uv-sync
	@mkdir -p "$$(@D)" "$(call ocah_reg_build,$(1))"
	@echo "Regenerating HTML register docs for $(1) sub-block $$*"
	@$(ocah_sh) '"$(UV)" run peakrdl html $(call ocah_reg_incdirs,$(1)) "$(OCAH_REGBLOCK_UDP)" "$$<" -o "$$(@D)" 2>&1 | tee "$(1)/build/regs/html_$$*.log"'
endef

# No register RTL (sourced outside regblock): skip the regblock run but keep the
# empty stamp so the .generated aggregate stays well-defined.
define ocah_reg_sv_skip_rule
$(call ocah_reg_sv_stamp,$(1)): $(call ocah_reg_rdl,$(1)) | uv-sync
	@mkdir -p "$(call ocah_reg_build,$(1))"
	@echo "Skipping register SV for $(1) (RTL sourced outside regblock)"
	@touch "$$@"
endef

# Register docs for plain (leaf) blocks: peakrdl markdown converted to AsciiDoc
# with pandoc, plus a peakrdl html site.
define ocah_reg_doc_plain_rule
$(call ocah_reg_md_output,$(1)): $(call ocah_reg_rdl,$(1)) $(OCAH_REGBLOCK_UDP) | uv-sync
	@mkdir -p "$(call ocah_reg_gen,$(1))/adoc" "$(call ocah_reg_build,$(1))"
	@echo "Regenerating Markdown register docs for $(1)"
	@$(ocah_sh) '"$(UV)" run peakrdl markdown $(call ocah_reg_incdirs,$(1)) "$(OCAH_REGBLOCK_UDP)" "$(call ocah_reg_rdl,$(1))" -o "$(call ocah_reg_md_output,$(1))" 2>&1 | tee "$(call ocah_reg_build,$(1))/markdown.log"'

$(call ocah_reg_adoc_output,$(1)): $(call ocah_reg_md_output,$(1))
	@command -v "$(OCAH_PANDOC)" >/dev/null 2>&1 || { \
		echo "error: pandoc is required to convert Markdown register docs to AsciiDoc"; \
		exit 1; \
	}
	@echo "Converting Markdown register docs to AsciiDoc for $(1)"
	@cd "$(OCAH_ROOT)" && "$(OCAH_PANDOC)" -f markdown -t asciidoc \
		"$(call ocah_reg_md_output,$(1))" \
		-o "$(call ocah_reg_adoc_output,$(1))"

$(call ocah_reg_html_output,$(1)): $(call ocah_reg_rdl,$(1)) $(OCAH_REGBLOCK_UDP) | uv-sync
	@mkdir -p "$$(@D)" "$(call ocah_reg_build,$(1))"
	@echo "Regenerating HTML register docs for $(1)"
	@$(ocah_sh) '"$(UV)" run peakrdl html $(call ocah_reg_incdirs,$(1)) "$(OCAH_REGBLOCK_UDP)" "$(call ocah_reg_rdl,$(1))" -o "$$(@D)" 2>&1 | tee "$(call ocah_reg_build,$(1))/html.log"'
endef

# Firmware C header for plain (leaf) blocks: one peakrdl c-header run.
define ocah_reg_cheader_plain_rule
$(call ocah_reg_c_output,$(1)): $(call ocah_reg_rdl,$(1)) $(OCAH_REGBLOCK_UDP) | uv-sync
	@mkdir -p "$(call ocah_reg_gen,$(1))/c" "$(call ocah_reg_build,$(1))"
	@echo "Regenerating firmware C header for $(1)"
	@$(ocah_sh) '"$(UV)" run peakrdl c-header $(call ocah_reg_incdirs,$(1)) "$(OCAH_REGBLOCK_UDP)" "$(call ocah_reg_rdl,$(1))" -o "$(call ocah_reg_c_output,$(1))" --bitfields $(call ocah_reg_c_bitfields,$(1)) --type-style lexical 2>&1 | tee "$(call ocah_reg_build,$(1))/c_header.log"'
endef

# Address exporters (raw-C, svpkg, py) and the .generated stamp for every block.
$(foreach block,$(OCAH_HJSON_REG_BLOCKS),$(eval $(call ocah_hjson_reg_block_rules,$(block))))
$(foreach block,$(OCAH_REG_BLOCKS),$(eval $(call ocah_reg_block_rules,$(block))))
# Composite tops: per-sub-block sv/c/adoc/html pattern rules.
$(foreach block,$(OCAH_REG_BLOCKS),$(if $(call ocah_reg_is_composite,$(block)),$(eval $(call ocah_reg_composite_rules,$(block)))))
# Plain (leaf) blocks: single-file sv (or header-only skip), docs, and C header.
$(foreach block,$(OCAH_REG_BLOCKS),$(if $(call ocah_reg_is_composite,$(block)),,$(eval $(call $(if $(call ocah_reg_sv_skipped,$(block)),ocah_reg_sv_skip_rule,ocah_reg_sv_plain_rule),$(block)))))
$(foreach block,$(OCAH_REG_BLOCKS),$(if $(call ocah_reg_is_composite,$(block)),,$(eval $(call ocah_reg_doc_plain_rule,$(block)))))
$(foreach block,$(OCAH_REG_BLOCKS),$(if $(call ocah_reg_is_composite,$(block)),,$(eval $(call ocah_reg_cheader_plain_rule,$(block)))))

## @section Register Regeneration

## A target suffix selects the output class (or clean); TARGET=<block> scopes to a
## single register block. With no TARGET, every block is regenerated.

## Regenerate non-documentation register collateral for all OCAH register blocks.
## @param OCAH_REG_BLOCKS Registered block roots to regenerate
## @param OCAH_HJSON_REG_BLOCKS HJSON-backed block roots that are converted to RDL first
## @param TARGET=smc Optional register block basename to regenerate
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

## Regenerate SystemVerilog address headers/packages for OCAH register blocks.
## @param TARGET=smc Optional register block basename to regenerate
.PHONY: ocah-regen-regs-svh
ocah-regen-regs-svh: $(OCAH_REGEN_REG_SVH)

## Regenerate flat Python address constants for OCAH register blocks.
## @param TARGET=smc Optional register block basename to regenerate
.PHONY: ocah-regen-regs-py
ocah-regen-regs-py: $(OCAH_REGEN_REG_PY)

## Regenerate AsciiDoc register documentation for OCAH register blocks.
## @param TARGET=smc Optional register block basename to regenerate
.PHONY: ocah-regen-regs-adoc
ocah-regen-regs-adoc: $(OCAH_REGEN_REG_ADOC)

## Regenerate HTML register documentation for OCAH register blocks.
## @param TARGET=smc Optional register block basename to regenerate
.PHONY: ocah-regen-regs-html
ocah-regen-regs-html: $(OCAH_REGEN_REG_HTML)

## Remove generated register collateral and transient register-generation stamps.
## @param TARGET=smc Optional register block basename to clean
.PHONY: ocah-regen-regs-clean
ocah-regen-regs-clean:
	@rm -rf $(foreach block,$(OCAH_SELECTED_REG_BLOCKS),$(foreach path,$(call ocah_reg_clean_paths,$(block)),"$(path)"))

OCAH_PHONY += \
  ocah-regen-regs \
  ocah-regen-regs-sv \
  ocah-regen-regs-h \
  ocah-regen-regs-svh \
  ocah-regen-regs-py \
  ocah-regen-regs-adoc \
  ocah-regen-regs-html \
  ocah-regen-regs-clean

endif
