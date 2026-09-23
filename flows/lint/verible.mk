# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_verible_mk
ocah_verible_mk := 1

OCAH_FORMAT_DIR := $(patsubst %/,%,$(dir $(lastword $(MAKEFILE_LIST))))
include $(OCAH_FORMAT_DIR)/../common.mk

# Filesystem scopes to lint and format.  The vendor root contributes only
# hand-authored overlays; upstream and generated overlay files are excluded
# below.  LINT_PATH / FORMAT_PATH accept one or more repository-relative paths.
OCAH_VERIBLE_PATHS ?= hw vendor
ifneq ($(BLOCK),)
LINT_PATH ?= hw/sys/$(BLOCK)
FORMAT_PATH ?= hw/sys/$(BLOCK)
else
LINT_PATH ?= $(OCAH_VERIBLE_PATHS)
FORMAT_PATH ?= $(OCAH_VERIBLE_PATHS)
endif

# parameter-name-style is deferred to issue #1051. line-length is disabled
# outright: the port/parameter/net alignment mode below (preserve) never
# wraps an aligned declaration regardless of its width, and Verible never
# reflows comment text, so most violations are structurally unfixable; the
# rest would need --try_wrap_long_lines, which the formatter's own docs flag
# as an experimental line-wrap optimizer, and which crashes outright on at
# least one file in this tree. unpacked-dimensions-range-ordering wants
# every unpacked array dimension declared big-endian ([0:N-1], or plain [N]
# for the zero-based case); this repo instead always writes unpacked array
# dimensions the same way it writes packed ranges, [N-1:0], and switching
# the two conventions per-declaration depending on packed vs. unpacked would
# be a net readability loss for no functional benefit. plusarg-assignment
# flags every $test$plusargs call in the tree; each one checks
# only whether a boolean flag was passed (waves, smc_hold_cpu_boot,
# sep_no_tcm_preload, ...), which is exactly what $test$plusargs is for -
# none of them extract a value, so the rule's suggested $value$plusargs
# would be wrong for all of them.
OCAH_LINT_VERIBLE_RULES ?= -parameter-name-style,-line-length,-unpacked-dimensions-range-ordering,-plusarg-assignment
OCAH_VERIBLE_EMPTY :=
OCAH_VERIBLE_SPACE := $(OCAH_VERIBLE_EMPTY) $(OCAH_VERIBLE_EMPTY)
OCAH_VERIBLE_COMMA := ,
OCAH_LINT_VERIBLE_WAIVER_FILES := $(shell find $(OCAH_ROOT)/hw $(OCAH_ROOT)/vendor \
	-type f -path '*/lint/*.verible.waiver' -not -path '*/upstream/*' | sort)
OCAH_LINT_VERIBLE_EXTRA_FLAGS ?= $(if $(OCAH_LINT_VERIBLE_WAIVER_FILES),\
	--waiver_files=$(subst $(OCAH_VERIBLE_SPACE),$(OCAH_VERIBLE_COMMA),$(strip $(OCAH_LINT_VERIBLE_WAIVER_FILES))))
OCAH_FORMAT_VERIBLE_FLAGS ?= --flagfile=$(OCAH_FORMAT_DIR)/verible-format.flags
OCAH_FORMAT_VERIBLE_EXTRA_FLAGS ?=
OCAH_SV_DECLARATION_SPACING_CHECK := $(OCAH_ROOT)/scripts/ci/check_sv_declaration_spacing.py

# These files consume macros defined by their compilation unit. The pinned
# Verible release cannot supply that context to a one-file lint/format command.
OCAH_VERIBLE_CONTEXT_EXCLUDES := \
	hw/common/axi/axi_lite_to_tlul.sv \
	hw/common/axi/tlul_to_axi_lite.sv \
	hw/common/och_prim/rtl/prim_jtag_scan_reg.sv \
	hw/common/och_prim/rtl/prim_ram_1p_adv_ext.sv \
	hw/common/och_prim/rtl/prim_ram_1p_scr_ext.sv \
	hw/common/tlul/rtl/tlul_adapter_host.sv \
	hw/common/tlul/rtl/tlul_adapter_reg.sv \
	hw/common/tlul/rtl/tlul_adapter_sram.sv \
	hw/ip/cross_trigger/cross_trigger_network/rtl/cross_trigger_network.sv \
	hw/ip/entropy_source/rtl/entropy_source.sv \
	hw/ip/jtag/jtag_ptap/rtl/jtag_caps_reg.sv \
	hw/ip/jtag/jtag_ptap/rtl/jtag_ptap.sv \
	hw/ip/system_timer_octs/rtl/system_timer_octs_core.sv \
	hw/sys/sep/rtl/sep_system_peripherals/rtl/sep_system_peripherals_xbar_wrapper.sv

