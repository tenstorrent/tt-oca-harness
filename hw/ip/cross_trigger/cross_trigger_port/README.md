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

## Documentation

See `doc/CTP_SPECIFICATION.md` for the detailed specification. The AsciiDoc pages
under `doc/` are published with the rest of the OCAH documentation; build the TRM,
which includes them under the DTP subsystem:

```bash
make -f ocah.mk ocah-doc-trm-html
```

## Dependencies

None - CTP is a standalone IP used by:
- `hw/ip/cross_trigger/cross_trigger_network` - Cross Trigger Network
- `hw/sys/dtp` - Debug and Test Ports subsystem
