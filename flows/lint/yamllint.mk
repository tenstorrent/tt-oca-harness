# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_lint_yamllint_mk
ocah_lint_yamllint_mk := 1

include $(patsubst %/,%,$(dir $(lastword $(MAKEFILE_LIST))))/../preamble.mk

# Path to lint, scoped by filesystem rather than by block. Not named PATH=,
# which would override the shell's own command-search PATH.
YAML_PATH ?= .

# .yml/.yaml files under YAML_PATH, found relative to OCAH_ROOT (not as
# absolute paths). yamllint's `ignore:` patterns are gitignore-style and
# rooted at the invocation directory; a multi-segment pattern like
# `hw/ip/i3ccore_wrap/dv/tb/yaml/` (see .yamllint.yml) silently never matches
# an absolute path, since that path's root has nothing to do with the repo
# root. Excludes (vendor/nonfree/build output, generated issue-curation
# lockfiles, Bender's own YAML dialect, and the i3ccore cross-file-anchor
# test-list format) live in .yamllint.yml's `ignore:` key so both this Make
# target and any future direct `yamllint -c .yamllint.yml` invocation see
# the same scope -- which only works as long as the paths handed to
# yamllint stay relative to $(OCAH_ROOT), matching the `--directory` below
# (which is also what makes those relative paths resolve at all).
ocah_yaml_files = $(shell cd $(OCAH_ROOT) && find $(YAML_PATH) \( -name '*.yml' -o -name '*.yaml' \) 2>/dev/null)

ocah_yaml_check_files = @[ -n "$(strip $(ocah_yaml_files))" ] || { echo "error: no .yml/.yaml files under $(YAML_PATH)" >&2; exit 1; }

ifndef OCAH_YAMLLINT_SKIP_UV
YAMLLINT := $(OCAH_UV_RUN) yamllint
else
YAMLLINT := yamllint
endif

## @section Lint (yamllint)

## Lint YAML sources with yamllint (no autofix; hand-fix reported violations).
## @param YAML_PATH=.github Optional path to scope the lint; default repo root
.PHONY: ocah-lint-yaml
ocah-lint-yaml:
	$(ocah_yaml_check_files)
	$(YAMLLINT) -c "$(OCAH_ROOT)/.yamllint.yml" $(ocah_yaml_files)

OCAH_PHONY += ocah-lint-yaml

endif
