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
# @antora/lunr-extension powers search -- only # registered/active in the combined playbook
# (antora-playbook.yml), harmless # to have available for the standalone per-product playbooks too.
OCAH_ANTORA ?= npx -y -p @antora/cli@3.1 -p @antora/site-generator@3.1 -p @antora/lunr-extension@1.0.0-alpha.13 antora
OCAH_ASCIIDOCTOR_PDF ?= asciidoctor-pdf
OCAH_DOC_PDF_THEME ?= $(OCAH_DOC_DIR)/theme.yml
OCAH_DOC_PDF_THEMESDIR ?= $(OCAH_DOC_DIR)
OCAH_CSV_TO_ADOC := python3 $(OCAH_ROOT)/tools/doc/csvadoc.py
OCAH_DOC_REGEN_REGS ?= 1
# Partner-facing output is a release build by default. AsciiDoc sources can use
# the generic `release` attribute to exclude internal-only material.
OCAH_DOC_RELEASE ?= 1
OCAH_DOC_RELEASE_ENABLED := $(filter 1 yes true,$(strip $(OCAH_DOC_RELEASE)))
OCAH_DOC_ANTORA_RELEASE_ARG := $(if $(OCAH_DOC_RELEASE_ENABLED),--attribute release)
OCAH_DOC_ASCIIDOCTOR_RELEASE_ARG := $(if $(OCAH_DOC_RELEASE_ENABLED),-a release)
# Optional Antora --url override (nested publish paths, e.g. /trm).
OCAH_DOC_SITE_URL ?=

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
-include $(OCAH_DOC_DIR)/programmer/doc.mk
-include $(OCAH_DOC_DIR)/appnotes/doc.mk
-include $(OCAH_DOC_DIR)/contributing/doc.mk
-include $(OCAH_DOC_DIR)/home/doc.mk

# GitHub Pages publish.
-include $(OCAH_DOC_DIR)/gh-pages.mk

## Compatibility aliases: default doc-* targets build the TRM.
.PHONY: ocah-doc-setup ocah-doc-html ocah-doc-pdf ocah-doc-serve ocah-doc-clean
ocah-doc-setup: ocah-doc-trm-setup
ocah-doc-html: ocah-doc-trm-html
ocah-doc-pdf: ocah-doc-trm-pdf
ocah-doc-serve: ocah-doc-trm-serve
ocah-doc-clean: ocah-doc-trm-clean ocah-doc-integrator-clean ocah-doc-programmer-clean ocah-doc-appnotes-clean ocah-doc-contributing-clean ocah-doc-home-clean

## Stage all books (registers + symlinks) without running Antora/asciidoctor-pdf.
.PHONY: ocah-doc-all-setup
ocah-doc-all-setup: ocah-doc-trm-setup ocah-doc-integrator-setup ocah-doc-programmer-setup ocah-doc-appnotes-setup ocah-doc-contributing-setup ocah-doc-home-setup

## Build standalone Antora HTML sites for every book.
.PHONY: ocah-doc-all-html
ocah-doc-all-html: ocah-doc-trm-html ocah-doc-integrator-html ocah-doc-programmer-html ocah-doc-appnotes-html ocah-doc-contributing-html ocah-doc-home-html

## Build PDFs for every book that has one (home is HTML-only).
.PHONY: ocah-doc-all-pdf
ocah-doc-all-pdf: ocah-doc-trm-pdf ocah-doc-integrator-pdf ocah-doc-programmer-pdf ocah-doc-appnotes-pdf ocah-doc-contributing-pdf

# Alias doc-all-serve to doc-combined-html, and then manually serve - consistency
.PHONY: ocah-doc-all-serve
ocah-doc-all-serve: ocah-doc-combined-html
	@echo "Serving all books at http://localhost:8000 (Ctrl+C to stop)"
	@cd "$(OCAH_GHPAGES_DIR)" && python3 -m http.server 8000

# Alias doc-all-clean to doc-clean
.PHONY: ocah-doc-all-clean
ocah-doc-all-clean: ocah-doc-clean

OCAH_PHONY += \
  ocah-doc-reg-setup \
  ocah-doc-setup \
  ocah-doc-html \
  ocah-doc-pdf \
  ocah-doc-serve \
  ocah-doc-clean \
  ocah-doc-all-setup \
  ocah-doc-all-html \
  ocah-doc-all-pdf \
  ocah-doc-all-serve \
  ocah-doc-all-clean

endif
