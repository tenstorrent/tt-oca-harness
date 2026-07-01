# Minimal makefile for Sphinx documentation
#

# You can set these variables from the command line, and also
# from the environment for the first two.
SPHINXOPTS    ?=
SPHINXBUILD  ?= sphinx-build
SOURCEDIR    = .
BUILDDIR     = _build

# Put it first so that "make" without argument is like "make help".
help:
	@echo "JTAG STAP IP Documentation Build System"
	@echo "========================================"
	@echo ""
	@echo "Quick Start:"
	@echo "  make html     - Build HTML documentation"
	@echo "  make view     - Build HTML and open in browser"
	@echo "  make pdf      - Build PDF documentation (requires LaTeX packages)"
	@echo "  make pdf-html - Build PDF via HTML (no LaTeX dependencies)"
	@echo "  make clean    - Remove build artifacts"
	@echo ""
	@echo "Development:"
	@echo "  make quick    - Fast HTML build (minimal warnings)"
	@echo "  make strict   - HTML build with warnings as errors"
	@echo "  make livehtml - Start live reload server for development"
	@echo ""
	@echo "Other:"
	@echo "  make all      - Build both HTML and PDF formats"
	@echo "  make linkcheck- Check documentation for broken links"
	@echo "  make info     - Show detailed build configuration"
	@echo ""
	@echo "Output Locations:"
	@echo "  HTML: $(BUILDDIR)/html/index.html"
	@echo "  PDF:  $(BUILDDIR)/latex/jtag-stap-ip.pdf"

.PHONY: help Makefile

# Build HTML documentation
html:
	@echo "Building HTML documentation..."
	@$(SPHINXBUILD) -b html "$(SOURCEDIR)" "$(BUILDDIR)/html" $(SPHINXOPTS)
	@echo "HTML documentation built in $(BUILDDIR)/html/"

# Build PDF documentation via LaTeX
pdf:
	@echo "Building PDF documentation..."
	@$(SPHINXBUILD) -b latex "$(SOURCEDIR)" "$(BUILDDIR)/latex" $(SPHINXOPTS)
	@echo "Running LaTeX (may need to run multiple times)..."
	@$(MAKE) -C "$(BUILDDIR)/latex" all-pdf
	@echo "PDF documentation built in $(BUILDDIR)/latex/jtag-stap-ip.pdf"

# Alternative PDF generation using basic pdflatex (fewer dependencies)
pdf-simple:
	@echo "Building simple PDF documentation..."
	@$(SPHINXBUILD) -b latex "$(SOURCEDIR)" "$(BUILDDIR)/latex-simple" $(SPHINXOPTS)
	@echo "Running basic pdflatex..."
	@cd "$(BUILDDIR)/latex-simple" && pdflatex jtag-stap-ip.tex
	@cd "$(BUILDDIR)/latex-simple" && pdflatex jtag-stap-ip.tex
	@echo "Simple PDF documentation built in $(BUILDDIR)/latex-simple/jtag-stap-ip.pdf"

# Build PDF from HTML using weasyprint (no LaTeX needed)
pdf-html:
	@echo "Building HTML for PDF conversion..."
	@$(SPHINXBUILD) -b html "$(SOURCEDIR)" "$(BUILDDIR)/html-for-pdf" $(SPHINXOPTS) \
		-D html_theme=basic -D html_sidebars= -D html_theme_options=
	@echo "Converting HTML to PDF with weasyprint..."
	@which weasyprint > /dev/null || (echo "Error: weasyprint not found. Install with: pip install weasyprint" && exit 1)
	@weasyprint "$(BUILDDIR)/html-for-pdf/index.html" "$(BUILDDIR)/jtag-stap-ip.pdf"
	@echo "PDF generated at $(BUILDDIR)/jtag-stap-ip.pdf"

# Build HTML and open in default browser
view: html
	@echo "Opening documentation in browser..."
	@python3 -c "import webbrowser, os; webbrowser.open('file://' + os.path.abspath('$(BUILDDIR)/html/index.html'))"

# Fast build for development (minimal warnings)
quick:
	@echo "Quick HTML build..."
	@$(SPHINXBUILD) -b html "$(SOURCEDIR)" "$(BUILDDIR)/html" $(SPHINXOPTS) -q

# Strict build with warnings as errors
strict:
	@echo "Strict HTML build (warnings as errors)..."
	@$(SPHINXBUILD) -b html "$(SOURCEDIR)" "$(BUILDDIR)/html" $(SPHINXOPTS) -W

# Start live reload server for development (requires sphinx-autobuild)
livehtml:
	@echo "Starting live reload server..."
	@which sphinx-autobuild > /dev/null || (echo "Error: sphinx-autobuild not found. Install with: pip install sphinx-autobuild" && exit 1)
	@sphinx-autobuild "$(SOURCEDIR)" "$(BUILDDIR)/html" $(SPHINXOPTS)

# Build all formats
all: html pdf
	@echo "All documentation formats built successfully"

# Check for broken links
linkcheck:
	@echo "Checking for broken links..."
	@$(SPHINXBUILD) -b linkcheck "$(SOURCEDIR)" "$(BUILDDIR)/linkcheck" $(SPHINXOPTS)
	@echo "Link check complete. See $(BUILDDIR)/linkcheck/output.txt"

# Show build configuration
info:
	@echo "Sphinx Build Configuration"
	@echo "==========================="
	@echo "SPHINXBUILD: $(SPHINXBUILD)"
	@echo "SOURCEDIR:   $(SOURCEDIR)"
	@echo "BUILDDIR:    $(BUILDDIR)"
	@echo "SPHINXOPTS:  $(SPHINXOPTS)"
	@echo ""
	@which $(SPHINXBUILD) > /dev/null && echo "Sphinx found: $$($(SPHINXBUILD) --version)" || echo "Sphinx not found"
	@which pdflatex > /dev/null && echo "pdflatex found: $$(pdflatex --version | head -1)" || echo "pdflatex not found"
	@which weasyprint > /dev/null && echo "weasyprint found: $$(weasyprint --version)" || echo "weasyprint not found"

# Clean build artifacts
clean:
	@echo "Cleaning build directory..."
	@rm -rf $(BUILDDIR)
	@echo "Build directory cleaned"

# Catch-all target: route all unknown targets to Sphinx using the new
# "make mode" option.  $(O) is meant as a shortcut for $(SPHINXOPTS).
%: Makefile
	@$(SPHINXBUILD) -M $@ "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)

