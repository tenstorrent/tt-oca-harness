# CTP Verification Environment

This directory contains the verification environment for the Cross-Trigger Port (CTP) module.

## Components

### CTP Bus Functional Model (`ctp_bfm.py`)

A comprehensive Bus Functional Model for the Cross-Trigger Port that supports both WIRE-OR and POINT-TO-POINT modes.

### Enumeration Template (`enum_template.py`)

A comprehensive template file demonstrating enumeration patterns and best practices for CocoTB testbenches. This template is a reference for creating clean, maintainable enumerations in verification code.

**Key Features:**
- Examples of `IntEnum`, `Enum`, `IntFlag`, and `auto()`
- Protocol-specific enumerations (AXI, APB, PCIe)
- Custom methods in enumerations
- Utility functions for enum handling
- Usage examples in CocoTB tests
- Best practices documentation

See `enum_template.py` for complete examples and patterns.

## CTP Protocol Overview

The Cross-Trigger Port (CTP) supports two operational modes:

### 1. WIRE-OR Mode (mode=0)
- Simple wired-OR configuration
- Multiple devices can share the same trigger line
- Uses pulse stretching to ensure pulse visibility
- Monitor `ct_req_out_din` for incoming triggers
- Triggers appear on `ct_dst` after synchronization

### 2. POINT-TO-POINT Mode (mode=1)
- Handshake-based protocol
- Dedicated request/acknowledge signaling
- One device sends request via `ct_req_out_dout`
- Other device responds with `ct_ack_in_din`
- More complex but supports flow control

## CTP BFM Features

- ✅ Full support for both WIRE-OR and POINT-TO-POINT modes
- ✅ Automatic trigger detection and response
- ✅ Configurable response timing
- ✅ Event tracking and logging
- ✅ Custom trigger callbacks
- ✅ Statistics collection
- ✅ Comprehensive debugging support

## Usage

### Basic Example

```python
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer
from env import create_ctp_bfm, DTPCTPMode_e

@cocotb.test()
async def test_ctp_bfm(dut):
    # Start clock
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    
    # Create CTP BFM
    ctp_bfm = create_ctp_bfm(dut.ctp_if, dut.clk, name="CTP_BFM")
    
    # Configure
    ctp_bfm.configure(
        auto_respond=True,
        response_delay_cycles=3,
        ack_pulse_cycles=5
    )
    
    # Wait for reset
    await ctp_bfm.wait_for_reset()
    
    # Start the BFM
    ctp_bfm.start()
    
    # Run test...
    await Timer(1000, units='ns')
    
    # Get statistics
    stats = ctp_bfm.get_statistics()
    print(f"Statistics: {stats}")
    
    # Stop BFM
    ctp_bfm.stop()
```

### With Custom Trigger Callback

```python
@cocotb.test()
async def test_ctp_with_callback(dut):
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    
    ctp_bfm = create_ctp_bfm(dut.ctp_if, dut.clk)
    
    # Define custom trigger handler
    def on_trigger(event):
        print(f"Trigger @ {event.timestamp}ns")
        print(f"  Mode: {'WIRE-OR' if event.mode == 0 else 'POINT-TO-POINT'}")
        print(f"  Source: {event.source}")
    
    ctp_bfm.set_trigger_callback(on_trigger)
    
    await ctp_bfm.wait_for_reset()
    ctp_bfm.start()
    
    # Test logic...
    await Timer(1000, units='ns')
    
    # Review captured events
    events = ctp_bfm.get_trigger_events()
    for event in events:
        print(event)
    
    ctp_bfm.stop()
```

### Sending Triggers

```python
@cocotb.test()
async def test_ctp_send_trigger(dut):
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    
    ctp_bfm = create_ctp_bfm(dut.ctp_if, dut.clk)
    await ctp_bfm.wait_for_reset()
    ctp_bfm.start()
    
    # Wait a bit
    await Timer(100, units='ns')
    
    # Send trigger in WIRE-OR mode
    dut.ctp_if.mode.value = DTPCTPMode_e.WIRE_OR
    await ctp_bfm.send_trigger()
    
    # Wait and switch to P2P mode
    await Timer(100, units='ns')
    dut.ctp_if.mode.value = DTPCTPMode_e.POINT_TO_POINT
    await ctp_bfm.send_trigger()
    
    ctp_bfm.stop()
```

## Configuration Options

### BFM Configuration

- `auto_respond` (bool): Automatically respond to triggers (default: True)
- `response_delay_cycles` (int): Cycles to wait before responding (default: 2)
- `ack_pulse_cycles` (int): Duration of ACK pulse in P2P mode (default: 3)

## API Reference

### CTPBFM

#### Methods

- `__init__(ctp_intf, clock, name)` - Initialize the BFM
- `start()` - Start the BFM operation
- `stop()` - Stop the BFM
- `wait_for_reset()` - Wait for reset deassertion
- `configure(**kwargs)` - Configure BFM parameters
- `set_trigger_callback(callback)` - Set custom trigger callback
- `send_trigger(mode)` - Send a trigger pulse
- `get_statistics()` - Get BFM statistics
- `reset_statistics()` - Reset statistics counters
- `get_trigger_events()` - Get list of captured trigger events
- `clear_trigger_events()` - Clear event history

#### Statistics

The BFM tracks the following statistics:

```python
{
    'wire_or_triggers': 0,      # Number of WIRE-OR triggers
    'p2p_triggers': 0,          # Number of P2P triggers
    'total_triggers': 0,        # Total triggers
    'ack_responses': 0          # ACK responses sent
}
```

### CTPTriggerEvent

A dataclass representing a trigger event:

```python
@dataclass
class CTPTriggerEvent:
    timestamp: int      # Simulation time in ns
    mode: int          # CTP mode (0=WIRE-OR, 1=P2P)
    source: str        # Source signal name
```

### DTPCTPMode_e

Enum for CTP modes (defined in `dtp_enum.py`):

```python
class DTPCTPMode_e(IntEnum):
    WIRE_OR = 0
    POINT_TO_POINT = 1
```

## Signal Mapping

### WIRE-OR Mode

| Signal | Direction | Purpose |
|--------|-----------|---------|
| `ct_req_out_din` | Input | Incoming trigger from pad |
| `ct_req_out_din_en` | Output | Enable input buffer |
| `ct_dst` | Output | Trigger output to core |

### POINT-TO-POINT Mode

| Signal | Direction | Purpose |
|--------|-----------|---------|
| `ct_req_in_din` | Input | Request from peer |
| `ct_req_in_din_en` | Output | Enable input buffer |
| `ct_ack_in_din` | Output | Acknowledge to peer |
| `ct_ack_out_dout` | Input | Acknowledge from peer |
| `ct_dst` | Output | Trigger output to core |

## Examples

See the test cases above for comprehensive usage examples.

## License

Copyright 2025 Tenstorrent Inc.

## Author

Andrew Hsiao (ahsiao@tenstorrent.com)

