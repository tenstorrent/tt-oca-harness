# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_lint_ruff_mk
ocah_lint_ruff_mk := 1

include $(patsubst %/,%,$(dir $(lastword $(MAKEFILE_LIST))))/../preamble.mk

# Paths to lint or format, relative to the repository root. These are the
# first-party Python roots; generated, vendored, and transient paths are
# excluded in pyproject.toml. Override with a space-separated subset.
PYTHON_PATH ?= tools scripts hw .github virtual_platform

ocah_python_check_paths = @for path in $(PYTHON_PATH); do \
	[ -e "$(OCAH_ROOT)/$$path" ] || { echo "error: Python path '$$path' does not exist" >&2; exit 1; }; \
done

ifndef OCAH_RUFF_SKIP_UV
RUFF := $(OCAH_UV_RUN) ruff
else
RUFF := ruff
endif

## @section Lint (ruff)

## Lint first-party Python sources with Ruff without modifying files.
## @param PYTHON_PATH=tools Optional space-separated paths; default tools scripts hw .github virtual_platform
.PHONY: ocah-lint-python
ocah-lint-python:
	$(ocah_python_check_paths)
	$(RUFF) check $(OCAH_LINT_RUFF_EXTRA_FLAGS) $(PYTHON_PATH)

## Apply Ruff's safe lint fixes to first-party Python sources.
## @param PYTHON_PATH=tools Optional space-separated paths; default tools scripts hw .github virtual_platform
.PHONY: ocah-lint-python-fix
ocah-lint-python-fix:
	$(ocah_python_check_paths)
	$(RUFF) check $(OCAH_LINT_RUFF_EXTRA_FLAGS) --fix $(PYTHON_PATH)


## @section Format (ruff)

## Format first-party Python sources in place with Ruff.
## @param PYTHON_PATH=tools Optional space-separated paths; default tools scripts hw .github virtual_platform
.PHONY: ocah-format-python
ocah-format-python:
	$(ocah_python_check_paths)
	$(RUFF) format $(OCAH_FORMAT_RUFF_EXTRA_FLAGS) $(PYTHON_PATH)

## Check Python formatting without modifying files.
## @param PYTHON_PATH=tools Optional space-separated paths; default tools scripts hw .github virtual_platform
.PHONY: ocah-format-python-check
ocah-format-python-check:
	$(ocah_python_check_paths)
	$(RUFF) format $(OCAH_FORMAT_RUFF_EXTRA_FLAGS) --check $(PYTHON_PATH)

OCAH_PHONY += ocah-lint-python ocah-lint-python-fix
OCAH_PHONY += ocah-format-python ocah-format-python-check

endif
