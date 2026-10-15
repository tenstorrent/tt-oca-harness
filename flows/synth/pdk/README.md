<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# Synthesis technologies

The RTL under `hw/` is technology independent. Its behavioral prim cells
(the [technology swap inventory](../../../hw/common/ocah_prim_generic/README.md#technology-swap-inventory))
are compiled for every target except `synth`. A synthesis flow selects
`-t synth -t tech_<tech>`, where `<tech>` is the directory name with hyphens
turned into underscores: `synth` drops the behavioral models and
`tech_<tech>` adds that technology's cell implementations in their place.

Each technology is one directory:

| Path | Contents |
|------|----------|
| `<tech>/Bender.yml` | Bender package listing `prim/` under `all(synth, tech_<tech>, not(emulation))` |
| `<tech>/prim/` | A cell-level implementation of every module in the swap inventory, with the same name, parameters and ports |
| `<tech>/yosys/tech.tcl` | Liberty files, tie cells and ABC settings, read by [`../yosys/scripts/init_tech.tcl`](../yosys/scripts/init_tech.tcl) |

To add a technology, create the directory, add it to the root
[`Bender.yml`](../../../Bender.yml) `dependencies` as
`pdk_<tech>: { path: "flows/synth/pdk/<tech>" }`, run `bender update`, and
register its PDK download in [`../yosys/pdks.mk`](../yosys/pdks.mk).

| Technology | Status |
|------------|--------|
| [`ihp-sg13g2`](ihp-sg13g2/) | All 29 prim cells; Yosys flow |
