<!-- SPDX-License-Identifier: Apache-2.0 -->
# SMC DV models

Behavioral / reference / simulation stand-ins for `--dut smc_wrapper`
(`tb_top` → `smc_wrapper`).

| Path | Role |
|------|------|
| `pll_wrap.sv` / `pvt_wrap.sv` / `regs/` | PeakRDL wraps pulled by Bender `smc_wrapper` |

SYS_OUT AXI slave is pulp `axi_sim_mem` in `tb/tb_top.sv` (SEP rom_boot style).
I3C DAT/DCT use `prim_ram_1p` generate blocks in `tb/tb_top.sv` (no custom
responder modules).

CPU ROM/scratch/L1$ live in `hw/top/smc_cpu_mem_integration.sv` (smc_wrapper,
smu_wrapper TB, and bare SMU TB).

Bender consumes only `regs/gen/sv/*_addrmap_pkg.sv` from the PeakRDL tree.
