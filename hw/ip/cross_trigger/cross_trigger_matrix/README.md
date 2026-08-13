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
is committed source, sized for the DTP cross-trigger topology of 26 CT_Src and
26 CT_Dst ports, from `dtp_pkg::DEFAULT_NUM_CTP` (16) plus
`dtp_pkg::DEFAULT_NUM_INT_CT` (10).

`NUM_CT_SRC` and `NUM_CT_DST` are module parameters, but only `NUM_CT_DST` is
adjustable, and only downward:

* `NUM_CT_SRC` must be 26. The `NumCtSrcMatchesGen_A` assertion in
  `rtl/cross_trigger_matrix.sv` enforces it, because the select decode there
  names each of the 26 `CT_SRCn_CONFIG_0` registers explicitly.
* `NUM_CT_DST` may be 1 to 26. The `CT_DST_SELECT` field is 26 bits wide with
  bits 31:26 reserved, and the decode truncates the mask to `NUM_CT_DST`, so a
  narrower matrix leaves the upper mask bits unused. The range assertion
  nominally permits up to `MAX_NUM_CT_DST` (64), but a wider matrix has no
  register bits to select with: the second config register the decode comments
  refer to (`CT_SRCn_CONFIG_1`, for CT_Dst[63:32]) is not part of this
  configuration.

Changing either dimension means editing `regs/cross_trigger_matrix.rdl` and the
select decode in `rtl/cross_trigger_matrix.sv` together, then rerunning the
register flow above.

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
* **Fixed 26x26 Configuration**: `NUM_CT_SRC` is pinned at 26; `NUM_CT_DST` may be narrowed

See `doc/` for detailed architecture and implementation documentation.
