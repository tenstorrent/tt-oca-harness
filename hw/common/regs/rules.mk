# SPDX-License-Identifier: Apache-2.0
# (c) 2026 Tenstorrent USA Inc

# The actual build rules: peakrdl command lines and the make rules that turn each
# block's RDL into SV/C/Python/docs, instantiated per block via foreach/eval.

# Composite sub-block prereqs are regs/blocks/<sub>/<sub>.rdl: the stem appears
# twice, so the second is resolved via secondary expansion ($$*). A no-op elsewhere.
.SECONDEXPANSION:

# Canned peakrdl exporter command lines. $(1) = block id (for -I); later args are
# input, output, name/bitfields, log.
ocah_reg_run_cheader  = "$(UV)" run peakrdl c-header $(call ocah_reg_incdirs,$(1)) "$(OCAH_REGBLOCK_UDP)" "$(2)" -o "$(3)" --bitfields $(4) --type-style lexical 2>&1 | tee "$(5)"
ocah_reg_run_regblock = "$(UV)" run peakrdl regblock $(call ocah_reg_incdirs,$(1)) "$(OCAH_REGBLOCK_UDP)" "$(2)" -o "$(3)" --cpuif "$(call ocah_reg_cpu_if,$(1))" --default-reset "$(OCAH_REG_DEFAULT_RESET)" --module-name "$(4)_reg" --package-name "$(4)_reg_pkg" 2>&1 | tee "$(5)"
# AsciiDoc register docs are emitted directly from RDL by a custom generator that
# produces a compact summary table + per-register field tables (table captions,
# no per-register headings). This replaces the old peakrdl-markdown -> pandoc
# path, which created a heading/TOC entry per register and exploded the PDF page
# count. $(2) = input RDL, $(3) = output adoc, $(4) = log.
ocah_reg_run_adoc     = "$(UV)" run python "$(OCAH_ROOT)/tools/regs/rdladoc.py" -u "$(OCAH_REGBLOCK_UDP)" $(call ocah_reg_incdirs,$(1)) "$(2)" "$(3)" 2>&1 | tee "$(4)"
ocah_reg_run_html     = "$(UV)" run python "$(OCAH_ROOT)/tools/regs/rdlhtml.py" -u "$(OCAH_REGBLOCK_UDP)" $(call ocah_reg_incdirs,$(1)) "$(2)" "$(3)" 2>&1 | tee "$(4)"

# Refresh one committed vendored RDL from its upstream hjson. This is intentionally
# NOT a make file rule on the RDL path: the committed RDL must never become a
# regen-regs prerequisite (otherwise a clean checkout with a newer vendored hjson
# would silently regenerate it). It is invoked only by the on-demand
# regen-vendor-rdl phony target (see phony.mk), which calls it per entry.
ocah_vendor_hjson_rdl_regen = cd "$(OCAH_ROOT)" && "$(UV)" run python tools/regs/reggen_wrapper.py --systemrdl $(call ocah_vhr_nameopt,$(1)) -o "$(call ocah_vhr_rdl,$(1))" "$(call ocah_vhr_hjson,$(1))"

define ocah_reg_block_rules
$(call ocah_reg_raw_c_output,$(1)): $(call ocah_reg_rdl,$(1)) $(OCAH_REGBLOCK_UDP) | uv-sync
	@mkdir -p "$(call ocah_reg_gen,$(1))/c" "$(call ocah_reg_build,$(1))"
	@echo "Regenerating raw C address header for $(1)"
	@$(ocah_sh) '"$(UV)" run peakrdl raw-header $(call ocah_reg_incdirs,$(1)) "$(OCAH_REGBLOCK_UDP)" "$(call ocah_reg_rdl,$(1))" --format c --base-name "$(shell echo $(call ocah_reg_name,$(1))_addr | tr a-z A-Z)" -o "$(call ocah_reg_raw_c_output,$(1))" 2>&1 | tee "$(call ocah_reg_build,$(1))/raw_c_header.log"'

$(call ocah_reg_svpkg_output,$(1)): $(call ocah_reg_rdl,$(1)) $(OCAH_REGBLOCK_UDP) | uv-sync
	@mkdir -p "$(call ocah_reg_gen,$(1))/sv" "$(call ocah_reg_build,$(1))"
	@echo "Regenerating SystemVerilog address package for $(1)"
	@$(ocah_sh) '"$(UV)" run peakrdl raw-header $(call ocah_reg_incdirs,$(1)) "$(OCAH_REGBLOCK_UDP)" "$(call ocah_reg_rdl,$(1))" --format svpkg -o "$(call ocah_reg_svpkg_output,$(1))" 2>&1 | tee "$(call ocah_reg_build,$(1))/raw_svpkg.log"'

