<!-- SPDX-License-Identifier: Apache-2.0 -->
# SMC DV models

Behavioral / reference / simulation stand-ins and DV collateral for
`--dut smc` (`tb_top` → `smc_wrapper`). Every file under this directory is
listed here.

| Path | Role |
|------|------|
| `pll_wrap.sv` / `pvt_wrap.sv` / `regs/` | Adopter PLL / PVT placeholder register wraps and their PeakRDL sources plus generated views; pulled by Bender `smc_wrapper` into `smc_ip_integration` (`u_pll_wrap`, `u_pvt_wrap`) on every tool. Handshake responders, not macro RTL |
| `axil_okay_slv.sv` | AXI-Lite OKAY terminator behind `pll_wrap` / `pvt_wrap`: completes every access with `RESP_OKAY` and all-zero read data (pulp `axi_err_slv` asserts at time zero on every simulator but Verilator) |
| `smc_scratch_map_pkg.sv` | Byte offset → (bank, entry) decode of the 1 MiB / 32-bank CPU scratchpad, shared by the `+smc_scratch_ram_hex` loader and the `tb_top` peeks. Geometry from `spm_memory.rdl` and `cpu.adoc`; the interleave is a DV-owned table declared in its header |
| `smc_cpu_mem_dv.sv` | DV collateral bound into `smc_ip_integration`: ROM / scratch / dcache observability counters, the firmware mailbox magic detector, the bank0 ECC hook counter, and the `+smc_rom_hex` / `+smc_scratch_ram_hex` time-zero image backdoors. Listed in `smc_sim_cfg.toml` `[build].sources` and `[frameworks.uvm.build].sources` |

`axil_okay_slv` is a stand-in that can answer a checker: which retired tests
would sit behind it, the one live consumer, and what that consumer does and
does not prove are recorded in the *Bench stand-ins* section of
`docs/SMC_VPLAN.adoc` (Known Limitations, "SMC deferred and OUT disposition"). The synchroniser
stand-ins that Verilator and Xcelium compile (VCS drops them) live in
`tb/verilator_stubs/` and are recorded in the same section.

The SYS_OUT AXI responder is the shared `ocah_axi_vip` slave agent, bound to the
`ocah_axi_if` instance that `ocah_axi_struct_bridge` feeds in `tb/tb_top.sv`.
On `--dut smc`, I3C DAT/DCT and DTP CSR boundaries are **not**
TB-terminated (no placeholder mem/err_slv). DTP CSR idle is smc_wrapper-only:
SMU wires DTP internally.

CPU ROM/scratch/L1$ live in `hw/top/smc_ip_integration.sv` (smc_wrapper,
smu_wrapper TB, and bare SMU TB).

`regs/gen/` holds every view `make regen-regs` emits from `regs/*.rdl` (`adoc/`,
`c/`, `html/`, `ipxact/`, `py/`, `sv/`, `svh/`), committed beside the source as
`CONTRIBUTING.md` requires. Bender consumes only `regs/gen/sv/*_addrmap_pkg.sv`;
`doc/stage-docs.sh` stages `regs/gen/html/*.html` into the documentation site
as the register-map partials for the two placeholder wraps.
