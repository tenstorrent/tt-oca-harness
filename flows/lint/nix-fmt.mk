# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_lint_nix_fmt_mk
ocah_lint_nix_fmt_mk := 1

include $(patsubst %/,%,$(dir $(lastword $(MAKEFILE_LIST))))/../preamble.mk

# Nix Fmt handles detection of all files automatically, by default, pass to restrict
OCAH_FORMAT_NIX_FILES ?=


## @section Format (nix fmt)

## Format nix infrastructure files using nix-declared formatter (alejandra) - see flake.nix#formatter
## @param OCAH_FORMAT_NIX_FILES='flake.nix ocah_deps.nix' Restrict formatter to these files
.PHONY: ocah-format-nix
ocah-format-nix:
ifndef OCAH_IN_CONTAINER
	$(OCAH_ROOT)/scripts/docker-run.sh nix-fmt -- $(OCAH_FORMAT_NIX_FILES)
else
	# Nix-fmt doesn't work in the OCAH-Container, it uses the NixOS build container
	# Use <ocah_directory> rather than $(OCAH_ROOT) to avoid path-mapping confusion with container
	@echo "Warning: Nix Formatter can't run in the container, please rerun '<ocah_directory>/scripts/docker-run.sh nix-fmt -- $(OCAH_FORMAT_NIX_FILES)' locally" >&2
endif

## Check Nix Infrastructure files formatting without modification
## @param OCAH_FORMAT_NIX_FILES='flake.nix ocah_deps.nix' Restrict format checks to these files
.PHONY: ocah-format-nix-check
ocah-format-nix-check:
ifndef OCAH_IN_CONTAINER
	$(OCAH_ROOT)/scripts/docker-run.sh nix-fmt-check -- $(OCAH_FORMAT_NIX_FILES)
else
	@echo "Warning: Nix Formatter can't run in the OCAH container, please rerun '<ocah_directory>/scripts/docker-run.sh nix-fmt-check -- $(OCAH_FORMAT_NIX_FILES)' locally" >&2
endif

OCAH_PHONY += ocah-format-nix ocah-format-nix-check

endif
