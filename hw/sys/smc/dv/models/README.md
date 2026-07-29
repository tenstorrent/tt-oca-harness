<!-- SPDX-License-Identifier: Apache-2.0 -->
# SMC DV models

Behavioral / reference / simulation stand-ins for `--dut smc_wrapper`
(`tb_top` → `smc_wrapper`).

| Path | Role |
|------|------|
| `mem/tb_smc_output_mem_responder.sv` | SYS_OUT AXI TB slave (`prim_ram_1p`) |
| `mem/tb_smc_i3c_mem_responder.sv` | I3C DAT/DCT TB memories |
| `pll_wrap.sv` / `pvt_wrap.sv` / `regs/` | PeakRDL wraps pulled by Bender `smc_wrapper` |

CPU ROM/scratch/L1$ live in `smc_cpu_mem_integration`. Bare-SMU CPU mem
responder lives under `hw/sys/smu/dv/shims/mem/`.

Bender consumes only `regs/gen/sv/*_addrmap_pkg.sv` from the PeakRDL tree.
