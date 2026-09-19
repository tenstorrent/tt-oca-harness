# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

ifndef ocah_doc_home_mk
ocah_doc_home_mk := 1

OCAH_HOME_DIR ?= $(OCAH_DOC_DIR)/home
OCAH_HOME_SRC ?= $(OCAH_HOME_DIR)/src
OCAH_HOME_MODULES ?= $(OCAH_HOME_DIR)/modules
OCAH_HOME_ASSETS ?= $(OCAH_HOME_DIR)/assets
OCAH_HOME_BUILD ?= $(OCAH_HOME_DIR)/_build
OCAH_HOME_PLAYBOOK ?= $(OCAH_ROOT)/antora-home-playbook.yml
# Web-only by design -- no PDF target for Home.

.PHONY: ocah-doc-home-setup
ocah-doc-home-setup: ocah-doc-reg-setup
	@OCAH_ROOT="$(OCAH_ROOT)" \
	  OCAH_DOC_PRODUCT_DIR="$(OCAH_HOME_DIR)" \
	  OCAH_DOC_PRODUCT_SRC="$(OCAH_HOME_SRC)" \
	  OCAH_DOC_PRODUCT_MODULES="$(OCAH_HOME_MODULES)" \
	  OCAH_DOC_PRODUCT_ASSETS="$(OCAH_HOME_ASSETS)" \
	  bash "$(OCAH_DOC_DIR)/stage-docs.sh"

.PHONY: ocah-doc-home-html
ocah-doc-home-html: ocah-doc-home-setup
	@command -v $(OCAH_ANTORA) >/dev/null 2>&1 || { echo "error: node/npx is required to build the Antora site."; echo "install Node.js, or run:"; echo "  ./scripts/docker-run.sh doc-html home"; exit 1; }
	@echo "Building Home page HTML documentation (Antora) with node $$(node --version 2>/dev/null)"
	@cd "$(OCAH_ROOT)" && $(OCAH_ANTORA) \
		$(if $(OCAH_DOC_SITE_URL),--url "$(OCAH_DOC_SITE_URL)") \
		--attribute basedir="$(OCAH_HOME_DIR)" "$(OCAH_HOME_PLAYBOOK)"
	@echo "Done: $(OCAH_HOME_BUILD)/html_antora/ocah-home/latest/index.html"

.PHONY: ocah-doc-home-serve
ocah-doc-home-serve: ocah-doc-home-html
	@echo "Serving Home at http://localhost:8000 (Ctrl+C to stop)"
	@cd "$(OCAH_HOME_BUILD)/html_antora" && python3 -m http.server 8000

.PHONY: ocah-doc-home-clean
ocah-doc-home-clean:
	@OCAH_ROOT="$(OCAH_ROOT)" \
	  OCAH_DOC_PRODUCT_DIR="$(OCAH_HOME_DIR)" \
	  OCAH_DOC_PRODUCT_MODULES="$(OCAH_HOME_MODULES)" \
	  OCAH_DOC_PRODUCT_ASSETS="$(OCAH_HOME_ASSETS)" \
	  bash "$(OCAH_DOC_DIR)/stage-docs.sh" --clean
	@rm -rf "$(OCAH_HOME_BUILD)"
	@echo "Cleaned Home documentation build artifacts."

OCAH_PHONY += \
  ocah-doc-home-setup \
  ocah-doc-home-html \
  ocah-doc-home-serve \
  ocah-doc-home-clean

endif
