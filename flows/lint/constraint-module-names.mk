# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_lint_constraint_module_names_mk
ocah_lint_constraint_module_names_mk := 1

include $(patsubst %/,%,$(dir $(lastword $(MAKEFILE_LIST))))/../preamble.mk

## @section Lint (constraint module names)

## Check that every module name in the synthesis, CDC, RDC and lint constraints
## is written through ${MODPREFIX}, cdc_mod, or ${PREFIX} in a lint waiver, so a
## design that renames its modules can set the prefix (no autofix).
.PHONY: ocah-lint-constraint-module-names
ocah-lint-constraint-module-names:
	cd "$(OCAH_ROOT)" && python3 scripts/ci/check_constraint_module_names.py

OCAH_PHONY += ocah-lint-constraint-module-names

endif
