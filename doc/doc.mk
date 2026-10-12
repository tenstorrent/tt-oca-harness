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
# @antora/lunr-extension powers combined-site search. asciidoctor-kroki 0.18
# is the Antora 3-compatible release and renders inline diagrams during builds.
OCAH_ANTORA ?= npx -y -p @antora/cli@3.1 -p @antora/site-generator@3.1 -p @antora/lunr-extension@1.0.0-alpha.13 -p asciidoctor-kroki@0.18.1 antora
OCAH_ASCIIDOCTOR_PDF ?= asciidoctor-pdf
OCAH_DOC_PDF_LOCALE ?= LC_ALL=C.UTF-8
# asciidoctor-diagram renders PlantUML locally with the bundled jar: no
# network call, so PDF builds never depend on kroki.io being reachable.
# (The Antora HTML builds still go through asciidoctor-kroki -- see
# antora-*-playbook.yml -- since Antora has no equivalent local renderer.)
OCAH_ASCIIDOCTOR_PDF_DIAGRAM_ARGS ?= -r asciidoctor-diagram
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

## @section Documentation

## Regenerate register docs best-effort for documentation products.
# A hard dependency on every block's adoc would fail the doc build on known
# regen gaps. -k regenerates what it can; stage-docs.sh stages whatever exists.
.PHONY: ocah-doc-reg-setup
ifeq ($(OCAH_DOC_REGEN_REGS),1)
ocah-doc-reg-setup:
	@-$(MAKE) --no-print-directory -k -C "$(OCAH_ROOT)" ocah-regen-regs-adoc
	@-$(MAKE) --no-print-directory -k -C "$(OCAH_ROOT)" ocah-regen-regs-html
else
ocah-doc-reg-setup:
	@true
endif

## Verification dashboard data.
#
# doc/home/src/dashboard.adoc fetches this JSON in the browser at page load.
OCAH_DASHBOARD_DATA_DIR ?= $(OCAH_DOC_DIR)/_build/dashboard-data
OCAH_DASHBOARD_DATA_REF ?= origin/dv-dashboard-data
OCAH_DASHBOARD_PUBLISHERS ?= vcs
OCAH_DASHBOARD_RUNS_LIMIT ?= 0
OCAH_DASHBOARD_STAGE := OCAH_ROOT="$(OCAH_ROOT)" \
	OCAH_DASHBOARD_DATA_DIR="$(OCAH_DASHBOARD_DATA_DIR)" \
	OCAH_DASHBOARD_DATA_REF="$(OCAH_DASHBOARD_DATA_REF)" \
	OCAH_DASHBOARD_PUBLISHERS="$(OCAH_DASHBOARD_PUBLISHERS)" \
	OCAH_DASHBOARD_RUNS_LIMIT="$(OCAH_DASHBOARD_RUNS_LIMIT)" \
	bash $(OCAH_ROOT)/tools/doc/stage_dashboard_data.sh

## Stage dashboard JSON from the local clone of the data branch.
.PHONY: ocah-doc-dashboard-data
ocah-doc-dashboard-data:
	@$(OCAH_DASHBOARD_STAGE)

# Copy staged dashboard data into a built site tree.
# $(call ocah_stage_dashboard_data,<site-root>)
define ocah_stage_dashboard_data
@$(OCAH_DASHBOARD_STAGE) "$(1)"
endef

# Product makefrags.
-include $(OCAH_DOC_DIR)/trm/doc.mk
-include $(OCAH_DOC_DIR)/integrator/doc.mk
-include $(OCAH_DOC_DIR)/programmer/doc.mk
-include $(OCAH_DOC_DIR)/appnotes/doc.mk
-include $(OCAH_DOC_DIR)/starting/doc.mk
-include $(OCAH_DOC_DIR)/home/doc.mk
-include $(OCAH_DOC_DIR)/datasheets/doc.mk

# GitHub Pages publish.
-include $(OCAH_DOC_DIR)/gh-pages.mk

## Compatibility aliases: default doc-* targets build the TRM.
.PHONY: ocah-doc-setup ocah-doc-html ocah-doc-pdf ocah-doc-serve ocah-doc-clean
ocah-doc-setup: ocah-doc-trm-setup
ocah-doc-html: ocah-doc-trm-html
ocah-doc-pdf: ocah-doc-trm-pdf
ocah-doc-serve: ocah-doc-trm-serve
ocah-doc-clean: ocah-doc-trm-clean ocah-doc-integrator-clean ocah-doc-programmer-clean ocah-doc-appnotes-clean ocah-doc-starting-clean ocah-doc-home-clean ocah-doc-datasheets-clean

## Stage all books (registers + symlinks) without running Antora/asciidoctor-pdf.
.PHONY: ocah-doc-all-setup
ocah-doc-all-setup: ocah-doc-trm-setup ocah-doc-integrator-setup ocah-doc-programmer-setup ocah-doc-appnotes-setup ocah-doc-starting-setup ocah-doc-home-setup ocah-doc-datasheets-setup

## Build combined Antora HTML site - alias of doc-combined-html for consistency
.PHONY: ocah-doc-all-html
ocah-doc-all-html: ocah-doc-combined-html

## Build PDFs for every book that has one (home is HTML-only).
.PHONY: ocah-doc-all-pdf
ocah-doc-all-pdf: ocah-doc-trm-pdf ocah-doc-integrator-pdf ocah-doc-programmer-pdf ocah-doc-appnotes-pdf ocah-doc-starting-pdf ocah-doc-datasheets-pdf

# Construct combined Antora HTML site, and then manually serve
.PHONY: ocah-doc-all-serve
ocah-doc-all-serve: ocah-doc-all-html
	@echo "Serving all books at http://localhost:8000 (Ctrl+C to stop)"
	@cd "$(OCAH_GHPAGES_DIR)" && python3 -m http.server 8000

# Alias doc-all-clean to doc-clean
.PHONY: ocah-doc-all-clean
ocah-doc-all-clean: ocah-doc-clean

OCAH_PHONY += \
  ocah-doc-reg-setup \
  ocah-doc-dashboard-data \
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
