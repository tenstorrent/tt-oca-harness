System Timer OCTS DV
====================

IP-level cocotb bench for the System Timer OCTS, running on the unified DV
flow (`tools/dv/run_dv.py`, DUT name `system_timer_octs`).

Layout
------

* `system_timer_octs_sim_cfg.toml` — flow configuration (build recipe, cocotb
  framework view, run modes).
* `tb/tb_top.sv` — pin-level testbench top (`system_timer_octs_tb_top`): a
  primary timer wired to a secondary timer, each on its own clock, with each
  instance's AXI4-Lite CSR port exposed as flattened `primary_axil_*` /
  `secondary_axil_*` pins for the shared AXI VIP's AXI4-Lite master. The
  `sync_load` and `cnt_credit` wires between the instances, both counters,
  the GPIO enables and the credit debug outputs are exposed for observation.
* `cocotb/tests/` — test modules; `system_timer_octs_base_test.py` carries the
  shared bench helpers: clock pairs, one VIP master per instance, the
  programming sequence, and pin-level pulse and counter observers. Register
  addresses, field layouts and reset values come from the generated RDL header
  in `../regs/gen/py/`.
* `testlists/all.toml` — testlist and groups (`smoke`, `all`).

The RTL closure comes from the `system_timer_octs` Bender target plus the
shared `axi_rtl`/`common_cells_rtl` dependency targets.

Running
-------

```bash
# Smoke group (default items)
python3 tools/dv/run_dv.py --dut system_timer_octs

# Everything
python3 tools/dv/run_dv.py --dut system_timer_octs --items all

# One test with waves
python3 tools/dv/run_dv.py --dut system_timer_octs --items system_timer_octs_sync_test --waves
```

Verilator is the default tool; VCS and Xcelium are available where licensed.

Tests
-----

* `system_timer_octs_sanity_test` — reset defaults and `STATUS.MODE` on both
  instances, write/read law with an aliasing guard, the GPIO-enable pins, and
  the primary's preset load and one-per-clock count after `TIMER_START`.
* `system_timer_octs_sync_test` — equal clocks: `sync_load` and `cnt_credit`
  pulse width and period, the secondary's preset load, counter tracking over
  random samples, STEP pacing against the credit debug pins, and the
  bounded `CREDIT_EXPIRED`.
* `system_timer_octs_clock_ratio_test` — the secondary at twice and at half
  the primary's clock period: tracking within tolerance, and `CREDIT_EXPIRED`
  accumulating and clearing on the fast secondary.

Expected behavior is taken from `../doc/architecture.adoc`,
`../doc/programming.adoc` and `../regs/system_timer_octs.rdl`. The timer is
also exercised inside the SMC (`--dut smc`).
