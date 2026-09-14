# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_pre_commit_mk
ocah_pre_commit_mk := 1

include $(patsubst %/,%,$(dir $(lastword $(MAKEFILE_LIST))))/../preamble.mk

ifndef OCAH_PRE_COMMIT_SKIP_UV
PRE_COMMIT := $(OCAH_UV_RUN) pre-commit
else
PRE_COMMIT := pre-commit
endif

## @section Git hooks (pre-commit)

## Install the optional check-only pre-commit hook in this worktree.
.PHONY: ocah-hooks-install
ocah-hooks-install:
	@hook=$$(git -C "$(OCAH_ROOT)" rev-parse --git-path hooks/pre-commit); \
	if [ -e "$$hook" ] && ! grep -q 'hook-impl' "$$hook"; then \
		echo "error: refusing to replace unmanaged pre-commit hook at $$hook" >&2; \
		exit 1; \
	fi
	$(PRE_COMMIT) install --install-hooks --hook-type pre-commit

## Run the configured checks on staged files without installing the hook.
.PHONY: ocah-hooks-run
ocah-hooks-run:
	$(PRE_COMMIT) run

## Run the configured checks on every eligible tracked file.
.PHONY: ocah-hooks-run-all
ocah-hooks-run-all:
	$(PRE_COMMIT) run --all-files

## Remove the optional pre-commit hook installed in this worktree.
.PHONY: ocah-hooks-uninstall
ocah-hooks-uninstall:
	@hook=$$(git -C "$(OCAH_ROOT)" rev-parse --git-path hooks/pre-commit); \
	if [ ! -e "$$hook" ]; then \
		echo "pre-commit hook is not installed"; \
	elif ! grep -q 'hook-impl' "$$hook"; then \
		echo "error: refusing to remove unmanaged pre-commit hook at $$hook" >&2; \
		exit 1; \
	else \
		$(PRE_COMMIT) uninstall --hook-type pre-commit; \
	fi

OCAH_PHONY += ocah-hooks-install ocah-hooks-run ocah-hooks-run-all ocah-hooks-uninstall

endif
