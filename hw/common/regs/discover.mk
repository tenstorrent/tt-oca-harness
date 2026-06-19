# SPDX-License-Identifier: Apache-2.0
# (c) 2026 Tenstorrent USA Inc

# Finds the register blocks and works out each one's input/output paths: the
# source RDL, gen/build dirs, source HJSON, and include search dirs. classify.mk
# then fills in the per-block policy (which outputs each block gets).

# First-party tops: dirs holding the dir-name RDL (hw/{ip,sys}/<name>/regs/<name>.rdl).
# Role == location (see doc/user_guide/regs.adoc), so discovery is a pure glob.
ocah_reg_dirs := $(wildcard $(OCAH_ROOT)/hw/ip/*/regs $(OCAH_ROOT)/hw/sys/*/regs)
ocah_reg_root_if_rdl = $(if $(wildcard $(1)/$(notdir $(patsubst %/regs,%,$(1))).rdl),$(patsubst $(OCAH_ROOT)/%,%,$(patsubst %/regs,%,$(1))))
OCAH_RDL_REG_BLOCKS := $(sort $(foreach d,$(ocah_reg_dirs),$(call ocah_reg_root_if_rdl,$(d))))

# Standalone siblings: regs/*.rdl minus the dir-name top (fragments live in
# regs/include/, sub-blocks in regs/blocks/). Emit flat via the file-backed path.
ocah_reg_sibling_rdls = $(filter-out $(1)/$(notdir $(patsubst %/regs,%,$(1))).rdl,$(wildcard $(1)/*.rdl))
OCAH_REG_SIBLING_RDL_FILES := $(foreach d,$(ocah_reg_dirs),$(call ocah_reg_sibling_rdls,$(d)))

# Extra RDL files exported as standalone blocks: DV shims plus the regs-root siblings.
OCAH_REG_STANDALONE_RDL_FILES ?= \
  $(wildcard $(OCAH_ROOT)/hw/sys/*/dv/shims/regs/*.rdl) \
  $(wildcard $(OCAH_ROOT)/hw/ip/*/dv/shims/regs/*.rdl) \
  $(OCAH_REG_SIBLING_RDL_FILES)
OCAH_EXTRA_REG_RDL_FILES ?=

ocah_reg_file_block_id = $(patsubst $(OCAH_ROOT)/%,%,$(basename $(1)))
OCAH_RDL_FILE_REG_FILES := $(sort $(OCAH_REG_STANDALONE_RDL_FILES) $(OCAH_EXTRA_REG_RDL_FILES))
OCAH_RDL_FILE_REG_BLOCKS := $(foreach f,$(OCAH_RDL_FILE_REG_FILES),$(call ocah_reg_file_block_id,$(f)))

OCAH_BENDER ?= bender
ocah_bender_path = $(strip $(shell $(OCAH_BENDER) path $(1) 2>/dev/null))
ocah_relpath = $(patsubst $(OCAH_ROOT)/%,%,$(1))

# Per-id accessors: name, source root, make-safe key (ids may contain '/').
ocah_reg_name = $(notdir $(1))
ocah_reg_root = $(OCAH_ROOT)/$(1)
ocah_reg_key = $(subst /,_,$(1))

# HJSON-backed vendor blocks as bender-package:package-relative-hjson. Collateral
# lands in the package gen/ dir, leaving the vendored tree untouched.
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

# Overlay hook (e.g. nonfree): extra block ids, usually variants reusing a top RDL.
OCAH_EXTRA_REG_BLOCKS ?=

OCAH_REG_BLOCKS ?= \
  $(OCAH_RDL_REG_BLOCKS) \
  $(OCAH_RDL_FILE_REG_BLOCKS) \
  $(OCAH_HJSON_REG_BLOCKS) \
  $(OCAH_EXTRA_REG_BLOCKS)

# Shared -I dirs for tops that pull sub-block/fragment RDLs by bare include:
# IP regs roots, regs/include, regs/blocks/<sub>, and the DV shim trees.
OCAH_REG_CATALOG_DIRS := \
  $(wildcard $(OCAH_ROOT)/hw/ip/*/regs) \
  $(wildcard $(OCAH_ROOT)/hw/ip/*/regs/include) \
  $(wildcard $(OCAH_ROOT)/hw/ip/*/regs/blocks/*) \
  $(wildcard $(OCAH_ROOT)/hw/sys/*/regs/include) \
  $(wildcard $(OCAH_ROOT)/hw/sys/*/regs/blocks/*) \
  $(wildcard $(OCAH_ROOT)/hw/sys/*/dv/shims/regs) \
  $(wildcard $(OCAH_ROOT)/hw/ip/*/dv/shims/regs)

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
OCAH_REG_HTML_OUTPUT_OVERRIDE_$(call ocah_reg_key,$(call ocah_reg_file_block_id,$(1))) := $(patsubst %/,%,$(dir $(1)))/gen/html/$(notdir $(basename $(1)))/index.html
OCAH_REG_EXTRA_SEARCH_$(call ocah_reg_key,$(call ocah_reg_file_block_id,$(1))) ?= $(patsubst %/,%,$(dir $(1)))
endef
$(foreach f,$(OCAH_RDL_FILE_REG_FILES),$(eval $(call ocah_reg_file_block_vars,$(f))))

# Source-path resolvers. RDL is overridable (OCAH_REG_RDL_OVERRIDE_<key>) so an
# overlay variant reuses a canonical RDL while emitting under its own gen/ dir.
ocah_reg_rdl_resolve = $(or $(OCAH_REG_RDL_OVERRIDE_$(call ocah_reg_key,$(1))),$(call ocah_reg_root,$(1))/regs/$(call ocah_reg_name,$(1)).rdl)
ocah_reg_hjson_vendor = $(strip $(foreach e,$(OCAH_VENDOR_HJSON_REG_BLOCKS),$(if $(filter $(call ocah_vendor_reg_block,$(e)),$(1)),$(call ocah_vendor_reg_hjson,$(e)))))
ocah_reg_hjson_default = $(call ocah_reg_root,$(1))/data/$(call ocah_reg_name,$(1)).hjson
ocah_reg_hjson_resolve = $(or $(call ocah_reg_hjson_vendor,$(1)),$(call ocah_reg_hjson_default,$(1)))
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
