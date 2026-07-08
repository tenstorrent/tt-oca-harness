# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_format_verible_mk
ocah_format_verible_mk := 1

OCAH_FORMAT_DIR := $(patsubst %/,%,$(dir $(lastword $(MAKEFILE_LIST))))
include $(OCAH_FORMAT_DIR)/../common.mk

# Path to format, scoped by filesystem rather than by block. Not named PATH=,
# which would override the shell's own command-search PATH.
FORMAT_PATH ?= hw

# .sv/.svh/.v files under FORMAT_PATH, excluding build output and vendored
# third-party sources.
ocah_format_files := $(shell find $(OCAH_ROOT)/$(FORMAT_PATH) \( -name '*.sv' -o -name '*.svh' -o -name '*.v' \) -not -path '*/build/*' -not -path '*/vendor/*' 2>/dev/null)

ocah_format_check_files = @[ -n "$(strip $(ocah_format_files))" ] || { echo "error: no .sv/.svh/.v files under $(FORMAT_PATH)" >&2; exit 1; }

## @section Format (verible)

## Format SystemVerilog sources in place with verible-verilog-format.
## @param FORMAT_PATH=hw/sys/smu Optional path to scope formatting; default hw
.PHONY: ocah-format
ocah-format:
	$(ocah_format_check_files)
	$(call ocah_eda_docker_run, verible-verilog-format --inplace $(ocah_format_files))

## Check formatting without modifying files (CI-friendly: exit 0 clean, 1 would-reformat).
## @param FORMAT_PATH=hw/sys/smu Optional path to scope the check; default hw
.PHONY: ocah-format-check
ocah-format-check:
	$(ocah_format_check_files)
	$(call ocah_eda_docker_run, verible-verilog-format --verify $(ocah_format_files))

OCAH_PHONY += ocah-format ocah-format-check

endif
