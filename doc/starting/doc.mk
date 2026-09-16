# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_doc_starting_mk
ocah_doc_starting_mk := 1

OCAH_STARTING_DIR ?= $(OCAH_DOC_DIR)/starting
OCAH_STARTING_SRC ?= $(OCAH_STARTING_DIR)/src
OCAH_STARTING_MODULES ?= $(OCAH_STARTING_DIR)/modules
OCAH_STARTING_ASSETS ?= $(OCAH_STARTING_DIR)/assets
OCAH_STARTING_BUILD ?= $(OCAH_STARTING_DIR)/_build
OCAH_STARTING_DIST ?= $(OCAH_STARTING_DIR)/dist
OCAH_STARTING_PLAYBOOK ?= $(OCAH_ROOT)/antora-starting-playbook.yml
OCAH_STARTING_PDF ?= ocah-starting.pdf

.PHONY: ocah-doc-starting-setup
ocah-doc-starting-setup: ocah-doc-reg-setup
	@OCAH_ROOT="$(OCAH_ROOT)" \
	  OCAH_DOC_PRODUCT_DIR="$(OCAH_STARTING_DIR)" \
	  OCAH_DOC_PRODUCT_SRC="$(OCAH_STARTING_SRC)" \
	  OCAH_DOC_PRODUCT_MODULES="$(OCAH_STARTING_MODULES)" \
	  OCAH_DOC_PRODUCT_ASSETS="$(OCAH_STARTING_ASSETS)" \
	  bash "$(OCAH_DOC_DIR)/stage-docs.sh"

.PHONY: ocah-doc-starting-html
ocah-doc-starting-html: ocah-doc-starting-setup
	@command -v npx >/dev/null 2>&1 || { echo "error: node/npx is required to build the Antora site."; echo "install Node.js, or run:"; echo "  ./scripts/docker-run.sh doc-html starting"; exit 1; }
	@echo "Building Getting Started Guide HTML documentation (Antora) with node $$(node --version 2>/dev/null)"
	@cd "$(OCAH_ROOT)" && $(OCAH_ANTORA) \
		$(if $(OCAH_DOC_SITE_URL),--url "$(OCAH_DOC_SITE_URL)") \
		--attribute basedir="$(OCAH_STARTING_DIR)" "$(OCAH_STARTING_PLAYBOOK)"
	@echo "Done: $(OCAH_STARTING_BUILD)/html_antora/ocah-starting/latest/index.html"

.PHONY: ocah-doc-starting-pdf
ocah-doc-starting-pdf: ocah-doc-starting-setup
	@command -v "$(OCAH_ASCIIDOCTOR_PDF)" >/dev/null 2>&1 || { echo "error: asciidoctor-pdf not found ($(OCAH_ASCIIDOCTOR_PDF))."; echo "install asciidoctor-pdf, or run:"; echo "  ./scripts/docker-run.sh doc-pdf starting"; exit 1; }
	@echo "Building Getting Started Guide PDF documentation (asciidoctor-pdf)"
	@mkdir -p "$(OCAH_STARTING_BUILD)/latex" "$(OCAH_STARTING_DIST)"
	@rm -rf "$(OCAH_STARTING_SRC)/assets" && ln -s ../assets "$(OCAH_STARTING_SRC)/assets"
	@cd "$(OCAH_STARTING_DIR)" && "$(OCAH_ASCIIDOCTOR_PDF)" \
		-a pdf-theme="$(OCAH_DOC_PDF_THEME)" -a pdf-themesdir="$(OCAH_DOC_PDF_THEMESDIR)" \
		-a toc -a toclevels=3 \
		-o "$(OCAH_STARTING_BUILD)/latex/$(OCAH_STARTING_PDF)" src/index.adoc
	@cp "$(OCAH_STARTING_BUILD)/latex/$(OCAH_STARTING_PDF)" "$(OCAH_STARTING_DIST)/$(OCAH_STARTING_PDF)"
	@echo "Done: $(OCAH_STARTING_DIST)/$(OCAH_STARTING_PDF)"

.PHONY: ocah-doc-starting-serve
ocah-doc-starting-serve: ocah-doc-starting-html
	@echo "Serving Getting Started Guide at http://localhost:8000 (Ctrl+C to stop)"
	@cd "$(OCAH_STARTING_BUILD)/html_antora" && python3 -m http.server 8000

.PHONY: ocah-doc-starting-clean
ocah-doc-starting-clean:
	@OCAH_ROOT="$(OCAH_ROOT)" \
	  OCAH_DOC_PRODUCT_DIR="$(OCAH_STARTING_DIR)" \
	  OCAH_DOC_PRODUCT_MODULES="$(OCAH_STARTING_MODULES)" \
	  OCAH_DOC_PRODUCT_ASSETS="$(OCAH_STARTING_ASSETS)" \
	  bash "$(OCAH_DOC_DIR)/stage-docs.sh" --clean
	@rm -rf "$(OCAH_STARTING_BUILD)" "$(OCAH_STARTING_DIST)"
	@echo "Cleaned Getting Started Guide documentation build artifacts."

OCAH_PHONY += \
  ocah-doc-starting-setup \
  ocah-doc-starting-html \
  ocah-doc-starting-pdf \
  ocah-doc-starting-serve \
  ocah-doc-starting-clean

endif
