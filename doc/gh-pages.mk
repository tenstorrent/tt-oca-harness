# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# GitHub Pages publish path (ghp-import -> gh-pages branch).
#
ifndef ocah_doc_ghpages_mk
ocah_doc_ghpages_mk := 1

# This is the combined Antora build's own output dir (see antora-playbook.yml output.dir)
OCAH_GHPAGES_DIR ?= $(OCAH_DOC_DIR)/_build/html_antora
OCAH_COMBINED_PLAYBOOK ?= $(OCAH_ROOT)/antora-playbook.yml
# Root-relative site URL once deployed, e.g. /tt-oca-harness for a plain
# org.github.io/repo host with no custom domain, or empty/unset if a
# custom domain fronts the repo root. Left as an override, not hardcoded.
OCAH_DOC_SITE_URL ?=

## Build the combined multi-book site (Home + every book, one Antora run).
.PHONY: ocah-doc-combined-html
ocah-doc-combined-html: ocah-doc-trm-setup ocah-doc-integrator-setup ocah-doc-programmer-setup ocah-doc-appnotes-setup ocah-doc-starting-setup ocah-doc-home-setup
	@command -v $(OCAH_ANTORA) >/dev/null 2>&1 || { \
		echo "error: node/npx is required to build the Antora site."; \
		echo "install Node.js, or run: ./scripts/docker-run.sh doc-html all"; \
		exit 1; \
	}
	@echo "Building combined OCAH documentation site (Antora, Home + books) with node $$(node --version 2>/dev/null)"
	@cd "$(OCAH_ROOT)" && SITE_SEARCH_PROVIDER=lunr $(OCAH_ANTORA) \
		$(if $(OCAH_DOC_SITE_URL),--url "$(OCAH_DOC_SITE_URL)") \
		$(OCAH_DOC_ANTORA_RELEASE_ARG) \
		"$(OCAH_COMBINED_PLAYBOOK)"
	@echo "Done: $(OCAH_GHPAGES_DIR)/ocah-home/latest/index.html"

## Stage the combined site for GitHub Pages: add PDFs + .nojekyll on top of
## the Antora output. No more manual copying of separate builds.
.PHONY: ocah-doc-stage-ghpages
ocah-doc-stage-ghpages: ocah-doc-combined-html
	@mkdir -p "$(OCAH_GHPAGES_DIR)/downloads"
	@touch "$(OCAH_GHPAGES_DIR)/.nojekyll"
	@if [ -f "$(OCAH_TRM_DIST)/$(OCAH_TRM_PDF)" ]; then \
		cp "$(OCAH_TRM_DIST)/$(OCAH_TRM_PDF)" "$(OCAH_GHPAGES_DIR)/downloads/"; \
	else \
		echo "warning: TRM PDF not found at $(OCAH_TRM_DIST)/$(OCAH_TRM_PDF), skipping (Downloads link will 404 until it exists)"; \
	fi
	@if [ -f "$(OCAH_INTEGRATOR_DIST)/$(OCAH_INTEGRATOR_PDF)" ]; then \
		cp "$(OCAH_INTEGRATOR_DIST)/$(OCAH_INTEGRATOR_PDF)" "$(OCAH_GHPAGES_DIR)/downloads/"; \
	else \
		echo "warning: Integrator Guide PDF not found at $(OCAH_INTEGRATOR_DIST)/$(OCAH_INTEGRATOR_PDF), skipping (Downloads link will 404 until it exists)"; \
	fi
	@if [ -f "$(OCAH_PROGRAMMER_DIST)/$(OCAH_PROGRAMMER_PDF)" ]; then \
		cp "$(OCAH_PROGRAMMER_DIST)/$(OCAH_PROGRAMMER_PDF)" "$(OCAH_GHPAGES_DIR)/downloads/"; \
	else \
		echo "warning: Programmer's Guide PDF not found at $(OCAH_PROGRAMMER_DIST)/$(OCAH_PROGRAMMER_PDF), skipping -- run: ./scripts/docker-run.sh doc-pdf programmer"; \
	fi
	@if [ -f "$(OCAH_APPNOTES_DIST)/$(OCAH_APPNOTES_PDF)" ]; then \
		cp "$(OCAH_APPNOTES_DIST)/$(OCAH_APPNOTES_PDF)" "$(OCAH_GHPAGES_DIR)/downloads/"; \
	else \
		echo "warning: Application Notes PDF not found at $(OCAH_APPNOTES_DIST)/$(OCAH_APPNOTES_PDF), skipping -- run: ./scripts/docker-run.sh doc-pdf appnotes"; \
	fi
	$(call ocah_stage_dashboard_data,$(OCAH_GHPAGES_DIR))
	@echo "Staged GitHub Pages tree at $(OCAH_GHPAGES_DIR)"
	@echo "Note: Datasheet PDFs (SMU/DTP/SEP/SMC/AOU) have no build pipeline yet -- those Downloads links will 404 until that content and a PDF build step exist."

## Push the already-staged tree to the gh-pages branch. This is what CI
## calls, after CI's own separate HTML/PDF build steps have already run.
.PHONY: ocah-doc-push-ghpages
ocah-doc-push-ghpages: ocah-doc-stage-ghpages
	@command -v uv >/dev/null 2>&1 || { \
		echo "error: uv is required to deploy GitHub Pages (ghp-import)."; \
		echo "install uv, or see https://docs.astral.sh/uv/"; \
		exit 1; \
	}
	@cd "$(OCAH_ROOT)" && uv run ghp-import -n -p -f "$(OCAH_GHPAGES_DIR)"
	@echo "Deployed to GitHub Pages (gh-pages branch)."

## All-in-one convenience for a manual local deploy: build everything
## (HTML + PDF for TRM/Integrator), stage, and push.
.PHONY: ocah-doc-deploy-ghpages
ocah-doc-deploy-ghpages:
	@$(MAKE) --no-print-directory -C "$(OCAH_ROOT)" ocah-doc-trm-pdf
	@$(MAKE) --no-print-directory -C "$(OCAH_ROOT)" ocah-doc-integrator-pdf
	@$(MAKE) --no-print-directory -C "$(OCAH_ROOT)" ocah-doc-push-ghpages

.PHONY: ocah-doc-ghpages-clean
ocah-doc-ghpages-clean:
	@rm -rf "$(OCAH_GHPAGES_DIR)"

# Hook into the shared clean target from doc/doc.mk.
ocah-doc-clean: ocah-doc-ghpages-clean

OCAH_PHONY += \
  ocah-doc-combined-html \
  ocah-doc-stage-ghpages \
  ocah-doc-push-ghpages \
  ocah-doc-deploy-ghpages \
  ocah-doc-ghpages-clean

endif
