# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_verible_mk
ocah_verible_mk := 1

include $(patsubst %/,%,$(dir $(lastword $(MAKEFILE_LIST))))/../common.mk

# Path to lint, scoped by filesystem or by block. Not named PATH=,
# which would override the shell's own command-search PATH.
ifneq ($(BLOCK),)
LINT_PATH ?= hw/sys/$(BLOCK)
else
LINT_PATH ?= hw
endif
# .sv/.svh/.v files under LINT_PATH, excluding build output, vendored
# third-party sources, and tool-generated RTL this repo doesn't hand-maintain:
# PeakRDL register blocks (regs/gen), fabric_gen-generated crossbars,
# Chipyard/CIRCT-generated CPU core internals, OpenTitan-origin package
# stubs (hw/common/ot_pkg), and a couple of individually-generated files
# living in otherwise hand-written directories.
ocah_lint_sv_verible_files = $(shell find $(OCAH_ROOT)/$(LINT_PATH) \( -name '*.sv' -o -name '*.svh' -o -name '*.v' \) \
	-not -path '*/build/*' \
	-not -path '*/vendor/*' \
	-not -path '*/regs/gen/*' \
	-not -path '*/crossbars/*' \
	-not -path '*/chipyard_generated_files/*' \
	-not -path '*/hw/common/ot_pkg/*' \
	-not -path '*/hw/sys/dtp/rtl/dtp_pkg.sv' \
	-not -path '*/hw/ip/cross_trigger/cross_trigger_network/rtl/cross_trigger_network_pkg.sv' \
	2>/dev/null)

ocah_lint_sv_verible_check_files = @[ -n "$(strip $(ocah_lint_sv_verible_files))" ] || { echo "error: no .sv/.svh/.v files under $(LINT_PATH)" >&2; exit 1; }

## @section Lint (verible)

## Lint SystemVerilog style with verible-verilog-lint (no autofix; hand-fix
## reported violations). Requires `verible-verilog-lint` on PATH; otherwise
## install it or run via `./scripts/docker-run.sh eda-run make lint-sv-verible`.
## @param LINT_PATH=hw/sys/smu Optional path to scope the lint; default hw
## @param BLOCK=smu Shorthand for the above, for consistency (LINT_PATH?=hw/sys/BLOCK if set)
.PHONY: ocah-lint-sv-verible
ocah-lint-sv-verible:
	$(ocah_lint_sv_verible_check_files)
	$(call ocah_require_host_tool,verible-verilog-lint,./scripts/docker-run.sh eda-run make lint-sv-verible)
	verible-verilog-lint $(ocah_lint_sv_verible_files)

OCAH_PHONY += ocah-lint-sv-verible

# Path to format, scoped by filesystem or by block. Not named PATH=,
# which would override the shell's own command-search PATH.
ifneq ($(BLOCK),)
FORMAT_PATH ?= hw/sys/$(BLOCK)
else
FORMAT_PATH ?= hw
endif

# .sv/.svh/.v files under FORMAT_PATH, excluding build output and vendored
# third-party sources.
ocah_format_sv_files = $(shell find $(OCAH_ROOT)/$(FORMAT_PATH) \( -name '*.sv' -o -name '*.svh' -o -name '*.v' \) -not -path '*/build/*' -not -path '*/vendor/*' 2>/dev/null)

ocah_format_sv_check_files = @[ -n "$(strip $(ocah_format_sv_files))" ] || { echo "error: no .sv/.svh/.v files under $(FORMAT_PATH)" >&2; exit 1; }

## @section Format (verible)

## Format SystemVerilog sources in place with verible-verilog-format.
## Requires `verible-verilog-format` on PATH; otherwise install it or run via
## `./scripts/docker-run.sh eda-run make format-sv`.
## @param FORMAT_PATH=hw/sys/smu Optional path to scope formatting; default hw
## @param BLOCK=smu Shorthand for the above, for consistency (FORMAT_PATH?=hw/sys/BLOCK if set)
.PHONY: ocah-format-sv
ocah-format-sv:
	$(ocah_format_sv_check_files)
	$(call ocah_require_host_tool,verible-verilog-format,./scripts/docker-run.sh eda-run make format-sv)
	verible-verilog-format --inplace $(ocah_format_sv_files)

## Check formatting without modifying files (CI-friendly: exit 0 clean, 1 would-reformat).
## @param FORMAT_PATH=hw/sys/smu Optional path to scope the check; default hw
## @param BLOCK=smu Shorthand for the above, for consistency (FORMAT_PATH?=hw/sys/BLOCK if set)
.PHONY: ocah-format-sv-check
ocah-format-sv-check:
	$(ocah_format_sv_check_files)
	$(call ocah_require_host_tool,verible-verilog-format,./scripts/docker-run.sh eda-run make format-sv-check)
	verible-verilog-format --verify $(ocah_format_sv_files)

OCAH_PHONY += ocah-format-sv ocah-format-sv-check

endif
