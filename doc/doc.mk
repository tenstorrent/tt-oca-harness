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

OCAH_PHONY += \
  ocah-doc-reg-setup \
  ocah-doc-setup \
  ocah-doc-html \
  ocah-doc-pdf \
  ocah-doc-serve \
  ocah-doc-clean

endif
