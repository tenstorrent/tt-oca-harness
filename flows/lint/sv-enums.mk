# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_lint_sv_enums_mk
ocah_lint_sv_enums_mk := 1

include $(patsubst %/,%,$(dir $(lastword $(MAKEFILE_LIST))))/../preamble.mk

## @section Lint (SystemVerilog enums)

## Check that every enum member in the SystemVerilog sources outside vendor/
## and regs/gen/ is UPPER_SNAKE_CASE and every enum type is lower_snake_case
## with an _e suffix (no autofix).
.PHONY: ocah-lint-sv-enums
ocah-lint-sv-enums:
	cd "$(OCAH_ROOT)" && git ls-files -z -- '*.sv' '*.svh' '*.v' '*.vh' \
		':!vendor/**' ':!**/regs/gen/**' | \
		xargs -0 $(OCAH_UV_RUN) python scripts/ci/check_sv_enums.py

OCAH_PHONY += ocah-lint-sv-enums

endif