# These valid files use conditional module headers, escaped hierarchical
# references, wildcard syntax, or macro-generated member selections that the
# formatter cannot process or reparse reliably. Slang compilation remains
# authoritative for their syntax.
OCAH_VERIBLE_FORMAT_PARSER_EXCLUDES := \
	hw/common/och_prim/rtl/prim_apb_mux_struct.sv \
	hw/sys/dtp/dv/tb/tb_top.sv \
	hw/sys/sep/dv/tb/tb_top.sv \
	hw/sys/smc/dv/tb/tb_top.sv \
	hw/sys/sep/rtl/sep_tcm_wrapper.sv \
	hw/top/smc_ip_integration.sv

# Lint parses these three conditional-header/integration files even though the
# formatter's output reparse does not. Keep their lint findings visible.
OCAH_VERIBLE_LINT_PARSER_EXCLUDES := \
	hw/common/och_prim/rtl/prim_apb_mux_struct.sv \
	hw/sys/sep/dv/tb/tb_top.sv \
	hw/sys/sep/rtl/sep_tcm_wrapper.sv

# The formatter fails its own convergence/output-reparse checks on these two
# files even though lint and compilation accept them.
OCAH_VERIBLE_CONVERGENCE_EXCLUDES := \
	hw/common/sync.sv \
	hw/ip/efuse/rtl/efuse_shadow_regs.sv

# Lint and format share the base inventory but not every exclusion. Lint keeps
# files that it can parse even when the formatter cannot converge or reparse
# its own output.
OCAH_VERIBLE_LINT_EXCLUDES := \
	$(OCAH_VERIBLE_CONTEXT_EXCLUDES) \
	$(OCAH_VERIBLE_LINT_PARSER_EXCLUDES)

OCAH_VERIBLE_FORMAT_EXCLUDES := \
	$(OCAH_VERIBLE_CONTEXT_EXCLUDES) \
	$(OCAH_VERIBLE_FORMAT_PARSER_EXCLUDES) \
	$(OCAH_VERIBLE_CONVERGENCE_EXCLUDES)

# Shared first-party, hand-maintained .sv/.svh/.v inventory for lint and
# format.  Keep this as a find expression rather than a Make-expanded file
# list: the complete tree exceeds the host's command-line length limit.
#
# Exclusions cover build output, materialized third-party sources, nested
# copied vendor trees, PeakRDL output, generated fabrics and CPU internals,
# OCAH-owned OpenTitan chip config packages, the individually
# generated overlay files that ship pre-generated rather than built by
# this tree, and the eFuse DV model's register block, which PeakRDL
# generated once into dv/models/
# (outside any regs/gen/ tree) and which stays hand-maintained rather than
# regenerated (see hw/ip/efuse/dv/models/README.md), so its struct/union
# style still reflects that origin rather than this repo's conventions.
ocah_verible_find = find $(addprefix $(OCAH_ROOT)/,$(1)) -type f \( -name '*.sv' -o -name '*.svh' -o -name '*.v' \) \
	-not -path '*/build/*' \
	-not -path '$(OCAH_ROOT)/vendor/*/*/upstream/*' \
	-not -path '$(OCAH_ROOT)/hw/*/vendor/*' \
	-not -path '*/regs/gen/*' \
	-not -path '*/rdl/gen/*' \
	-not -path '*/crossbars/*' \
	-not -path '*/chipyard_generated_files/*' \
	-not -path '*/hw/common/ot_chip_cfg/*' \
	-not -path '$(OCAH_ROOT)/vendor/pulp-platform/idma/overlay/target/rtl/*' \
	-not -path '$(OCAH_ROOT)/hw/ip/efuse/dv/models/efuse_bank_reg.sv' \
	-not -path '$(OCAH_ROOT)/hw/ip/efuse/dv/models/efuse_bank_reg_pkg.sv' \
	$(foreach file,$(2),-not -path '$(OCAH_ROOT)/$(file)')

ocah_verible_check_files = @$(call ocah_verible_find,$(1),$(2)) -print -quit 2>/dev/null | grep -q . || { \
	echo "error: no hand-maintained .sv/.svh/.v files under $(1)" >&2; \
	exit 1; \
}

## @section Lint (verible)

