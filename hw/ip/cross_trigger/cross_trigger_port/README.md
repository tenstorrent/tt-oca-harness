# Cross Trigger Port (CTP) IP

The Cross Trigger Port (CTP) is a module that controls the sending and receiving of cross triggers between chiplets using GPIO pads.

## Quick Start

### Generate Register Files

```bash
cd hw/ip/cross_trigger_port
python3 generate_ip.py
```

This generates all register-related files from the SystemRDL definition.

### Clean Generated Files

```bash
python3 generate_ip.py --clean
```

## Generation Script

### Usage

```bash
python3 generate_ip.py [OPTIONS]

Options:
  -c, --clean    Remove all generated files
  -h, --help     Show help message
```

**Note**: The `-i/--io-port` argument is accepted for compatibility with `generate_all.py`
but is ignored since CTP registers use a fixed AXI4-Lite interface.

## Generated Files

After running the generation script, the following files are created:

**Register Files** (from SystemRDL):
* `regs/rtl/cross_trigger_port_reg.sv` - Register RTL module
* `regs/rtl/cross_trigger_port_reg_pkg.sv` - Register package
* `regs/c/cross_trigger_port_reg.h` - C header
* `regs/py_headers/cross_trigger_port_reg.py` - Python header
* `regs/svh/cross_trigger_port_reg.svh` - SystemVerilog header
* `regs/adoc/cross_trigger_port_reg.adoc` - AsciiDoc documentation

## Integration with generate_all.py

CTP is included in the `tools/generate_all.py` script and is generated as part of
the standard IP generation flow. When using `generate_all.py`, CTP registers are
generated before CTM and CTN (which depend on CTP).

```bash
# Generate all IPs including CTP
python3 tools/generate_all.py -i axi4-lite

# Clean all IPs including CTP
python3 tools/generate_all.py --clean
```

## Requirements

* Python 3
* PeakRDL: `pip install systemrdl-compiler peakrdl-regblock`
* OCH_ROOT environment variable set (see repository root README)

## Documentation

See `CTP_SPECIFICATION.md` for detailed specification and `doc/` directory for
Sphinx documentation.

## Dependencies

None - CTP is a standalone IP used by:
- `hw/comp/cross_trigger_network` - Cross Trigger Network component
- `hw/dtp` - Debug and Test Ports module
