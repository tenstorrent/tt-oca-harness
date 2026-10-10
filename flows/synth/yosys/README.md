<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# Yosys synthesis flow

**Status: work in progress.** This flow provides basic RTL elaboration and
technology mapping for `smc`, `sep`, `smu`, `dtp`, and the vendored `aou`
package. It is not a qualified synthesis or sign-off flow.

The default driver produces a technology-mapped Verilog netlist and Yosys
reports for IHP SG13G2. Timing constraints are not consumed, and the flow has
no STA or place-and-route stage. Its reports must therefore not be treated as
sign-off results.

## Running the flow

From the repository root:

```bash
make synth-yosys-all
make synth-yosys-all BLOCK=smu
make synth-yosys-all BLOCK=smu TECH=ihp-sg13g2
```

Omit `BLOCK` to run every discovered flow descriptor. `ihp-sg13g2` is the
only PDK with synthesis technology data. The selected PDK is downloaded on
demand with `ciel` into `PDK_ROOT`, which defaults to `local/pdks`; see
[`pdks.md`](pdks.md).

A native run requires `bender`, `ciel`, `slang`, and Yosys with the
`yosys-slang` plugin on `PATH`. The repository's Nix-built container provides
these tools:

```bash
./scripts/docker-run.sh run-here make synth-yosys-all BLOCK=smu
```

Outputs are written below each block's
`build/synth/<tech>/{out,tmp,reports}` directory.

## Implemented scope

- `yosys.mk` generates a Bender file list and dispatches synthesis per block.
  The list adds the `synth` and `tech_<TECH>` targets, which replace the
  behavioral prim cells with the technology's cell-level implementations
  under [`../pdk/<tech>/prim/`](../pdk/). VeeR EL2's behavioral TCM models stay in the list until the technology has
  SRAM macro wrappers.
- `scripts/synth.tcl` elaborates SystemVerilog, performs generic synthesis,
  maps to the selected technology with ABC, and writes netlists and reports.
- `scripts/readiness.tcl` provides a structural driver, without technology
  mapping, that rejects latches outside the modules allowlisted in the script
  (clock gates and the retained eFuse token digest) and unresolved blackboxes.
  It reads the technology's Liberty files only to define the cells the prim
  implementations instantiate.
- [`../pdk/ihp-sg13g2/`](../pdk/ihp-sg13g2/) is the only current technology;
  its `yosys/tech.tcl` names the Liberty files and mapping settings.
- Block SDC files and the helpers in `flows/synth/constraints/` exist, but the
  Yosys flow does not read them.

## Provenance

This flow was adapted from the
[Croc Yosys synthesis flow](https://github.com/pulp-platform/croc/tree/main/yosys).
