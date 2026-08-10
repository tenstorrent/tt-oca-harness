# Cross Trigger Port (CTP) IP

The Cross Trigger Port (CTP) is a module that controls the sending and receiving of cross triggers between chiplets using GPIO pads.

## Quick Start

### Generate Register Files

```bash
make -f ocah.mk ocah-regen-regs TARGET=cross_trigger_port
```

This generates all register collateral from `regs/cross_trigger_port.rdl`.
Omit `TARGET` to regenerate every block in the tree.

### Clean Generated Files

```bash
make -f ocah.mk ocah-regen-regs-clean TARGET=cross_trigger_port
```

## Generated Files

Everything lands under `regs/gen/`, one directory per output format:

* `sv/` - register RTL module and its package
* `c/` - C header
* `py/` - Python header
* `svh/` - flattened SystemVerilog header
* `adoc/`, `html/` - documentation

## Requirements

The flow runs through `uv`, which installs peakrdl and the exporters from the
lockfile; nothing else needs to be on PATH.
* PeakRDL: `pip install systemrdl-compiler peakrdl-regblock`
* OCH_ROOT environment variable set (see repository root README)

## Documentation

See `CTP_SPECIFICATION.md` for detailed specification and `doc/` directory for
Sphinx documentation.

## Dependencies

None - CTP is a standalone IP used by:
- `hw/comp/cross_trigger_network` - Cross Trigger Network component
- `hw/dtp` - Debug and Test Ports module
