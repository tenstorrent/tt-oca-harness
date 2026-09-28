# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_lint_sv_comments_mk
ocah_lint_sv_comments_mk := 1

include $(patsubst %/,%,$(dir $(lastword $(MAKEFILE_LIST))))/../preamble.mk

## @section Lint (SystemVerilog comments)

## Check the // header and parameter/port clauses of every RTL source the RTL
## Modules Reference documents (no autofix).
.PHONY: ocah-lint-sv-comments
ocah-lint-sv-comments:
	cd "$(OCAH_ROOT)" && python3 tools/doc/check_sv_comments.py --root .

OCAH_PHONY += ocah-lint-sv-comments

endif
