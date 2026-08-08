# JTAG Verification Environment for CocoTB

A comprehensive JTAG Bus Functional Model (BFM) and verification environment designed for CocoTB testbenches. This package provides a complete solution for IEEE 1149.1 JTAG protocol verification with interface-based design, TAP state machine tracking, and extensive transaction analysis capabilities.

## 🎯 Overview

This verification environment includes:
- **Interface-based Design**: Unified signal definitions through SystemVerilog interfaces
- **JTAG Master BFM**: Full-featured JTAG controller for driving transactions
- **JTAG Slave BFM**: Configurable JTAG slave model with custom instruction support
- **JTAG Monitor**: Passive monitoring with transaction analysis and TAP state tracking
- **TAP State Machine**: Complete IEEE 1149.1 TAP controller state machine implementation
- **Advanced Features**: Random interruption, pause state handling, comprehensive logging

## 📁 File Structure

```
jtag_vip/
├── README.md             # This documentation
├── __init__.py           # Package initialization and exports
├── jtag_intf.sv          # JTAG SystemVerilog interface
├── jtag_mst_bfm.py       # JTAG Master Bus Functional Model
├── jtag_slv_bfm.py       # JTAG Slave Bus Functional Model
├── jtag_mon.py           # JTAG Monitor
├── jtag_test_example.py  # Comprehensive test examples
└── package_test.py       # Package functionality test
```

## 🔧 Core Components

### 1. JTAG Interface (`jtag_intf.sv`)

The foundation of the verification environment - a comprehensive SystemVerilog interface that defines all JTAG signals and provides multiple modports for different perspectives.

**Features:**
- ✅ Standard 4-wire JTAG interface (TCK, TMS, TDI, TDO)
- ✅ Optional TRST (Test Reset) signal with parameter control
- ✅ Master, slave, and monitor modports
- ✅ Built-in TAP state machine tracking
- ✅ Utility tasks and protocol assertions
- ✅ IEEE 1149.1 compliant state transitions

**Parameters:**
```systemverilog
jtag_intf #(
    .ENABLE_TRST(1'b1)    // Enable TRST signal (0 = disable, 1 = enable)
) jtag_ptap_if ();
```

**Signal Definitions:**
- `tck`  - Test Clock (JTAG clock signal)
- `tms`  - Test Mode Select (controls TAP state machine)
- `tdi`  - Test Data In (serial data input)
- `tdo`  - Test Data Out (serial data output)
- `trst` - Test Reset (optional active-low reset)

### 2. JTAG BFM (`jtag_mst_bfm.py`)

A full-featured JTAG controller BFM for driving JTAG transactions with advanced verification features.

**Key Classes:**
- `JTAG_Master_BFM`: Main BFM class
- `TAPState`: TAP state enumeration (imported from BFM)

**Features:**
- ✅ Complete IEEE 1149.1 TAP state machine navigation
- ✅ Instruction Register (IR) and Data Register (DR) scanning
- ✅ Random interruption with pause state handling
- ✅ Configurable TCK period and timing
- ✅ Hardware (TRST) and software (TMS) reset
- ✅ Advanced BFM behavior for robust verification

**Basic Usage:**
```python
# Create JTAG BFM using interface
jtag_vip = JTAG_Master_BFM(jtag_intf, tck_period_ns=10)

# Perform reset
await jtag_vip.reset()

# Scan Instruction Register
ir_result = await jtag_vip.scan_ir(0x5, 4)  # 4-bit instruction

# Scan Data Register  
dr_result = await jtag_vip.scan_dr(0xDEADBEEF, 32)  # 32-bit data
```

**Advanced Features:**
- **Random Interruption**: 25% chance of interrupting scans with pause states
- **State Navigation**: Smart navigation between TAP states
- **Timing Control**: Configurable TCK period and cycle management
- **Reset Support**: Both TRST and TMS-based reset sequences

### 3. JTAG Slave BFM (`jtag_slv_bfm.py`)

A full-featured JTAG slave model for responding to JTAG master transactions with configurable instruction set.

**Key Classes:**
- `JTAG_Slave_BFM`: Main slave BFM class
- `JTAGInstruction`: Instruction definition with configurable DR width
- `create_jtag_slave_bfm()`: Convenience function to create slave BFM

