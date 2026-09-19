# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_format_clang_format_mk
ocah_format_clang_format_mk := 1

include $(patsubst %/,%,$(dir $(lastword $(MAKEFILE_LIST))))/../preamble.mk

# Path to format, scoped by filesystem or by block. Not named PATH=,
# which would override the shell's own command-search PATH.
ifneq ($(BLOCK),)
FORMAT_C_PATH ?= hw/sys/$(BLOCK)
else
FORMAT_C_PATH ?= hw
endif

# Git submodules carry upstream code, which must not be reformatted: it would show
# up as local modifications in the submodule and collide with the next update.
# Read from .gitmodules rather than listing paths so a new submodule is covered
# without editing this file, and so it also resolves when none are checked out.
ocah_format_c_submodules = $(shell git config --file $(OCAH_ROOT)/.gitmodules --get-regexp '\.path$$' 2>/dev/null | awk '{print $$2}')
ocah_format_c_exclude_submodules = $(foreach p,$(ocah_format_c_submodules),-not -path '$(OCAH_ROOT)/$(p)/*')

# .c/.h/.cpp files under FORMAT_C_PATH, excluding build output, vendored
# third-party sources, and generated register headers (see hw/common/regs/).
# 'build*' also covers the SEP boot ROM's variant dirs (build_ot/, build_ot_pio/,
# build_release/), which hold generated sources.
ocah_format_c_files = $(shell find $(OCAH_ROOT)/$(FORMAT_C_PATH) \( -name '*.c' -o -name '*.h' -o -name '*.cpp' \) -not -path '*/build/*' -not -path '*/build_*/*' -not -path '*/vendor/*' -not -path '*/regs/gen/*' $(ocah_format_c_exclude_submodules) 2>/dev/null)

ocah_format_c_check_files = @[ -n "$(strip $(ocah_format_c_files))" ] || { echo "error: no .c/.h/.cpp files under $(FORMAT_C_PATH)" >&2; exit 1; }

ifndef OCAH_CLANG_FORMAT_SKIP_UV
CLANG_FORMAT := $(OCAH_UV_RUN) clang-format
else
CLANG_FORMAT := clang-format
endif

## @section Format (clang-format)

## Format C/C++ sources in place with clang-format (style: .clang-format).
## @param FORMAT_C_PATH=hw/sys/smc Optional path to scope formatting; default hw
## @param BLOCK=smu Shorthand for the above, for consistency (FORMAT_C_PATH?=hw/sys/BLOCK if set)
.PHONY: ocah-format-c
ocah-format-c:
	$(ocah_format_c_check_files)
	$(CLANG_FORMAT) -style=file -i $(ocah_format_c_files)

## Check C/C++ formatting without modifying files (CI-friendly: exit 0 clean, 1 would-reformat).
## @param FORMAT_C_PATH=hw/sys/smc Optional path to scope the check; default hw
## @param BLOCK=smu Shorthand for the above, for consistency (FORMAT_C_PATH?=hw/sys/BLOCK if set)
.PHONY: ocah-format-c-check
ocah-format-c-check:
	$(ocah_format_c_check_files)
	$(CLANG_FORMAT) -style=file --dry-run --Werror $(ocah_format_c_files)

OCAH_PHONY += ocah-format-c ocah-format-c-check

endif
