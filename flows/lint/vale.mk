# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_lint_vale_mk
ocah_lint_vale_mk := 1

include $(patsubst %/,%,$(dir $(lastword $(MAKEFILE_LIST))))/../common.mk

# Vale is a Go binary with no PyPI wheel; CI fetches a pinned release the
# same way lint-make (checkmake) does. Locally: a release binary from
# https://github.com/vale-cli/vale/releases, or `go install
# github.com/vale-cli/vale/cmd/vale@v3.15.2`.
#
# Vale's own AsciiDoc support shells out to a real `asciidoctor` for every
# .adoc file; without one on PATH, that's a hard runtime error partway
# through the file list, not a skipped file (`gem install asciidoctor`,
# same as doc.mk's PDF/HTML builds).
OCAH_VALE ?= vale

# Extra CLI flags, e.g. `--output=<template>` to switch report shape for
# CI's reviewdog hand-off (see .github/workflows/lint.yml's lint-vale job).
# Local runs want none of that -- plain CLI output straight to the terminal.
OCAH_VALE_FLAGS ?=

# Path to lint, scoped by filesystem rather than by block. Not named PATH=,
# which would override the shell's own command-search PATH. Empty (the
# default) scopes to the whole repo. Rules live under styles/OCAH/,
# selected by .vale.ini, which --config passes explicitly so it applies
# regardless of cwd.
VALE_PATH ?=

ocah_vale_root := $(if $(VALE_PATH),$(OCAH_ROOT)/$(VALE_PATH),$(OCAH_ROOT))

# .adoc/.md prose under VALE_PATH, excluding vendor/nonfree, build output,
# generated register collateral (regenerated from RDL; a prose fix there is
# reverted by the next regen-regs run, so the real fix belongs in the RDL
# desc/name upstream, not the generated adoc -- same reasoning as
# [tool.codespell]'s skip list), the doc/*/modules/ Antora staging copies
# (gitignored build output of doc/stage-docs.sh, not source -- linting them
# would just double-report every finding under a second path), the
# tt-oca-manifest submodule (another repo's prose, fixable only by a PR there,
# so a finding in it cannot gate this repo -- same reasoning as vendor/), and
# the local uv/node_modules caches.
ocah_vale_files = $(shell find $(ocah_vale_root) \( -name '*.adoc' -o -name '*.md' \) \
	-not -path '*/vendor/*' -not -path '*/nonfree/*' \
	-not -path '*/build/*' -not -path '*/build_ot/*' -not -path '*/build_ot_pio/*' \
	-not -path '*/regs/gen/*' -not -path '*/doc/*/modules/*' \
	-not -path '*/tools/tt-oca-manifest/*' \
	-not -path '*/.venv/*' -not -path '*/node_modules/*' 2>/dev/null)

ocah_vale_check_files = @[ -n "$(strip $(ocah_vale_files))" ] || { echo "error: no .adoc/.md files under $(if $(VALE_PATH),$(VALE_PATH),repo root)" >&2; exit 1; }

## @section Lint (Vale)

## Check documentation prose with Vale (no autofix -- the CLI has none;
## a finding names the correct value in its message, but applying it is a
## manual edit). Rules live in styles/OCAH/; see that directory's
## Acronyms.yml and styles/config/scripts/AcronymDefinitions.tengo.
## @param VALE_PATH=doc Optional path to scope the check; default repo root
.PHONY: ocah-lint-vale
ocah-lint-vale:
	$(ocah_vale_check_files)
	$(call ocah_require_host_tool,$(OCAH_VALE),curl -fsSL -o vale.tar.gz https://github.com/vale-cli/vale/releases/download/v3.15.2/vale_3.15.2_Linux_64-bit.tar.gz && tar xzf vale.tar.gz vale)
	@# Silenced (@): Make's own recipe-echo goes to stdout, same stream as
	@# Vale's --output=<template> findings. CI's OCAH_VALE_FLAGS picks the
	@# rdjsonl template for reviewdog, which requires every stdout line to
	@# be a JSON object; an unsilenced echo of this command line would be
	@# the first line of that file and break the parse.
	@$(OCAH_VALE) $(OCAH_VALE_FLAGS) --config "$(OCAH_ROOT)/.vale.ini" $(ocah_vale_files)

OCAH_PHONY += ocah-lint-vale

endif