$(call ocah_reg_py_output,$(1)): $(call ocah_reg_raw_c_output,$(1)) $(OCAH_ROOT)/tools/regs/rdlpyhdr.py
	@mkdir -p "$(call ocah_reg_gen,$(1))/py" "$(call ocah_reg_build,$(1))"
	@echo "Regenerating Python address constants for $(1)"
	@cd "$(OCAH_ROOT)" && "$(UV)" run python tools/regs/rdlpyhdr.py \
		"$(call ocah_reg_raw_c_output,$(1))" \
		"$(call ocah_reg_py_output,$(1))"

$(call ocah_reg_build,$(1))/.generated: $(call ocah_reg_sv_target,$(1)) $(call ocah_reg_h_target,$(1)) $(call ocah_reg_raw_c_output,$(1)) $(call ocah_reg_svpkg_output,$(1)) $(call ocah_reg_py_output,$(1))
	@mkdir -p "$(call ocah_reg_build,$(1))"
	@touch "$$@"
endef

# Plain-leaf register RTL: one regblock run on the block's own RDL.
define ocah_reg_sv_plain_rule
$(call ocah_reg_sv_stamp,$(1)): $(call ocah_reg_rdl,$(1)) $(OCAH_REGBLOCK_UDP) | uv-sync
	@mkdir -p "$(call ocah_reg_gen,$(1))/sv" "$(call ocah_reg_build,$(1))"
	@echo "Regenerating register SV for $(1)"
	@$(ocah_sh) '$(call ocah_reg_run_regblock,$(1),$(call ocah_reg_rdl,$(1)),$(call ocah_reg_gen,$(1))/sv,$(call ocah_reg_name,$(1)),$(call ocah_reg_build,$(1))/peakrdl_sv.log)'
	@touch "$$@"

$(call ocah_reg_sv_outputs,$(1)): $(call ocah_reg_sv_stamp,$(1))
	@test -f "$$@" || { echo "error: expected generated file missing: $$@"; exit 1; }
endef

# Composite-top collateral: pattern rules running the matching exporter on each
# regs/blocks/<sub>/<sub>.rdl (doubled stem via secondary expansion).
define ocah_reg_composite_rules
$(call ocah_reg_sv_block_dir,$(1))/%_reg.sv: $(call ocah_reg_root,$(1))/regs/blocks/$$$$*/$$$$*.rdl $(OCAH_REGBLOCK_UDP) | uv-sync
	@mkdir -p "$$(@D)" "$(call ocah_reg_build,$(1))"
	@echo "Regenerating register SV for $(1) sub-block $$*"
	@$(ocah_sh) '$(call ocah_reg_run_regblock,$(1),$$<,$$(@D),$$*,$(1)/regs/build/peakrdl_sv_$$*.log)'

$(call ocah_reg_c_block_dir,$(1))/%.h: $(call ocah_reg_root,$(1))/regs/blocks/$$$$*/$$$$*.rdl $(OCAH_REGBLOCK_UDP) | uv-sync
	@mkdir -p "$$(@D)" "$(call ocah_reg_build,$(1))"
	@echo "Regenerating firmware C header for $(1) sub-block $$*"
	@$(ocah_sh) '$(call ocah_reg_run_cheader,$(1),$$<,$$@,$$(if $$(filter $$*,$(OCAH_REG_NO_BITFIELDS)),none,ltoh),$(1)/regs/build/c_header_$$*.log)'

$(call ocah_reg_adoc_block_dir,$(1))/%.adoc: $(call ocah_reg_root,$(1))/regs/blocks/$$$$*/$$$$*.rdl $(OCAH_REGBLOCK_UDP) tools/regs/rdladoc.py tools/regs/rdlview.py | uv-sync
	@mkdir -p "$$(@D)" "$(call ocah_reg_build,$(1))"
	@echo "Regenerating AsciiDoc register docs for $(1) sub-block $$*"
	@$(ocah_sh) '$(call ocah_reg_run_adoc,$(1),$$<,$$@,$(1)/regs/build/adoc_$$*.log)'

