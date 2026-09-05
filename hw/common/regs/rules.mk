# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# The actual build rules: peakrdl command lines and the make rules that turn each
# block's RDL into SV/C/Python/docs, instantiated per block via foreach/eval.

# Composite sub-block prereqs are regs/blocks/<sub>/<sub>.rdl: the stem appears
# twice, so the second is resolved via secondary expansion ($$*). A no-op elsewhere.
.SECONDEXPANSION:

# Local svpkg template: upstream peakrdl-rawheader 0.2.4 sizes enum widths by the
# number of entries rather than the largest value, silently truncating any enum
# whose largest value needs more bits than its entry count, and ends the package
# with a stray `endpackage;` (empty statement, lint W193). Both fixed in our copy;
# drop this and the --template flag once the fixes land upstream.
OCAH_SVPKG_TEMPLATE ?= $(OCAH_ROOT)/hw/common/regs/templates/svpkg.mako

# Prepend SPDX to generated register files after PeakRDL / custom exporters.
# Always pass the exact file(s) a recipe emitted, never a directory: several
# blocks share one regs/gen/sv (the key_manager top and its ten sibling RDLs,
# each a leaf) and composite sub-blocks share regs/gen/sv/blocks. Stamping the
# whole directory made every block's recipe read-modify-write the others' files,
# which truncated them non-deterministically under the flow's default -j. The
# stamper accepts many paths and no-ops on ones that do not exist.
ocah_reg_stamp_after = $(if $(filter 1,$(OCAH_REG_DEFER_STAMP)),, && python3 "$(OCAH_ROOT)/tools/regs/stamp_spdx.py" $(1))

# Canned peakrdl exporter command lines. $(1) = block id (for -I); later args are
# input, output, name/bitfields, log.
ocah_reg_run_cheader  = "$(OCAH_REG_PEAKRDL)" c-header $(call ocah_reg_incdirs,$(1)) "$(OCAH_REGBLOCK_UDP)" "$(2)" -o "$(3)" --bitfields $(4) --type-style lexical 2>&1 | tee "$(5)"
ocah_reg_run_regblock = "$(OCAH_REG_PEAKRDL)" regblock $(call ocah_reg_incdirs,$(1)) "$(OCAH_REGBLOCK_UDP)" "$(2)"$(if $(strip $(6)), --rename "$(strip $(6))") -o "$(3)" --cpuif "$(call ocah_reg_cpu_if,$(1))" $(call ocah_reg_regblock_opts,$(1)) --default-reset "$(OCAH_REG_DEFAULT_RESET)" --module-name "$(4)_reg" --package-name "$(4)_reg_pkg" 2>&1 | tee "$(5)"
# AsciiDoc register docs are emitted directly from RDL by a custom generator that
# produces a compact summary table + per-register field tables (table captions,
# no per-register headings). This replaces the old peakrdl-markdown -> pandoc
# path, which created a heading/TOC entry per register and exploded the PDF page
# count. $(2) = input RDL, $(3) = output adoc, $(4) = log.
ocah_reg_run_adoc     = "$(OCAH_REG_PYTHON)" "$(OCAH_ROOT)/tools/regs/rdladoc.py" -u "$(OCAH_REGBLOCK_UDP)" $(call ocah_reg_incdirs,$(1)) "$(2)" "$(3)" 2>&1 | tee "$(4)"
ocah_reg_run_html     = "$(OCAH_REG_PYTHON)" "$(OCAH_ROOT)/tools/regs/rdlhtml.py" -u "$(OCAH_REGBLOCK_UDP)" $(call ocah_reg_incdirs,$(1)) "$(2)" "$(3)" 2>&1 | tee "$(4)"
ocah_reg_run_svh      = "$(OCAH_REG_PYTHON)" "$(OCAH_ROOT)/tools/regs/rdlsvh.py" -u "$(OCAH_REGBLOCK_UDP)" $(subst -I ,-i ,$(call ocah_reg_incdirs,$(1))) "$(2)" "$(3)" 2>&1 | tee "$(4)"
# $(4) = bitfields policy (none|ltoh), $(5) = log.
ocah_reg_run_py       = "$(OCAH_REG_PYTHON)" "$(OCAH_ROOT)/tools/regs/rdlpyhdr.py" -u "$(OCAH_REGBLOCK_UDP)" $(subst -I ,-i ,$(call ocah_reg_incdirs,$(1))) "$(2)" "$(3)" --bitfields $(4) $(if $(call ocah_reg_has_py_field_access,$(1)),--field-access) 2>&1 | tee "$(5)"
# UVM RAL, straight from the stock peakrdl-uvm exporter. The flags are not
# defaults: `header` because the models are included into one TB package rather
# than compiled standalone, and `hier` because the TB expects one class per
# register instance (lexical would collapse same-typed instances such as
# sep_cpu_ctrl's eight TIMEOUT_COUNT_* onto a shared class).
# $(2) = input RDL, $(3) = top addrmap, $(4) = output, $(5) = rename (may be
# empty), $(6) = log.
ocah_reg_run_ral      = "$(OCAH_REG_PEAKRDL)" uvm $(call ocah_reg_incdirs,$(1)) "$(OCAH_REGBLOCK_UDP)" "$(2)" -t "$(3)" -o "$(4)"$(if $(strip $(5)), --rename "$(strip $(5))") --file-type header --type-style hier --use-factory 2>&1 | tee "$(6)"
# JSON register model. --repo-root keeps the recorded def_file paths relative to
# the checkout rather than absolute. Arrays stay compact (a size/stride pair
# rather than one entry per index): the model is the whole SMC space, and
# unrolling it triples the register count for consumers that only ever walk the
# first element anyway.
ocah_reg_run_json     = "$(OCAH_REG_PYTHON)" "$(OCAH_ROOT)/tools/regs/rdljson.py" -u "$(OCAH_REGBLOCK_UDP)" $(subst -I ,-i ,$(call ocah_reg_incdirs,$(1))) --repo-root "$(OCAH_ROOT)" --compact_arrays "$(2)" "$(3)" 2>&1 | tee "$(4)"
# IP-XACT 1685-2014 component XML, straight from the stock peakrdl-ipxact
# exporter. Fixed vendor/library/version and an explicit --standard keep the
# output byte-stable for the regen gate (the exporter embeds no timestamps or
# paths); --name defaults to the top component's own name. $(2) = input RDL,
# $(3) = output xml, $(4) = log.
ocah_reg_run_ipxact   = "$(OCAH_REG_PEAKRDL)" ip-xact $(call ocah_reg_incdirs,$(1)) "$(OCAH_REGBLOCK_UDP)" "$(2)" -o "$(3)" --vendor tenstorrent.com --library ocah --version 1.0 --standard 2014 2>&1 | tee "$(4)"

