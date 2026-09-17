# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_doc_integrator_mk
ocah_doc_integrator_mk := 1

OCAH_INTEGRATOR_DIR ?= $(OCAH_DOC_DIR)/integrator
OCAH_INTEGRATOR_SRC ?= $(OCAH_INTEGRATOR_DIR)/src
OCAH_INTEGRATOR_META ?= $(OCAH_INTEGRATOR_DIR)/meta
OCAH_INTEGRATOR_MODULES ?= $(OCAH_INTEGRATOR_DIR)/modules
OCAH_INTEGRATOR_ASSETS ?= $(OCAH_INTEGRATOR_DIR)/assets
OCAH_INTEGRATOR_BUILD ?= $(OCAH_INTEGRATOR_DIR)/_build
OCAH_INTEGRATOR_DIST ?= $(OCAH_INTEGRATOR_DIR)/dist
OCAH_INTEGRATOR_PLAYBOOK ?= $(OCAH_ROOT)/antora-integrator-playbook.yml
OCAH_INTEGRATOR_PDF ?= ocah-integrator-guide.pdf

.PHONY: ocah-doc-integrator-meta
ocah-doc-integrator-meta:
	@test -f "$(OCAH_INTEGRATOR_META)/ocah_gpio_table.csv" && $(OCAH_CSV_TO_ADOC) \
		"$(OCAH_INTEGRATOR_META)/ocah_gpio_table.csv" -o "$(OCAH_INTEGRATOR_META)/ocah_gpio_table.adoc" \
		--title "OCAH GPIO Requirements" \
		--table-attrs "[.small,stretch]" \
		--cols-spec '[%autowidth,options="header",frame=all,grid=all]' || true

.PHONY: ocah-doc-integrator-setup
ocah-doc-integrator-setup: ocah-doc-integrator-meta ocah-doc-reg-setup
	@OCAH_ROOT="$(OCAH_ROOT)" \
	  OCAH_DOC_PRODUCT_DIR="$(OCAH_INTEGRATOR_DIR)" \
	  OCAH_DOC_PRODUCT_SRC="$(OCAH_INTEGRATOR_SRC)" \
	  OCAH_DOC_PRODUCT_META="$(OCAH_INTEGRATOR_META)" \
	  OCAH_DOC_PRODUCT_MODULES="$(OCAH_INTEGRATOR_MODULES)" \
	  OCAH_DOC_PRODUCT_ASSETS="$(OCAH_INTEGRATOR_ASSETS)" \
	  bash "$(OCAH_DOC_DIR)/stage-docs.sh"

.PHONY: ocah-doc-integrator-html
ocah-doc-integrator-html: ocah-doc-integrator-setup
	@command -v npx >/dev/null 2>&1 || { echo "error: node/npx is required to build the Antora site."; echo "install Node.js, or run:"; echo "  ./scripts/docker-run.sh doc-html integrator"; exit 1; }
	@echo "Building Integrator Guide HTML documentation (Antora) with node $$(node --version 2>/dev/null)"
	@cd "$(OCAH_ROOT)" && $(OCAH_ANTORA) \
		$(if $(OCAH_DOC_SITE_URL),--url "$(OCAH_DOC_SITE_URL)") \
		--attribute basedir="$(OCAH_INTEGRATOR_DIR)" "$(OCAH_INTEGRATOR_PLAYBOOK)"
	@echo "Done: $(OCAH_INTEGRATOR_BUILD)/html_antora/ocah-integrator-guide/latest/index.html"

.PHONY: ocah-doc-integrator-pdf
ocah-doc-integrator-pdf: ocah-doc-integrator-setup
	@command -v "$(OCAH_ASCIIDOCTOR_PDF)" >/dev/null 2>&1 || { echo "error: asciidoctor-pdf not found ($(OCAH_ASCIIDOCTOR_PDF))."; echo "install asciidoctor-pdf, or run:"; echo "  ./scripts/docker-run.sh doc-pdf integrator"; exit 1; }
	@echo "Building Integrator Guide PDF documentation (asciidoctor-pdf)"
	@mkdir -p "$(OCAH_INTEGRATOR_BUILD)/latex" "$(OCAH_INTEGRATOR_DIST)"
	@rm -rf "$(OCAH_INTEGRATOR_SRC)/assets" && ln -s ../assets "$(OCAH_INTEGRATOR_SRC)/assets"
	@cd "$(OCAH_INTEGRATOR_DIR)" && "$(OCAH_ASCIIDOCTOR_PDF)" \
		$(OCAH_ASCIIDOCTOR_PDF_DIAGRAM_ARGS) \
		-a pdf-theme="$(OCAH_DOC_PDF_THEME)" -a pdf-themesdir="$(OCAH_DOC_PDF_THEMESDIR)" \
		-a toc -a toclevels=3 \
		-o "$(OCAH_INTEGRATOR_BUILD)/latex/$(OCAH_INTEGRATOR_PDF)" src/index.adoc
	@cp "$(OCAH_INTEGRATOR_BUILD)/latex/$(OCAH_INTEGRATOR_PDF)" "$(OCAH_INTEGRATOR_DIST)/$(OCAH_INTEGRATOR_PDF)"
	@echo "Done: $(OCAH_INTEGRATOR_DIST)/$(OCAH_INTEGRATOR_PDF)"

.PHONY: ocah-doc-integrator-serve
ocah-doc-integrator-serve: ocah-doc-integrator-html
	@echo "Serving Integrator Guide at http://localhost:8000 (Ctrl+C to stop)"
	@cd "$(OCAH_INTEGRATOR_BUILD)/html_antora" && python3 -m http.server 8000

.PHONY: ocah-doc-integrator-clean
ocah-doc-integrator-clean:
	@OCAH_ROOT="$(OCAH_ROOT)" \
	  OCAH_DOC_PRODUCT_DIR="$(OCAH_INTEGRATOR_DIR)" \
	  OCAH_DOC_PRODUCT_MODULES="$(OCAH_INTEGRATOR_MODULES)" \
	  OCAH_DOC_PRODUCT_ASSETS="$(OCAH_INTEGRATOR_ASSETS)" \
	  bash "$(OCAH_DOC_DIR)/stage-docs.sh" --clean
	@rm -rf "$(OCAH_INTEGRATOR_BUILD)" "$(OCAH_INTEGRATOR_DIST)"
	@echo "Cleaned Integrator Guide documentation build artifacts."

OCAH_PHONY += \
  ocah-doc-integrator-meta \
  ocah-doc-integrator-setup \
  ocah-doc-integrator-html \
  ocah-doc-integrator-pdf \
  ocah-doc-integrator-serve \
  ocah-doc-integrator-clean

endif