$(call ocah_reg_html_block_dir,$(1))/%.html: $(call ocah_reg_root,$(1))/regs/blocks/$$$$*/$$$$*.rdl $(OCAH_REGBLOCK_UDP) $(OCAH_ROOT)/tools/regs/rdlhtml.py $(OCAH_ROOT)/tools/regs/rdlview.py | uv-sync
	@mkdir -p "$$(@D)" "$(call ocah_reg_build,$(1))"
	@echo "Regenerating HTML register docs for $(1) sub-block $$*"
	@$(ocah_sh) '$(call ocah_reg_run_html,$(1),$$<,$$@,$(1)/regs/build/html_$$*.log)'
endef

# RTL sourced outside regblock: skip the run, keep the empty stamp so .generated
# stays well-defined.
define ocah_reg_sv_skip_rule
$(call ocah_reg_sv_stamp,$(1)): $(call ocah_reg_rdl,$(1)) | uv-sync
	@mkdir -p "$(call ocah_reg_build,$(1))"
	@echo "Skipping register SV for $(1) (RTL sourced outside regblock)"
	@touch "$$@"
endef

# Plain-leaf docs: RDL -> compact AsciiDoc (custom generator), plus a peakrdl html site.
define ocah_reg_doc_plain_rule
$(call ocah_reg_adoc_output,$(1)): $(call ocah_reg_rdl,$(1)) $(OCAH_REGBLOCK_UDP) $(OCAH_ROOT)/tools/regs/rdladoc.py $(OCAH_ROOT)/tools/regs/rdlview.py | uv-sync
	@mkdir -p "$(call ocah_reg_gen,$(1))/adoc" "$(call ocah_reg_build,$(1))"
	@echo "Regenerating AsciiDoc register docs for $(1)"
	@$(ocah_sh) '$(call ocah_reg_run_adoc,$(1),$(call ocah_reg_rdl,$(1)),$(call ocah_reg_adoc_output,$(1)),$(call ocah_reg_build,$(1))/adoc.log)'

$(call ocah_reg_html_output,$(1)): $(call ocah_reg_rdl,$(1)) $(OCAH_REGBLOCK_UDP) $(OCAH_ROOT)/tools/regs/rdlhtml.py $(OCAH_ROOT)/tools/regs/rdlview.py | uv-sync
	@mkdir -p "$$(@D)" "$(call ocah_reg_build,$(1))"
	@echo "Regenerating HTML register docs for $(1)"
	@$(ocah_sh) '$(call ocah_reg_run_html,$(1),$(call ocah_reg_rdl,$(1)),$$@,$(call ocah_reg_build,$(1))/html.log)'
endef

# Plain-leaf firmware C header: one peakrdl c-header run.
define ocah_reg_cheader_plain_rule
$(call ocah_reg_c_output,$(1)): $(call ocah_reg_rdl,$(1)) $(OCAH_REGBLOCK_UDP) | uv-sync
	@mkdir -p "$(call ocah_reg_gen,$(1))/c" "$(call ocah_reg_build,$(1))"
	@echo "Regenerating firmware C header for $(1)"
	@$(ocah_sh) '$(call ocah_reg_run_cheader,$(1),$(call ocah_reg_rdl,$(1)),$(call ocah_reg_c_output,$(1)),$(call ocah_reg_c_bitfields,$(1)),$(call ocah_reg_build,$(1))/c_header.log)'
endef

# Address exporters (raw-C, SV package, py) and the .generated stamp for every block.
$(foreach block,$(OCAH_REG_BLOCKS),$(eval $(call ocah_reg_block_rules,$(block))))
# Composite tops: per-sub-block sv/c/adoc/html pattern rules.
$(foreach block,$(OCAH_REG_COMPOSITE_BLOCK_IDS),$(eval $(call ocah_reg_composite_rules,$(block))))
# Plain leaves: single-file sv (or skip when RTL is elsewhere), docs, C header.
$(foreach block,$(OCAH_REG_PLAIN_BLOCK_IDS),$(eval $(call $(if $(call ocah_reg_sv_skipped,$(block)),ocah_reg_sv_skip_rule,ocah_reg_sv_plain_rule),$(block))))
$(foreach block,$(OCAH_REG_PLAIN_BLOCK_IDS),$(eval $(call ocah_reg_doc_plain_rule,$(block))))
$(foreach block,$(OCAH_REG_PLAIN_BLOCK_IDS),$(eval $(call ocah_reg_cheader_plain_rule,$(block))))