## Lint SystemVerilog style with verible-verilog-lint (no autofix; hand-fix
## reported violations). Requires `verible-verilog-lint` on PATH; otherwise
## install it or run via `./scripts/docker-run.sh run-here make lint-sv-verible`.
## parameter-name-style is deferred to issue #1051; line-length is disabled
## outright (see OCAH_LINT_VERIBLE_RULES above).
## @param LINT_PATH=hw/sys/smu Optional path(s) to scope the lint; default hw vendor
## @param BLOCK=smu Shorthand for the above (LINT_PATH?=hw/sys/BLOCK if set)
.PHONY: ocah-lint-sv-verible
ocah-lint-sv-verible:
	$(call ocah_require_host_tool,verible-verilog-lint,./scripts/docker-run.sh run-here make lint-sv-verible)
	$(call ocah_verible_check_files,$(LINT_PATH),$(OCAH_VERIBLE_LINT_EXCLUDES))
	@$(call ocah_verible_find,$(LINT_PATH),$(OCAH_VERIBLE_LINT_EXCLUDES)) -print0 2>/dev/null | \
		xargs -0 -n 1 verible-verilog-lint \
			--rules="$(OCAH_LINT_VERIBLE_RULES)" \
			$(OCAH_LINT_VERIBLE_EXTRA_FLAGS)

OCAH_PHONY += ocah-lint-sv-verible

## @section Format (verible)

## Check hand-maintained SystemVerilog for tabs and padding immediately inside
## declaration dimensions. These forms are preserved by the formatter and
## otherwise reintroduce unstable or right-justified alignment.
## @param FORMAT_PATH=hw/sys/smu Optional path(s) to scope the check; default hw vendor
## @param BLOCK=smu Shorthand for the above (FORMAT_PATH?=hw/sys/BLOCK if set)
.PHONY: ocah-check-sv-declaration-spacing
ocah-check-sv-declaration-spacing:
	$(call ocah_verible_check_files,$(FORMAT_PATH),$(OCAH_VERIBLE_FORMAT_EXCLUDES))
	@$(call ocah_verible_find,$(FORMAT_PATH),$(OCAH_VERIBLE_FORMAT_EXCLUDES)) -print0 2>/dev/null | \
		xargs -0 python3 $(OCAH_SV_DECLARATION_SPACING_CHECK)

## Format SystemVerilog sources in place with verible-verilog-format.
## Requires `verible-verilog-format` on PATH; otherwise install it or run via
## `./scripts/docker-run.sh run-here make format-sv`.
## @param FORMAT_PATH=hw/sys/smu Optional path(s) to scope formatting; default hw vendor
## @param BLOCK=smu Shorthand for the above (FORMAT_PATH?=hw/sys/BLOCK if set)
.PHONY: ocah-format-sv
ocah-format-sv:
	$(call ocah_require_host_tool,verible-verilog-format,./scripts/docker-run.sh run-here make format-sv)
	$(call ocah_verible_check_files,$(FORMAT_PATH),$(OCAH_VERIBLE_FORMAT_EXCLUDES))
	@$(call ocah_verible_find,$(FORMAT_PATH),$(OCAH_VERIBLE_FORMAT_EXCLUDES)) -print0 2>/dev/null | \
		xargs -0 -n 1 verible-verilog-format \
			$(OCAH_FORMAT_VERIBLE_FLAGS) \
			$(OCAH_FORMAT_VERIBLE_EXTRA_FLAGS) \
			--inplace

## Check formatting without modifying files (CI-friendly: exit 0 clean, 1 would-reformat).
## @param FORMAT_PATH=hw/sys/smu Optional path(s) to scope the check; default hw vendor
## @param BLOCK=smu Shorthand for the above (FORMAT_PATH?=hw/sys/BLOCK if set)
.PHONY: ocah-format-sv-check
ocah-format-sv-check: ocah-check-sv-declaration-spacing
	$(call ocah_require_host_tool,verible-verilog-format,./scripts/docker-run.sh run-here make format-sv-check)
	$(call ocah_verible_check_files,$(FORMAT_PATH),$(OCAH_VERIBLE_FORMAT_EXCLUDES))
	@$(call ocah_verible_find,$(FORMAT_PATH),$(OCAH_VERIBLE_FORMAT_EXCLUDES)) -print0 2>/dev/null | \
		xargs -0 -n 1 sh -c '\
			output="$$(verible-verilog-format \
				$(OCAH_FORMAT_VERIBLE_FLAGS) \
				$(OCAH_FORMAT_VERIBLE_EXTRA_FLAGS) \
				--verify "$$1" 2>&1)"; \
			status=$$?; \
			if [ -n "$$output" ]; then \
				printf "%s\n" "$$output"; \
				[ $$status -ne 0 ] || status=1; \
			fi; \
			exit $$status' sh

OCAH_PHONY += ocah-check-sv-declaration-spacing ocah-format-sv ocah-format-sv-check

endif
