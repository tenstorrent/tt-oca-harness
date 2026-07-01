# Cross Trigger Matrix IP

A configurable crossbar for routing cross trigger pulses between M source ports (CT_Dst) and N sink ports (CT_Src).

## Quick Start

### Generate IP Files

The IP uses template-based generation to create register files based on the number of CT_Src and CT_Dst ports:

```bash
cd hw/ip/cross_trigger_matrix
python3 generate_ip.py --num-ct-src <N> --num-ct-dst <M>
```

Where:
- `<N>` is the number of CT_Src ports (1-32, default: 4)
- `<M>` is the number of CT_Dst ports (1-32, default: 4)

This script:
1. Generates the SystemRDL register definition file from a Mako template
2. Generates all register-related files (RTL, headers, documentation) using PeakRDL
3. Generates the main RTL module (`cross_trigger_matrix.sv`) from a template
4. Generates the RTL package and testbench from templates

### Build and Test

```bash
# Generate register files (if not already done)
python3 generate_ip.py --num-ct-src 4

# Run tests
cd tb_vcs
make test
```

### Integration with generate_all.py

CTM is included in the `tools/generate_all.py` script. When using `generate_all.py`,
CTM is generated with `num-ct-src` and `num-ct-dst` set to `num_ctp + num_int_ct`
(default: 16 + 9 = 25 ports).

```bash
# Generate all IPs including CTM with 25 ports
python3 tools/generate_all.py -i axi4-lite

# Generate with custom CTM port count
python3 tools/generate_all.py -i axi4-lite --num-ctp 8 --num-int-ct 4
```

## Generation Script

### Usage

```bash
python3 generate_ip.py [OPTIONS]

Options:
  -n, --num-ct-src <N>    Number of CT_Src ports (1-32, default: 4)
  -m, --num-ct-dst <M>    Number of CT_Dst ports (1-32, default: 4)
  -c, --clean              Remove all generated files
  -h, --help               Show help message
```

### Examples

Generate IP with 8 CT_Src ports and 16 CT_Dst ports:
```bash
python3 generate_ip.py --num-ct-src 8 --num-ct-dst 16
```

Generate IP with default 4 CT_Src and 4 CT_Dst ports:
```bash
python3 generate_ip.py
```

Generate IP with 4 CT_Src ports and 8 CT_Dst ports:
```bash
python3 generate_ip.py --num-ct-dst 8
```

Clean all generated files:
```bash
python3 generate_ip.py --clean
```

## Generated Files

After running the generation script, the following files are created:

**Register Files** (from SystemRDL):
* `regs/cross_trigger_matrix.rdl` - SystemRDL register definition (generated from template)
* `regs/rtl/cross_trigger_matrix_reg.sv` - Register RTL module
* `regs/rtl/cross_trigger_matrix_reg_pkg.sv` - Register package
* `regs/c/cross_trigger_matrix_reg.h` - C header
* `regs/py_headers/cross_trigger_matrix_reg.py` - Python header
* `regs/svh/cross_trigger_matrix_reg.svh` - SystemVerilog header
* `regs/rst/cross_trigger_matrix_reg.rst` - reStructuredText documentation (for Sphinx)

**RTL Files** (from templates):
* `rtl/cross_trigger_matrix.sv` - Main RTL module with generated case statements matching NUM_CT_SRC
* `rtl/cross_trigger_matrix_pkg.sv` - Package with parameterized defaults (DEFAULT_NUM_CT_SRC, DEFAULT_NUM_CT_DST)
* `tb_vcs/tb_cross_trigger_matrix.sv` - Testbench with parameterized localparams (NUM_CT_SRC, NUM_CT_DST)

**Note**: The main RTL module, package, and testbench are generated with parameters matching the generation script arguments. The main RTL module only includes case statements for the configured number of CT_SRC ports, ensuring the RTL matches the generated register definitions exactly.

## Requirements

* Python 3 with Mako template library: `pip install mako`
* PeakRDL: `pip install systemrdl-compiler peakrdl-regblock`
* OCH_ROOT environment variable set (see repository root README)

## Documentation

Full documentation is available in the `doc/` directory. Build with:

```bash
cd doc
make html
```

Then open `_build/html/index.html` in your browser.

## Architecture

The CTM consists of:

* **Register Interface**: AXI4-Lite interface for configuration
* **Source Selector Modules**: One per CT_Src port, implements selection and OR logic
* **Parameterized Design**: Supports 1-32 CT_Src and 1-32 CT_Dst ports

See `doc/` for detailed architecture and implementation documentation.
