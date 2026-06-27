# Cross Trigger Network (CTN)

The Cross Trigger Network is a component-level module within the Debug and Test Ports (DTP) subsystem that aggregates cross trigger functionality for both die-to-die and on-chip cross triggering.

## Overview

The CTN implements the Open Chiplet Cross Triggering (OCCT) specification and contains:

- **External Cross Trigger Ports (CTPs)**: GPIO-based die-to-die cross triggering
- **Internal Cross Trigger Ports**: On-chip cross trigger signal processing
- **Cross Trigger Matrix (CTM)**: Configurable routing between all CTPs
- **Clock Stop Control**: Aggregation of clock stop requests
- **AXI-Lite Crossbar**: Unified CSR access to all modules

## Directory Structure

```
cross_trigger_network/
├── rtl/
│   ├── cross_trigger_network_pkg.sv    # Package with types and parameters
│   ├── cross_trigger_network.sv        # Top-level module
│   └── ctn_clock_stop_ctrl.sv          # Clock stop control module
├── doc/                                 # Sphinx documentation
├── tb_vcs/                             # VCS/cocotb testbench
├── syn/                                # Synthesis constraints
├── generate_comp.py                    # Configuration script
└── README.md
```

## Configuration

Run the configuration script to set up the CTN:

```bash
./generate_comp.py --num-ctp 16 --num-int-ct 9
```

This generates CTN-specific files:

**CTN files**:
- `rtl/cross_trigger_network_pkg.sv` - Package with matching NUM_CTP/NUM_INT_CT
- `tb_vcs/test/test_base.py` - Test utilities with matching configuration
- `data/registers/rdl/cross_trigger_network.rdl` - Address map RDL

**Note**: CTP and CTM are generated separately by `tools/generate_all.py` or their
respective `generate_ip.py` scripts. When using `generate_all.py`, CTP/CTM/CTN are
generated in the correct dependency order with matching parameters.

Options:
- `--num-ctp`: Number of external CTPs (1-32, default: 16)
- `--num-int-ct`: Number of internal cross triggers (0-32, default: 10)
- `--num-clk-stop-req`: Number of clock stop request inputs (1-32, default: 9)
- `--clean`: Remove generated files

## Integration

The CTN is instantiated within the DTP module (`hw/dtp/rtl/dtp.sv`):

```systemverilog
cross_trigger_network #(
    .INT_CT_MODE      (XTRIG_INT_CT_MODE),
    .axil_req_t       (xtrig_axil_req_t),
    .axil_resp_t      (xtrig_axil_resp_t)
) u_cross_trigger_network (
    // ... port connections
);
```

## Address Map

The AXI-Lite address space is organized as (CTM first, then CTPs) within a 2KB (0x800) address range:

| Module    | Address Range                     | Size             |
|-----------|-----------------------------------|------------------|
| CTM       | 0x0000 - 0x01FF                   | 512 bytes (0x200)|
| CTP[0]    | 0x0200 - 0x020F                   | 16 bytes (0x10)  |
| CTP[1]    | 0x0210 - 0x021F                   | 16 bytes (0x10)  |
| ...       | ...                               | ...              |
| CTP[N-1]  | 0x0200 + (N-1)*0x10 - 0x020F + (N-1)*0x10 | 16 bytes (0x10)  |

## Testing

Run the testbench:

```bash
cd tb_vcs
make TEST=test_sanity      # Basic register access
make TEST=test_routing     # CTM routing (basic + mixed mode)
make TEST=test_loopback    # Loopback tests (Wire-OR, P2P, internal, external)
make TEST=test_clock_stop  # Clock stop control
make regression            # Run all tests
```

### Test Coverage

| Test File | Tests |
|-----------|-------|
| test_sanity.py | Basic CTM and CTP register access |
| test_routing.py | CTM routing config, mixed-mode routing |
| test_loopback.py | Wire-OR/P2P loopback, routing matrix, multi-source OR |
| test_clock_stop.py | Clock stop aggregation and gating |

## Documentation

Build the Sphinx documentation:

```bash
cd doc
make html
```

## Dependencies

- `hw/ip/cross_trigger_port` - Cross Trigger Port IP
- `hw/ip/cross_trigger_matrix` - Cross Trigger Matrix IP
- `deps/axi` - AXI infrastructure (axi_lite_xbar)
