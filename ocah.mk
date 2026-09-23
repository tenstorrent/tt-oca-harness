# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_mk
ocah_mk := 1

ifndef OCAH_ROOT
OCAH_ROOT := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
endif
UV ?= uv

OCAH_PHONY ?=

## @section Environment

## Sync the uv-managed Python environment used by OCAH generation flows.
.PHONY: uv-sync
uv-sync:
	@command -v "$(UV)" >/dev/null 2>&1 || { echo "error: uv is required; see https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }
	@"$(UV)" --directory "$(OCAH_ROOT)" sync

OCAH_PHONY += uv-sync

OCAH_NONFREE_REMOTE ?= git@github.com:tenstorrent/tt-oca-harness-nonfree.git
OCAH_NONFREE_DIR ?= $(OCAH_ROOT)/nonfree
OCAH_ADOPTER_OVERLAY_MK ?=

## @section Optional nonfree components

## Clone the optional nonfree repository with resources that are not open-sourced.
## This step is optional and not required for normal OCAH use.
.PHONY: ocah-nonfree-init
ocah-nonfree-init:
	@test -n "$(OCAH_NONFREE_REMOTE)" || { echo "error: OCAH_NONFREE_REMOTE is not set"; exit 1; }
	@[ -d "$(OCAH_NONFREE_DIR)/.git" ] && echo "nonfree repo already cloned at $(OCAH_NONFREE_DIR)" || git clone "$(OCAH_NONFREE_REMOTE)" "$(OCAH_NONFREE_DIR)"

-include $(OCAH_ROOT)/nonfree/nonfree.mk
-include $(OCAH_ADOPTER_OVERLAY_MK)

OCAH_PHONY += ocah-nonfree-init

## @section Private submodules

# Some submodules live in private repositories: the OCA manifest tooling (packer
# plus the validator library the ROM links against) and, on the virtual-platform
# branches, the harness model. .gitmodules addresses them over SSH, which a
# developer has a key for and a CI runner does not.
#
# The recipe rewrites each SSH URL to HTTPS carrying a token. The rewrite is a
# per-submodule url override rather than a global insteadOf, so the credential
# reaches exactly these repositories and no other github.com fetch, and
# .gitmodules itself is never modified. The HTTPS URL is derived from whatever
# .gitmodules already says, so adding a private submodule is one entry here and
# nothing else.
#
# The token is OCAH_SUBMODULE_TOKEN when that is exported. Otherwise an ambient
# insteadOf that maps git@github.com: onto https://<user>@github.com/ (user, no
# password) is treated as the token, because that form blocks a headless clone.
# Only that mapping is harvested: an insteadOf for another host, or one that
# does not rewrite git@github.com:, is ignored so a third-party forge
# credential is never pasted onto github.com. Developers with an SSH key and
# no such insteadOf keep the .gitmodules URL.
#
# The token is read by the recipe shell and never expanded by make, so it stays
# out of the recipe, out of `make -n` and out of build logs. It is still handed
# to `git config` in argv for an instant, exactly as the nonfree clone above
# hands its own token to `git clone`.
OCAH_PRIVATE_SUBMODULES ?= hw/sys/sep/bootrom/prod/tools/tt-oca-manifest

## Check out the private submodules (OCA manifest tooling, and the VP model where present).
## Uses each .gitmodules SSH URL unless a token is available (see above).
.PHONY: ocah-submodules-init
ocah-submodules-init:
	@set -e; \
	for d in $(OCAH_PRIVATE_SUBMODULES); do \
	  git -C "$(OCAH_ROOT)" config -f .gitmodules --get "submodule.$$d.url" >/dev/null 2>&1 || { \
	    echo "error: $$d is not a submodule of this tree"; exit 1; }; \
	  git -C "$(OCAH_ROOT)" submodule init "$$d"; \
	  token="$${OCAH_SUBMODULE_TOKEN:-}"; \
	  if [ -z "$$token" ]; then \
	    token=$$(git -C "$(OCAH_ROOT)" config --get-regexp '^url\..*\.insteadof' 2>/dev/null | \
	      while read -r key from; do \
	        case "$$from" in git@github.com:*) ;; *) continue ;; esac; \
	        case "$$key" in \
	          url.https://*@github.com/.insteadof) ;; \
	          *) continue ;; \
	        esac; \
	        user=$${key#url.https://}; \
	        user=$${user%%@*}; \
	        case "$$user" in \
	          ''|x-access-token|oauth2) continue ;; \
	        esac; \
	        printf '%s\n' "$$user"; \
	        break; \
	      done); \
	  fi; \
	  if [ -n "$$token" ]; then \
	    url=$$(git -C "$(OCAH_ROOT)" config -f .gitmodules --get "submodule.$$d.url"); \
	    case "$$url" in \
	      git@github.com:*) url="https://x-access-token:$${token}@github.com/$${url#git@github.com:}" ;; \
	    esac; \
	    git -C "$(OCAH_ROOT)" config "submodule.$$d.url" "$$url"; \
	  fi; \
	  GIT_TERMINAL_PROMPT=0 git -C "$(OCAH_ROOT)" submodule update "$$d" \
	    || { echo "error: $$d: submodule update failed (set OCAH_SUBMODULE_TOKEN for a headless checkout)"; exit 1; }; \
	  test -n "$$(ls -A "$(OCAH_ROOT)/$$d" 2>/dev/null)" || { \
	    echo "error: $$d checked out but is empty"; exit 1; }; \
	done

