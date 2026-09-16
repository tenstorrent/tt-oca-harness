# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_lint_checkmake_mk
ocah_lint_checkmake_mk := 1

include $(patsubst %/,%,$(dir $(lastword $(MAKEFILE_LIST))))/../common.mk

# checkmake is a Go binary with no PyPI wheel; CI fetches a pinned release
# (see .github/workflows/lint.yml's setup-tools) the same way lint-sv-slang
# fetches slang. Locally: `go install
# github.com/checkmake/checkmake/cmd/checkmake@v0.3.2` or a release binary
# from https://github.com/checkmake/checkmake/releases.
OCAH_CHECKMAKE ?= checkmake

# Path to lint, scoped by filesystem rather than by block. Not named PATH=,
# which would override the shell's own command-search PATH. Empty (the
# default) scopes to the whole repo. Rule config lives in checkmake.ini
# (see it for why minphony is disabled), passed explicitly via --config.
MAKEFILE_PATH ?=

ocah_checkmake_root := $(if $(MAKEFILE_PATH),$(OCAH_ROOT)/$(MAKEFILE_PATH),$(OCAH_ROOT))

# Makefile/*.mk files under MAKEFILE_PATH, excluding vendor/nonfree, build
# output, and the local uv venv -- none of which are hand-authored here.
ocah_checkmake_files = $(shell find $(ocah_checkmake_root) \( -name '*.mk' -o -name 'Makefile' \) \
	-not -path '*/vendor/*' -not -path '*/nonfree/*' \
	-not -path '*/build/*' -not -path '*/build_ot/*' -not -path '*/build_ot_pio/*' \
	-not -path '*/.venv/*' 2>/dev/null)

ocah_checkmake_check_files = @[ -n "$(strip $(ocah_checkmake_files))" ] || { echo "error: no Makefile/*.mk files under $(if $(MAKEFILE_PATH),$(MAKEFILE_PATH),repo root)" >&2; exit 1; }

# One violation per line as `file:line: rule: message`, in place of
# checkmake's default multi-line table -- both so it reads like every other
# tool's output here and so CI can hand it to reviewdog with a plain efm.
OCAH_CHECKMAKE_FORMAT := {{.FileName}}:{{.LineNumber}}: {{.Rule}}: {{.Violation}}

## @section Lint (checkmake)

## Lint Makefiles with checkmake (no autofix; hand-fix reported violations).
## Report-only in CI: maxbodylength/phonydeclared/uniquetargets all have
## false-positive modes against conventions this repo relies on deliberately
## (long multi-step recipe bodies, the deferred OCAH_PHONY += ... accumulator
## instead of an inline .PHONY per file, and legitimate pattern-rule/ifeq
## target overloads) -- read each finding rather than reflexively trusting it.
## @param MAKEFILE_PATH=flows Optional path to scope the lint; default repo root
.PHONY: ocah-lint-make
ocah-lint-make:
	$(ocah_checkmake_check_files)
	$(call ocah_require_host_tool,$(OCAH_CHECKMAKE),go install github.com/checkmake/checkmake/cmd/checkmake@v0.3.2)
	$(OCAH_CHECKMAKE) --config "$(OCAH_ROOT)/checkmake.ini" --format '$(OCAH_CHECKMAKE_FORMAT)' $(ocah_checkmake_files)

OCAH_PHONY += ocah-lint-make

endif
