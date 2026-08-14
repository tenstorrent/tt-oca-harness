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

The matrix is sized for the DTP cross-trigger topology of 26 CT_Src and 26 CT_Dst
ports, from `dtp_pkg::DEFAULT_NUM_CTP` (16) plus `dtp_pkg::DEFAULT_NUM_INT_CT`
(10). The register map is the source of both bounds:

* `NUM_CT_SRC` must equal the number of `CT_SRC` array elements the register map
  declares. `rtl/cross_trigger_matrix.sv` asserts this against
  `CROSS_TRIGGER_MATRIX_CT_SRC_NUM` from the generated address package, so it
  follows a regenerated map without further edits.
* `NUM_CT_DST` may be 1 up to the width of the `CT_DST_SELECT` field. The RTL
  bounds it with `$bits` on that field and truncates the select mask to
  `NUM_CT_DST`, so a matrix narrower than the register map leaves the upper mask
  bits unused.

Both dimensions are parameters of the address map in
`regs/cross_trigger_matrix.rdl`, so resizing either one is a change to its default
there plus a rerun of the register flow above. The RTL needs no edit: the select
decode indexes the register array with its generate loop variable, and both
parameters follow the generated collateral.

`NUM_CT_DST` in the RDL is limited to 31, because the select mask and its reserved
remainder share `CONFIG_0`. Selecting among more destinations means adding a
`CONFIG_1` register in the doubleword reserved at each element's offset 0x4 and
extending the mask concatenation in the RTL to span both registers.

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

The RTL under `rtl/` is hand-written and parameterized; it indexes the generated
register array rather than enumerating one decode branch per port.

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
* **26x26 Default Configuration**: `NUM_CT_SRC` follows the register map array size; `NUM_CT_DST` may be narrowed

See `doc/` for detailed architecture and implementation documentation.
