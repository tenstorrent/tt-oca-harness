# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_lint_bender_sources_mk
ocah_lint_bender_sources_mk := 1

include $(patsubst %/,%,$(dir $(lastword $(MAKEFILE_LIST))))/../preamble.mk

## @section Lint (Bender sources)

## Reject a source path listed twice in one Bender.yml when both targets can
## match. Bender would keep only the first match, so the file's compile
## position would depend on the targets passed.
.PHONY: ocah-lint-bender-sources
ocah-lint-bender-sources:
	cd "$(OCAH_ROOT)" && python3 scripts/ci/check_bender_sources.py "$(OCAH_ROOT)"

OCAH_PHONY += ocah-lint-bender-sources

endif