# Refresh one committed vendored RDL from its upstream hjson. This is intentionally
# NOT a make file rule on the RDL path: the committed RDL must never become a
# regen-regs prerequisite (otherwise a clean checkout with a newer vendored hjson
# would silently regenerate it). It is invoked only by the on-demand
# regen-vendor-rdl phony target (see phony.mk), which calls it per entry.
ocah_vendor_hjson_rdl_regen = cd "$(OCAH_ROOT)" && "$(OCAH_REG_PYTHON)" tools/regs/reggen_wrapper.py --systemrdl $(call ocah_vhr_nameopt,$(1)) -o "$(call ocah_vhr_rdl,$(1))" "$(call ocah_vhr_hjson,$(1))"

define ocah_reg_block_rules
$(call ocah_reg_raw_c_output,$(1)): $(call ocah_reg_rdl,$(1)) $(OCAH_REGBLOCK_UDP) | $(OCAH_REG_UV_PREREQ)
	@mkdir -p "$(call ocah_reg_gen,$(1))/c" "$(call ocah_reg_build,$(1))"
	@echo "Regenerating raw C address header for $(1)"
	@$(ocah_sh) '"$(OCAH_REG_PEAKRDL)" raw-header $(call ocah_reg_incdirs,$(1)) "$(OCAH_REGBLOCK_UDP)" "$(call ocah_reg_rdl,$(1))" --format c --base-name "$(shell echo $(call ocah_reg_name,$(1))_addr | tr a-z A-Z)" -o "$(call ocah_reg_raw_c_output,$(1))" 2>&1 | tee "$(call ocah_reg_build,$(1))/raw_c_header.log"$(call ocah_reg_stamp_after,"$(call ocah_reg_raw_c_output,$(1))")'

