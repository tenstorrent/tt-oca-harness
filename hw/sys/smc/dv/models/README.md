<!-- SPDX-License-Identifier: Apache-2.0 -->
# SMC DV models

Behavioral / reference / simulation stand-ins for `--dut smc`
(`tb_top` → `smc_wrapper`). Taxonomy:

| Kind | Location |
|------|----------|
| Protocol VIP | `hw/common/dv/vip/ocah_*_vip/` |
| Behavioral models | `hw/sys/smc/dv/models/` (this tree) |
| Verilator overrides | `hw/sys/smc/dv/tb/verilator_stubs/` |
| Design RTL bridges | RTL / `hw/top/` (not under `dv/`) |

## Contents

| Path | Role |
|------|------|
| `mem/tb_smc_output_mem_responder.sv` | SYS_OUT AXI TB slave (`prim_ram_1p`) |
| `mem/tb_smc_i3c_mem_responder.sv` | I3C DAT/DCT TB memories |
| `mem/tb_smc_cpu_mem_responder.sv` | Kept for bare SMU; SMC wrapper absorbs CPU mem |
| `pll_wrap.sv` / `pvt_wrap.sv` / `regs/` | PeakRDL wraps + packages (Bender `smc_wrapper`) |

## Absorbed in `smc_wrapper` / `smc_ip_integration`

CPU ROM/scratch/L1$, eFuse bank/shim, GPIO-ctrl AXI, PLL/PVT macros — not
replicated as TB-local responders.
