# DRBG Wrapper Cocotb Flow

This directory contains the shared `cocotb` environment for the `hw/comp/drbg`
wrapper. VCS is the primary day-to-day simulator, but the supported directed
scope is intended to run through the same `tb_drbg.sv` plus `test_drbg.py`
environment in both VCS and Verilator.

## Prerequisites

1. Source the project environment once per shell session:

   ```bash
   source bin/setup_env.sh
   ```

2. Regenerate or verify the Bender filelist if new wrapper files were added:

   ```bash
   make -C hw/comp/drbg/tb_vcs filelist
   ```

3. Use the `drbg` Bender target added by this feature so the wrapper and its
   wrapped IP dependencies are compiled together.

## Primary Workflow

VCS is the expected default simulator while the wrapper is under active
development.

```bash
make -C hw/comp/drbg/tb_vcs sim-vcs
```

To run a single named `cocotb` test:

```bash
make -C hw/comp/drbg/tb_vcs sim-vcs TESTCASE=test_entropy_routing_priority
```

Enable simple waveform dumping:

```bash
make -C hw/comp/drbg/tb_vcs sim-vcs WAVES=1
```

## Verilator Parity Flow

Run the same harness and Python tests through Verilator:

```bash
make -C hw/comp/drbg/tb_vcs sim-verilator
```

Use the same `TESTCASE=<name>` knob for focused debug. The wrapper support goal
for this feature is pass/fail parity for the directed tests that do not depend
on simulator-specific behavior.

## Lint and Build Targets

```bash
make -C hw/comp/drbg/tb_vcs lint
make -C hw/comp/drbg/tb_vcs lint-verilator
make -C hw/comp/drbg/tb_vcs build-verilator
```

## Non-default Parameter Smoke

The wrapper must also be exercised with at least one non-default elaboration to
cover configurable FIFO depths and multiple EDN endpoints.

```bash
make -C hw/comp/drbg/tb_vcs smoke-nondefault-vcs
make -C hw/comp/drbg/tb_vcs smoke-nondefault-verilator
```

These targets override:

- `INGRESS_FIFO_DEPTH = 4`
- `SEED_FIFO_DEPTH = 2`
- `EDN_ENDPOINT_COUNT = 2`
- `ENDPOINT_FIFO_DEPTH = 4`

## Debug Notes

- `tb_drbg.sv` exports wrapper-local observability hooks for route decisions,
  FIFO occupancy, seed queue visibility, unsupported AXI-Lite access pulses,
  and internal TL-UL request activity.
- Supported control-plane accesses are aligned single-lane 32-bit operations on
  the external 64-bit AXI-Lite ports.
- Unsupported multi-lane or unaligned accesses must return AXI `SLVERR` and
  emit no TL-UL request.
