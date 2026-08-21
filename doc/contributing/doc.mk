# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_doc_contributing_mk
ocah_doc_contributing_mk := 1

OCAH_CONTRIBUTING_DIR ?= $(OCAH_DOC_DIR)/contributing
OCAH_CONTRIBUTING_SRC ?= $(OCAH_CONTRIBUTING_DIR)/src
OCAH_CONTRIBUTING_MODULES ?= $(OCAH_CONTRIBUTING_DIR)/modules
OCAH_CONTRIBUTING_ASSETS ?= $(OCAH_CONTRIBUTING_DIR)/assets
OCAH_CONTRIBUTING_BUILD ?= $(OCAH_CONTRIBUTING_DIR)/_build
OCAH_CONTRIBUTING_DIST ?= $(OCAH_CONTRIBUTING_DIR)/dist
OCAH_CONTRIBUTING_PLAYBOOK ?= $(OCAH_ROOT)/antora-contributing-playbook.yml
OCAH_CONTRIBUTING_PDF ?= ocah-contributing.pdf

.PHONY: ocah-doc-contributing-setup
ocah-doc-contributing-setup: ocah-doc-reg-setup
	@OCAH_ROOT="$(OCAH_ROOT)" \
	  OCAH_DOC_PRODUCT_DIR="$(OCAH_CONTRIBUTING_DIR)" \
	  OCAH_DOC_PRODUCT_SRC="$(OCAH_CONTRIBUTING_SRC)" \
	  OCAH_DOC_PRODUCT_MODULES="$(OCAH_CONTRIBUTING_MODULES)" \
	  OCAH_DOC_PRODUCT_ASSETS="$(OCAH_CONTRIBUTING_ASSETS)" \
	  bash "$(OCAH_DOC_DIR)/stage-docs.sh"

.PHONY: ocah-doc-contributing-html
ocah-doc-contributing-html: ocah-doc-contributing-setup
	@command -v npx >/dev/null 2>&1 || { echo "error: node/npx is required to build the Antora site."; echo "install Node.js, or run:"; echo "  ./scripts/docker-run.sh doc-html contributing"; exit 1; }
	@echo "Building Contributing Guide HTML documentation (Antora) with node $$(node --version 2>/dev/null)"
	@cd "$(OCAH_ROOT)" && $(OCAH_ANTORA) \
		$(if $(OCAH_DOC_SITE_URL),--url "$(OCAH_DOC_SITE_URL)") \
		--attribute basedir="$(OCAH_CONTRIBUTING_DIR)" "$(OCAH_CONTRIBUTING_PLAYBOOK)"
	@echo "Done: $(OCAH_CONTRIBUTING_BUILD)/html_antora/ocah-contributing/latest/index.html"

.PHONY: ocah-doc-contributing-pdf
ocah-doc-contributing-pdf: ocah-doc-contributing-setup
	@command -v "$(OCAH_ASCIIDOCTOR_PDF)" >/dev/null 2>&1 || { echo "error: asciidoctor-pdf not found ($(OCAH_ASCIIDOCTOR_PDF))."; echo "install asciidoctor-pdf, or run:"; echo "  ./scripts/docker-run.sh doc-pdf contributing"; exit 1; }
	@echo "Building Contributing Guide PDF documentation (asciidoctor-pdf)"
	@mkdir -p "$(OCAH_CONTRIBUTING_BUILD)/latex" "$(OCAH_CONTRIBUTING_DIST)"
	@rm -rf "$(OCAH_CONTRIBUTING_SRC)/assets" && ln -s ../assets "$(OCAH_CONTRIBUTING_SRC)/assets"
	@cd "$(OCAH_CONTRIBUTING_DIR)" && "$(OCAH_ASCIIDOCTOR_PDF)" \
		-a pdf-theme="$(OCAH_DOC_PDF_THEME)" -a pdf-themesdir="$(OCAH_DOC_PDF_THEMESDIR)" \
		-a toc -a toclevels=3 \
		-o "$(OCAH_CONTRIBUTING_BUILD)/latex/$(OCAH_CONTRIBUTING_PDF)" src/index.adoc
	@cp "$(OCAH_CONTRIBUTING_BUILD)/latex/$(OCAH_CONTRIBUTING_PDF)" "$(OCAH_CONTRIBUTING_DIST)/$(OCAH_CONTRIBUTING_PDF)"
	@echo "Done: $(OCAH_CONTRIBUTING_DIST)/$(OCAH_CONTRIBUTING_PDF)"

.PHONY: ocah-doc-contributing-serve
ocah-doc-contributing-serve: ocah-doc-contributing-html
	@echo "Serving Contributing Guide at http://localhost:8000 (Ctrl+C to stop)"
	@cd "$(OCAH_CONTRIBUTING_BUILD)/html_antora" && python3 -m http.server 8000

.PHONY: ocah-doc-contributing-clean
ocah-doc-contributing-clean:
	@OCAH_ROOT="$(OCAH_ROOT)" \
	  OCAH_DOC_PRODUCT_DIR="$(OCAH_CONTRIBUTING_DIR)" \
	  OCAH_DOC_PRODUCT_MODULES="$(OCAH_CONTRIBUTING_MODULES)" \
	  OCAH_DOC_PRODUCT_ASSETS="$(OCAH_CONTRIBUTING_ASSETS)" \
	  bash "$(OCAH_DOC_DIR)/stage-docs.sh" --clean
	@rm -rf "$(OCAH_CONTRIBUTING_BUILD) $(OCAH_CONTRIBUTING_DIST)"
	@echo "Cleaned Contributing Guide documentation build artifacts."

OCAH_PHONY += \
  ocah-doc-contributing-setup \
  ocah-doc-contributing-html \
  ocah-doc-contributing-pdf \
  ocah-doc-contributing-serve \
  ocah-doc-contributing-clean

endif