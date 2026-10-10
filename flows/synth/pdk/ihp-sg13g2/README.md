<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# IHP SG13G2

| Path | Contents |
|------|----------|
| `Bender.yml` | Package `pdk_ihp_sg13g2`; lists `prim/` under `all(synth, tech_ihp_sg13g2, not(emulation))` |
| `prim/` | SG13G2 cell implementations of all 29 modules in the [technology swap inventory](../../../../hw/common/ocah_prim_generic/README.md#technology-swap-inventory) |
| `yosys/tech.tcl` | Liberty files, tie cells and ABC settings for the Yosys flow |
| `yosys/abc.constr` | ABC driving cell and output load |

Each `prim/` file keeps the generic module's name, parameters and ports and
instantiates `sg13g2_*` standard cells marked `dont_touch`, so synthesis keeps
the cells written here. The cell definitions come from the PDK Liberty files.

## Mapping

The cell library lacks some functions the generic models describe. These
substitutions apply:

| Generic behavior | SG13G2 implementation |
|------------------|-----------------------|
| Flop reset to 1 | `sdfbbp_1` with `SET_B` on the reset and scan tied off |
| Flop without reset | `dfrbpq_1` with `RESET_B` tied high |
| Set-only synchronizer (`_s`) | `sdfbbp_1` chain with `SET_B` on `set_ni` |
| Metastability-hardened flop | `dfrbpq_1` |
| Negative-edge flop | `inv_1` on the clock ahead of the flop |
| Enable flop | `mux2_1` feedback ahead of the flop |
| `prim_ao222` | `a22oi_1` and two `nand2_1` |
| Random CDC delay of `prim_flop_2sync` | None; simulation only |

Every other prim is a single cell per bit with the matching function.
