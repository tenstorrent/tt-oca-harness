<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# Vivado elaboration flow

This flow elaborates a block with Vivado (`synth_design -rtl`) to check that the
emulation view an integrator receives as `integration/filelists/<block>.emul.f`
reads and elaborates in Vivado. It does not synthesize, implement or time the
design, and it reads no constraints. Only `smu` includes it today.

## Running the flow

From the repository root, with `vivado` and `bender` on `PATH`:

```bash
make emul-vivado-all BLOCK=smu
make emul-vivado-all BLOCK=smu OCAH_VIVADO_INPUT=script
make emul-vivado-all BLOCK=smu OCAH_VIVADO_PART=<part>
```

`OCAH_VIVADO_INPUT` selects the source description Vivado reads:

- `flist` (default) reads the Bender file list (`bender script flist-plus`).
- `script` sources Bender's Vivado script (`bender script vivado`).

Both are generated with the Bender targets of `<block>.emul.f`
(`OCAH_EMUL_BENDER_TARGETS` in `flows/common.mk`). Vivado defines `SYNTHESIS`
itself during `synth_design`. The log, the generated file list and script, and
`reports/<top>_compile_order.rpt` are written to the block's
`build/emul/vivado/` directory. A successful run prints
`VIVADO_ELABORATION_PASS: <top>`.

## What the scripts adjust

`scripts/readiness.tcl` loads the sources into an in-memory project and applies
three settings before elaboration:

- `source_mgmt_mode` is `None`, so Vivado compiles in Bender's order instead of
  its own, which misses package references in parameter port lists.
- Every listed `.vh` and `.svh` file is compiled as SystemVerilog. Some carry
  packages, others macros that later sources use without including them. Bender's
  Vivado script leaves these files out, so in `script` mode they are added back in
  the position the file list gives them.
- Every `.v` file is compiled as SystemVerilog, because some vendored `.v`
  sources are written in SystemVerilog.
