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
  exposed directly for cocotb stimulus and observation. The CT_Req_out pad
  sits on an open-drain shared wire (`ocah_open_drain_bus` from
  `hw/common/dv/shims/analog/`) with two bench-side chiplet drivers; cocotb
  sets the wire's pull and the drivers and observes the resolved wire.
* `cocotb/tests/` — test modules; `ctp_base_test.py` carries the shared
  bench helpers (bring-up, register access, pulse/window measurement, the
  shared-wire drivers, and the cycle-exact wire-OR receive model).
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
  STATUS read-only law (writes complete OKAY and change nothing), and a
  single-pulse wire-OR smoke.
* `ctp_wire_or_test` — pad enable matrix and resting data levels for both
  INVERT senses, stretched transmit window (`STRETCH_MULT+1` cycles) over
  deterministic corners and randomized values, back-to-back restart, and
  receive: one `ct_dst` pulse per wire assertion, at the assertion edge, for
  both INVERT senses on the matching board pull.
* `ctp_wire_or_bus_test` — the port on a shared wire with two other
  chiplets: reset with the wire resting and held asserted, INVERT written
  against the board, overlapping and adjacent pulls merging into one
  trigger, the port hearing its own pull, and the bench's pull-mismatch flag.
* `ctp_p2p_test` — pad enable matrix, sender and receiver four-phase
  handshake FSMs, full-duplex operation, `CONFIG.RESET` deadlock recovery,
  and INVERT-sense operation with logical STATUS readouts.
* `ctp_mode_switch_test` — switching between wire-OR and point-to-point
  behind a pad model that reads 0 while an input is disabled: no request
  left behind by a wire-OR trigger or a handshake abandoned mid-exchange, no
  request when MODE and RESET share a write, and no `ct_dst` pulse or
  acknowledge when MODE and INVERT share a write against an idle far end.

Expected behavior is taken from `../doc/architecture.adoc`,
`../doc/interface.adoc`, and `../regs/cross_trigger_port.rdl`. The subsystem
integration of the CTP is additionally exercised at the DTP level by the
`dtp_xtrig_*`/`dtp_ctm_*` scenarios (`--dut dtp`).
