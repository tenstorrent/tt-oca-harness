<!-- SPDX-License-Identifier: Apache-2.0 -->
# Verilator stubs (SMC)

Listed in `smc_wrapper_sim_cfg.toml` `[build].stubs` ahead of the Bender
filelist so `-Wno-MODDUP` first-wins under Verilator. VCS ignores this list.

**Only tooling shims are allowed here** — never override a product module
(`smc_reset_*`, `smc_dfx_*`, etc.).

| Stub | Role |
|------|------|
| `prim_sync2.sv` / `prim_sync3.sv` | OSS `prim_flop_*sync` port remap + X-init (product `och_prim` still uses private `.i_CK` ports; see README B2) |

Historical PeakRDL nested-struct Verilator codegen issues (B1) are worked
around via `disable_public_flat_rw` + `smc_public_scope.vlt`, not module stubs.