OCAH_PHONY += ocah-submodules-init

## Core hardware collateral and DV firmware build targets.
include $(OCAH_ROOT)/hw/common/regs/regs.mk
include $(OCAH_ROOT)/hw/common/dv/fw/fw.mk
## Documentation build targets (after regs.mk so the register accessors exist).
include $(OCAH_ROOT)/doc/doc.mk
## Open-source lint/synth/format flow targets (slang/verible native-or-fail;
## yosys Docker-by-default; see tools/docker/README.md and
## flows/synth/yosys/README.md).
include $(OCAH_ROOT)/flows/lint/slang.mk
include $(OCAH_ROOT)/flows/lint/verilator.mk
include $(OCAH_ROOT)/flows/lint/verible.mk
include $(OCAH_ROOT)/flows/lint/clang-format.mk
include $(OCAH_ROOT)/flows/lint/ruff.mk
include $(OCAH_ROOT)/flows/lint/mypy.mk
include $(OCAH_ROOT)/flows/lint/codespell.mk
include $(OCAH_ROOT)/flows/lint/markdownlint.mk
include $(OCAH_ROOT)/flows/lint/vale.mk
include $(OCAH_ROOT)/flows/lint/yamllint.mk
include $(OCAH_ROOT)/flows/lint/tomllint.mk
include $(OCAH_ROOT)/flows/lint/checkmake.mk
include $(OCAH_ROOT)/flows/lint/shell.mk
include $(OCAH_ROOT)/flows/lint/pre-commit.mk
include $(OCAH_ROOT)/flows/lint/tclint.mk
include $(OCAH_ROOT)/flows/lint/nix-fmt.mk
include $(OCAH_ROOT)/flows/synth/yosys/yosys.mk

## Generate the filelist for the OCAH repository.
## Optional overrides: EXTRA_TARGETS (bender -t flags), FLIST_OUT (output path).
.PHONY: generate_filelist
generate_filelist:
	@echo "Generating HW filelist for the OCAH repository"
	bender script flist-plus $(EXTRA_TARGETS) > $(if $(FLIST_OUT),$(FLIST_OUT),$(OCAH_ROOT)/hw_filelist.f)
	@echo "Generated $(if $(FLIST_OUT),$(FLIST_OUT),$(OCAH_ROOT)/hw_filelist.f)"

OCAH_PHONY += generate_filelist

HELP_TITLE = "OCAH Make Targets"
HELP_DESCRIPTION = "Regeneration and helper targets for the OCA Harness repository"
include $(OCAH_ROOT)/help.mk

endif
