# och_prim_generic

Behavioral models of standard cells that a synthesis flow replaces one-for-one
with a technology cell: multi-stage synchronizer flops, a metastability-hardened
flop, a negative latch, a clock NAND, a data mux and a handful of logic gates.

| Path | Contents |
|------|----------|
| `rtl/` | 15 behavioral `prim_*.sv` cells |

Every file here is a direct tech swap. The root [`Bender.yml`](../../../Bender.yml)
lists this directory under `not(synth)`, so simulation, lint and FPGA builds
use these models as-is, and a technology synthesis flow must supply a
replacement for each module under `-t synth`. A module with no technology
replacement belongs in [`../och_prim/`](../och_prim/) instead.

The cells OpenTitan already provides are not duplicated here. `prim_and2`,
`prim_buf`, `prim_clock_buf`, `prim_clock_gating`, `prim_clock_inv`,
`prim_clock_mux2`, `prim_flop`, `prim_flop_2sync`, `prim_inv`, `prim_xnor2` and
`prim_xor2` come from `vendor/lowRISC/opentitan/upstream/hw/ip/prim_generic/rtl/`,
which [`vendor/lowRISC/opentitan/Bender.yml`](../../../vendor/lowRISC/opentitan/Bender.yml)
guards with the same `not(synth)` target, and need the same technology
replacement.
