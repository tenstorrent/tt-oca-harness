# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_lint_nix_fmt_mk
ocah_lint_nix_fmt_mk := 1

include $(patsubst %/,%,$(dir $(lastword $(MAKEFILE_LIST))))/../preamble.mk

## @section Format (nix fmt)

## Format nix infrastructure files using nix-declared formatter (alejandra) - see flake.nix#formatter
.PHONY: ocah-format-nix
ocah-format-nix:
	$(OCAH_ROOT)/scripts/docker-run.sh nix-fmt

## Check Nix Infrastructure files formatting without modification
ocah-format-nix-check:
	$(OCAH_ROOT)/scripts/docker-run.sh nix-fmt-check

OCAH_PHONY += ocah-format-nix ocah-format-nix-check

endif
