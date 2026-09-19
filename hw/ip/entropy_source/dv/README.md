<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# Entropy Source DV

IP-level cocotb verification for the entropy source on the unified native DV
runner.

## Layout

- `entropy_source_sim_cfg.toml` defines the build, tools, and run modes.
- `tb/tb_top.sv` exposes the AXI4-Lite port and deterministic leaf-module
  harnesses.
- `cocotb/entropy_source_models/` contains the noise, decorrelator, BIW, and
  SHA reference models used by both this suite and SEP system DV.
- `cocotb/tests/` contains the bench and test scenarios.
- `testlists/all.toml` defines the `smoke` and `all` groups.

The RTL closure comes from the `entropy_source` Bender target. Register
transactions use the shared AXI4-Lite VIP, and register expectations come from
the generated Python register header.

## Running

```bash
# CSR and interrupt smoke test
python3 tools/dv/run_dv.py --dut entropy_source

# Complete IP-level suite
python3 tools/dv/run_dv.py --dut entropy_source --items all

# One scenario with waves
python3 tools/dv/run_dv.py --dut entropy_source \
  --items entropy_fifo --waves
```

Verilator is the default simulator. VCS and Xcelium are supported where
licensed. The pin-level harness disables the imported OpenTitan primitives'
SoC alert-binding assertions under four-state simulators because those
assertions require integration-level alert hierarchy. The suite still observes
the corresponding FIFO and health-test error outputs directly.

## Tests

- `register_walk` and `axi_random` cover the generated CSR map and AXI4-Lite
  transactions.
- `decorrelator_modes` checks every bypass-mask class, sampling rates, byte
  masks, and BIW extraction against the entropy-source DV models.
- `entropy_fifo` checks ordering, wraparound, simultaneous traffic, flush,
  overflow, underflow, parity, hardened pointer operation, and security alerts.
- `health_tests` checks repetition, adaptive-proportion, and Markov thresholds,
  boundaries, recovery, interrupts, and oscillator tuning.
- `sampling` checks ring-noise enable/detune behavior and sample-clock division.
- `debug_monitor` checks signal selection and every divider boundary.
- `pipeline_integration` and `entropy_sanity` check decorrelator-to-FIFO data
  flow, SHA-256 conditioning, bypass, and status counters.

SEP-level entropy bring-up, FIPS locking, watermark arming, alert delivery,
entropy-pool integration, and coordinated reset remain in `hw/sys/sep/dv`.
Those tests import the same `entropy_source_models` package rather than keeping
subsystem-local copies.
