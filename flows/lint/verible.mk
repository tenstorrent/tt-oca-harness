# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_verible_mk
ocah_verible_mk := 1

include $(patsubst %/,%,$(dir $(lastword $(MAKEFILE_LIST))))/../common.mk

# Filesystem scopes to lint and format.  The vendor root contributes only
# hand-authored overlays; upstream and generated overlay files are excluded
# below.  LINT_PATH / FORMAT_PATH accept one or more repository-relative paths.
OCAH_VERIBLE_PATHS ?= hw vendor
LINT_PATH ?= $(OCAH_VERIBLE_PATHS)
FORMAT_PATH ?= $(OCAH_VERIBLE_PATHS)

OCAH_LINT_VERIBLE_RULES ?= -parameter-name-style
OCAH_LINT_VERIBLE_EXTRA_FLAGS ?=
OCAH_FORMAT_VERIBLE_FLAGS ?= --flagfile=$(OCAH_FORMAT_DIR)/verible-format.flags
OCAH_FORMAT_VERIBLE_EXTRA_FLAGS ?=

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
# pinned single-file parser rejects. Slang compilation below remains
# authoritative for their syntax.
OCAH_VERIBLE_PARSER_EXCLUDES := \
	hw/common/och_prim/rtl/prim_apb_mux_struct.sv \
	hw/ip/entropy_source/dv/tb_vcs/models/decorrelator/decor_cfg_if.sv \
	hw/ip/entropy_source/dv/tb_vcs/models/ro/ro_cfg_if.sv \
	hw/sys/dtp/dv/tb/tb_top.sv \
	hw/sys/sep/dv/tb/tb_top.sv \
	hw/sys/sep/rtl/sep_tcm_wrapper.sv \
	hw/top/smc_ip_integration.sv

# The formatter fails its own convergence/output-reparse checks on these two
# files even though lint and compilation accept them.
OCAH_VERIBLE_CONVERGENCE_EXCLUDES := \
	hw/common/sync.sv \
	hw/ip/efuse/rtl/efuse_shadow_regs.sv

# Lint and format intentionally share this inventory. Keeping failed
# single-file parses out of both avoids presenting parser cascades as style
# findings; correctness-oriented compilation and elaboration still cover them.
OCAH_VERIBLE_SINGLE_FILE_EXCLUDES := \
	$(OCAH_VERIBLE_CONTEXT_EXCLUDES) \
	$(OCAH_VERIBLE_PARSER_EXCLUDES) \
	$(OCAH_VERIBLE_CONVERGENCE_EXCLUDES)

# Shared first-party, hand-maintained .sv/.svh/.v inventory for lint and
# format.  Keep this as a find expression rather than a Make-expanded file
# list: the complete tree exceeds the host's command-line length limit.
#
# Exclusions cover build output, materialized third-party sources, nested
# copied vendor trees, PeakRDL output, generated fabrics and CPU internals,
# generated overlay output, OpenTitan-origin package stubs, and the two
# individually generated package files in otherwise hand-authored trees.  The
ocah_verible_find = find $(addprefix $(OCAH_ROOT)/,$(1)) -type f \( -name '*.sv' -o -name '*.svh' -o -name '*.v' \) \
	-not -path '*/build/*' \
	-not -path '$(OCAH_ROOT)/vendor/*/*/upstream/*' \
	-not -path '$(OCAH_ROOT)/hw/*/vendor/*' \
	-not -path '*/regs/gen/*' \
	-not -path '*/rdl/gen/*' \
	-not -path '*/crossbars/*' \
	-not -path '*/chipyard_generated_files/*' \
	-not -path '*/hw/common/ot_pkg/*' \
	-not -path '$(OCAH_ROOT)/vendor/pulp-platform/idma/overlay/target/rtl/*' \
	-not -path '$(OCAH_ROOT)/vendor/lowRISC/opentitan/overlay/spi_controller/rtl/spi_controller_reg.sv' \
	-not -path '$(OCAH_ROOT)/vendor/lowRISC/opentitan/overlay/spi_controller/rtl/spi_controller_reg_pkg.sv' \
	-not -path '*/hw/sys/dtp/rtl/dtp_pkg.sv' \
	-not -path '*/hw/ip/cross_trigger/cross_trigger_network/rtl/cross_trigger_network_pkg.sv' \
	$(foreach file,$(OCAH_VERIBLE_SINGLE_FILE_EXCLUDES),-not -path '$(OCAH_ROOT)/$(file)')

ocah_verible_check_files = @$(call ocah_verible_find,$(1)) -print -quit 2>/dev/null | grep -q . || { \
	echo "error: no hand-maintained .sv/.svh/.v files under $(1)" >&2; \
	exit 1; \
}

## @section Lint (verible)

## Lint SystemVerilog style with verible-verilog-lint (no autofix; hand-fix
## reported violations). Requires `verible-verilog-lint` on PATH; otherwise
## install it or run via `./scripts/docker-run.sh eda-run make lint-sv-verible`.
## parameter-name-style is deferred to issue #1051.
## @param LINT_PATH=hw/sys/smu Optional path(s) to scope the lint; default hw vendor
.PHONY: ocah-lint-sv-verible
ocah-lint-sv-verible:
	$(call ocah_require_host_tool,verible-verilog-lint,./scripts/docker-run.sh eda-run make lint-sv-verible)
	$(call ocah_verible_check_files,$(LINT_PATH))
	@$(call ocah_verible_find,$(LINT_PATH)) -print0 2>/dev/null | \
		xargs -0 -n 1 verible-verilog-lint \
			--rules="$(OCAH_LINT_VERIBLE_RULES)" \
			$(OCAH_LINT_VERIBLE_EXTRA_FLAGS)

OCAH_PHONY += ocah-lint-sv-verible

## @section Format (verible)

## Format SystemVerilog sources in place with verible-verilog-format.
## Requires `verible-verilog-format` on PATH; otherwise install it or run via
## `./scripts/docker-run.sh eda-run make format-sv`.
## @param FORMAT_PATH=hw/sys/smu Optional path(s) to scope formatting; default hw vendor
.PHONY: ocah-format-sv
ocah-format-sv:
	$(call ocah_require_host_tool,verible-verilog-format,./scripts/docker-run.sh eda-run make format-sv)
	$(call ocah_verible_check_files,$(FORMAT_PATH))
	@$(call ocah_verible_find,$(FORMAT_PATH)) -print0 2>/dev/null | \
		xargs -0 -n 1 verible-verilog-format \
			$(OCAH_FORMAT_VERIBLE_FLAGS) \
			$(OCAH_FORMAT_VERIBLE_EXTRA_FLAGS) \
			--inplace

## Check formatting without modifying files (CI-friendly: exit 0 clean, 1 would-reformat).
## @param FORMAT_PATH=hw/sys/smu Optional path(s) to scope the check; default hw vendor
.PHONY: ocah-format-sv-check
ocah-format-sv-check:
	$(call ocah_require_host_tool,verible-verilog-format,./scripts/docker-run.sh eda-run make format-sv-check)
	$(call ocah_verible_check_files,$(FORMAT_PATH))
	@$(call ocah_verible_find,$(FORMAT_PATH)) -print0 2>/dev/null | \
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

OCAH_PHONY += ocah-format-sv ocah-format-sv-check

endif
