<!-- SPDX-License-Identifier: Apache-2.0 -->
# SMC DV models

Behavioral / reference / simulation stand-ins for the bare-SMC and wrapper
flows. Taxonomy:

| Kind | Location |
|------|----------|
| Protocol VIP | `hw/common/dv/vip/ocah_*_vip/` |
| Behavioral models | `hw/sys/smc/dv/models/` (this tree) |
| Verilator overrides | `hw/sys/smc/dv/tb/verilator_stubs/` |
| Design RTL bridges | RTL / `hw/top/` (not under `dv/`) |

## Contents

| Path | Role |
|------|------|
| `mem/` | output-fabric AXI (`prim_ram_1p`), I3C DAT/DCT (`prim_ram_1p`) — TB boundary responders (SEP outbound posture) |
| `wrapper/` | DV shadow of `smc_padring_ext` (ASSIGNIN fix for Verilator) |
| `pll_wrap.sv` / `pvt_wrap.sv` / `regs/` | PeakRDL wraps + generated packages |

## Absorbed elsewhere (not TB-local responders)

| Resource | Bare `--dut smc` | `--dut smc_wrapper` |
|----------|------------------|---------------------|
| CPU ROM/scratch/L1$ | TB: `smc_cpu_mem_integration` | absorbed in wrapper |
| eFuse bank/shim | TB: `efuse_interface_shim` + `efuse_bank_model` (same as integration) | `smc_ip_integration` |
| GPIO-ctrl AXI | TB: `prim_axi_lite_err_slv` DECERR | same inside integration |
| PLL/PVT | TB: DECERR | `pll_wrap` / `pvt_wrap` |
