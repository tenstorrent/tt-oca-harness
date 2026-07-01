# Documentation Generator

## Installation of Sphinx tools

```bash
python -m venv venv
source venv/bin/activate

pip3 install sphinx
pip3 install sphinx-rtd-theme
pip3 install weasyprint
```

## Documentation Generation

### Quick Start

```bash
# Show available targets
make help

# Build HTML documentation
make html

# Build and view in browser
make view
```

### Output Formats

**HTML Documentation** (recommended):

```bash
make html
```

Open `_build/html/index.html` in your browser.

**PDF Documentation via HTML**:

```bash
make pdf-html
```

This generates `_build/jtag-stap-ip.pdf` using weasyprint (no LaTeX required).

**PDF Documentation via LaTeX**:

```bash
make pdf
```

Requires a full LaTeX installation. Generates `_build/latex/jtag-stap-ip.pdf`.

### Development Workflow

**Live reload server** (recommended for writing docs):

```bash
pip install sphinx-autobuild
make livehtml
```

Opens a browser with auto-refresh on file changes.

**Quick builds**:

```bash
make quick    # Fast build, minimal warnings
make strict   # Build with warnings as errors
```

### Additional Commands

```bash
make all       # Build both HTML and PDF
make linkcheck # Check for broken links
make info      # Show build configuration
make clean     # Remove build artifacts
```

## Documentation Structure

```
doc/
├── conf.py              # Sphinx configuration
├── index.rst            # Main documentation page
├── architecture.rst     # Architecture details
├── interface.rst        # Signal specifications
├── testing.rst          # Test information
├── Makefile             # Build system
└── README.md            # This file
```

## Current RTL Notes

The `jtag_stap` RTL includes a `security_disable_i` input that blocks access to the STAP host
port without blocking access to the internal 3DCR control path.

When `security_disable_i` is asserted:

- the 3DCR select bit is forced low on capture
- 3DCR updates are blocked so the stored enable state cannot be changed while disabled
- `host_tdo_o` is clamped low
- `host_tdo_oen_o` deasserts because the masked `stap_sel` no longer enables the host shift path
- `host_tap_ctrl_o.tms` falls back to the programmed hold state instead of the client TMS stream

This behavior is used by the DTP lifecycle gating flow to disable selected STAP host interfaces
while preserving required control and readback semantics.

## Unit Test

The STAP unit testbench includes dedicated coverage for `security_disable_i`.

```bash
source "$(git rev-parse --show-toplevel)/bin/setup_env.sh"
make -C hw/ip/jtag_stap/tb stap-test
```

## Writing Documentation

### reStructuredText Basics

Documentation uses reStructuredText (.rst) format:

```rst
Section Heading
===============

Subsection
----------

Subsubsection
~~~~~~~~~~~~~

* Bullet list item
* Another item

1. Numbered list
2. Second item

**Bold text**
*Italic text*
``Code text``

.. code-block:: verilog

   module example;
   endmodule

.. note::
   This is a note box.

.. warning::
   This is a warning box.
```

### Adding New Sections

1. Create a new `.rst` file in `doc/`
2. Add content using reStructuredText
3. Add to table of contents in `index.rst`:

```rst
.. toctree::
   :maxdepth: 2

   architecture
   interface
   testing
   newsection       # Add your new section here
```

4. Rebuild documentation:

```bash
make html
```

## Troubleshooting

### Sphinx not found

```bash
# Activate virtual environment
source venv/bin/activate

# Or install globally
pip3 install sphinx
```

### LaTeX errors

If `make pdf` fails:

1. Try `make pdf-html` instead (no LaTeX required)
2. Or install required LaTeX packages:
   - Ubuntu/Debian: `sudo apt-get install texlive-latex-extra`
   - MacOS: Install MacTeX
   - Windows: Install MiKTeX

### Weasyprint errors

```bash
pip3 install --upgrade weasyprint
```

On Linux, may need system dependencies:

```bash
sudo apt-get install python3-pip python3-cffi python3-brotli libpango-1.0-0 libpangoft2-1.0-0
```

### Build warnings

To see detailed warnings:

```bash
make clean
make strict
```

Warnings as errors help maintain documentation quality.

## Best Practices

1. **Write incrementally**: Use `make livehtml` for real-time feedback
2. **Check links**: Run `make linkcheck` before committing
3. **Test all formats**: Build both HTML and PDF to catch issues
4. **Follow structure**: Keep consistent heading hierarchy
5. **Add examples**: Code examples make documentation more useful
6. **Use tables**: Tables format signal lists nicely
7. **Cross-reference**: Link between sections using `:ref:`
8. **Update regularly**: Keep docs in sync with code changes

## Output Locations

After building, documentation is available at:

* **HTML**: `_build/html/index.html`
* **PDF (LaTeX)**: `_build/latex/jtag-stap-ip.pdf`
* **PDF (HTML)**: `_build/jtag-stap-ip.pdf`

## Publishing

To publish documentation:

1. Build HTML: `make html`
2. Copy `_build/html/` to web server or docs hosting
3. Or commit to repository for GitLab/GitHub Pages

## Notes

* HTML documentation renders best and is recommended
* PDF via HTML (`make pdf-html`) is easier than LaTeX
* LaTeX PDF generation has some package dependency issues
* Use `make view` for quick checks during development