$(call ocah_reg_svpkg_output,$(1)): $(call ocah_reg_rdl,$(1)) $(OCAH_REGBLOCK_UDP) $(OCAH_SVPKG_TEMPLATE) | $(OCAH_REG_UV_PREREQ)
	@mkdir -p "$(call ocah_reg_gen,$(1))/sv" "$(call ocah_reg_build,$(1))"
	@echo "Regenerating SystemVerilog address package for $(1)"
	@$(ocah_sh) '"$(OCAH_REG_PEAKRDL)" raw-header $(call ocah_reg_incdirs,$(1)) "$(OCAH_REGBLOCK_UDP)" "$(call ocah_reg_rdl,$(1))" --format svpkg --template "$(OCAH_SVPKG_TEMPLATE)" -o "$(call ocah_reg_svpkg_output,$(1))" 2>&1 | tee "$(call ocah_reg_build,$(1))/raw_svpkg.log"$(call ocah_reg_stamp_after,"$(call ocah_reg_svpkg_output,$(1))")'

$(call ocah_reg_py_output,$(1)): $(call ocah_reg_rdl,$(1)) $(OCAH_REGBLOCK_UDP) $(OCAH_ROOT)/tools/regs/rdlpyhdr.py $(OCAH_ROOT)/tools/regs/common/regcollect.py | $(OCAH_REG_UV_PREREQ)
	@mkdir -p "$(call ocah_reg_gen,$(1))/py" "$(call ocah_reg_build,$(1))"
	@echo "Regenerating Python register header for $(1)"
	@$(ocah_sh) '$(call ocah_reg_run_py,$(1),$(call ocah_reg_rdl,$(1)),$(call ocah_reg_py_output,$(1)),$(call ocah_reg_py_bitfields,$(1)),$(call ocah_reg_build,$(1))/py.log)$(call ocah_reg_stamp_after,"$(call ocah_reg_py_output,$(1))")'

$(call ocah_reg_svh_output,$(1)): $(call ocah_reg_rdl,$(1)) $(OCAH_REGBLOCK_UDP) $(OCAH_ROOT)/tools/regs/rdlsvh.py $(OCAH_ROOT)/tools/regs/common/regcollect.py | $(OCAH_REG_UV_PREREQ)
	@mkdir -p "$(call ocah_reg_gen,$(1))/svh" "$(call ocah_reg_build,$(1))"
	@echo "Regenerating flattened SV header for $(1)"
	@$(ocah_sh) '$(call ocah_reg_run_svh,$(1),$(call ocah_reg_rdl,$(1)),$(call ocah_reg_svh_output,$(1)),$(call ocah_reg_build,$(1))/svh.log)$(call ocah_reg_stamp_after,"$(call ocah_reg_svh_output,$(1))")'

$(call ocah_reg_ipxact_output,$(1)): $(call ocah_reg_rdl,$(1)) $(OCAH_REGBLOCK_UDP) | $(OCAH_REG_UV_PREREQ)
	@mkdir -p "$(call ocah_reg_gen,$(1))/ipxact" "$(call ocah_reg_build,$(1))"
	@echo "Regenerating IP-XACT component for $(1)"
	@$(ocah_sh) '$(call ocah_reg_run_ipxact,$(1),$(call ocah_reg_rdl,$(1)),$(call ocah_reg_ipxact_output,$(1)),$(call ocah_reg_build,$(1))/ipxact.log)$(call ocah_reg_stamp_after,"$(call ocah_reg_ipxact_output,$(1))")'

$(call ocah_reg_dep_output,$(1)): $(call ocah_reg_rdl,$(1)) $(OCAH_REGBLOCK_UDP) $(OCAH_ROOT)/tools/regs/dep_scanner.py | $(OCAH_REG_UV_PREREQ)
	@mkdir -p "$(call ocah_reg_build,$(1))"
	@echo "Scanning register includes for $(1)"
	@$(ocah_sh) '"$(OCAH_REG_PYTHON)" "$(OCAH_ROOT)/tools/regs/dep_scanner.py" -u "$(OCAH_REGBLOCK_UDP)" $(subst -I ,-i ,$(call ocah_reg_incdirs,$(1))) "$(call ocah_reg_rdl,$(1))" $(foreach t,$(call ocah_reg_dep_targets,$(1)),--target "$(t)") -o "$(call ocah_reg_dep_output,$(1))"'

$(call ocah_reg_build,$(1))/.generated: $(call ocah_reg_sv_target,$(1)) $(call ocah_reg_h_target,$(1)) $(call ocah_reg_raw_c_output,$(1)) $(call ocah_reg_svpkg_output,$(1)) $(call ocah_reg_svh_output,$(1)) $(call ocah_reg_py_output,$(1)) $(call ocah_reg_ipxact_output,$(1))
	@mkdir -p "$(call ocah_reg_build,$(1))"
	@touch "$$@"
