# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

#==============================================================================
# Cross Trigger Matrix Documentation Build System
# Makefile for Sphinx documentation generation
#==============================================================================

# Build configuration
SPHINXOPTS    ?=
SPHINXBUILD  ?= sphinx-build
SOURCEDIR    = .
BUILDDIR     = _build

# Python and virtual environment
PYTHON       = python3
VENV_DIR     = venv
VENV_ACTIVATE = $(VENV_DIR)/bin/activate

# SystemRDL and register generation
RDL_SOURCE   = ../data/registers/rdl/cross_trigger_matrix.rdl
RDL_HTML_DIR = _build/html/registers
RDL_HTML_OUT = $(RDL_HTML_DIR)/index.html

#==============================================================================
# PRIMARY TARGETS
#==============================================================================

# Default target shows help
all: help

# Build HTML documentation (most common use case)
html: check-sphinx registers-html
	@echo "=== Building HTML Documentation ==="
	@$(SPHINXBUILD) -b html "$(SOURCEDIR)" "$(BUILDDIR)/html" $(SPHINXOPTS)
	@echo ""
	@echo "✓ Build complete! HTML pages are in $(BUILDDIR)/html/"
	@echo "  Open $(BUILDDIR)/html/index.html in your browser"

# Build PDF documentation
pdf: check-sphinx
	@echo "=== Building PDF Documentation ==="
	@$(SPHINXBUILD) -b latex "$(SOURCEDIR)" "$(BUILDDIR)/latex" $(SPHINXOPTS)
	@make -C $(BUILDDIR)/latex all-pdf
	@echo ""
	@echo "✓ PDF build complete! Document is at $(BUILDDIR)/latex/CrossTriggerMatrix.pdf"

# Build all formats
all-formats: html pdf
	@echo "✓ All documentation formats built successfully!"

#==============================================================================
# DEVELOPMENT TARGETS
#==============================================================================

# Fast HTML build (no cleanup, for development)
html-fast:
	@echo "=== Fast HTML Build ==="
	@$(SPHINXBUILD) -b html "$(SOURCEDIR)" "$(BUILDDIR)/html" $(SPHINXOPTS)
	@echo "✓ Fast build complete!"

# Live reload development server
serve: html
	@echo "=== Starting Documentation Server ==="
	@echo "Checking for available port..."
	@PORT=8001; \
	while lsof -Pi :$$PORT -sTCP:LISTEN -t >/dev/null 2>&1; do \
		echo "Port $$PORT is in use, trying $$(($$PORT + 1))"; \
		PORT=$$(($$PORT + 1)); \
		if [ $$PORT -gt 8010 ]; then \
			echo "No available ports found in range 8001-8010"; \
			exit 1; \
		fi; \
	done; \
	echo "Server will be available at: http://localhost:$$PORT"; \
	echo "Press Ctrl+C to stop the server"; \
	cd $(BUILDDIR)/html && $(PYTHON) -m http.server $$PORT

#==============================================================================
# SYSTEMRDL REGISTER DOCUMENTATION
#==============================================================================

# Generate HTML documentation from SystemRDL
registers-html: check-peakrdl
	@echo "=== Generating Register HTML from SystemRDL ==="
	@mkdir -p $(RDL_HTML_DIR)
	@if [ -f "$(RDL_SOURCE)" ]; then \
		peakrdl html "$(RDL_SOURCE)" -o "$(RDL_HTML_DIR)" --title "Cross Trigger Matrix Registers"; \
		echo "✓ Register HTML generated in $(RDL_HTML_DIR)/"; \
	else \
		echo "⚠ SystemRDL source not found: $(RDL_SOURCE)"; \
		echo "  Creating placeholder register documentation..."; \
		mkdir -p $(RDL_HTML_DIR); \
		echo '<html><head><title>Register Documentation</title></head><body><h1>Register Documentation</h1><p>SystemRDL source file not found. Please generate register files first.</p><p>Expected location: $(RDL_SOURCE)</p></body></html>' > $(RDL_HTML_OUT); \
	fi

# Check if PeakRDL is available
check-peakrdl:
	@command -v peakrdl >/dev/null 2>&1 || { \
		echo "❌ PeakRDL not found!"; \
		echo "Install with: pip install systemrdl-compiler peakrdl-html"; \
		exit 1; \
	}

# Clean register HTML
registers-clean:
	@echo "=== Cleaning Register HTML ==="
	@rm -rf $(RDL_HTML_DIR)
	@echo "✓ Cleaned $(RDL_HTML_DIR)/"

#==============================================================================
# SETUP AND ENVIRONMENT TARGETS
#==============================================================================

# Check if Sphinx is available
check-sphinx:
	@command -v sphinx-build >/dev/null 2>&1 || { \
		echo "❌ Sphinx not found!"; \
		echo "Install with: pip install sphinx sphinx_rtd_theme"; \
		exit 1; \
	}

#==============================================================================
# VALIDATION AND QUALITY TARGETS
#==============================================================================

# Quick syntax validation
syntax-check:
	@echo "=== Checking RST Syntax ==="
	@$(PYTHON) -c "import docutils.core; docutils.core.publish_file(source_path='index.rst', writer_name='html')" >/dev/null 2>&1 && \
		echo "✓ Basic RST syntax appears valid" || \
		echo "⚠ Potential RST syntax issues detected"

# Link checking
linkcheck: check-sphinx
	@echo "=== Checking External Links ==="
	@$(SPHINXBUILD) -b linkcheck "$(SOURCEDIR)" "$(BUILDDIR)/linkcheck" $(SPHINXOPTS)
	@echo "Link check results in $(BUILDDIR)/linkcheck/"

# Build with warnings as errors (strict mode)
strict: check-sphinx
	@echo "=== Building with Warnings as Errors ==="
	@$(SPHINXBUILD) -W -b html "$(SOURCEDIR)" "$(BUILDDIR)/html" $(SPHINXOPTS)

#==============================================================================
# MAINTENANCE TARGETS
#==============================================================================

# Clean all build artifacts
clean: registers-clean
	@echo "=== Cleaning Build Artifacts ==="
	rm -rf $(BUILDDIR)/*
	@echo "✓ Cleaned $(BUILDDIR)/"

#==============================================================================
# UTILITY TARGETS
#==============================================================================

# Show help
help:
	@echo "================================================================================"
	@echo "                    CROSS TRIGGER MATRIX DOCUMENTATION BUILD"
	@echo "================================================================================"
	@echo ""
	@echo "QUICK START:"
	@echo "  make html        - Build HTML documentation with registers"
	@echo "  make serve      - Build and serve documentation locally"
	@echo "  make pdf        - Build PDF documentation"
	@echo "  make clean      - Clean build artifacts"
	@echo ""
	@echo "REQUIREMENTS:"
	@echo "  - Python 3.7+"
	@echo "  - sphinx, sphinx_rtd_theme (pip install sphinx sphinx_rtd_theme)"
	@echo "  - systemrdl-compiler, peakrdl-html (for register docs)"
	@echo ""

.PHONY: all html pdf all-formats html-fast serve
.PHONY: registers-html registers-clean check-peakrdl
.PHONY: check-sphinx syntax-check linkcheck strict
.PHONY: clean help
