<!-- SPDX-License-Identifier: Apache-2.0 -->
# Verilator stubs (SMC)

Listed in `smc_sim_cfg.toml` `[build].stubs` ahead of the Bender
filelist so `-Wno-MODDUP` first-wins under Verilator. VCS ignores this list.
Also reused by `smu_wrapper` / bare `smu`.

**Tooling vs product (do not confuse):**

| Kind | Examples | Signoff? |
|------|----------|----------|
| Tooling shim (allowed here) | `prim_sync2/3` port remap + X-init | Compile-only; not a feature PASS |
| Product stub in DUT RTL | `pll_wrap`/`pvt_wrap` OKAY+0 | Green only as *signature/reachability* when labeled; protocol not covered |
| TB glue | `tb_dfd_fault_inject` token `0xDB5C_AFE1` | Never green feature PASS |

**Only tooling shims are allowed in this directory** — never override a
product module (`smc_reset_*`, `smc_dfx_*`, etc.).

| Stub | Role |
|------|------|
| `prim_sync2.sv` | Hand-rolled two-flop sync with X-init; the SMC/SMU LSIO path needs a defined sync without a reset input |
| `prim_sync3.sv` | Hand-rolled three-flop sync with X-init |

PeakRDL nested hwif structs break Verilator's public C++ codegen; that is
handled by `disable_public_flat_rw` + `smc_public_scope.vlt`, never by a module stub.