**Features:**
- ✅ Full IEEE 1149.1 TAP state machine implementation (slave perspective)
- ✅ Configurable Instruction Register (IR) width
- ✅ User-defined instructions with variable-width Data Registers
- ✅ Automatic BYPASS (1-bit DR) for undefined instructions
- ✅ IDCODE instruction support (optional)
- ✅ Proper TCK edge timing (sample on rising, update on falling)
- ✅ Callback support for UPDATE-DR state
- ✅ FIFO-like shift register implementation per IEEE standard

**Basic Usage:**
```python
# Create JTAG slave with 5-bit IR and IDCODE
jtag_slave = JTAG_Slave_BFM(jtag_intf, ir_width=5, idcode=0x12345678)

# Register custom 32-bit control register at instruction 0x08
jtag_slave.register_instruction(
    opcode=0x08,
    dr_width=32,
    name="CTRL_REG",
    capture_value=0x0,
    update_callback=lambda val: print(f"Control updated: 0x{val:08X}")
)

# Register 64-bit status register at instruction 0x09
jtag_slave.register_instruction(
    opcode=0x09,
    dr_width=64,
    name="STATUS_REG",
    capture_value=0xDEADBEEF_CAFEBABE
)

# Start the slave BFM (runs continuously)
cocotb.start_soon(jtag_slave.run())
```

**Advanced Features:**
```python
# Get current DR value after UPDATE-DR
dr_value = jtag_slave.get_dr_value()

# Dynamically update capture value
jtag_slave.set_dr_capture_value(0xNEW_VALUE)

# Register instruction with custom callback
def my_callback(dr_value):
    print(f"Received: 0x{dr_value:X}")
    # Perform custom actions...

jtag_slave.register_instruction(
    opcode=0x0A,
    dr_width=16,
    name="CUSTOM_CMD",
    update_callback=my_callback
)
```

