# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# Temporary GitHub Pages publish path (ghp-import → gh-pages branch).
# Drop this whole mechanism once docs move to a custom-hosted landing page.
#
# Remove checklist:
#   - this file (and its -include from doc/doc.mk)
#   - doc/gh-pages-index.html
#   - ghp-import in pyproject.toml (+ uv.lock refresh)
#   - Deploy step / Pages URL overrides in .github/workflows/doc.yml
#   - Pages blurb + `make ocah-doc-deploy-ghpages` in README.md
#   - remote gh-pages branch + repo Settings → Pages (manual)

ifndef ocah_doc_ghpages_mk
ocah_doc_ghpages_mk := 1

OCAH_GHPAGES_DIR ?= $(OCAH_DOC_DIR)/_build/gh-pages
# Root-relative Antora site URLs (works for public org.github.io/repo and
# private *.pages.github.io hosts).
OCAH_GHPAGES_TRM_URL ?= /trm
OCAH_GHPAGES_INTEGRATOR_URL ?= /integrator
OCAH_GHPAGES_INDEX ?= $(OCAH_DOC_DIR)/gh-pages-index.html

## Stage TRM + Integrator HTML under doc/_build/gh-pages/ with a landing page.
.PHONY: ocah-doc-stage-ghpages
ocah-doc-stage-ghpages:
	@test -d "$(OCAH_TRM_BUILD)/html_antora" || { \
		echo "error: missing TRM HTML at $(OCAH_TRM_BUILD)/html_antora"; \
		echo "run: make ocah-doc-trm-html OCAH_DOC_SITE_URL=$(OCAH_GHPAGES_TRM_URL)"; \
		exit 1; \
	}
	@test -d "$(OCAH_INTEGRATOR_BUILD)/html_antora" || { \
		echo "error: missing Integrator HTML at $(OCAH_INTEGRATOR_BUILD)/html_antora"; \
		echo "run: make ocah-doc-integrator-html OCAH_DOC_SITE_URL=$(OCAH_GHPAGES_INTEGRATOR_URL)"; \
		exit 1; \
	}
	@test -f "$(OCAH_GHPAGES_INDEX)" || { echo "error: missing $(OCAH_GHPAGES_INDEX)"; exit 1; }
	@rm -rf "$(OCAH_GHPAGES_DIR)"
	@mkdir -p "$(OCAH_GHPAGES_DIR)/trm" "$(OCAH_GHPAGES_DIR)/integrator"
	@cp -a "$(OCAH_TRM_BUILD)/html_antora/." "$(OCAH_GHPAGES_DIR)/trm/"
	@cp -a "$(OCAH_INTEGRATOR_BUILD)/html_antora/." "$(OCAH_GHPAGES_DIR)/integrator/"
	@cp "$(OCAH_GHPAGES_INDEX)" "$(OCAH_GHPAGES_DIR)/index.html"
	@touch "$(OCAH_GHPAGES_DIR)/.nojekyll"
	@echo "Staged GitHub Pages tree at $(OCAH_GHPAGES_DIR)"

## Build both products (with Pages site URLs), stage, and push to gh-pages.
.PHONY: ocah-doc-deploy-ghpages
ocah-doc-deploy-ghpages:
	@command -v uv >/dev/null 2>&1 || { \
		echo "error: uv is required to deploy GitHub Pages (ghp-import)."; \
		echo "install uv, or see https://docs.astral.sh/uv/"; \
		exit 1; \
	}
	@$(MAKE) --no-print-directory -C "$(OCAH_ROOT)" \
		ocah-doc-trm-html OCAH_DOC_SITE_URL="$(OCAH_GHPAGES_TRM_URL)"
	@$(MAKE) --no-print-directory -C "$(OCAH_ROOT)" \
		ocah-doc-integrator-html OCAH_DOC_SITE_URL="$(OCAH_GHPAGES_INTEGRATOR_URL)"
	@$(MAKE) --no-print-directory -C "$(OCAH_ROOT)" ocah-doc-stage-ghpages
	@cd "$(OCAH_ROOT)" && uv run ghp-import -n -p -f "$(OCAH_GHPAGES_DIR)"
	@echo "Deployed to GitHub Pages (gh-pages branch)."

## Push an already-staged gh-pages tree (used by CI after HTML builds).
.PHONY: ocah-doc-push-ghpages
ocah-doc-push-ghpages: ocah-doc-stage-ghpages
	@command -v uv >/dev/null 2>&1 || { \
		echo "error: uv is required to deploy GitHub Pages (ghp-import)."; \
		echo "install uv, or see https://docs.astral.sh/uv/"; \
		exit 1; \
	}
	@cd "$(OCAH_ROOT)" && uv run ghp-import -n -p -f "$(OCAH_GHPAGES_DIR)"
	@echo "Deployed to GitHub Pages (gh-pages branch)."

.PHONY: ocah-doc-ghpages-clean
ocah-doc-ghpages-clean:
	@rm -rf "$(OCAH_GHPAGES_DIR)"

# Hook into the shared clean target from doc/doc.mk.
ocah-doc-clean: ocah-doc-ghpages-clean

OCAH_PHONY += \
  ocah-doc-stage-ghpages \
  ocah-doc-deploy-ghpages \
  ocah-doc-push-ghpages \
  ocah-doc-ghpages-clean

endif
