# SPDX-License-Identifier: Apache-2.0
# (c) 2026 Tenstorrent USA Inc

ifndef ocah_doc_trm_mk
ocah_doc_trm_mk := 1

OCAH_TRM_DIR ?= $(OCAH_DOC_DIR)/trm
OCAH_TRM_SRC ?= $(OCAH_TRM_DIR)/src
OCAH_TRM_META ?= $(OCAH_TRM_DIR)/meta
OCAH_TRM_MODULES ?= $(OCAH_TRM_DIR)/modules
OCAH_TRM_ASSETS ?= $(OCAH_TRM_DIR)/assets
OCAH_TRM_BUILD ?= $(OCAH_TRM_DIR)/_build
OCAH_TRM_DIST ?= $(OCAH_TRM_DIR)/dist
OCAH_TRM_PLAYBOOK ?= $(OCAH_ROOT)/antora-trm-playbook.yml
OCAH_TRM_PDF ?= ocah-trm.pdf

.PHONY: ocah-doc-trm-meta
ocah-doc-trm-meta:
	@test -f "$(OCAH_TRM_META)/ocah_hsr.csv" && $(OCAH_CSV_TO_ADOC) \
		"$(OCAH_TRM_META)/ocah_hsr.csv" -o "$(OCAH_TRM_META)/ocah_hsr_table.adoc" \
		--columns "Requirement ID,Requirement Description,Comments" \
		--id-prefix OCAH-HSR \
		--title "High-Level Safety Requirements" \
		--cols-spec '[cols="1,4,2", options="header"]' || true
	@test -f "$(OCAH_TRM_META)/ocah_hwsr.csv" && $(OCAH_CSV_TO_ADOC) \
		"$(OCAH_TRM_META)/ocah_hwsr.csv" -o "$(OCAH_TRM_META)/ocah_hwsr_table.adoc" \
		--columns "Requirement ID,Category,Requirement Description" \
		--id-prefix OCAH-HWSR \
		--title "Hardware Safety Requirements" \
		--cols-spec '[cols="1,1,4", options="header"]' || true

.PHONY: ocah-doc-trm-setup
ocah-doc-trm-setup: ocah-doc-trm-meta ocah-doc-reg-setup
	@OCAH_ROOT="$(OCAH_ROOT)" \
	  OCAH_DOC_PRODUCT_DIR="$(OCAH_TRM_DIR)" \
	  OCAH_DOC_PRODUCT_SRC="$(OCAH_TRM_SRC)" \
	  OCAH_DOC_PRODUCT_META="$(OCAH_TRM_META)" \
	  OCAH_DOC_PRODUCT_MODULES="$(OCAH_TRM_MODULES)" \
	  OCAH_DOC_PRODUCT_ASSETS="$(OCAH_TRM_ASSETS)" \
	  bash "$(OCAH_DOC_DIR)/stage-docs.sh"

.PHONY: ocah-doc-trm-html
ocah-doc-trm-html: ocah-doc-trm-setup
	@command -v npx >/dev/null 2>&1 || { echo "error: node/npx is required to build the Antora site; use the project Docker image or install Node.js"; exit 1; }
	@echo "Building TRM HTML documentation (Antora) with node $$(node --version 2>/dev/null)"
	@cd "$(OCAH_ROOT)" && $(OCAH_ANTORA) --attribute basedir="$(OCAH_TRM_DIR)" "$(OCAH_TRM_PLAYBOOK)"
	@echo "Done: $(OCAH_TRM_BUILD)/html_antora/ocah-docs/latest/index.html"

.PHONY: ocah-doc-trm-pdf
ocah-doc-trm-pdf: ocah-doc-trm-setup
	@command -v "$(OCAH_ASCIIDOCTOR_PDF)" >/dev/null 2>&1 || { echo "error: asciidoctor-pdf not found ($(OCAH_ASCIIDOCTOR_PDF)); install it or set OCAH_ASCIIDOCTOR_PDF"; exit 1; }
	@echo "Building TRM PDF documentation (asciidoctor-pdf)"
	@mkdir -p "$(OCAH_TRM_BUILD)/latex" "$(OCAH_TRM_DIST)"
	@rm -rf "$(OCAH_TRM_SRC)/assets" && ln -s ../assets "$(OCAH_TRM_SRC)/assets"
	@cd "$(OCAH_TRM_DIR)" && "$(OCAH_ASCIIDOCTOR_PDF)" \
		-a pdf-theme="$(OCAH_DOC_PDF_THEME)" -a pdf-themesdir="$(OCAH_DOC_PDF_THEMESDIR)" \
		-a toc -a toclevels=3 \
		-o "$(OCAH_TRM_BUILD)/latex/$(OCAH_TRM_PDF)" src/index.adoc
	@cp "$(OCAH_TRM_BUILD)/latex/$(OCAH_TRM_PDF)" "$(OCAH_TRM_DIST)/$(OCAH_TRM_PDF)"
	@echo "Done: $(OCAH_TRM_DIST)/$(OCAH_TRM_PDF)"

.PHONY: ocah-doc-trm-serve
ocah-doc-trm-serve: ocah-doc-trm-html
	@echo "Serving TRM at http://localhost:8000 (Ctrl+C to stop)"
	@cd "$(OCAH_TRM_BUILD)/html_antora" && python3 -m http.server 8000

.PHONY: ocah-doc-trm-clean
ocah-doc-trm-clean:
	@OCAH_ROOT="$(OCAH_ROOT)" \
	  OCAH_DOC_PRODUCT_DIR="$(OCAH_TRM_DIR)" \
	  OCAH_DOC_PRODUCT_MODULES="$(OCAH_TRM_MODULES)" \
	  OCAH_DOC_PRODUCT_ASSETS="$(OCAH_TRM_ASSETS)" \
	  bash "$(OCAH_DOC_DIR)/stage-docs.sh" --clean
	@rm -rf "$(OCAH_TRM_BUILD)" "$(OCAH_TRM_DIST)"
	@echo "Cleaned TRM documentation build artifacts."

OCAH_PHONY += \
  ocah-doc-trm-meta \
  ocah-doc-trm-setup \
  ocah-doc-trm-html \
  ocah-doc-trm-pdf \
  ocah-doc-trm-serve \
  ocah-doc-trm-clean

endif