**Key Behavior:**
- **Undefined Instructions**: Any instruction not explicitly registered defaults to BYPASS (1-bit DR)
- **Standard Instructions**: BYPASS (all 1's) and IDCODE (0x01, if enabled) are pre-registered
- **TDR Width**: Fully configurable per instruction, implementing FIFO behavior per IEEE 1149.1
- **State Machine**: Automatically tracks TAP states and handles IR/DR capture, shift, and update

### 4. JTAG Monitor (`jtag_mon.py`)

A comprehensive monitor for JTAG transaction analysis and protocol checking.

**Key Classes:**
- `JTAGMonitor`: Main monitor class
- `JTAGTransaction`: Transaction data structure
- `TAPState`: TAP state enumeration

**Features:**
- ✅ Real-time TAP state machine tracking
- ✅ IR and DR transaction correlation
- ✅ Transaction timing analysis
- ✅ Comprehensive statistics collection
- ✅ CSV export for detailed analysis
- ✅ Protocol violation detection

**Basic Usage:**
```python
# Create JTAG monitor using interface
jtag_monitor = create_jtag_monitor(jtag_intf, "JTAG_Monitor")

# Start monitoring
await jtag_monitor.start_monitoring()

# ... run tests ...

# Stop and analyze
await jtag_monitor.stop_monitoring()

# Get results
ir_transactions = jtag_monitor.get_transaction_history("IR")
dr_transactions = jtag_monitor.get_transaction_history("DR")
stats = jtag_monitor.get_statistics()
```

## 📦 Package Installation and Import

The JTAG BFM is designed as a proper Python package that can be easily imported and used in other Python code.

### Package Structure
```
jtag_vip/
├── __init__.py           # Package initialization and exports
├── jtag_mst_bfm.py      # JTAG Master BFM implementation
├── jtag_mon.py          # JTAG Monitor implementation
├── jtag_intf.sv         # SystemVerilog interface
└── package_test.py      # Package functionality test
```

### Import Methods

**Method 1: Import specific classes**
```python
from jtag_vip import JTAG_Master_BFM, create_jtag_monitor, TAPState, JTAGTransaction

# Use directly
jtag_vip = JTAG_Master_BFM(jtag_intf, tck_period_ns=10)
jtag_monitor = create_jtag_monitor(jtag_intf, "Monitor")
```

**Method 2: Import entire package**
```python
import jtag_vip

# Use with qualified names
jtag_vip_instance = jtag_vip.JTAG_Master_BFM(jtag_intf, tck_period_ns=10)
monitor = jtag_vip.create_jtag_monitor(jtag_intf, "Monitor")

# Get package information
print(jtag_vip.get_package_info())
```

**Method 3: Import with wildcard (all exported items)**
```python
from jtag_vip import *

# All main classes and functions available directly
jtag_vip = JTAG_Master_BFM(jtag_intf)
current_state = TAPState.RUN_TEST_IDLE
```

### Package Installation (Optional)

**Option 1: Use directly without installation**
```bash
# Add to Python path in your script
import sys
sys.path.append('/path/to/common')
from jtag_vip import JTAG_Master_BFM
```

**Option 2: Install as editable package**
```bash
cd jtag_vip/
pip install -e .
```

**Option 3: Install with development dependencies**
```bash
cd jtag_vip/
pip install -e .[dev]
```

### Package Validation

Test package functionality:
```bash
cd jtag_vip/
python package_test.py

# Or if installed:
jtag-bfm-test
```

This will validate all imports and demonstrate usage patterns.

## 🚀 Quick Start Guide

### Step 1: SystemVerilog Testbench Setup

```systemverilog
module testbench_top;
    // Instantiate JTAG interface
    jtag_intf #(
        .ENABLE_TRST(1'b1)
    ) jtag_ptap_if ();
    
    // Connect to your DUT
    your_jtag_device dut (
        .jtag_tck(jtag_ptap_if.tck),
        .jtag_tms(jtag_ptap_if.tms),
        .jtag_tdi(jtag_ptap_if.tdi),
        .jtag_tdo(jtag_ptap_if.tdo),
        .jtag_trst(jtag_ptap_if.trst)
    );
    
    initial begin
        $dumpfile("jtag_test.vcd");
        $dumpvars(0, testbench_top);
    end
endmodule
```

### Step 2: CocoTB Test Implementation

```python
import cocotb
from cocotb.triggers import Timer
from jtag_vip.jtag_mst_bfm import JTAG_Master_BFM, TAPState
from jtag_vip.jtag_mon import create_jtag_monitor

@cocotb.test()
async def test_jtag_basic(dut):
    # Access interface
    jtag_intf = dut.jtag_ptap_if
    
    # Create components
    jtag_vip = JTAG_Master_BFM(jtag_intf, tck_period_ns=10)
    jtag_monitor = create_jtag_monitor(jtag_intf, "Test_Monitor")
    
    # Start monitoring
    await jtag_monitor.start_monitoring()
    
    # Perform JTAG operations
    await jtag_vip.reset()
    
    # Scan IR and DR
    ir_result = await jtag_vip.scan_ir(0x5, 4)
    dr_result = await jtag_vip.scan_dr(0xDEADBEEF, 32)
    
    # Stop monitoring and analyze
    await jtag_monitor.stop_monitoring()
    
    # Get results
    stats = jtag_monitor.get_statistics()
    print(f"Statistics: {stats}")
```

## 📊 Advanced Features

### TAP State Machine Navigation

The BFM provides intelligent TAP state navigation:

```python
# Direct state navigation
await jtag_vip.goto_state(TAPState.SHIFT_IR)
await jtag_vip.goto_state(TAPState.SHIFT_DR)

# Safe navigation to Run-Test/Idle from any state
await jtag_vip.goto_run_test_idle()

# Check current state via monitor
current_state = jtag_monitor.get_current_state()
print(f"Current TAP state: {current_state.name}")
```

### Random Interruption Testing

The BFM includes advanced features for robust verification:

```python
# The BFM automatically includes random interruptions
# 25% chance of interrupting scans with pause states
for i in range(5):
    result = await jtag_vip.scan_dr(0xA5A5A5A5, 32)
    print(f"Scan {i} result: 0x{result:X}")
```

### Transaction Analysis

The monitor provides comprehensive transaction analysis:

```python
# Get transaction history
all_transactions = jtag_monitor.get_transaction_history()
ir_transactions = jtag_monitor.get_transaction_history("IR")
dr_transactions = jtag_monitor.get_transaction_history("DR")

# Analyze transactions
for tx in ir_transactions:
    print(f"IR: TDI=0x{tx.tdi_value:X}, TDO=0x{tx.tdo_value:X}, "
          f"Duration={tx.duration:.1f}ns")

# Get instruction usage statistics
instruction_usage = jtag_monitor.get_instruction_usage()
print(f"Instruction usage: {instruction_usage}")

# Export detailed analysis
jtag_monitor.export_transactions_csv("jtag_analysis.csv")
```

### State History Tracking

```python
# Get detailed state change history
state_history = jtag_monitor.get_state_history()
for timestamp, old_state, new_state in state_history[-10:]:
    print(f"@{timestamp:.1f}ns: {old_state.name} -> {new_state.name}")
```

## 🧪 Test Examples

The `jtag_test_example.py` file contains comprehensive test examples:

1. **`test_jtag_basic_operations`** - Basic IR/DR scan operations
2. **`test_jtag_error_injection`** - Error scenarios and protocol violations
3. **`test_jtag_concurrent_operations`** - Multiple BFM instances and timing

Run the examples:
```bash
# Run all examples
make test MODULE=jtag_test_example

# Run specific test
make test MODULE=jtag_test_example TESTCASE=test_jtag_basic_operations
```

## 🔍 Protocol Compliance

### IEEE 1149.1 Specifications Supported

- ✅ **Complete TAP State Machine**: All 16 states with proper transitions
- ✅ **Standard JTAG Signals**: TCK, TMS, TDI, TDO, TRST
- ✅ **Instruction/Data Registers**: Full support for IR and DR operations
- ✅ **Reset Mechanisms**: Both hardware (TRST) and software (TMS) reset
- ✅ **Pause States**: Support for PAUSE-DR and PAUSE-IR states
- ✅ **Boundary Scan**: Compatible with boundary scan operations

### TAP State Machine

The environment implements the complete IEEE 1149.1 TAP state machine:

```
Test-Logic-Reset → Run-Test/Idle → Select-DR-Scan → Capture-DR → Shift-DR → Exit1-DR → Update-DR
                                 → Select-IR-Scan → Capture-IR → Shift-IR → Exit1-IR → Update-IR
                                                                           → Pause-DR → Exit2-DR
                                                                           → Pause-IR → Exit2-IR
```

## 📈 Performance Characteristics

### Timing
- **Configurable TCK Period**: Default 10ns, fully configurable
- **State Transitions**: Single cycle state changes
- **Reset Sequences**: Optimized reset patterns

### Scalability
- **Data Width**: Supports any data width (tested up to 1024 bits)
- **Transaction History**: Configurable history depth (default 1000 transactions)
- **Concurrent Monitoring**: Multiple BFM instances supported

## 🛠️ Customization

### Extending the JTAG BFM

```python
class CustomJTAGBFM(JTAG_Master_BFM):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.custom_feature = True
    
    async def custom_scan_sequence(self, instructions, data_list):
        # Implement custom scan sequences
        for instruction, data in zip(instructions, data_list):
            await self.scan_ir(instruction, 4)
            result = await self.scan_dr(data, 32)
            yield result
```

### Custom Monitor Analysis

```python
class CustomJTAGMonitor(JTAGMonitor):
    def analyze_custom_pattern(self):
        # Custom analysis of JTAG patterns
        pattern_transactions = []
        for tx in self.completed_transactions:
            if self.is_custom_pattern(tx):
                pattern_transactions.append(tx)
        return pattern_transactions
```

## 🐛 Debugging and Troubleshooting

### Common Issues

1. **Interface Not Found**
   ```
   AttributeError: 'SimHandle' object has no attribute 'jtag_ptap_if'
   ```
   **Solution**: Ensure the interface is instantiated as `jtag_ptap_if` in your testbench

2. **TDO Timing Issues**
   ```
   Warning: TDO timing may not follow standard
   ```
   **Solution**: Check that TDO changes on falling edge of TCK

3. **State Machine Stuck**
   ```
   JTAG: Transaction interrupted by reset
   ```
   **Solution**: Check TRST signal behavior or increase reset duration

### Debug Logging

Enable detailed logging for debugging:

```python
import logging
logging.getLogger("cocotb").setLevel(logging.DEBUG)

# Enable JTAG debug logging
jtag_vip.log.setLevel(logging.DEBUG)
jtag_monitor.log.setLevel(logging.DEBUG)
```

### Protocol Assertions

Enable protocol checking assertions:
```systemverilog
// In your testbench
`define JTAG_ENABLE_ASSERTIONS
```

### Waveform Analysis

Use the generated VCD files for detailed signal analysis:
```bash
gtkwave jtag_test.vcd &
```

Key signals to observe:
- `tck` - Clock signal
- `tms` - Mode select transitions
- `tdi/tdo` - Data flow
- `current_tap_state` - State machine progression

## 📝 Best Practices

### 1. Interface Management
- Always use the interface-based approach
- Ensure TRST parameter matches your DUT requirements
- Use modports for clear signal direction definition

### 2. State Machine Management
- Always reset before starting operations
- Check current state before complex operations
- Use `goto_run_test_idle()` for safe state recovery

### 3. Transaction Management
- Monitor transaction completion
- Check TDO values for expected responses
- Use appropriate data widths for your operations

### 4. Testing Strategy
- Start with basic IR/DR scans
- Progress to complex scan sequences
- Include error injection scenarios
- Test reset and recovery mechanisms

### 5. Performance Optimization
- Use appropriate TCK frequencies for your DUT
- Monitor transaction timing for performance analysis
- Consider pause state impacts on timing

## 🔄 Advanced Usage Patterns

### Instruction-Based Testing

```python
# Define instruction set
INSTRUCTIONS = {
    'BYPASS': 0x0,
    'IDCODE': 0x1,
    'SAMPLE': 0x2,
    'PRELOAD': 0x3,
    'EXTEST': 0x4
}

# Test each instruction
for name, instruction in INSTRUCTIONS.items():
    await jtag_vip.scan_ir(instruction, 4)
    result = await jtag_vip.scan_dr(0x0, 32)
    print(f"{name}: 0x{result:X}")
```

### Boundary Scan Operations

```python
# Boundary scan sequence
await jtag_vip.scan_ir(INSTRUCTIONS['SAMPLE'], 4)  # Sample
sample_data = await jtag_vip.scan_dr(0x0, boundary_length)

await jtag_vip.scan_ir(INSTRUCTIONS['PRELOAD'], 4)  # Preload
await jtag_vip.scan_dr(test_pattern, boundary_length)

await jtag_vip.scan_ir(INSTRUCTIONS['EXTEST'], 4)   # External test
result = await jtag_vip.scan_dr(0x0, boundary_length)
```

### Multi-Device Chain Testing

```python
# For multi-device JTAG chains
class JTAGChain:
    def __init__(self, jtag_intf, device_ir_lengths):
        self.jtag_vip = JTAG_Master_BFM(jtag_intf)
        self.ir_lengths = device_ir_lengths
        self.total_ir_length = sum(device_ir_lengths)
    
    async def scan_device_ir(self, device_index, instruction):
        # Build instruction for entire chain
        chain_instruction = self.build_chain_instruction(device_index, instruction)
        return await self.jtag_vip.scan_ir(chain_instruction, self.total_ir_length)
```

## 📊 Statistics and Analysis

### Transaction Statistics

```python
# Get comprehensive statistics
stats = jtag_monitor.get_statistics()
print(f"Total TCK cycles: {stats['total_clocks']}")
print(f"IR transactions: {stats['ir_transactions']}")
print(f"DR transactions: {stats['dr_transactions']}")
print(f"State changes: {stats['state_changes']}")
print(f"Resets: {stats['resets']}")
```

### Performance Analysis

```python
# Analyze transaction performance
transactions = jtag_monitor.get_transaction_history()
if transactions:
    avg_duration = sum(tx.duration for tx in transactions) / len(transactions)
    max_duration = max(tx.duration for tx in transactions)
    min_duration = min(tx.duration for tx in transactions)
    
    print(f"Average transaction time: {avg_duration:.1f}ns")
    print(f"Max transaction time: {max_duration:.1f}ns")
    print(f"Min transaction time: {min_duration:.1f}ns")
```

## 🔄 Version History

### v1.0.0 (Current)
- Initial release with full IEEE 1149.1 support
- Interface-based design with unified signal naming
- JTAG BFM with advanced verification features
- Comprehensive monitor with transaction analysis
- TAP state machine tracking and protocol assertions

## 🤝 Contributing

To contribute to this verification environment:

1. Follow the existing interface-based design pattern
2. Maintain compatibility with IEEE 1149.1 specification
3. Add comprehensive tests for new features
4. Update documentation for any API changes
5. Ensure TAP state machine compatibility

## 📞 Support

For questions or issues:
- Review the test examples in `jtag_test_example.py`
- Check the debugging section above
- Examine the interface definition in `jtag_intf.sv`
- Verify TAP state machine behavior with monitor

## 📄 License

This JTAG verification environment is provided as-is for verification purposes.

---

**Happy JTAG Testing! 🔧**

*Author: Andrew Hsiao (ahsiao@tenstorrent.com)*
