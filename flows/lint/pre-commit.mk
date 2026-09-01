# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_pre_commit_mk
ocah_pre_commit_mk := 1

OCAH_PRE_COMMIT_DIR := $(patsubst %/,%,$(dir $(lastword $(MAKEFILE_LIST))))
include $(OCAH_PRE_COMMIT_DIR)/../common.mk

## @section Git hooks (pre-commit)

## Install the optional check-only pre-commit hook in this worktree.
.PHONY: ocah-hooks-install
ocah-hooks-install:
	@hook=$$(git -C "$(OCAH_ROOT)" rev-parse --git-path hooks/pre-commit); \
	if [ -e "$$hook" ] && ! grep -q 'hook-impl' "$$hook"; then \
		echo "error: refusing to replace unmanaged pre-commit hook at $$hook" >&2; \
		exit 1; \
	fi
	$(UV) --directory "$(OCAH_ROOT)" run --locked pre-commit install --install-hooks --hook-type pre-commit

## Run the configured checks on staged files without installing the hook.
.PHONY: ocah-hooks-run
ocah-hooks-run:
	$(UV) --directory "$(OCAH_ROOT)" run --locked pre-commit run

## Run the configured checks on every eligible tracked file.
.PHONY: ocah-hooks-run-all
ocah-hooks-run-all:
	$(UV) --directory "$(OCAH_ROOT)" run --locked pre-commit run --all-files

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
		$(UV) --directory "$(OCAH_ROOT)" run --locked pre-commit uninstall --hook-type pre-commit; \
	fi

OCAH_PHONY += ocah-hooks-install ocah-hooks-run ocah-hooks-run-all ocah-hooks-uninstall

endif
