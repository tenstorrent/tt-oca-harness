<!-- SPDX-License-Identifier: Apache-2.0 -->
# SMC `tb/verilator_stubs`

Verilator-only **module overrides** for the SMC OSS DV flow. Same folder
convention as DTP (`hw/sys/dtp/dv/tb/verilator_stubs/`). SEP keeps equivalent
overrides under `hw/sys/sep/dv/shims/{prim,cpu}/`.

## Purpose (not "modules Verilator cannot find")

These files are **not** missing-RTL placeholders. They are intentional
substitutes listed in `[build].stubs` of `smc_sim_cfg.toml` /
`smc_wrapper_sim_cfg.toml` **ahead of** the Bender filelist so that with
`-Wno-MODDUP` the first definition wins.

| Audience | Behavior |
|----------|----------|
| **Verilator** | Uses the stub / wrap listed in `[build].stubs` |
| **VCS / Xcelium** | Typically keep the real RTL from the Bender graph (stubs unused or unused for GPIO) |

## Two families

### 1. Public-primitive / CDC port compatibility

| File | Why |
|------|-----|
| `prim_sync2.sv` | Remap legacy `i_clk`/`i_d`/`o_q` ports onto `prim_flop_2sync`; init-zero 2-flop (no `rst_ni`) |
| `prim_sync3.sv` | Same for `SYNC_STAGES=3` (I2C enable → LSIO CDC) |

### 2. Verilator 5.046 PeakRDL / C++ type workarounds

| File | Why |
|------|-----|
| `smc_dfx_ctrl_status_wrap.sv` | Avoid nested-struct C++ emission bugs in PeakRDL wrap |
| `smc_cool_reset_wrap.sv` | Same class of PeakRDL/reset_unit struct issue |
| `smc_reset_unit.sv` | Functional cold-reset chain without the broken struct path |
| `smc_subsystem_resets.sv` | Tie-offs; smoke uses the reset_ctrl path |
| `gpio_macro_wrapper.sv` | FOSS-only: real RTL's parameterized `gpio_shim` / PeakRDL structs collide in generated C++ (`Iz31_Uz31` / …). **Wrapper DUT only** (`smc_wrapper_sim_cfg.toml`) |
| `input_gpio_macro_wrapper.sv` | Same for the input GPIO macro (wrapper DUT) |

## With-CPU vs without-CPU (review clarification)

SMC does **not** use this folder to stub out the Rocket/Chipyard CPU cluster.

- **Bare `--dut smc`**: the real CPU RTL stays in the Bender graph. Memory ports
  are driven by behavioral models under `dv/models/mem/` (not by these stubs).
- **`--dut smc_wrapper`**: pad/GPIO macros may use the GPIO stubs above for
  Verilator C++ size/type reasons; CPU memory macros are still external ports
  (not absorbed the way `sep_wrapper` absorbed TCM/SRAM).

If a future flow compiles SMC **without** the CPU core for faster bring-up,
that override belongs with an explicit CPU stub (SEP pattern:
`shims/cpu/sep_cpu_stub.sv`) and a dedicated Bender/sim-cfg target — not as an
undocumented file dropped into this directory.

## Retirement criteria

Remove a stub from `[build].stubs` when the upstream RTL (or a newer Verilator)
builds cleanly without the override, then delete the unused file.
