# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_doc_programmer_mk
ocah_doc_programmer_mk := 1

OCAH_PROGRAMMER_DIR ?= $(OCAH_DOC_DIR)/programmer
OCAH_PROGRAMMER_SRC ?= $(OCAH_PROGRAMMER_DIR)/src
OCAH_PROGRAMMER_META ?= $(OCAH_PROGRAMMER_DIR)/meta
OCAH_PROGRAMMER_MODULES ?= $(OCAH_PROGRAMMER_DIR)/modules
OCAH_PROGRAMMER_ASSETS ?= $(OCAH_PROGRAMMER_DIR)/assets
OCAH_PROGRAMMER_BUILD ?= $(OCAH_PROGRAMMER_DIR)/_build
OCAH_PROGRAMMER_DIST ?= $(OCAH_PROGRAMMER_DIR)/dist
OCAH_PROGRAMMER_PLAYBOOK ?= $(OCAH_ROOT)/antora-programmer-playbook.yml
OCAH_PROGRAMMER_PDF ?= ocah-programmer-guide.pdf

# Null builder: no meta CSVs / requirement tables for this product yet.
# Add a real ocah-doc-programmer-meta step here (mirroring TRM's hsr/hwsr
# pattern) once this product has requirement tables to build.
.PHONY: ocah-doc-programmer-meta
ocah-doc-programmer-meta:
	@true

.PHONY: ocah-doc-programmer-setup
ocah-doc-programmer-setup: ocah-doc-programmer-meta ocah-doc-reg-setup
	@OCAH_ROOT="$(OCAH_ROOT)" \
	  OCAH_DOC_PRODUCT_DIR="$(OCAH_PROGRAMMER_DIR)" \
	  OCAH_DOC_PRODUCT_SRC="$(OCAH_PROGRAMMER_SRC)" \
	  OCAH_DOC_PRODUCT_META="$(OCAH_PROGRAMMER_META)" \
	  OCAH_DOC_PRODUCT_MODULES="$(OCAH_PROGRAMMER_MODULES)" \
	  OCAH_DOC_PRODUCT_ASSETS="$(OCAH_PROGRAMMER_ASSETS)" \
	  bash "$(OCAH_DOC_DIR)/stage-docs.sh"

.PHONY: ocah-doc-programmer-html
ocah-doc-programmer-html: ocah-doc-programmer-setup
	@command -v npx >/dev/null 2>&1 || { echo "error: node/npx is required to build the Antora site."; echo "install Node.js, or run:"; echo "  ./scripts/docker-run.sh doc-html programmer"; exit 1; }
	@echo "Building Programmer's Guide HTML documentation (Antora) with node $$(node --version 2>/dev/null)"
	@cd "$(OCAH_ROOT)" && $(OCAH_ANTORA) \
		$(if $(OCAH_DOC_SITE_URL),--url "$(OCAH_DOC_SITE_URL)") \
		--attribute basedir="$(OCAH_PROGRAMMER_DIR)" "$(OCAH_PROGRAMMER_PLAYBOOK)"
	@echo "Done: $(OCAH_PROGRAMMER_BUILD)/html_antora/ocah-programmer-guide/latest/index.html"

.PHONY: ocah-doc-programmer-pdf
ocah-doc-programmer-pdf: ocah-doc-programmer-setup
	@command -v "$(OCAH_ASCIIDOCTOR_PDF)" >/dev/null 2>&1 || { echo "error: asciidoctor-pdf not found ($(OCAH_ASCIIDOCTOR_PDF))."; echo "install asciidoctor-pdf, or run:"; echo "  ./scripts/docker-run.sh doc-pdf programmer"; exit 1; }
	@echo "Building Programmer's Guide PDF documentation (asciidoctor-pdf)"
	@mkdir -p "$(OCAH_PROGRAMMER_BUILD)/latex" "$(OCAH_PROGRAMMER_DIST)"
	@rm -rf "$(OCAH_PROGRAMMER_SRC)/assets" && ln -s ../assets "$(OCAH_PROGRAMMER_SRC)/assets"
	@cd "$(OCAH_PROGRAMMER_DIR)" && "$(OCAH_ASCIIDOCTOR_PDF)" \
		$(OCAH_ASCIIDOCTOR_PDF_DIAGRAM_ARGS) \
		-a pdf-theme="$(OCAH_DOC_PDF_THEME)" -a pdf-themesdir="$(OCAH_DOC_PDF_THEMESDIR)" \
		-a toc -a toclevels=3 \
		-o "$(OCAH_PROGRAMMER_BUILD)/latex/$(OCAH_PROGRAMMER_PDF)" src/index.adoc
	@cp "$(OCAH_PROGRAMMER_BUILD)/latex/$(OCAH_PROGRAMMER_PDF)" "$(OCAH_PROGRAMMER_DIST)/$(OCAH_PROGRAMMER_PDF)"
	@echo "Done: $(OCAH_PROGRAMMER_DIST)/$(OCAH_PROGRAMMER_PDF)"

.PHONY: ocah-doc-programmer-serve
ocah-doc-programmer-serve: ocah-doc-programmer-html
	@echo "Serving Programmer's Guide at http://localhost:8000 (Ctrl+C to stop)"
	@cd "$(OCAH_PROGRAMMER_BUILD)/html_antora" && python3 -m http.server 8000

.PHONY: ocah-doc-programmer-clean
ocah-doc-programmer-clean:
	@OCAH_ROOT="$(OCAH_ROOT)" \
	  OCAH_DOC_PRODUCT_DIR="$(OCAH_PROGRAMMER_DIR)" \
	  OCAH_DOC_PRODUCT_MODULES="$(OCAH_PROGRAMMER_MODULES)" \
	  OCAH_DOC_PRODUCT_ASSETS="$(OCAH_PROGRAMMER_ASSETS)" \
	  bash "$(OCAH_DOC_DIR)/stage-docs.sh" --clean
	@rm -rf "$(OCAH_PROGRAMMER_BUILD)" "$(OCAH_PROGRAMMER_DIST)"
	@echo "Cleaned Programmer's Guide documentation build artifacts."

OCAH_PHONY += \
  ocah-doc-programmer-meta \
  ocah-doc-programmer-setup \
  ocah-doc-programmer-html \
  ocah-doc-programmer-pdf \
  ocah-doc-programmer-serve \
  ocah-doc-programmer-clean

endif
