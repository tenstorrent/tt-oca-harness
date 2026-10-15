# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_doc_datasheets_mk
ocah_doc_datasheets_mk := 1

OCAH_DATASHEETS_DIR ?= $(OCAH_DOC_DIR)/datasheets
OCAH_DATASHEETS_SRC ?= $(OCAH_DATASHEETS_DIR)/src
OCAH_DATASHEETS_BUILD ?= $(OCAH_DATASHEETS_DIR)/_build
OCAH_DATASHEETS_THEME ?= $(OCAH_DATASHEETS_DIR)/datasheet-theme.yml
OCAH_DATASHEETS_LOGO ?= $(OCAH_DOC_DIR)/ui-supplemental/img/tt_logo_color-yellow-black.png
OCAH_DATASHEET_PRODUCTS ?= $(notdir $(basename $(wildcard $(OCAH_DATASHEETS_SRC)/*.adoc)))
OCAH_DATASHEET_PDFS := $(addprefix ocah-,$(addsuffix -datasheet.pdf,$(OCAH_DATASHEET_PRODUCTS)))
OCAH_DATASHEET_BUILD_FILES := $(addprefix $(OCAH_DATASHEETS_BUILD)/,$(OCAH_DATASHEET_PDFS))
OCAH_DATASHEET_VALIDATE := python3 $(OCAH_ROOT)/tools/doc/validate_datasheets.py

.PHONY: ocah-doc-datasheets-setup
ocah-doc-datasheets-setup:
	@$(OCAH_DATASHEET_VALIDATE) \
		--source "$(OCAH_DATASHEETS_DIR)/template.adoc" \
		$(foreach product,$(OCAH_DATASHEET_PRODUCTS),--source "$(OCAH_DATASHEETS_SRC)/$(product).adoc")

define ocah_datasheet_rule
$(OCAH_DATASHEETS_BUILD)/ocah-$(1)-datasheet.pdf: $(OCAH_DATASHEETS_SRC)/$(1).adoc $(OCAH_DATASHEETS_THEME) $(wildcard $(OCAH_DATASHEETS_DIR)/$(1)-theme.yml) $(OCAH_DATASHEETS_LOGO) $(wildcard $(OCAH_DATASHEETS_DIR)/assets/*) | ocah-doc-datasheets-setup
	@command -v "$(OCAH_ASCIIDOCTOR_PDF)" >/dev/null 2>&1 || { echo "error: asciidoctor-pdf not found ($(OCAH_ASCIIDOCTOR_PDF))."; echo "install asciidoctor-pdf, or run:"; echo "  ./scripts/docker-run.sh doc-pdf datasheets"; exit 1; }
	@echo "Building $(1) datasheet PDF (asciidoctor-pdf)"
	@mkdir -p "$(OCAH_DATASHEETS_BUILD)"
	@cd "$(OCAH_DATASHEETS_DIR)" && env $(OCAH_DOC_PDF_LOCALE) "$(OCAH_ASCIIDOCTOR_PDF)" \
		-a pdf-theme="$(or $(wildcard $(OCAH_DATASHEETS_DIR)/$(1)-theme.yml),$(OCAH_DATASHEETS_THEME))" \
		-o "$(OCAH_DATASHEETS_BUILD)/ocah-$(1)-datasheet.pdf" "src/$(1).adoc"
	@$(OCAH_DATASHEET_VALIDATE) \
		--source "$(OCAH_DATASHEETS_SRC)/$(1).adoc" \
		--pdf "$(OCAH_DATASHEETS_BUILD)/ocah-$(1)-datasheet.pdf"
	@echo "Done: $(OCAH_DATASHEETS_BUILD)/ocah-$(1)-datasheet.pdf"

.PHONY: ocah-doc-$(1)-datasheet-pdf
ocah-doc-$(1)-datasheet-pdf: $(OCAH_DATASHEETS_BUILD)/ocah-$(1)-datasheet.pdf
endef

$(foreach product,$(OCAH_DATASHEET_PRODUCTS),$(eval $(call ocah_datasheet_rule,$(product))))

.PHONY: ocah-doc-datasheets-pdf
ocah-doc-datasheets-pdf: $(OCAH_DATASHEET_BUILD_FILES)

.PHONY: ocah-doc-datasheets-clean
ocah-doc-datasheets-clean:
	@rm -rf "$(OCAH_DATASHEETS_BUILD)"
	@echo "Cleaned datasheet build artifacts."

OCAH_PHONY += \
  ocah-doc-datasheets-setup \
  $(foreach product,$(OCAH_DATASHEET_PRODUCTS),ocah-doc-$(product)-datasheet-pdf) \
  ocah-doc-datasheets-pdf \
  ocah-doc-datasheets-clean

endif
