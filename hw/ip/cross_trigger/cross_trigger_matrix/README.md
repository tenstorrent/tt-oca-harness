# Cross Trigger Matrix IP

A configurable crossbar for routing cross trigger pulses between M source ports (CT_Dst) and N sink ports (CT_Src).

## Quick Start

### Build and Test

The VCS testbench lives in `dv/tb_vcs`; see its README for how to run it.

### Register generation

CTM's register collateral comes from the tree-wide flow, which reads the
committed `regs/cross_trigger_matrix.rdl` and writes `regs/gen/`:

```bash
make -f ocah.mk ocah-regen-regs TARGET=cross_trigger_matrix
```

## Port Counts

The matrix is sized for the DTP cross-trigger topology of 26 CT_Src and 26
CT_Dst ports, from `dtp_pkg::DEFAULT_NUM_CTP` (16) plus
`dtp_pkg::DEFAULT_NUM_INT_CT` (10). Both counts are localparams in
`rtl/cross_trigger_matrix_pkg.sv` read from the generated collateral, not
module parameters:

* `NUM_CT_SRC` is the number of `CT_SRC` array elements the register map
  declares, from `CROSS_TRIGGER_MATRIX_CT_SRC_NUM` in the generated address
  package.
* `NUM_CT_DST` is the width of their `CT_DST_SELECT` field, from the register
  package. `rtl/cross_trigger_matrix.sv` checks it against `$bits` of the field
  the map actually generated.

Neither can be overridden at instantiation, because a matrix of a size the
register map cannot address has nothing to program it. Both dimensions are
parameters of the address map in `regs/cross_trigger_matrix.rdl`, so resizing
the matrix is a change to its defaults there plus a rerun of the register flow
above; the RTL follows without edit, since the select decode indexes the
register array with its generate loop variable.

A consequence for integrators: the register map must be generated for the port
count the enclosing design wires up. `cross_trigger_network` connects
`NUM_CTM_PORTS` signals and no longer sizes the matrix, so the two have to be
resized together. `dtp_pkg` checks that they were, failing elaboration if the
DTP's cross trigger port counts and this map disagree.

Each port occupies 8 bytes whatever the port count, so selecting among more than 32
destinations widens the select field to fill that space instead of moving any
addresses. The register map switches form on `NUM_CT_DST`:

| `NUM_CT_DST` | Register | Writes |
| --- | --- | --- |
| 1 to 32 | 32 bits, second word unmapped | immediate |
| 33 to 64 | 64 bits, accessed a word at a time | buffered |

Buffering is required above 32 because the select mask then spans both words: it
commits when the upper word is written, so a mask never takes effect
half-programmed, and firmware must write both words, low first. Below that
threshold nothing about the register or its programming changes, and at the DTP's
26 destinations the generated collateral is identical either way.

## Generated Files

The register flow writes `regs/gen/` from `regs/cross_trigger_matrix.rdl`:

* `regs/gen/sv/cross_trigger_matrix_reg.sv` - Register RTL module
* `regs/gen/sv/cross_trigger_matrix_reg_pkg.sv` - Register package
* `regs/gen/sv/cross_trigger_matrix_addrmap_pkg.sv` - Address and array-size constants
* `regs/gen/c/cross_trigger_matrix.h` - Firmware C header
* `regs/gen/c/cross_trigger_matrix_addr.h` - Raw address header
* `regs/gen/py/cross_trigger_matrix_reg.py` - Python header used by the cocotb tests
* `regs/gen/svh/cross_trigger_matrix_reg.svh` - Flattened SystemVerilog header
* `regs/gen/adoc/cross_trigger_matrix.adoc` - Register documentation, included by the CTN memory map page

## Documentation

The `doc/` pages are AsciiDoc partials published through the tree-wide Antora
site. Build the HTML books from the repository root:

```bash
make -f ocah.mk ocah-doc-html
```

## Architecture

The CTM consists of:

* **Register Interface**: AXI4-Lite interface for configuration
* **Source Selector Modules**: One per CT_Src port, implements selection and OR logic
* **26x26 Configuration**: both counts follow the register map, as described under Port Counts

See `doc/` for detailed architecture and implementation documentation.
