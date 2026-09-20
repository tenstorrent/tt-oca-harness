<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

Entropy Source DV
=================

IP-level cocotb bench for the entropy source, running on the unified DV flow
(`tools/dv/run_dv.py`, DUT name `entropy_source`).

Layout
------

* `entropy_source_sim_cfg.toml` — flow configuration, build recipe, cocotb
  framework view, and run modes.
* `tb/tb_top.sv` — pin-level testbench top (`entropy_source_tb_top`): the
  AXI4-Lite CSR port is flattened as `axil_*` pins for the AXI VIP, while
  deterministic leaf harnesses expose FIFO, health-test, decorrelator,
  conditioner, noise-source, sampler-clock, and debug-monitor behavior.
* `cocotb/models/` — entropy-source DV models for noise, decorrelation, BIW,
  and SHA conditioning. SEP system DV imports these models.
* `cocotb/tests/` — test modules; `entropy_source_base_test.py` carries the
  bench setup and AXI sequencer, while `entropy_source_scenarios.py` and
  `entropy_source_register_scenarios.py` carry reusable scenario helpers.
* `testlists/all.toml` — testlist and groups (`smoke`, `all`).

The RTL closure comes from the `entropy_source` Bender target plus the
`axi_rtl` and `common_cells_rtl` dependency targets. Register transactions use
the AXI4-Lite VIP, and register expectations come from the generated Python
register header.

Running
-------

```bash
# CSR and interrupt smoke test
python3 tools/dv/run_dv.py --dut entropy_source

# Complete IP-level suite
python3 tools/dv/run_dv.py --dut entropy_source --items all

# One scenario with waves
python3 tools/dv/run_dv.py --dut entropy_source \
  --items entropy_source_fifo_test --waves
```

Verilator is the default simulator. VCS and Xcelium are supported where
licensed. The pin-level harness disables the imported OpenTitan primitives'
SoC alert-binding assertions under four-state simulators because those
assertions require integration-level alert hierarchy. The suite still observes
the corresponding FIFO and health-test error outputs directly.

Tests
-----

* `entropy_source_sanity_test` — reset defaults, AXI4-Lite access, interrupt
  injection, and status clearing.
* `entropy_source_register_walk_test` and `entropy_source_axi_random_test` —
  generated CSR-map walking and randomized AXI4-Lite transactions.
* `entropy_source_decorrelator_modes_test` — bypass-mask classes, sampling
  rates, byte masks, and BIW extraction against the entropy-source DV models.
* `entropy_source_fifo_test` — ordering, wraparound, simultaneous traffic,
  flush, overflow, underflow, parity, hardened pointer operation, and security
  alerts.
* `entropy_source_health_test` and
  `entropy_source_health_algorithms_test` — repetition,
  adaptive-proportion, and Markov thresholds, boundaries, recovery,
  interrupts, and oscillator tuning.
* `entropy_source_sampling_test` — ring-noise enable/detune behavior and
  sample-clock division.
* `entropy_source_debug_monitor_test` — signal selection and divider
  boundaries.
* `entropy_source_downsample_rate_test` — CSR-controlled decorrelator
  downsampling.
* `entropy_source_pipeline_integration_test` and
  `entropy_source_conditioning_test` — decorrelator-to-FIFO data flow,
  SHA-256 conditioning, bypass, and status counters.

SEP-level entropy bring-up, FIPS locking, watermark arming, alert delivery,
entropy-pool integration, and coordinated reset remain in `hw/sys/sep/dv`.
Those tests import `cocotb/models/` rather than keeping subsystem-local copies.
