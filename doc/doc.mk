# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_doc_mk
ocah_doc_mk := 1

# Common documentation build plumbing. Product-specific targets live in
# doc/<product>/doc.mk (TRM, Integrator Guide, etc.) and reuse these toolchain
# knobs/helpers.

# Global knobs.
OCAH_DOC_DIR ?= $(OCAH_ROOT)/doc
# Documentation tools are expected on PATH. The project Docker image provides
# Node/npm for Antora and asciidoctor-pdf for PDF builds.
OCAH_ANTORA ?= npx -y -p @antora/cli@3.1 -p @antora/site-generator@3.1 antora
OCAH_ASCIIDOCTOR_PDF ?= asciidoctor-pdf
OCAH_DOC_PDF_THEME ?= $(OCAH_DOC_DIR)/theme.yml
OCAH_DOC_PDF_THEMESDIR ?= $(OCAH_DOC_DIR)
OCAH_CSV_TO_ADOC := python3 $(OCAH_ROOT)/tools/doc/csvadoc.py
OCAH_DOC_REGEN_REGS ?= 1
# Optional Antora --url override (used by GitHub Pages deploy for nested products).
OCAH_DOC_SITE_URL ?=
OCAH_GHPAGES_DIR ?= $(OCAH_DOC_DIR)/_build/gh-pages
OCAH_GHPAGES_BASE_URL ?= https://tenstorrent.github.io/tt-oca
OCAH_GHPAGES_INDEX ?= $(OCAH_DOC_DIR)/gh-pages-index.html

# Reuse the reg flow's per-block adoc accessor over every block (regs.mk filters
# OCAH_REGEN_REG_ADOC by TARGET; docs want all blocks). Depending on these would
# couple the doc build to blocks with known Plan A regen gaps, so the setup step
# regenerates them best-effort (-k) instead and stages whatever exists.
OCAH_DOC_REG_ADOC := $(foreach b,$(OCAH_REG_BLOCKS),$(call ocah_reg_adoc_target,$(b)))

