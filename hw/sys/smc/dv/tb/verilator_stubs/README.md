<!-- SPDX-License-Identifier: Apache-2.0 -->
# Verilator stubs (SMC)

Behavioural stand-ins for two `och_prim` synchroniser cells. The runner
compiles them on Verilator and Xcelium and drops them on VCS.

| File | Replaces | Difference from the product cell |
|------|----------|----------------------------------|
| `prim_sync2.sv` | `hw/common/och_prim/rtl/prim_sync2.sv` | same two-flop pipe, every stage `initial '0` |
| `prim_sync3.sv` | `hw/common/och_prim/rtl/prim_sync3.sv` | same three-flop pipe, every stage `initial '0` |

The port lists (`i_clk` / `i_d` / `o_q`) and parameters are identical to the
product cells, which are in the same compile. `RANDOM_DELAY_ENABLE` is not
defined on any DV build, so the product cells' `prim_sync_randomized_delay`
stage passes its input through and they too are a plain flop pipe; the one
behaviour these files add is a defined `0` on the far side of the crossing
before the pipe has filled; the product cell shows X there on a four-state
simulator.

Enrolment: `smc_sim_cfg.toml` `[build].stubs`. The runner
(`tools/dv/runlib/stages.py`) filters that list only when `tool == "vcs"`:
there it drops any stub whose basename the Bender graph supplies, so the
product cells elaborate on VCS. On Verilator and Xcelium it keeps both files
and emits them ahead of the Bender filelist, so the stub and the product cell
are in the same compile; Verilator's `-Wno-MODDUP` first-definition-wins picks
the stub, and no Xcelium build of this bench is recorded. The SMU benches
enrol the same two files: `hw/sys/smu/dv/smu_sim_cfg.toml` (`--dut smu`) and
`hw/sys/smu/dv/smu_block_sim_cfg.toml` (`--dut smu_block`), each in its
`[build].stubs`.

Nothing under this directory may replace an SMC module (`smc_*`). PeakRDL
nested hwif structs are kept compilable by `disable_public_flat_rw` plus
`smc_public_scope.vlt`, never by a module stub.

Which enrolled leaves read a signal behind one of these crossings, what each
verdict reads, and the VCS control run that keeps those claims honest are
recorded in the *Bench stand-ins* section of
`hw/sys/smc/doc/dv/SMC_DEFERRED_DISPOSITION.adoc`.
