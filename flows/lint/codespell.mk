# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_lint_codespell_mk
ocah_lint_codespell_mk := 1

include $(patsubst %/,%,$(dir $(lastword $(MAKEFILE_LIST))))/../preamble.mk

# Path to spell-check, scoped by filesystem rather than by block. Not named
# PATH=, which would override the shell's own command-search PATH. Empty
# (the default) scopes to the whole repo. Skip/ignore lists live in
# [tool.codespell] in pyproject.toml, which codespell auto-discovers.
CODESPELL_PATH ?= .

ifndef OCAH_CODESPELL_SKIP_UV
CODESPELL := $(OCAH_UV_RUN) codespell
else
CODESPELL := codespell
endif

## @section Lint (codespell)

## Check spelling with codespell (no autofix; use ocah-lint-spelling-fix).
## @param CODESPELL_PATH=doc Optional path to scope the check; default repo root
.PHONY: ocah-lint-spelling
ocah-lint-spelling:
	$(CODESPELL) $(CODESPELL_PATH)

## Apply codespell's suggested fixes in place. Words with more than one
## candidate fix are left unmodified (and still reported) -- resolve those
## by hand, then review the diff before committing (see CONTRIBUTING.md).
## @param CODESPELL_PATH=doc Optional path to scope the fix; default repo root
.PHONY: ocah-lint-spelling-fix
ocah-lint-spelling-fix:
	$(CODESPELL) --write-changes $(CODESPELL_PATH)

OCAH_PHONY += ocah-lint-spelling ocah-lint-spelling-fix

endif
