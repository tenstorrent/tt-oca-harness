# Entropy Source Documentation

This directory contains comprehensive Sphinx-based documentation for the entropy source hardware component.

## Overview

The entropy source implements a hardware true random number generator (TRNG) based on ring oscillator sampling with metastable D flip-flops. The design includes comprehensive health testing per NIST SP 800-90B requirements and post-processing for bias removal.

## Documentation Structure

The documentation is organized into the following sections:

- **Overview** - System requirements, design methodology, and key components
- **Architecture** - Detailed system architecture and component descriptions
- **Implementation** - Module hierarchy and SystemVerilog implementation details
- **Register Interface** - Complete memory map and programming model
- **Register Reference** - Interactive HTML documentation from SystemRDL
- **Verification** - Comprehensive testing methodology and results
- **Integration** - System-level integration guidelines and considerations
- **Tools** - Development environment and tool usage
- **Appendices** - Reference materials, templates, and troubleshooting

## Building the Documentation

### Prerequisites

Install the required Python packages. It's recommended to use a virtual environment:

```bash
# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install Sphinx and theme
pip install sphinx sphinx_rtd_theme

# Or install from requirements file
pip install -r requirements.txt
```

Create a `requirements.txt` file with:
```
sphinx>=4.0.0
sphinx_rtd_theme>=1.0.0
```

### Building HTML Documentation

First, ensure you have the prerequisites installed, then build:

```bash
# Check if Sphinx is available
make check-sphinx

# Build HTML documentation
make html

# Quick build (faster for development)
make html-fast

# Serve locally for viewing
make serve
# Then open http://localhost:8000 in your browser
```

**Note**: The HTML build automatically generates interactive register documentation from SystemRDL sources.

### Register Documentation Generation

The build system automatically generates interactive HTML register documentation:

```bash
# Generate register HTML from SystemRDL (included in main build)
make registers-html

# Clean register documentation
make registers-clean

# View register docs directly
open _build/html/registers/index.html
```

The register documentation is embedded in the main Sphinx documentation and provides:
- Interactive register map
- Detailed field descriptions
- Reset values and access permissions
- Generated directly from SystemRDL source

### Building PDF Documentation

```bash
# Install LaTeX dependencies first
sudo apt-get install texlive-latex-full  # Ubuntu/Debian
# or
brew install --cask mactex             # macOS

# Build PDF
make latexpdf
```

## Key Files

- `conf.py` - Sphinx configuration
- `index.rst` - Main documentation index
- `*.rst` - Individual documentation sections
- `Makefile` - Build automation
- Existing specification files and diagrams are referenced from the doc directory

## Design Features

The entropy source component includes:

- **12 Ring Oscillators** - Independent noise sources with tunable frequencies
- **Health Test Engine** - NIST SP 800-90B compliant monitoring
  - Repetition Count Test
  - Adaptive Proportion Test (1-4 bit patterns)
  - Markov Chain Test
- **Post-Processing** - Feedback shift register decorrelator for bias removal
- **APB Register Interface** - SystemRDL-generated configuration and status
- **Debug and Test Features** - Comprehensive characterization support

## Technology Stack

- **SystemVerilog** - RTL implementation
- **SystemRDL** - Register interface definition
- **PeakRDL** - Register block generation
- **iVerilog** - Open-source simulation
- **Sphinx** - Documentation generation

## Integration

The component integrates into larger systems via:

- **APB3/APB4** - 32-bit register access
- **AXI4-Stream** - Entropy data output
- **Interrupt Interface** - Health test and error reporting
- **Debug Interface** - Signal observation and characterization

## Compliance

The design meets requirements for:

- **NIST SP 800-90B** - Entropy source validation
- **NIST SP 800-22** - Statistical test suite compliance
- **AIS 31** - Common Criteria evaluation support
- **OpenTitan Standards** - Coding style and verification methodology

## Quick Start

1. **Setup Environment**:
   ```bash
   source venv/bin/activate  # Activate Python environment
   ```

2. **Generate Register RTL**:
   ```bash
   cd regs/
   peakrdl regblock entropy_source.rdl -o ../../../rtl/ --cpuif apb3-flat
   ```

3. **Build Documentation**:
   ```bash
   cd doc/
   make html
   ```

4. **Run Basic Verification**:
   ```bash
   cd tb/
   make ring      # Test ring oscillators
   make health    # Test health test modules
   make test      # Run full test suite
   ```

For detailed information, refer to the complete documentation sections.

The generated HTML pages can easily be viewed locally by: make serve
View the HTML by pointing the browser to https://localhost:8000
