# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_lint_sv_enum_members_mk
ocah_lint_sv_enum_members_mk := 1

include $(patsubst %/,%,$(dir $(lastword $(MAKEFILE_LIST))))/../preamble.mk

## @section Lint (SystemVerilog enum members)

## Check that every enum member in the SystemVerilog sources outside vendor/
## and regs/gen/ is UPPER_SNAKE_CASE (no autofix).
.PHONY: ocah-lint-sv-enum-members
ocah-lint-sv-enum-members:
	cd "$(OCAH_ROOT)" && git ls-files -z -- '*.sv' '*.svh' '*.v' '*.vh' \
		':!vendor/**' ':!**/regs/gen/**' | \
		xargs -0 $(OCAH_UV_RUN) python scripts/ci/check_sv_enum_members.py

OCAH_PHONY += ocah-lint-sv-enum-members

endif
