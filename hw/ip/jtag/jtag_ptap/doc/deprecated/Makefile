# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# Makefile for Sphinx documentation
#
# JTAG PTAP IP Documentation

# You can set these variables from the command line, and also
# from the environment for the first two.
SPHINXOPTS    ?=
SPHINXBUILD   ?= sphinx-build
SOURCEDIR     = .
BUILDDIR      = _build

# Use the repository's virtual environment (set up via bin/setup_env.sh)
# Try git first, fall back to OCH_ROOT, fail if neither available
_OCH_ROOT_GIT := $(shell git rev-parse --show-toplevel 2>/dev/null)
ifneq ($(_OCH_ROOT_GIT),)
  OCH_ROOT := $(_OCH_ROOT_GIT)
else ifndef OCH_ROOT
  $(error Not in a git repository and OCH_ROOT is not set)
endif
VENV_ACTIVATE = $(OCH_ROOT)/venv/bin/activate

# Put it first so that "make" without argument is like "make help".
help:
	@echo "JTAG PTAP Documentation Build System"
	@echo ""
	@echo "Usage:"
	@echo "  make html     - Build HTML documentation"
	@echo "  make clean    - Remove build artifacts"
	@echo "  make help     - Show this help message"
	@echo ""
	@echo "Note: Run 'source bin/setup_env.sh' from repository root before building."

.PHONY: help Makefile clean html

# Build HTML documentation using repository venv
html:
	@if [ -f "$(VENV_ACTIVATE)" ]; then \
		. $(VENV_ACTIVATE) && $(SPHINXBUILD) -M html "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O); \
	else \
		echo "Error: Virtual environment not found at $(VENV_ACTIVATE)"; \
		echo "Please run 'source bin/setup_env.sh' from the repository root first."; \
		exit 1; \
	fi
	@echo ""
	@echo "Build finished. The HTML pages are in $(BUILDDIR)/html."

# Clean build artifacts
clean:
	rm -rf $(BUILDDIR)
	@echo "Build directory cleaned."

# Build all formats
all: html

# Catch-all target: route all unknown targets to Sphinx using the new
# "make mode" option.  $(O) is meant as a shortcut for $(SPHINXOPTS).
%: Makefile
	@if [ -f "$(VENV_ACTIVATE)" ]; then \
		. $(VENV_ACTIVATE) && $(SPHINXBUILD) -M $@ "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O); \
	else \
		echo "Error: Virtual environment not found."; \
		echo "Please run 'source bin/setup_env.sh' from the repository root first."; \
		exit 1; \
	fi