endef

# Plain-leaf register RTL: one regblock run on the block's own RDL.
define ocah_reg_sv_plain_rule
$(call ocah_reg_sv_stamp,$(1)): $(call ocah_reg_rdl,$(1)) $(OCAH_REGBLOCK_UDP) | $(OCAH_REG_UV_PREREQ)
	@mkdir -p "$(call ocah_reg_gen,$(1))/sv" "$(call ocah_reg_build,$(1))"
	@echo "Regenerating register SV for $(1)"
	@$(ocah_sh) '$(call ocah_reg_run_regblock,$(1),$(call ocah_reg_rdl,$(1)),$(call ocah_reg_gen,$(1))/sv,$(call ocah_reg_sv_model,$(1)),$(call ocah_reg_build,$(1))/peakrdl_sv.log,$(call ocah_reg_sv_rename,$(1)))$(call ocah_reg_stamp_after,"$(call ocah_reg_gen,$(1))/sv/$(call ocah_reg_sv_model,$(1))_reg.sv" "$(call ocah_reg_gen,$(1))/sv/$(call ocah_reg_sv_model,$(1))_reg_pkg.sv")'
	@touch "$$@"

$(call ocah_reg_sv_outputs,$(1)): $(call ocah_reg_sv_stamp,$(1))
	@test -f "$$@" || { echo "error: expected generated file missing: $$@"; exit 1; }
endef

# Composite-top collateral: pattern rules running the matching exporter on each
# regs/blocks/<sub>/<sub>.rdl (doubled stem via secondary expansion).
define ocah_reg_composite_rules
$(call ocah_reg_sv_block_dir,$(1))/%_reg.sv: $(call ocah_reg_root,$(1))/regs/blocks/$$$$*/$$$$*.rdl $(OCAH_REGBLOCK_UDP) | $(OCAH_REG_UV_PREREQ)
	@mkdir -p "$$(@D)" "$(call ocah_reg_build,$(1))"
	@echo "Regenerating register SV for $(1) sub-block $$*"
	@$(ocah_sh) '$(call ocah_reg_run_regblock,$(1),$$<,$$(@D),$$*,$(1)/regs/build/peakrdl_sv_$$*.log)$(call ocah_reg_stamp_after,"$$(@D)/$$*_reg.sv" "$$(@D)/$$*_reg_pkg.sv")'

$(call ocah_reg_c_block_dir,$(1))/%.h: $(call ocah_reg_root,$(1))/regs/blocks/$$$$*/$$$$*.rdl $(OCAH_REGBLOCK_UDP) | $(OCAH_REG_UV_PREREQ)
	@mkdir -p "$$(@D)" "$(call ocah_reg_build,$(1))"
	@echo "Regenerating firmware C header for $(1) sub-block $$*"
	@$(ocah_sh) '$(call ocah_reg_run_cheader,$(1),$$<,$$@,$$(if $$(filter $$*,$(OCAH_REG_NO_BITFIELDS)),none,ltoh),$(1)/regs/build/c_header_$$*.log)$(call ocah_reg_stamp_after,"$$@")'

$(call ocah_reg_adoc_block_dir,$(1))/%.adoc: $(call ocah_reg_root,$(1))/regs/blocks/$$$$*/$$$$*.rdl $(OCAH_REGBLOCK_UDP) tools/regs/rdladoc.py tools/regs/common/rdlview.py | $(OCAH_REG_UV_PREREQ)
	@mkdir -p "$$(@D)" "$(call ocah_reg_build,$(1))"
	@echo "Regenerating AsciiDoc register docs for $(1) sub-block $$*"
	@$(ocah_sh) '$(call ocah_reg_run_adoc,$(1),$$<,$$@,$(1)/regs/build/adoc_$$*.log)$(call ocah_reg_stamp_after,"$$@")'

$(call ocah_reg_html_block_dir,$(1))/%.html: $(call ocah_reg_root,$(1))/regs/blocks/$$$$*/$$$$*.rdl $(OCAH_REGBLOCK_UDP) $(OCAH_ROOT)/tools/regs/rdlhtml.py $(OCAH_ROOT)/tools/regs/common/rdlview.py | $(OCAH_REG_UV_PREREQ)
	@mkdir -p "$$(@D)" "$(call ocah_reg_build,$(1))"
	@echo "Regenerating HTML register docs for $(1) sub-block $$*"
	@$(ocah_sh) '$(call ocah_reg_run_html,$(1),$$<,$$@,$(1)/regs/build/html_$$*.log)$(call ocah_reg_stamp_after,"$$@")'

