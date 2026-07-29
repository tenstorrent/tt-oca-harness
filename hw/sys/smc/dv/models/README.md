<!-- SPDX-License-Identifier: Apache-2.0 -->
# SMC DV models

Behavioral / reference / simulation stand-ins for `--dut smc`
(`tb_top` → `smc_wrapper`).

| Path | Role |
|------|------|
| `mem/tb_smc_output_mem_responder.sv` | SYS_OUT AXI TB slave (`prim_ram_1p`) |
| `mem/tb_smc_i3c_mem_responder.sv` | I3C DAT/DCT TB memories |
| `mem/tb_smc_cpu_mem_responder.sv` | Shared with bare SMU TB; not used by SMC wrapper |
| `pll_wrap.sv` / `pvt_wrap.sv` / `regs/` | PeakRDL wraps pulled by Bender `smc_wrapper` |

CPU ROM/scratch/L1$, eFuse, GPIO-ctrl AXI, PLL/PVT macros are absorbed in
`smc_wrapper` / `smc_ip_integration` — not replicated as TB-local responders.
