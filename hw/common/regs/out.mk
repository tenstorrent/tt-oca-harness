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
ocah_reg_py_bitfields = $(OCAH_REG_BITFIELDS_PY_$(call ocah_reg_key,$(1)))
ocah_reg_html_output = $(OCAH_REG_HTML_$(call ocah_reg_key,$(1)))
ocah_reg_cpu_if      = $(or $(OCAH_REG_CPU_IF_$(call ocah_reg_key,$(1))),$(OCAH_REG_CPU_IF_NAME_$(call ocah_reg_name,$(1))),$(OCAH_REG_CPU_IF))
# Decode-error responses (--err-if-bad-addr / --err-if-bad-rw). Off by default
# because a block behind a decoder that already filters its window has nothing
# to report, and the checks cost a comparator per register. On where the DV env
# expects the block itself to answer a bad access with an error.
ocah_reg_err_checks  = $(filter $(call ocah_reg_name,$(1)),$(OCAH_REG_ERR_CHECK_BLOCKS))
ocah_reg_regblock_opts = $(if $(call ocah_reg_err_checks,$(1)),--err-if-bad-addr --err-if-bad-rw)
# PeakRDL addrmap parameter overrides (`-P NAME=VALUE`). Keyed by the RDL stem.
ocah_reg_rdl_params = $(foreach p,$(OCAH_REG_RDL_PARAMS_$(call ocah_reg_name,$(1))),-P $(p))
# Non-empty when the block's register RTL is sourced outside regblock.
ocah_reg_sv_skipped  = $(filter skip,$(OCAH_REG_SVMODE_$(call ocah_reg_key,$(1))))
# Composite sub-blocks by output class.
ocah_reg_ch_blocks   = $(OCAH_REG_SUBCH_$(call ocah_reg_key,$(1)))
ocah_reg_doc_blocks  = $(OCAH_REG_SUBDOC_$(call ocah_reg_key,$(1)))
ocah_reg_sv_blocks   = $(OCAH_REG_SUBSV_$(call ocah_reg_key,$(1)))

# A leaf may need a distinct generated module/package name when its RDL addrmap
# name must remain canonical but another block with that name is also compiled.
ocah_reg_sv_stamp = $(call ocah_reg_build,$(1))/sv.generated
ocah_reg_sv_rename = $(OCAH_REG_SV_RENAME_$(call ocah_reg_key,$(1)))
ocah_reg_sv_model = $(or $(call ocah_reg_sv_rename,$(1)),$(call ocah_reg_name,$(1)))
ocah_reg_sv_outputs = \
  $(call ocah_reg_gen,$(1))/sv/$(call ocah_reg_sv_model,$(1))_reg.sv \
  $(call ocah_reg_gen,$(1))/sv/$(call ocah_reg_sv_model,$(1))_reg_pkg.sv
# Composite tops emit per-sub-block collateral under blocks/; leaves use the
# single-file outputs below.
ocah_reg_sv_block_dir = $(call ocah_reg_gen,$(1))/sv/blocks
ocah_reg_c_block_dir = $(call ocah_reg_gen,$(1))/c/blocks
ocah_reg_adoc_block_dir = $(call ocah_reg_gen,$(1))/adoc/blocks
ocah_reg_html_block_dir = $(call ocah_reg_gen,$(1))/html/blocks
# UVM RAL models are flat under gen/ral for both composites and leaves: a RAL is
# named after the model, not the top that happens to contain it, and the SEP TB
# puts one +incdir on this directory.
ocah_reg_ral_dir = $(call ocah_reg_gen,$(1))/ral
ocah_reg_c_output = $(call ocah_reg_gen,$(1))/c/$(call ocah_reg_name,$(1)).h
ocah_reg_svpkg_output = $(call ocah_reg_gen,$(1))/sv/$(call ocah_reg_name,$(1))_addrmap_pkg.sv
ocah_reg_svh_output = $(call ocah_reg_gen,$(1))/svh/$(call ocah_reg_name,$(1))_reg.svh
ocah_reg_raw_c_output = $(call ocah_reg_gen,$(1))/c/$(call ocah_reg_name,$(1))_addr.h
ocah_reg_py_output = $(call ocah_reg_gen,$(1))/py/$(call ocah_reg_name,$(1))_reg.py
ocah_reg_json_output = $(call ocah_reg_gen,$(1))/json/$(call ocah_reg_name,$(1)).json
# IP-XACT component XML, one per block top (composite or leaf), like svh/py.
ocah_reg_ipxact_output = $(call ocah_reg_gen,$(1))/ipxact/$(call ocah_reg_name,$(1)).xml
# RAL model name and top-instance rename. Both default to the block name; see
# classify.mk for why a block would override either.
ocah_reg_ral_model = $(or $(OCAH_REG_RAL_MODEL_$(call ocah_reg_key,$(1))),$(call ocah_reg_name,$(1)))
ocah_reg_ral_rename = $(OCAH_REG_RAL_RENAME_$(call ocah_reg_key,$(1)))
ocah_reg_ral_output = $(call ocah_reg_ral_dir,$(1))/$(call ocah_reg_ral_model,$(1))_ral_pkg.sv
ocah_reg_md_output = $(call ocah_reg_gen,$(1))/adoc/$(call ocah_reg_name,$(1)).md
ocah_reg_adoc_output = $(call ocah_reg_gen,$(1))/adoc/$(call ocah_reg_name,$(1)).adoc

