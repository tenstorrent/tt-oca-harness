# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# Turns the per-block facts from discover.mk/classify.mk into output file paths
# and the aggregate lists of files each regen target builds.

# Per-block accessors: one flat var each, keyed by the block key.
ocah_reg_rdl         = $(OCAH_REG_RDL_$(call ocah_reg_key,$(1)))
ocah_reg_gen         = $(OCAH_REG_GEN_$(call ocah_reg_key,$(1)))
ocah_reg_build       = $(OCAH_REG_BUILD_$(call ocah_reg_key,$(1)))
ocah_reg_hjson       = $(OCAH_REG_HJSON_$(call ocah_reg_key,$(1)))
ocah_reg_incdirs     = $(OCAH_REG_SEARCH_$(call ocah_reg_key,$(1)))
ocah_reg_c_bitfields = $(OCAH_REG_BITFIELDS_$(call ocah_reg_key,$(1)))
ocah_reg_html_output = $(OCAH_REG_HTML_$(call ocah_reg_key,$(1)))
ocah_reg_cpu_if      = $(or $(OCAH_REG_CPU_IF_$(call ocah_reg_key,$(1))),$(OCAH_REG_CPU_IF_NAME_$(call ocah_reg_name,$(1))),$(OCAH_REG_CPU_IF))
# Non-empty when the block's register RTL is sourced outside regblock.
ocah_reg_sv_skipped  = $(filter skip,$(OCAH_REG_SVMODE_$(call ocah_reg_key,$(1))))
# Composite sub-blocks by output class.
ocah_reg_ch_blocks   = $(OCAH_REG_SUBCH_$(call ocah_reg_key,$(1)))
ocah_reg_doc_blocks  = $(OCAH_REG_SUBDOC_$(call ocah_reg_key,$(1)))
ocah_reg_sv_blocks   = $(OCAH_REG_SUBSV_$(call ocah_reg_key,$(1)))

ocah_reg_sv_stamp = $(call ocah_reg_build,$(1))/sv.generated
ocah_reg_sv_outputs = \
  $(call ocah_reg_gen,$(1))/sv/$(call ocah_reg_name,$(1))_reg.sv \
  $(call ocah_reg_gen,$(1))/sv/$(call ocah_reg_name,$(1))_reg_pkg.sv
# Composite tops emit per-sub-block collateral under blocks/; leaves use the
# single-file outputs below.
ocah_reg_sv_block_dir = $(call ocah_reg_gen,$(1))/sv/blocks
ocah_reg_c_block_dir = $(call ocah_reg_gen,$(1))/c/blocks
ocah_reg_adoc_block_dir = $(call ocah_reg_gen,$(1))/adoc/blocks
ocah_reg_html_block_dir = $(call ocah_reg_gen,$(1))/html/blocks
ocah_reg_c_output = $(call ocah_reg_gen,$(1))/c/$(call ocah_reg_name,$(1)).h
ocah_reg_svpkg_output = $(call ocah_reg_gen,$(1))/sv/$(call ocah_reg_name,$(1))_addrmap_pkg.sv
ocah_reg_svh_output = $(call ocah_reg_gen,$(1))/svh/$(call ocah_reg_name,$(1))_reg.svh
ocah_reg_raw_c_output = $(call ocah_reg_gen,$(1))/c/$(call ocah_reg_name,$(1))_addr.h
ocah_reg_py_output = $(call ocah_reg_gen,$(1))/py/$(call ocah_reg_name,$(1))_addr.py
ocah_reg_md_output = $(call ocah_reg_gen,$(1))/adoc/$(call ocah_reg_name,$(1)).md
ocah_reg_adoc_output = $(call ocah_reg_gen,$(1))/adoc/$(call ocah_reg_name,$(1)).adoc

# Per-sub-block output lists for a composite top (one file each, so make rebuilds
# only the changed RDL).
ocah_reg_sv_block_outputs = $(foreach b,$(call ocah_reg_sv_blocks,$(1)),$(call ocah_reg_sv_block_dir,$(1))/$(b)_reg.sv)
ocah_reg_c_block_outputs = $(foreach b,$(call ocah_reg_ch_blocks,$(1)),$(call ocah_reg_c_block_dir,$(1))/$(b).h)
ocah_reg_adoc_block_outputs = $(foreach b,$(call ocah_reg_doc_blocks,$(1)),$(call ocah_reg_adoc_block_dir,$(1))/$(b).adoc)
ocah_reg_html_block_outputs = $(foreach b,$(call ocah_reg_doc_blocks,$(1)),$(call ocah_reg_html_block_dir,$(1))/$(b).html)

