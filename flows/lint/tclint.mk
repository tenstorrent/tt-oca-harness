# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_lint_tclint_mk
ocah_lint_tclint_mk := 1

include $(patsubst %/,%,$(dir $(lastword $(MAKEFILE_LIST))))/../preamble.mk

# Path to lint/format, scoped by filesystem rather than by block. Not named
# PATH=, which would override the shell's own command-search PATH. Empty
# (the default) scopes to the whole repo.
TCL_PATH ?=

ocah_tcl_root := $(if $(TCL_PATH),$(OCAH_ROOT)/$(TCL_PATH),$(OCAH_ROOT))

# .tcl files under TCL_PATH, excluding build output, the local uv venv, and
# vendored third-party sources.
ocah_tcl_files = $(shell find $(ocah_tcl_root) -name '*.tcl' -not -path '*/build/*' -not -path '*/.venv/*' -not -path '*/vendor/*' 2>/dev/null)

ocah_tcl_check_files = @[ -n "$(strip $(ocah_tcl_files))" ] || { echo "error: no .tcl files under $(if $(TCL_PATH),$(TCL_PATH),repo root)" >&2; exit 1; }

ifndef OCAH_TCLINT_SKIP_UV
TCLINT = $(OCAH_UV_RUN) tclint
TCLFMT = $(OCAH_UV_RUN) tclfmt
else
TCLINT = tclint
TCLFMT = tclfmt
endif

## @section Lint (tclint)

## Lint Tcl sources with tclint (no autofix; hand-fix reported violations).
## Style checks are left to `ocah-format-tcl` (tclfmt); only correctness
## rules and line-length (which tclfmt can't yet autofix) are enforced here.
## @param TCL_PATH=flows/synth Optional path to scope the lint; default repo root
.PHONY: ocah-lint-tcl
ocah-lint-tcl:
	$(ocah_tcl_check_files)
	$(TCLINT) --no-check-style --style-line-length 100 $(ocah_tcl_files)

OCAH_PHONY += ocah-lint-tcl

## @section Format (tclfmt)

## Format Tcl sources in place with tclfmt.
## @param TCL_PATH=flows/synth Optional path to scope formatting; default repo root
.PHONY: ocah-format-tcl
ocah-format-tcl:
	$(ocah_tcl_check_files)
	$(TCLFMT) --in-place --spaces-in-braces $(ocah_tcl_files)

## Check Tcl formatting without modifying files (CI-friendly: exit 0 clean, 1 would-reformat).
## @param TCL_PATH=flows/synth Optional path to scope the check; default repo root
.PHONY: ocah-format-tcl-check
ocah-format-tcl-check:
	$(ocah_tcl_check_files)
	$(TCLFMT) --check --spaces-in-braces $(ocah_tcl_files)

OCAH_PHONY += ocah-format-tcl ocah-format-tcl-check

endif
