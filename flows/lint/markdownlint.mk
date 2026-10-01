# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_lint_markdownlint_mk
ocah_lint_markdownlint_mk := 1

include $(patsubst %/,%,$(dir $(lastword $(MAKEFILE_LIST))))/../preamble.mk

# Pinned via npx, the same Node-tooling pattern OCAH_ANTORA uses in doc/doc.mk.
# Requires a modern Node (npx's argument parsing breaks on ancient ones; see
# AGENTS.md's toolchain notes if `npx` misbehaves).
OCAH_MARKDOWNLINT ?= npx -y -p markdownlint-cli@0.49.1 markdownlint

# Path to lint/format, scoped by filesystem rather than by block. Not named
# PATH=, which would override the shell's own command-search PATH. Empty
# (the default) scopes to the whole repo. Rule config lives in
# .markdownlint.yml, which -c passes explicitly so it applies regardless of cwd.
MARKDOWN_PATH ?=

ocah_markdown_root := $(if $(MARKDOWN_PATH),$(OCAH_ROOT)/$(MARKDOWN_PATH),$(OCAH_ROOT))

# .md files under MARKDOWN_PATH, excluding vendor/nonfree, the tt-oca-manifest
# submodule (another repo's prose), build output, and
# the local uv/node_modules caches -- none of which are hand-authored here.
ocah_markdown_files = $(shell find $(ocah_markdown_root) -name '*.md' \
	-not -path '*/vendor/*' -not -path '*/nonfree/*' \
	-not -path '*/build/*' -not -path '*/build_ot/*' -not -path '*/build_ot_pio/*' \
	-not -path '*/tools/tt-oca-manifest/*' \
	-not -path '*/.venv/*' -not -path '*/node_modules/*' 2>/dev/null)

ocah_markdown_check_files = @[ -n "$(strip $(ocah_markdown_files))" ] || { echo "error: no .md files under $(if $(MARKDOWN_PATH),$(MARKDOWN_PATH),repo root)" >&2; exit 1; }

## @section Lint (markdownlint)

## Lint Markdown sources with markdownlint (no autofix; use ocah-lint-markdown-fix).
## @param MARKDOWN_PATH=doc Optional path to scope the lint; default repo root
.PHONY: ocah-lint-markdown
ocah-lint-markdown:
	$(ocah_markdown_check_files)
	$(OCAH_MARKDOWNLINT) -c "$(OCAH_ROOT)/.markdownlint.yml" $(ocah_markdown_files)

OCAH_PHONY += ocah-lint-markdown

## Apply markdownlint's autofixes in place. Review the diff before committing --
## structural fixes (heading/list spacing) are safe, but markdownlint can
## misread literal `*` (e.g. multiplication in prose) as emphasis markup and
## "fix" the spacing around it into something that renders wrong.
## @param MARKDOWN_PATH=doc Optional path to scope the fix; default repo root
.PHONY: ocah-lint-markdown-fix
ocah-lint-markdown-fix:
	$(ocah_markdown_check_files)
	$(OCAH_MARKDOWNLINT) -c "$(OCAH_ROOT)/.markdownlint.yml" --fix $(ocah_markdown_files)

OCAH_PHONY += ocah-lint-markdown-fix

endif
