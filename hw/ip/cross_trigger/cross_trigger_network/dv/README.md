Cross Trigger Network DV
========================

IP-level cocotb bench for the Cross Trigger Network (CTN), running on the
unified DV flow (`tools/dv/run_dv.py`, DUT name `cross_trigger_network`).

Layout
------

* `cross_trigger_network_sim_cfg.toml` — flow configuration (build recipe,
  cocotb framework view, run modes).
* `tb/tb_top.sv` — pin-level testbench top (`cross_trigger_network_tb_top`):
  the DUT's AXI4-Lite CSR crossbar is exposed as flattened `axil_*` pins for
  the shared AXI VIP's AXI4-Lite master; the external CTP GPIO pads, the
  internal CT ports, and the clock-stop controls are exposed directly. The
  internal CT ports are built with the lower half in wire-OR mode and the
  upper half in point-to-point mode. Every CT_Req_out pad sits on an
  open-drain shared wire (`ocah_open_drain_bus` from
  `hw/common/dv/shims/analog/`): a private wire with one bench-side chiplet
  driver, or the group wire the pads in `ctp_wire_group` share; each port's
  receive pulse is exposed for cycle checks.
* `cocotb/tests/` — test modules; `ctn_base_test.py` carries the shared
  bench helpers (address map, packed-vector drivers, pulse watchers). CSR
  offsets inside each endpoint window come from the embedded IPs' generated
  RDL headers; the network geometry mirrors `cross_trigger_network_pkg.sv`.
* `testlists/all.toml` — testlist and groups (`smoke`, `all`).

The RTL closure comes from the `cross_trigger` Bender target plus the shared
`axi_rtl`/`common_cells_rtl` dependency targets (the AXI-Lite crossbar and
its common-cells closure included).

Running
-------

```bash
# Smoke group (default items)
python3 tools/dv/run_dv.py --dut cross_trigger_network

# Everything
python3 tools/dv/run_dv.py --dut cross_trigger_network --items all

# One test with waves
python3 tools/dv/run_dv.py --dut cross_trigger_network --items ctn_loopback_test --waves
```

Verilator is the default tool; VCS and Xcelium are available where licensed.

Tests
-----

* `ctn_sanity_test` — endpoint reset defaults through the crossbar, a
  distinct-value write/read sweep across every CTM port and CTP window
  (endpoint-aliasing guard), and unmapped-address decode errors.
* `ctn_routing_test` — one CTM route per scenario across every source/target
  mode combination (external wire-OR/P2P pads, internal wire-OR/P2P ports),
  deterministic corners plus a randomized sweep, each with an unrouted-port
  isolation check; a wire-OR source's port fires exactly once,
  `CT_DST_LATENCY` cycles after its wire or CLA request asserts.
* `ctn_loopback_test` — complete multi-hop paths over chip-to-chip wiring: a
  wire-OR repeater pulling a shared wire with two listening CTPs, an
  external P2P pair completing the four-phase handshake autonomously over
  pad mirrors, and an internal P2P duplex exchange.
* `ctn_clock_stop_test` — clock-stop OR aggregation: walking-one and
  randomized request subsets, and the JTAG stop's discrimination from the
  CLA status output.

Expected behavior is taken from `../doc/architecture.adoc`,
`../doc/interface.adoc`, the embedded IPs' specs, and
`cross_trigger_network_pkg.sv` (address map). The subsystem integration of
the CTN is additionally exercised at the DTP level by the `dtp_xtrig_*`
scenarios (`--dut dtp`).