# Output selectors per block: composite -> sub-block lists, RTL-elsewhere leaf ->
# stamp, plain leaf -> files.
ocah_reg_sv_target = $(if $(call ocah_reg_is_composite,$(1)),$(call ocah_reg_sv_block_outputs,$(1)),$(if $(call ocah_reg_sv_skipped,$(1)),$(call ocah_reg_sv_stamp,$(1)),$(call ocah_reg_sv_outputs,$(1))))
ocah_reg_h_target = $(if $(call ocah_reg_is_composite,$(1)),$(call ocah_reg_c_block_outputs,$(1)),$(call ocah_reg_c_output,$(1)))
ocah_reg_adoc_target = $(if $(call ocah_reg_is_composite,$(1)),$(call ocah_reg_adoc_block_outputs,$(1)),$(call ocah_reg_adoc_output,$(1)))
ocah_reg_html_target = $(if $(call ocah_reg_is_composite,$(1)),$(call ocah_reg_html_block_outputs,$(1)),$(call ocah_reg_html_output,$(1)))
ocah_reg_html_dir = $(patsubst %/,%,$(dir $(call ocah_reg_html_output,$(1))))
ocah_reg_is_file_backed = $(OCAH_REG_GEN_OVERRIDE_$(call ocah_reg_key,$(1)))
ocah_reg_file_clean_outputs = \
  $(if $(call ocah_reg_sv_skipped,$(1)),,$(call ocah_reg_sv_outputs,$(1))) \
  $(call ocah_reg_svpkg_output,$(1)) \
  $(call ocah_reg_svh_output,$(1)) \
  $(call ocah_reg_c_output,$(1)) \
  $(call ocah_reg_raw_c_output,$(1)) \
  $(call ocah_reg_py_output,$(1)) \
  $(call ocah_reg_md_output,$(1)) \
  $(call ocah_reg_adoc_output,$(1)) \
  $(call ocah_reg_html_dir,$(1))
ocah_reg_clean_paths = $(if $(call ocah_reg_is_file_backed,$(1)),$(call ocah_reg_file_clean_outputs,$(1)) $(call ocah_reg_build,$(1)),$(call ocah_reg_gen,$(1)) $(call ocah_reg_build,$(1)))

# Map a per-block output function over the selected blocks.
ocah_reg_collect = $(foreach block,$(OCAH_SELECTED_REG_BLOCKS),$(call $(1),$(block)))
ocah_reg_h_full  = $(call ocah_reg_h_target,$(1)) $(call ocah_reg_raw_c_output,$(1))
ocah_reg_stamp   = $(call ocah_reg_build,$(1))/.generated

OCAH_REGEN_REG_SV     := $(call ocah_reg_collect,ocah_reg_sv_target)
OCAH_REGEN_REG_H      := $(call ocah_reg_collect,ocah_reg_h_full)
OCAH_REGEN_REG_ADDRPKG := $(call ocah_reg_collect,ocah_reg_svpkg_output)
OCAH_REGEN_REG_SVH     := $(call ocah_reg_collect,ocah_reg_svh_output)
OCAH_REGEN_REG_PY     := $(call ocah_reg_collect,ocah_reg_py_output)
OCAH_REGEN_REG_ADOC   := $(call ocah_reg_collect,ocah_reg_adoc_target)
OCAH_REGEN_REG_HTML   := $(call ocah_reg_collect,ocah_reg_html_target)
OCAH_REGEN_REG_STAMPS := $(call ocah_reg_collect,ocah_reg_stamp)
# regen-regs skips docs; generate them via regen-regs-adoc/-html.
OCAH_REGEN_ALL := \
  $(OCAH_REGEN_REG_SV) \
  $(OCAH_REGEN_REG_H) \
  $(OCAH_REGEN_REG_ADDRPKG) \
  $(OCAH_REGEN_REG_SVH) \
  $(OCAH_REGEN_REG_PY)
