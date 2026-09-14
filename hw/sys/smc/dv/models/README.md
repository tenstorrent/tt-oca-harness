<!-- SPDX-License-Identifier: Apache-2.0 -->
# SMC DV models

Behavioral / reference / simulation stand-ins for `--dut smc`
(`tb_top` → `smc_wrapper`).

| Path | Role |
|------|------|
| `pll_wrap.sv` / `pvt_wrap.sv` / `regs/` | PeakRDL wraps pulled by Bender `smc_wrapper` |
| `axil_okay_slv.sv` | AXI-Lite OKAY terminator behind `pll_wrap` / `pvt_wrap` (pulp `axi_err_slv` rejects `RESP_OKAY` on every simulator but Verilator) |
| `smc_scratch_map_pkg.sv` | Byte offset → (bank, entry) decode of the 1 MiB / 32-bank CPU scratchpad, shared by the `+smc_scratch_ram_hex` loader and the `tb_top` peeks. Geometry from `spm_memory.rdl` and `cpu.adoc`; the interleave is a DV-owned table declared in its header |
| `smc_cpu_mem_dv.sv` | DV collateral bound into `smc_ip_integration`: ROM / scratch / dcache observability counters, the firmware mailbox magic detector, the bank0 ECC hook counter, and the `+smc_rom_hex` / `+smc_scratch_ram_hex` time-zero image backdoors |

The SYS_OUT AXI responder is the shared `ocah_axi_vip` slave agent, bound to the
`ocah_axi_if` instance that `ocah_axi_struct_bridge` feeds in `tb/tb_top.sv`.
On `--dut smc`, I3C DAT/DCT and DTP CSR boundaries are **not**
TB-terminated (no placeholder mem/err_slv). DTP CSR idle is smc_wrapper-only:
SMU wires DTP internally.

CPU ROM/scratch/L1$ live in `hw/top/smc_ip_integration.sv` (smc_wrapper,
smu_wrapper TB, and bare SMU TB).

Bender consumes only `regs/gen/sv/*_addrmap_pkg.sv` from the PeakRDL tree.
