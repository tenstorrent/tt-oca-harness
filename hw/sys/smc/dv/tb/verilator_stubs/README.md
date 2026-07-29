<!-- SPDX-License-Identifier: Apache-2.0 -->
# Verilator stubs (SMC)

Module overrides listed in `smc_sim_cfg.toml` `[build].stubs` **ahead of** the
Bender filelist so that with `-Wno-MODDUP` the first definition wins under
Verilator. VCS ignores this list.

| Stub | Role |
|------|------|
| `prim_sync2.sv` / `prim_sync3.sv` | Init-zero CDC flops for Verilator |
| `smc_dfx_ctrl_status_wrap.sv` | DFX wrap Verilator-safe |
| `smc_subsystem_resets.sv` / `smc_cool_reset_wrap.sv` / `smc_reset_unit.sv` | Reset-path Verilator overrides |
