<!-- SPDX-License-Identifier: Apache-2.0 -->
# SMC DV models

Behavioral / reference / simulation stand-ins for `--dut smc`
(`tb_top` → `smc_wrapper`).

| Path | Role |
|------|------|
| `pll_wrap.sv` / `pvt_wrap.sv` / `regs/` | PeakRDL wraps pulled by Bender `smc_wrapper` |
| `smc_cpu_mem_integration.sv` | CPU ROM/scratch/L1$ macros + DV observability (counters, FW mailbox, ECC inject, `$readmemh` backdoor) |

SYS_OUT AXI slave is pulp `axi_sim_mem` in `tb/tb_top.sv` (SEP rom_boot style).
On `--dut smc`, I3C DAT/DCT and DTP CSR boundaries are **not**
TB-terminated (no placeholder mem/err_slv); dependent tests are deferred.
(I3C DAT/DCT is a real integration gap; DTP CSR idle is smc_wrapper-only —
SMU already wires DTP internally.)

CPU ROM/scratch/L1$ live in `smc_cpu_mem_integration.sv` here, shared by
`smc_wrapper`, the smu_wrapper TB, and the bare SMU TB.

Bender consumes only `regs/gen/sv/*_addrmap_pkg.sv` from the PeakRDL tree.
