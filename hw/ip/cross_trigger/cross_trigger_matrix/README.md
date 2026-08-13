# Cross Trigger Matrix IP

A configurable crossbar for routing cross trigger pulses between M source ports (CT_Dst) and N sink ports (CT_Src).

## Quick Start

### Register Generation

CTM's register collateral comes from the tree-wide flow, which reads the
committed `regs/cross_trigger_matrix.rdl` and writes `regs/gen/`:

```bash
make -f ocah.mk ocah-regen-regs TARGET=cross_trigger_matrix
```

Clean it with:

```bash
make -f ocah.mk ocah-regen-regs-clean TARGET=cross_trigger_matrix
```

### Port Count

The Mako templates that produced the RDL, the RTL, and the testbench from a
`--num-ct-src`/`--num-ct-dst` pair were not carried into this tree. The CTM here
is committed source, sized for the DTP cross-trigger topology of 26 CT_Src and 26
CT_Dst ports, from `dtp_pkg::DEFAULT_NUM_CTP` (16) plus
`dtp_pkg::DEFAULT_NUM_INT_CT` (10).

`NUM_CT_SRC` and `NUM_CT_DST` are module parameters, so a *smaller* matrix can be
instantiated without touching the sources; the unused CSRs simply stay
unconnected. Going *above* 26 CT_Src means extending both
`regs/cross_trigger_matrix.rdl` and the per-source select decode in
`rtl/cross_trigger_matrix.sv`, which names each `CT_SRCn_CONFIG_*` register
explicitly, and then rerunning the register flow above.

### Test

```bash
cd dv/tb_vcs
make test
```

## Generated Files

Register collateral from `regs/cross_trigger_matrix.rdl` lands under `regs/gen/`,
one directory per output format:

* `sv/` - register RTL module and its package
* `c/` - C header
* `py/` - Python header
* `svh/` - flattened SystemVerilog header
* `adoc/`, `html/` - documentation, included by the CTN memory map page

## Requirements

The register flow runs through `uv`, which installs peakrdl and the exporters
from the lockfile; nothing else needs to be on PATH.

## Documentation

The pages under `doc/` are AsciiDoc sources published with the rest of the OCAH
documentation. Build the TRM, which includes them under the DTP subsystem:

```bash
make -f ocah.mk ocah-doc-trm-html
```

## Architecture

The CTM consists of:

* **Register Interface**: AXI4-Lite interface for configuration
* **Source Selector Modules**: One per CT_Src port, implements selection and OR logic
* **Parameterized Design**: `NUM_CT_SRC` and `NUM_CT_DST` up to the 26 ports the committed RDL and select decode provide

See `doc/` for detailed architecture and implementation documentation.
