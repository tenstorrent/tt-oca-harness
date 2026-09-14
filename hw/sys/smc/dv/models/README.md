<!-- SPDX-License-Identifier: Apache-2.0 -->
# SMC DV models

Behavioral / reference / simulation stand-ins and DV collateral for
`--dut smc` (`tb_top` → `smc_wrapper`). Every file under this directory is
listed here.

| Path | Role |
|------|------|
| `pll_wrap.sv` / `pvt_wrap.sv` / `regs/` | Adopter PLL / PVT placeholder register wraps and their PeakRDL sources plus generated views; pulled by Bender `smc_wrapper` into `smc_ip_integration` (`u_pll_wrap`, `u_pvt_wrap`) on every tool. Handshake responders, not macro RTL |
| `axil_okay_slv.sv` | AXI-Lite OKAY terminator behind `pll_wrap` / `pvt_wrap`: completes every access with `RESP_OKAY` and all-zero read data (pulp `axi_err_slv` asserts at time zero on every simulator but Verilator) |
| `smc_cpu_mem_dv.sv` | DV collateral bound into `smc_ip_integration` for the CPU memory macros: observability counters, the firmware mailbox, the ECC inject hook and the time-0 ROM / scratch image backdoors. Listed in `smc_sim_cfg.toml` `[build].sources` and `[frameworks.uvm.build].sources` |
| `smc_scratch_map_pkg.sv` | The scratch bank / entry decode that `smc_cpu_mem_dv.sv` and `tb/tb_top.sv` share for the image backdoors |

`axil_okay_slv` is a stand-in that can answer a checker: which retired tests
would sit behind it, the one live consumer, and what that consumer does and
does not prove are recorded in the *Bench stand-ins* section of
`hw/sys/smc/doc/dv/SMC_DEFERRED_DISPOSITION.adoc`. The synchroniser
stand-ins that Verilator and Xcelium compile (VCS drops them) live in
`tb/verilator_stubs/` and are recorded in the same section.

The SYS_OUT AXI responder is the shared `ocah_axi_vip` slave agent, bound to the
`ocah_axi_if` instance that `ocah_axi_struct_bridge` feeds in `tb/tb_top.sv`.
On `--dut smc`, I3C DAT/DCT and DTP CSR boundaries are **not**
TB-terminated (no placeholder mem/err_slv). DTP CSR idle is smc_wrapper-only:
SMU wires DTP internally.

CPU ROM/scratch/L1$ live in `hw/top/smc_ip_integration.sv` (smc_wrapper,
smu_wrapper TB, and bare SMU TB).

Bender consumes only `regs/gen/sv/*_addrmap_pkg.sv` from the PeakRDL tree.
