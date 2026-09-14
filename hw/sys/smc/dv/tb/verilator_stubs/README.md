<!-- SPDX-License-Identifier: Apache-2.0 -->
# Verilator stubs (SMC)

Behavioural stand-ins for two `och_prim` synchroniser cells, used by the
Verilator flow only.

| File | Replaces | Difference from the product cell |
|------|----------|----------------------------------|
| `prim_sync2.sv` | `hw/common/och_prim/rtl/prim_sync2.sv` | same two-flop pipe, every stage `initial '0` |
| `prim_sync3.sv` | `hw/common/och_prim/rtl/prim_sync3.sv` | same three-flop pipe, every stage `initial '0` |

The port lists (`i_clk` / `i_d` / `o_q`) and parameters are identical to the
product cells, which are in the same compile. Under `SYNTHESIS`, defined on
every DV build, the product cells also reduce to a plain flop pipe, so the one
behaviour these files add is a defined `0` on the far side of the crossing
before the pipe has filled; the product cell shows X there on a four-state
simulator.

Enrolment: `smc_sim_cfg.toml` `[build].stubs`, emitted ahead of the Bender
filelist so `-Wno-MODDUP` first-definition-wins picks them under Verilator.
On VCS the runner drops any stub whose basename the Bender graph supplies, so
the product cells elaborate there. `smu_sim_cfg.toml` enrols the same two
files for the SMU bench.

Nothing under this directory may replace an SMC module (`smc_*`). PeakRDL
nested hwif structs are kept compilable by `disable_public_flat_rw` plus
`smc_public_scope.vlt`, never by a module stub.

Which enrolled leaves read a signal behind one of these crossings, what each
verdict reads, and the VCS control run that keeps those claims honest are
recorded in the *Bench stand-ins* section of
`hw/sys/smc/doc/dv/SMC_DEFERRED_DISPOSITION.adoc`.
