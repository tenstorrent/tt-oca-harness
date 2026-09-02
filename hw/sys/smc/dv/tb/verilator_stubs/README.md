<!-- SPDX-License-Identifier: Apache-2.0 -->
# Verilator stubs (SMC)

Listed in `smc_sim_cfg.toml` `[build].stubs` ahead of the Bender
filelist so `-Wno-MODDUP` first-wins under Verilator. VCS ignores this list.
Also reused by `smu_wrapper` / bare `smu`.

**Tooling vs product (do not confuse):**

| Kind | Examples | Signoff? |
|------|----------|----------|
| Tooling shim (allowed here) | `prim_sync2/3` port remap + X-init | Compile-only; not a feature PASS |
| Product stub in DUT RTL | `pll_wrap`/`pvt_wrap` OKAY+0 | Green only as *signature/reachability* when labeled; protocol → deferred |
| TB glue | `tb_dfd_fault_inject` token `0xDB5C_AFE1` | Deferred (`tb_glue`) — never green feature PASS |

**Only tooling shims are allowed in this directory** — never override a
product module (`smc_reset_*`, `smc_dfx_*`, etc.).

| Stub | Role vs SEP |
|------|-------------|
| `prim_sync2.sv` | Same port remap need as `sep/dv/shims/prim/prim_sync2.sv`, but **hand-rolled + X-init** (SEP wraps `prim_flop_2sync` with `rst_ni=1`; SMC/SMU LSIO needs defined sync without reset) |
| `prim_sync3.sv` | 3-flop sync + X-init (SEP has no `prim_sync3` shim) |

Historical PeakRDL nested-struct Verilator codegen issues (B1) are worked
around via `disable_public_flat_rw` + `smc_public_scope.vlt`, not module stubs.