# Per-sub-block output lists for a composite top (one file each, so make rebuilds
# only the changed RDL).
ocah_reg_sv_block_outputs = $(foreach b,$(call ocah_reg_sv_blocks,$(1)),$(call ocah_reg_sv_block_dir,$(1))/$(b)_reg.sv)
ocah_reg_c_block_outputs = $(foreach b,$(call ocah_reg_ch_blocks,$(1)),$(call ocah_reg_c_block_dir,$(1))/$(b).h)
ocah_reg_adoc_block_outputs = $(foreach b,$(call ocah_reg_doc_blocks,$(1)),$(call ocah_reg_adoc_block_dir,$(1))/$(b).adoc)
ocah_reg_html_block_outputs = $(foreach b,$(call ocah_reg_doc_blocks,$(1)),$(call ocah_reg_html_block_dir,$(1))/$(b).html)
ocah_reg_ral_block_outputs = $(foreach b,$(call ocah_reg_ral_blocks,$(1)),$(call ocah_reg_ral_dir,$(1))/$(b)_ral_pkg.sv)

# Output selectors per block: composite -> sub-block lists, RTL-elsewhere leaf ->
# stamp, plain leaf -> files.
ocah_reg_sv_target = $(if $(call ocah_reg_is_composite,$(1)),$(call ocah_reg_sv_block_outputs,$(1)),$(if $(call ocah_reg_sv_skipped,$(1)),$(call ocah_reg_sv_stamp,$(1)),$(call ocah_reg_sv_outputs,$(1))))
ocah_reg_h_target = $(if $(call ocah_reg_is_composite,$(1)),$(call ocah_reg_c_block_outputs,$(1)),$(call ocah_reg_c_output,$(1)))
ocah_reg_adoc_target = $(if $(call ocah_reg_is_composite,$(1)),$(call ocah_reg_adoc_block_outputs,$(1)),$(call ocah_reg_adoc_output,$(1)))
ocah_reg_html_target = $(if $(call ocah_reg_is_composite,$(1)),$(call ocah_reg_html_block_outputs,$(1)),$(call ocah_reg_html_output,$(1)))
# RAL is opt-in, so a block with none selects nothing (composite: the sub-blocks
# on the list; leaf: itself, only if its id is listed).
ocah_reg_ral_target = $(if $(call ocah_reg_is_composite,$(1)),$(call ocah_reg_ral_block_outputs,$(1)),$(if $(call ocah_reg_leaf_has_ral,$(1)),$(call ocah_reg_ral_output,$(1))))
# JSON describes a whole address space, so it is emitted for the top itself
# (composite or leaf) rather than per sub-block.
ocah_reg_json_target = $(if $(call ocah_reg_has_json,$(1)),$(call ocah_reg_json_output,$(1)))
ocah_reg_html_dir = $(patsubst %/,%,$(dir $(call ocah_reg_html_output,$(1))))
ocah_reg_is_file_backed = $(OCAH_REG_GEN_OVERRIDE_$(call ocah_reg_key,$(1)))
ocah_reg_file_clean_outputs = \
  $(if $(call ocah_reg_sv_skipped,$(1)),,$(call ocah_reg_sv_outputs,$(1))) \
  $(call ocah_reg_svpkg_output,$(1)) \
  $(call ocah_reg_svh_output,$(1)) \
  $(call ocah_reg_c_output,$(1)) \
  $(call ocah_reg_raw_c_output,$(1)) \
  $(call ocah_reg_py_output,$(1)) \
  $(call ocah_reg_ral_output,$(1)) \
  $(call ocah_reg_json_output,$(1)) \
  $(call ocah_reg_ipxact_output,$(1)) \
  $(call ocah_reg_md_output,$(1)) \
  $(call ocah_reg_adoc_output,$(1)) \
  $(call ocah_reg_html_dir,$(1))
