# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_lint_shell_mk
ocah_lint_shell_mk := 1

include $(patsubst %/,%,$(dir $(lastword $(MAKEFILE_LIST))))/../preamble.mk

# shellcheck-py/shfmt-py wrap the real Go/Haskell binaries in a PyPI wheel
# (same idea as this repo's existing clang-format dependency), so both are
# uv-managed like every other Python-fronted tool here.

# Path to lint/format, scoped by filesystem rather than by block. Not named
# PATH=, which would override the shell's own command-search PATH. Empty
# (the default) scopes to the whole repo.
SHELL_PATH ?=

ocah_shell_root := $(if $(SHELL_PATH),$(OCAH_ROOT)/$(SHELL_PATH),$(OCAH_ROOT))

# .sh files under SHELL_PATH, excluding vendor/nonfree, build output, and the
# local uv venv (which vendors its own third-party activation scripts).
ocah_shell_files = $(shell find $(ocah_shell_root) -name '*.sh' \
	-not -path '*/vendor/*' -not -path '*/nonfree/*' \
	-not -path '*/build/*' -not -path '*/build_pio/*' -not -path '*/.cache/*' \
	-not -path '*/.venv/*' 2>/dev/null)

ocah_shell_check_files = @[ -n "$(strip $(ocah_shell_files))" ] || { echo "error: no .sh files under $(if $(SHELL_PATH),$(SHELL_PATH),repo root)" >&2; exit 1; }

# style/info-level findings (e.g. SC2001 sed-vs-substitution, SC2015
# &&/|| idiom, SC2086 word-splitting in already-quoted-variable contexts)
# are left as documented judgment calls rather than mass-rewritten sight
# unseen; warning-and-above is where a finding is plausibly a real bug.
SHELLCHECK_SEVERITY ?= warning

ifndef OCAH_SHELLCHECK_SKIP_UV
SHELLCHECK := $(OCAH_UV_RUN) shellcheck
SHFMT := $(OCAH_UV_RUN) shfmt
else
SHELLCHECK := shellcheck
SHFMT := shfmt
endif

## @section Lint (shellcheck)

## Lint shell scripts with shellcheck (no autofix; hand-fix reported issues).
## @param SHELL_PATH=scripts Optional path to scope the lint; default repo root
## @param OCAH_LINT_SHELLCHECK_EXTRA_FLAGS=-f=gcc Optional extra shellcheck flags (e.g. CI's -f gcc for reviewdog)
.PHONY: ocah-lint-shell
ocah-lint-shell:
	$(ocah_shell_check_files)
	$(SHELLCHECK) --severity=$(SHELLCHECK_SEVERITY) $(OCAH_LINT_SHELLCHECK_EXTRA_FLAGS) $(ocah_shell_files)

OCAH_PHONY += ocah-lint-shell

## @section Format (shfmt)

## Format shell scripts in place with shfmt (2-space indent, matching this
## repo's existing shell style rather than shfmt's tab-indent default).
## @param SHELL_PATH=scripts Optional path to scope formatting; default repo root
.PHONY: ocah-format-shell
ocah-format-shell:
	$(ocah_shell_check_files)
	$(SHFMT) -i 2 -w $(ocah_shell_files)

## Check shell formatting without modifying files (CI-friendly: exit 0 clean, 1 would-reformat).
## @param SHELL_PATH=scripts Optional path to scope the check; default repo root
.PHONY: ocah-format-shell-check
ocah-format-shell-check:
	$(ocah_shell_check_files)
	$(SHFMT) -i 2 -d $(ocah_shell_files)

OCAH_PHONY += ocah-format-shell ocah-format-shell-check

endif
