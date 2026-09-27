# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_lint_tomllint_mk
ocah_lint_tomllint_mk := 1

include $(patsubst %/,%,$(dir $(lastword $(MAKEFILE_LIST))))/../preamble.mk

# Path to lint, scoped by filesystem rather than by block. Not named PATH=,
# which would override the shell's own command-search PATH. Empty (the
# default) scopes to the whole repo. tomllint takes no config file (there is
# nothing to ignore by), so exclusions live in this find call rather than in
# a sibling config, unlike yamllint's .yamllint.yml.
TOML_PATH ?=

ocah_toml_root := $(if $(TOML_PATH),$(OCAH_ROOT)/$(TOML_PATH),$(OCAH_ROOT))

# .toml files under TOML_PATH, excluding vendor/nonfree, build output, and the
# local uv venv (which vendors its own third-party Cargo.toml resources).
ocah_toml_files = $(shell find $(ocah_toml_root) -name '*.toml' \
	-not -path '*/vendor/*' -not -path '*/nonfree/*' \
	-not -path '*/build/*' -not -path '*/build_pio/*' \
	-not -path '*/.venv/*' 2>/dev/null)

ocah_toml_check_files = @[ -n "$(strip $(ocah_toml_files))" ] || { echo "error: no .toml files under $(if $(TOML_PATH),$(TOML_PATH),repo root)" >&2; exit 1; }

ifndef OCAH_TOMLLINT_SKIP_UV
TOMLLINT := $(OCAH_UV_RUN) tomllint
else
TOMLLINT := tomllint
endif

## @section Lint (tomllint)

## Check TOML syntax with tomllint (basic syntactic errors only -- it carries
## no style rules and no autofix, unlike yamllint/markdownlint). Mainly
## catches malformed DV testlists and sim configs (hw/**/dv/**/*.toml) before
## the runner that reads them fails with a less legible error.
## @param TOML_PATH=hw/sys/smc/dv/testlists Optional path to scope the check; default repo root
.PHONY: ocah-lint-toml
ocah-lint-toml:
	$(ocah_toml_check_files)
	$(TOMLLINT) $(ocah_toml_files)

OCAH_PHONY += ocah-lint-toml

endif