$(call ocah_reg_ral_dir,$(1))/%_ral_pkg.sv: $(call ocah_reg_root,$(1))/regs/blocks/$$$$*/$$$$*.rdl $(OCAH_REGBLOCK_UDP) | $(OCAH_REG_UV_PREREQ)
	@mkdir -p "$$(@D)" "$(call ocah_reg_build,$(1))"
	@echo "Regenerating UVM RAL model for $(1) sub-block $$*"
	@$(ocah_sh) '$(call ocah_reg_run_ral,$(1),$$<,$$*,$$@,,$(1)/regs/build/ral_$$*.log)$(call ocah_reg_stamp_after,"$$@")'
endef

# RTL sourced outside regblock: skip the run, keep the empty stamp so .generated
# stays well-defined.
define ocah_reg_sv_skip_rule
$(call ocah_reg_sv_stamp,$(1)): $(call ocah_reg_rdl,$(1)) | $(OCAH_REG_UV_PREREQ)
	@mkdir -p "$(call ocah_reg_build,$(1))"
	@echo "Skipping register SV for $(1) (RTL sourced outside regblock)"
	@touch "$$@"
endef

# Plain-leaf docs: RDL -> compact AsciiDoc (custom generator), plus a peakrdl html site.
define ocah_reg_doc_plain_rule
$(call ocah_reg_adoc_output,$(1)): $(call ocah_reg_rdl,$(1)) $(OCAH_REGBLOCK_UDP) $(OCAH_ROOT)/tools/regs/rdladoc.py $(OCAH_ROOT)/tools/regs/common/rdlview.py | $(OCAH_REG_UV_PREREQ)
	@mkdir -p "$(call ocah_reg_gen,$(1))/adoc" "$(call ocah_reg_build,$(1))"
	@echo "Regenerating AsciiDoc register docs for $(1)"
	@$(ocah_sh) '$(call ocah_reg_run_adoc,$(1),$(call ocah_reg_rdl,$(1)),$(call ocah_reg_adoc_output,$(1)),$(call ocah_reg_build,$(1))/adoc.log)$(call ocah_reg_stamp_after,"$(call ocah_reg_adoc_output,$(1))")'

$(call ocah_reg_html_output,$(1)): $(call ocah_reg_rdl,$(1)) $(OCAH_REGBLOCK_UDP) $(OCAH_ROOT)/tools/regs/rdlhtml.py $(OCAH_ROOT)/tools/regs/common/rdlview.py | $(OCAH_REG_UV_PREREQ)
	@mkdir -p "$$(@D)" "$(call ocah_reg_build,$(1))"
	@echo "Regenerating HTML register docs for $(1)"
	@$(ocah_sh) '$(call ocah_reg_run_html,$(1),$(call ocah_reg_rdl,$(1)),$$@,$(call ocah_reg_build,$(1))/html.log)$(call ocah_reg_stamp_after,"$$@")'
endef

# JSON register model for a whole top (composite or leaf), opt-in list only.
define ocah_reg_json_rule
$(call ocah_reg_json_output,$(1)): $(call ocah_reg_rdl,$(1)) $(OCAH_REGBLOCK_UDP) $(OCAH_ROOT)/tools/regs/rdljson.py | $(OCAH_REG_UV_PREREQ)
	@mkdir -p "$$(@D)" "$(call ocah_reg_build,$(1))"
	@echo "Regenerating JSON register model for $(1)"
	@$(ocah_sh) '$(call ocah_reg_run_json,$(1),$(call ocah_reg_rdl,$(1)),$$@,$(call ocah_reg_build,$(1))/json.log)$(call ocah_reg_stamp_after,"$$@")'
endef

