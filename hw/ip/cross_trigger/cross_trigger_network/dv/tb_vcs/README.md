# Cross Trigger Network Testbench

This directory contains the VCS/cocotb-based testbench for the Cross Trigger Network (CTN).

## Prerequisites

- VCS simulator
- Python 3.8+
- cocotb (`pip install cocotb`)

## Directory Structure

```
tb_vcs/
├── Makefile                    # Build and run tests
├── rtl.f                       # RTL file list
├── tb.f                        # Testbench file list
├── tb_cross_trigger_network.sv # Top-level testbench
├── test/
│   ├── __init__.py
│   ├── test_base.py           # Common test utilities
│   ├── test_sanity.py         # Basic sanity test
│   ├── test_routing.py        # Cross trigger routing test
│   └── test_clock_stop.py     # Clock stop control test
└── README.md
```

## Running Tests

### Run a single test

```bash
make TEST=test_sanity
make TEST=test_routing
make TEST=test_clock_stop
```

### Run all tests

```bash
make regression
```

### Enable waveform dumping

```bash
make TEST=test_sanity WAVES=1
```

### View results

Test results are saved in `sim/logs/<test_name>/`:

- `vcs.log` - Compilation and simulation log
- `cocotb_<test_name>.log` - cocotb log
- `results_<test_name>.xml` - JUnit test results

## Test Descriptions

### test_sanity

Basic sanity test that verifies:

- AXI-Lite crossbar routes correctly to CTP[0]
- CTP register read/write works
- CTM register read/write works
- Clock stop output is inactive at reset

### test_routing

Tests cross trigger routing through the CTM:

- Configure CTM routing between CTPs
- Verify routing configuration readback
- Test OR-ing of multiple sources

### test_clock_stop

Tests `ctn_clock_stop_ctrl` behavior inside the CTN (CLA requests, JTAG stop, and registered `stop_clks_o`):

- Reset: `stop_clks` is inactive
- CLA path: `clk_stop_req_i` OR-reduces into `stop_clks_o` and `cla_clock_stop_o` (status is CLA requests only)
- Multiple CLA request bits: OR aggregation and partial clear
- JTAG path: `jtag_clock_stop_i` combines into `stop_clks_o`; `cla_clock_stop_o` stays low when only JTAG asserts (no CLA requests)

## Configuration

The testbench uses reduced parameters for faster simulation:

- NUM_CTP = 4 (vs 16 default)
- NUM_INT_CT = 2 (vs 1 default)
- NUM_CLK_STOP_REQ = 2 (vs 1 default)