# The one genuinely new bit of discovery: the doc page sources (analogous to
# discover.mk's ocah_reg_dirs glob).
OCAH_DOC_PAGE_DIRS := $(wildcard $(OCAH_ROOT)/hw/ip/*/doc $(OCAH_ROOT)/hw/ip/*/*/doc $(OCAH_ROOT)/hw/sys/*/doc)

## @section Documentation

## Regenerate register docs best-effort for documentation products.
.PHONY: ocah-doc-reg-setup
ifeq ($(OCAH_DOC_REGEN_REGS),1)
ocah-doc-reg-setup:
	@-$(MAKE) --no-print-directory -k -C "$(OCAH_ROOT)" ocah-regen-regs-adoc
	@-$(MAKE) --no-print-directory -k -C "$(OCAH_ROOT)" ocah-regen-regs-html
else
ocah-doc-reg-setup:
	@true
endif

# Product makefrags.
-include $(OCAH_DOC_DIR)/trm/doc.mk
-include $(OCAH_DOC_DIR)/integrator/doc.mk

## Compatibility aliases: default doc-* targets build the TRM.
.PHONY: ocah-doc-setup ocah-doc-html ocah-doc-pdf ocah-doc-serve ocah-doc-clean
ocah-doc-setup: ocah-doc-trm-setup
ocah-doc-html: ocah-doc-trm-html
ocah-doc-pdf: ocah-doc-trm-pdf
ocah-doc-serve: ocah-doc-trm-serve
ocah-doc-clean: ocah-doc-trm-clean ocah-doc-integrator-clean
	@rm -rf "$(OCAH_GHPAGES_DIR)"

## Stage TRM + Integrator HTML under doc/_build/gh-pages/ with a landing page.
.PHONY: ocah-doc-stage-ghpages
ocah-doc-stage-ghpages:
	@test -d "$(OCAH_TRM_BUILD)/html_antora" || { \
		echo "error: missing TRM HTML at $(OCAH_TRM_BUILD)/html_antora"; \
		echo "run: make ocah-doc-trm-html OCAH_DOC_SITE_URL=$(OCAH_GHPAGES_BASE_URL)/trm"; \
		exit 1; \
	}
	@test -d "$(OCAH_INTEGRATOR_BUILD)/html_antora" || { \
		echo "error: missing Integrator HTML at $(OCAH_INTEGRATOR_BUILD)/html_antora"; \
		echo "run: make ocah-doc-integrator-html OCAH_DOC_SITE_URL=$(OCAH_GHPAGES_BASE_URL)/integrator"; \
		exit 1; \
	}
	@test -f "$(OCAH_GHPAGES_INDEX)" || { echo "error: missing $(OCAH_GHPAGES_INDEX)"; exit 1; }
	@rm -rf "$(OCAH_GHPAGES_DIR)"
	@mkdir -p "$(OCAH_GHPAGES_DIR)/trm" "$(OCAH_GHPAGES_DIR)/integrator"
	@cp -a "$(OCAH_TRM_BUILD)/html_antora/." "$(OCAH_GHPAGES_DIR)/trm/"
	@cp -a "$(OCAH_INTEGRATOR_BUILD)/html_antora/." "$(OCAH_GHPAGES_DIR)/integrator/"
	@cp "$(OCAH_GHPAGES_INDEX)" "$(OCAH_GHPAGES_DIR)/index.html"
	@touch "$(OCAH_GHPAGES_DIR)/.nojekyll"
	@echo "Staged GitHub Pages tree at $(OCAH_GHPAGES_DIR)"

## Build both products (with Pages site URLs), stage, and push to gh-pages.
.PHONY: ocah-doc-deploy-ghpages
ocah-doc-deploy-ghpages:
	@command -v uv >/dev/null 2>&1 || { \
		echo "error: uv is required to deploy GitHub Pages (ghp-import)."; \
		echo "install uv, or see https://docs.astral.sh/uv/"; \
		exit 1; \
	}
	@$(MAKE) --no-print-directory -C "$(OCAH_ROOT)" \
		ocah-doc-trm-html OCAH_DOC_SITE_URL="$(OCAH_GHPAGES_BASE_URL)/trm"
	@$(MAKE) --no-print-directory -C "$(OCAH_ROOT)" \
		ocah-doc-integrator-html OCAH_DOC_SITE_URL="$(OCAH_GHPAGES_BASE_URL)/integrator"
	@$(MAKE) --no-print-directory -C "$(OCAH_ROOT)" ocah-doc-stage-ghpages
	@cd "$(OCAH_ROOT)" && uv run ghp-import -n -p -f "$(OCAH_GHPAGES_DIR)"
	@echo "Deployed to GitHub Pages ($(OCAH_GHPAGES_BASE_URL)/)."

## Push an already-staged gh-pages tree (used by CI after HTML builds).
.PHONY: ocah-doc-push-ghpages
ocah-doc-push-ghpages: ocah-doc-stage-ghpages
	@command -v uv >/dev/null 2>&1 || { \
		echo "error: uv is required to deploy GitHub Pages (ghp-import)."; \
		echo "install uv, or see https://docs.astral.sh/uv/"; \
		exit 1; \
	}
	@cd "$(OCAH_ROOT)" && uv run ghp-import -n -p -f "$(OCAH_GHPAGES_DIR)"
	@echo "Deployed to GitHub Pages ($(OCAH_GHPAGES_BASE_URL)/)."

OCAH_PHONY += \
  ocah-doc-reg-setup \
  ocah-doc-setup \
  ocah-doc-html \
  ocah-doc-pdf \
  ocah-doc-serve \
  ocah-doc-clean \
  ocah-doc-stage-ghpages \
  ocah-doc-deploy-ghpages \
  ocah-doc-push-ghpages

endif