# Plain-leaf UVM RAL: one peakrdl uvm run. Only instantiated for leaves on the
# opt-in list, so there is no skip variant.
define ocah_reg_ral_plain_rule
$(call ocah_reg_ral_output,$(1)): $(call ocah_reg_rdl,$(1)) $(OCAH_REGBLOCK_UDP) | $(OCAH_REG_UV_PREREQ)
	@mkdir -p "$(call ocah_reg_ral_dir,$(1))" "$(call ocah_reg_build,$(1))"
	@echo "Regenerating UVM RAL model for $(1)"
	@$(ocah_sh) '$(call ocah_reg_run_ral,$(1),$(call ocah_reg_rdl,$(1)),$(call ocah_reg_name,$(1)),$(call ocah_reg_ral_output,$(1)),$(call ocah_reg_ral_rename,$(1)),$(call ocah_reg_build,$(1))/ral.log)$(call ocah_reg_stamp_after,"$(call ocah_reg_ral_output,$(1))")'
endef

# Plain-leaf firmware C header: one peakrdl c-header run.
define ocah_reg_cheader_plain_rule
$(call ocah_reg_c_output,$(1)): $(call ocah_reg_rdl,$(1)) $(OCAH_REGBLOCK_UDP) | $(OCAH_REG_UV_PREREQ)
	@mkdir -p "$(call ocah_reg_gen,$(1))/c" "$(call ocah_reg_build,$(1))"
	@echo "Regenerating firmware C header for $(1)"
	@$(ocah_sh) '$(call ocah_reg_run_cheader,$(1),$(call ocah_reg_rdl,$(1)),$(call ocah_reg_c_output,$(1)),$(call ocah_reg_c_bitfields,$(1)),$(call ocah_reg_build,$(1))/c_header.log)$(call ocah_reg_stamp_after,"$(call ocah_reg_c_output,$(1))")'
endef

# Address exporters (raw-C, SV package, py) and the .generated stamp for every block.
$(foreach block,$(OCAH_REG_BLOCKS),$(eval $(call ocah_reg_block_rules,$(block))))
# Composite tops: per-sub-block sv/c/adoc/html pattern rules.
$(foreach block,$(OCAH_REG_COMPOSITE_BLOCK_IDS),$(eval $(call ocah_reg_composite_rules,$(block))))
# Plain leaves: single-file sv (or skip when RTL is elsewhere), docs, C header.
$(foreach block,$(OCAH_REG_PLAIN_BLOCK_IDS),$(eval $(call $(if $(call ocah_reg_sv_skipped,$(block)),ocah_reg_sv_skip_rule,ocah_reg_sv_plain_rule),$(block))))
$(foreach block,$(OCAH_REG_PLAIN_BLOCK_IDS),$(eval $(call ocah_reg_doc_plain_rule,$(block))))
$(foreach block,$(OCAH_REG_PLAIN_BLOCK_IDS),$(eval $(call ocah_reg_cheader_plain_rule,$(block))))
# Opt-in leaves only: RAL is not generated for every block.
$(foreach block,$(filter $(OCAH_REG_RAL_LEAF_BLOCKS),$(OCAH_REG_PLAIN_BLOCK_IDS)),$(eval $(call ocah_reg_ral_plain_rule,$(block))))
# JSON applies to a top of either shape, so it loops over all blocks, not the
# composite/leaf split.
$(foreach block,$(filter $(OCAH_REG_JSON_BLOCKS),$(OCAH_REG_BLOCKS)),$(eval $(call ocah_reg_json_rule,$(block))))

# Pull in the per-block depfiles (built by the rule in ocah_reg_block_rules): each
# adds its `include`d RDLs as prerequisites of that block's generated outputs, so
# an include-only change rebuilds the top collateral. Silent `-` so a missing
# depfile on a clean tree is not an error — make builds it, re-reads it, and the
# include prerequisites take effect. Depfiles live in the gitignored build dir.
#
# The depfiles only matter to the regen flow. Because make brings `-include`d
# files up to date before any goal, an unconditional include makes every build
# that reads this fragment — RTL and FW smokes, docs — rescan every block (one
# dep_scanner run each) even though those builds only consume the committed
# collateral. The regen-diff CI job already guards collateral staleness, so pull
# the depfiles in only for the goals that regenerate.
OCAH_REGEN_DEP_GOALS := \
  ocah-regen-regs ocah-regen-regs-sv ocah-regen-regs-h ocah-regen-regs-addrpkg \
  ocah-regen-regs-svh ocah-regen-regs-py ocah-regen-regs-ral ocah-regen-regs-json \
  ocah-regen-regs-ipxact ocah-regen-regs-adoc ocah-regen-regs-html
ifneq ($(filter $(OCAH_REGEN_DEP_GOALS),$(MAKECMDGOALS)),)
-include $(OCAH_REGEN_REG_DEPS)
endif
