# Entropy Source DV

IP-level cocotb verification for the entropy source on the unified native DV
runner.

## Layout

- `entropy_source_sim_cfg.toml` defines the build, tools, and run modes.
- `tb/tb_top.sv` exposes the AXI4-Lite port and deterministic leaf-module
  harnesses.
- `cocotb/tests/` contains the shared bench and test scenarios.
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
  --items entropy_source_fifo_test --waves
```

Verilator is the default simulator. VCS and Xcelium are supported where
licensed. The pin-level harness disables the imported OpenTitan primitives'
SoC alert-binding assertions under four-state simulators because those
assertions require integration-level alert hierarchy. The suite still observes
the corresponding FIFO and health-test error outputs directly.

## Tests

- `entropy_source_sanity_test` checks reset values, AXI4-Lite register access,
  interrupt injection, interrupt status, and write-one-to-clear behavior.
- `entropy_source_datapath_test` checks decorrelator enable, bypass,
  downsampling-valid behavior, and byte masking with deterministic noise.
- `entropy_source_fifo_test` checks ordering, occupancy, flush, underflow,
  overflow, and the security-alert baseline.
- `entropy_source_health_test` checks repetition threshold detection, disable
  clearing, counter integrity, and edge-triggered oscillator tuning.
- `entropy_source_debug_test` checks debug signal selection and frequency
  division.

SEP-level entropy bring-up, FIPS locking, watermark arming, alert delivery,
entropy-pool integration, and coordinated reset remain owned by
`hw/sys/sep/dv`.
