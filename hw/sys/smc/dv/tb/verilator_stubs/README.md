<!-- SPDX-License-Identifier: Apache-2.0 -->
# Verilator stubs (SMC)

Behavioural stand-in for the `och_prim` three-stage synchroniser. The runner
compiles it on Verilator and Xcelium and drops it on VCS.

| File | Replaces | Difference from the product cell |
|------|----------|----------------------------------|
| `prim_sync3.sv` | `hw/common/och_prim/rtl/prim_sync3.sv` | same three-flop pipe, every stage `initial '0` |

The port list (`clk_i` / `d_i` / `q_o`) and parameters are identical to the
product cell, which is in the same compile. The product cell's
`prim_cdc_rand_delay` stage passes its input through unless a run sets
`+cdc_instrumentation_enabled=1`, so it too is a plain flop pipe; the one
behaviour this file adds is a defined `0` on the far side of the crossing
before the pipe has filled; the product cell shows X there on a four-state
simulator. Two-stage crossings use OpenTitan `prim_flop_2sync`, which has a
reset port and no stand-in.

Enrolment: `smc_sim_cfg.toml` `[build].stubs`. The runner
(`tools/dv/runlib/stages.py`) filters that list only when `tool == "vcs"`:
there it drops any stub whose basename the Bender graph supplies, so the
product cell elaborates on VCS. On Verilator and Xcelium it keeps both files
and emits the stub ahead of the Bender filelist, so the stub and the product
cell are in the same compile; Verilator's `-Wno-MODDUP` first-definition-wins picks
the stub, and no Xcelium build of this bench is recorded. The SMU bench
enrols the same file in the `[build].stubs` of
`hw/sys/smu/dv/smu_sim_cfg.toml` (`--dut smu`).

Nothing under this directory may replace an SMC module (`smc_*`). PeakRDL
nested hwif structs are kept compilable by `disable_public_flat_rw` plus
`smc_public_scope.vlt`, never by a module stub.

Which enrolled leaves read a signal behind one of these crossings, what each
verdict reads, and the VCS control run that keeps those claims honest are
recorded in the *Bench stand-ins* section of
`docs/SMC_VPLAN.adoc` (Known Limitations, "SMC deferred and OUT disposition").