ocah_reg_clean_paths = $(if $(call ocah_reg_is_file_backed,$(1)),$(call ocah_reg_file_clean_outputs,$(1)) $(call ocah_reg_build,$(1)),$(call ocah_reg_gen,$(1)) $(call ocah_reg_build,$(1)))

# Map a per-block output function over the selected blocks.
ocah_reg_collect = $(foreach block,$(OCAH_SELECTED_REG_BLOCKS),$(call $(1),$(block)))
ocah_reg_h_full  = $(call ocah_reg_h_target,$(1)) $(call ocah_reg_raw_c_output,$(1))
ocah_reg_stamp   = $(call ocah_reg_build,$(1))/.generated

# Depfile (gcc -MMD style): the block's `include`d RDLs, listed as prerequisites
# of every output that flattens the block's `include` closure, so an include-only
# change (top RDL mtime unchanged) still rebuilds the top collateral. Written into
# the gitignored build dir; never committed, so it does not affect the regen-diff
# gate. The target set reuses the existing per-class selectors.
ocah_reg_dep_output = $(call ocah_reg_build,$(1))/deps.d
ocah_reg_dep_targets = \
  $(call ocah_reg_sv_target,$(1)) \
  $(call ocah_reg_h_full,$(1)) \
  $(call ocah_reg_svpkg_output,$(1)) \
  $(call ocah_reg_svh_output,$(1)) \
  $(call ocah_reg_py_output,$(1)) \
  $(call ocah_reg_ral_target,$(1)) \
  $(call ocah_reg_ipxact_output,$(1)) \
  $(call ocah_reg_adoc_target,$(1)) \
  $(call ocah_reg_html_target,$(1)) \
  $(call ocah_reg_json_target,$(1))

OCAH_REGEN_REG_SV     := $(call ocah_reg_collect,ocah_reg_sv_target)
OCAH_REGEN_REG_H      := $(call ocah_reg_collect,ocah_reg_h_full)
OCAH_REGEN_REG_ADDRPKG := $(call ocah_reg_collect,ocah_reg_svpkg_output)
OCAH_REGEN_REG_SVH     := $(call ocah_reg_collect,ocah_reg_svh_output)
OCAH_REGEN_REG_PY     := $(call ocah_reg_collect,ocah_reg_py_output)
OCAH_REGEN_REG_RAL    := $(call ocah_reg_collect,ocah_reg_ral_target)
OCAH_REGEN_REG_JSON   := $(call ocah_reg_collect,ocah_reg_json_target)
OCAH_REGEN_REG_IPXACT := $(call ocah_reg_collect,ocah_reg_ipxact_output)
OCAH_REGEN_REG_ADOC   := $(call ocah_reg_collect,ocah_reg_adoc_target)
OCAH_REGEN_REG_HTML   := $(call ocah_reg_collect,ocah_reg_html_target)
OCAH_REGEN_REG_STAMPS := $(call ocah_reg_collect,ocah_reg_stamp)
# Per-block depfiles, pulled in via -include at the tail of rules.mk. Not part of
# OCAH_REGEN_ALL: they are build byproducts, not committed collateral.
OCAH_REGEN_REG_DEPS   := $(call ocah_reg_collect,ocah_reg_dep_output)
# regen-regs skips docs; generate them via regen-regs-adoc/-html.
OCAH_REGEN_ALL := \
  $(OCAH_REGEN_REG_SV) \
  $(OCAH_REGEN_REG_H) \
  $(OCAH_REGEN_REG_ADDRPKG) \
  $(OCAH_REGEN_REG_SVH) \
  $(OCAH_REGEN_REG_PY) \
  $(OCAH_REGEN_REG_RAL) \
  $(OCAH_REGEN_REG_JSON) \
  $(OCAH_REGEN_REG_IPXACT)
