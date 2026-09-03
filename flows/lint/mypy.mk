# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_lint_mypy_mk
ocah_lint_mypy_mk := 1

include $(patsubst %/,%,$(dir $(lastword $(MAKEFILE_LIST))))/../preamble.mk

# Paths to type-check, relative to the repository root. Mirrors ruff.mk's
# PYTHON_PATH; excluded/generated paths are configured in [tool.mypy] instead.
MYPY_PATH ?= tools scripts hw .github

ocah_mypy_check_paths = @for path in $(MYPY_PATH); do \
	[ -e "$(OCAH_ROOT)/$$path" ] || { echo "error: Python path '$$path' does not exist" >&2; exit 1; }; \
done

ifndef OCAH_MYPY_SKIP_UV
MYPY := $(OCAH_UV_RUN) mypy
else
MYPY := mypy
endif

## @section Lint (mypy)

## Type-check first-party Python sources with mypy. No autofix exists for a
## type checker; hand-fix reported issues.
## @param MYPY_PATH=tools Optional space-separated paths; default tools scripts hw .github
.PHONY: ocah-lint-python-mypy
ocah-lint-python-mypy:
	$(ocah_mypy_check_paths)
	$(MYPY) $(MYPY_PATH)

OCAH_PHONY += ocah-lint-python-mypy

endif
