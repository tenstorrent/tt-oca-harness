# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_doc_appnotes_mk
ocah_doc_appnotes_mk := 1

OCAH_APPNOTES_DIR ?= $(OCAH_DOC_DIR)/appnotes
OCAH_APPNOTES_SRC ?= $(OCAH_APPNOTES_DIR)/src
OCAH_APPNOTES_META ?= $(OCAH_APPNOTES_DIR)/meta
OCAH_APPNOTES_MODULES ?= $(OCAH_APPNOTES_DIR)/modules
OCAH_APPNOTES_ASSETS ?= $(OCAH_APPNOTES_DIR)/assets
OCAH_APPNOTES_BUILD ?= $(OCAH_APPNOTES_DIR)/_build
OCAH_APPNOTES_DIST ?= $(OCAH_APPNOTES_DIR)/dist
OCAH_APPNOTES_PLAYBOOK ?= $(OCAH_ROOT)/antora-appnotes-playbook.yml
OCAH_APPNOTES_PDF ?= ocah-appnotes.pdf

# Null builder: no meta CSVs / requirement tables for this product yet.
# Add a real ocah-doc-appnotes-meta step here (mirroring TRM's hsr/hwsr
# pattern) once this product has requirement tables to build.
.PHONY: ocah-doc-appnotes-meta
ocah-doc-appnotes-meta:
	@true

.PHONY: ocah-doc-appnotes-setup
ocah-doc-appnotes-setup: ocah-doc-appnotes-meta ocah-doc-reg-setup
	@OCAH_ROOT="$(OCAH_ROOT)" \
	  OCAH_DOC_PRODUCT_DIR="$(OCAH_APPNOTES_DIR)" \
	  OCAH_DOC_PRODUCT_SRC="$(OCAH_APPNOTES_SRC)" \
	  OCAH_DOC_PRODUCT_META="$(OCAH_APPNOTES_META)" \
	  OCAH_DOC_PRODUCT_MODULES="$(OCAH_APPNOTES_MODULES)" \
	  OCAH_DOC_PRODUCT_ASSETS="$(OCAH_APPNOTES_ASSETS)" \
	  bash "$(OCAH_DOC_DIR)/stage-docs.sh"

.PHONY: ocah-doc-appnotes-html
ocah-doc-appnotes-html: ocah-doc-appnotes-setup
	@command -v $(OCAH_ANTORA) >/dev/null 2>&1 || { echo "error: node/npx is required to build the Antora site."; echo "install Node.js, or run:"; echo "  ./scripts/docker-run.sh doc-html appnotes"; exit 1; }
	@echo "Building Application Notes HTML documentation (Antora) with node $$(node --version 2>/dev/null)"
	@cd "$(OCAH_ROOT)" && $(OCAH_ANTORA) \
		$(if $(OCAH_DOC_SITE_URL),--url "$(OCAH_DOC_SITE_URL)") \
		--attribute basedir="$(OCAH_APPNOTES_DIR)" "$(OCAH_APPNOTES_PLAYBOOK)"
	@echo "Done: $(OCAH_APPNOTES_BUILD)/html_antora/ocah-appnotes/latest/index.html"

.PHONY: ocah-doc-appnotes-pdf
ocah-doc-appnotes-pdf: ocah-doc-appnotes-setup
	@command -v "$(OCAH_ASCIIDOCTOR_PDF)" >/dev/null 2>&1 || { echo "error: asciidoctor-pdf not found ($(OCAH_ASCIIDOCTOR_PDF))."; echo "install asciidoctor-pdf, or run:"; echo "  ./scripts/docker-run.sh doc-pdf appnotes"; exit 1; }
	@echo "Building Application Notes PDF documentation (asciidoctor-pdf)"
	@mkdir -p "$(OCAH_APPNOTES_BUILD)/latex" "$(OCAH_APPNOTES_DIST)"
	@rm -rf "$(OCAH_APPNOTES_SRC)/assets" && ln -s ../assets "$(OCAH_APPNOTES_SRC)/assets"
	@cd "$(OCAH_APPNOTES_DIR)" && "$(OCAH_ASCIIDOCTOR_PDF)" \
		-a pdf-theme="$(OCAH_DOC_PDF_THEME)" -a pdf-themesdir="$(OCAH_DOC_PDF_THEMESDIR)" \
		-a toc -a toclevels=3 \
		-o "$(OCAH_APPNOTES_BUILD)/latex/$(OCAH_APPNOTES_PDF)" src/index.adoc
	@cp "$(OCAH_APPNOTES_BUILD)/latex/$(OCAH_APPNOTES_PDF)" "$(OCAH_APPNOTES_DIST)/$(OCAH_APPNOTES_PDF)"
	@echo "Done: $(OCAH_APPNOTES_DIST)/$(OCAH_APPNOTES_PDF)"

.PHONY: ocah-doc-appnotes-serve
ocah-doc-appnotes-serve: ocah-doc-appnotes-html
	@echo "Serving Application Notes at http://localhost:8000 (Ctrl+C to stop)"
	@cd "$(OCAH_APPNOTES_BUILD)/html_antora" && python3 -m http.server 8000

.PHONY: ocah-doc-appnotes-clean
ocah-doc-appnotes-clean:
	@OCAH_ROOT="$(OCAH_ROOT)" \
	  OCAH_DOC_PRODUCT_DIR="$(OCAH_APPNOTES_DIR)" \
	  OCAH_DOC_PRODUCT_MODULES="$(OCAH_APPNOTES_MODULES)" \
	  OCAH_DOC_PRODUCT_ASSETS="$(OCAH_APPNOTES_ASSETS)" \
	  bash "$(OCAH_DOC_DIR)/stage-docs.sh" --clean
	@rm -rf "$(OCAH_APPNOTES_BUILD)" "$(OCAH_APPNOTES_DIST)"
	@echo "Cleaned Application Notes documentation build artifacts."

OCAH_PHONY += \
  ocah-doc-appnotes-meta \
  ocah-doc-appnotes-setup \
  ocah-doc-appnotes-html \
  ocah-doc-appnotes-pdf \
  ocah-doc-appnotes-serve \
  ocah-doc-appnotes-clean

endif
