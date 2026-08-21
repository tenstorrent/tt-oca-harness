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
├── doc/                                # AsciiDoc pages published via Antora
├── dv/
│   ├── tb_vcs/                         # VCS/cocotb testbench
│   └── syn/                            # Synthesis constraints
└── README.md
```

## Configuration

The CTN has no generator. `rtl/cross_trigger_network_pkg.sv` is a committed
source file, and the topology is set by editing its `DEFAULT_NUM_CTP`,
`DEFAULT_NUM_INT_CT`, and `DEFAULT_NUM_CLK_STOP_REQ` values, or by overriding the
corresponding module parameters at the instantiation:

- `NUM_CTP`: Number of external CTPs (1-32, default: 16)
- `NUM_INT_CT`: Number of internal cross triggers (0-32, default: 10)
- `NUM_CLK_STOP_REQ`: Number of clock stop request inputs (1-32, default: 9)
- `INT_CT_MODE`: Per-internal-CTP signalling mode

The DTP drives these from `dtp_pkg` (`hw/sys/dtp/rtl/dtp_pkg.sv`), so a change to
the port count belongs there when the CTN is used inside the DTP. The CTN has no
register block of its own; the CTM and CTP register collateral comes from
`make -f ocah.mk ocah-regen-regs`, like every other block.

## Integration

The CTN is instantiated within the DTP module (`hw/sys/dtp/rtl/dtp.sv`):

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
cd dv/tb_vcs
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

The pages under `doc/` are AsciiDoc sources published with the rest of the OCAH
documentation. Build the TRM, which includes them under the DTP subsystem:

```bash
make -f ocah.mk ocah-doc-trm-html
```

## Dependencies

- `hw/ip/cross_trigger/cross_trigger_port` - Cross Trigger Port IP
- `hw/ip/cross_trigger/cross_trigger_matrix` - Cross Trigger Matrix IP
- `vendor/pulp-platform/axi` - AXI infrastructure (`axi_lite_xbar`)
