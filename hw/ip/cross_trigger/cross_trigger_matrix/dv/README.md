Cross Trigger Matrix DV
=======================

IP-level cocotb bench for the Cross Trigger Matrix (CTM), running on the
unified DV flow (`tools/dv/run_dv.py`, DUT name `cross_trigger_matrix`).

Layout
------

* `cross_trigger_matrix_sim_cfg.toml` — flow configuration (build recipe,
  cocotb framework view, run modes).
* `tb/tb_top.sv` — pin-level testbench top (`cross_trigger_matrix_tb_top`):
  the DUT's AXI4-Lite CSR port is exposed as flattened `axil_*` pins for the
  shared AXI VIP's AXI4-Lite master; the `ct_dst`/`ct_src` crossbar vectors
  are exposed directly for cocotb stimulus and observation.
* `cocotb/tests/` — test modules; `ctm_base_test.py` carries the shared
  bench helpers and the OR-reduction reference model. The matrix geometry,
  register addresses, and reset values are derived from the generated RDL
  header in `../regs/gen/py/`, so a matrix resize regenerates the bench's
  expectations.
* `testlists/all.toml` — testlist and groups (`smoke`, `all`).

The RTL closure comes from the `cross_trigger` Bender target plus the shared
`axi_rtl`/`common_cells_rtl` dependency targets.

Running
-------

```bash
# Smoke group (default items)
python3 tools/dv/run_dv.py --dut cross_trigger_matrix

# Everything
python3 tools/dv/run_dv.py --dut cross_trigger_matrix --items all

# One test with waves
python3 tools/dv/run_dv.py --dut cross_trigger_matrix --items ctm_routing_test --waves
```

Verilator is the default tool; VCS and Xcelium are available where licensed.

Tests
-----

* `ctm_sanity_test` — reset defaults on every per-port CONFIG_0, write/read
  law with a distinct-value aliasing guard across all ports, and the
  no-routing default with a positive control.
* `ctm_routing_test` — diagonal walk over every port, broadcast, randomized
  OR-combining with isolation checks, and randomized full-matrix scenarios
  judged against the OR-reduction reference model as both steady levels and
  single-cycle pulses.

Expected behavior is taken from `../doc/architecture.adoc`,
`../doc/interface.adoc`, and `../regs/cross_trigger_matrix.rdl`. The
subsystem integration of the CTM is additionally exercised at the DTP level
by the `dtp_ctm_*` scenarios (`--dut dtp`).
