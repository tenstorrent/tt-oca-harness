Cross Trigger Port DV
=====================

IP-level cocotb bench for the Cross Trigger Port (CTP), running on the
unified DV flow (`tools/dv/run_dv.py`, DUT name `cross_trigger_port`).

Layout
------

* `cross_trigger_port_sim_cfg.toml` — flow configuration (build recipe,
  cocotb framework view, run modes).
* `tb/tb_top.sv` — pin-level testbench top (`cross_trigger_port_tb_top`):
  the DUT's AXI4-Lite CSR port is exposed as flattened `axil_*` pins for the
  shared AXI VIP's AXI4-Lite master; the core-side and GPIO pad pins are
  exposed directly for cocotb stimulus and observation.
* `cocotb/tests/` — test modules; `ctp_base_test.py` carries the shared
  bench helpers (bring-up, register access, pulse/window measurement).
* `testlists/all.toml` — testlist and groups (`smoke`, `all`).

The RTL closure comes from the `cross_trigger` Bender target plus the shared
`axi_rtl`/`common_cells_rtl` dependency targets; register addresses and reset
values come from the generated Python header in `../regs/gen/py/`.

Running
-------

```bash
# Smoke group (default items)
python3 tools/dv/run_dv.py --dut cross_trigger_port

# Everything
python3 tools/dv/run_dv.py --dut cross_trigger_port --items all

# One test with waves
python3 tools/dv/run_dv.py --dut cross_trigger_port --items ctp_p2p_test --waves
```

Verilator is the default tool; VCS and Xcelium are available where licensed.

Tests
-----

* `ctp_sanity_test` — reset defaults, CONFIG/STRETCH_MULT write/read law,
  STATUS read-only law, and a single-pulse wire-OR smoke.
* `ctp_wire_or_test` — pad enable matrix and static data levels for both
  INVERT senses, stretched transmit window (`STRETCH_MULT+1` cycles) over
  deterministic corners and randomized values, back-to-back restart, and
  receive (`ct_dst`) checks for both INVERT senses and idle levels.
* `ctp_p2p_test` — pad enable matrix, sender and receiver four-phase
  handshake FSMs, full-duplex operation, `CONFIG.RESET` deadlock recovery,
  and INVERT-sense operation with logical STATUS readouts.

Expected behavior is taken from `../doc/architecture.adoc`,
`../doc/interface.adoc`, and `../regs/cross_trigger_port.rdl`. The subsystem
integration of the CTP is additionally exercised at the DTP level by the
`dtp_xtrig_*`/`dtp_ctm_*` scenarios (`--dut dtp`).
