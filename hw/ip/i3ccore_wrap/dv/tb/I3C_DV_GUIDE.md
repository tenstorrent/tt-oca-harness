# I3C Core Design Verification Guide

## Table of Contents

1. [Introduction](#1-introduction)
2. [Testbench Architecture](#2-testbench-architecture)
3. [Getting Started - Running Tests](#3-getting-started---running-tests)
4. [Software Interface - Programming the I3C Device](#4-software-interface---programming-the-i3c-device)
5. [Python Test API Reference](#5-python-test-api-reference)
6. [Test Coverage](#6-test-coverage)
7. [Corner Cases and Error Conditions](#7-corner-cases-and-error-conditions)
8. [Key Operational Details](#8-key-operational-details)
9. [Test Execution Examples](#9-test-execution-examples)
10. [Limitations](#10-limitations)

---

## 1. Introduction

### Purpose

This document provides a comprehensive guide to the I3C core testing infrastructure for Design Verification (DV) engineers. It explains how the I3C controller and target devices are tested, covering everything from basic initialization to advanced features like In-Band Interrupts (IBI) and Common Command Codes (CCC).

The testbench validates an I3C core wrapper that implements the MIPI I3C specification, supporting both controller and target modes with a full register-based software interface.

### Key Features Tested

The I3C testbench validates the following capabilities:

- **Controller Mode**: Bus mastering, device addressing, private transfers, CCC command generation
- **Target Mode**: Static/dynamic address assignment, private read/write responses, IBI transmission
- **Common Command Codes (CCC)**: GETBCR, GETMWL, GETMRL, SETMWL, SETMRL, RSTACT
- **Private Transfers**: Read and write operations up to 500 bytes
- **In-Band Interrupts (IBI)**: Target-initiated interrupts with payload data
- **Error Handling**: NACK detection, FIFO overflow, invalid addresses
- **Register Interface**: 100+ registers across controller and target modes

### Technology Stack

- **Simulation**: VCS (Synopsys) with FSDB waveform dumping
- **Test Framework**: Cocotb (Python-based testbench)
- **Bus Interface**: AXI4-Lite for register access
- **I3C Bus**: Open-drain SDA/SCL with dual-instance modeling (controller + target)
- **Language**: SystemVerilog (RTL/TB), Python (tests)

---

## 2. Testbench Architecture

### Directory Structure

The testbench is organized in a flat structure at `hw/ip/i3ccore_wrap/dv/tb/`:

```
tb/
├── tb_i3ccore.sv              # SystemVerilog testbench top-level
├── i3ccore_filelist.f         # RTL compilation file list (bender-generated)
├── Makefile                   # Test execution and build orchestration
│
├── i3c_api.py                 # Core test infrastructure & API classes
│
├── test_i3ccore.py            # Main test: reset, registers, basic checks
├── test_i3c_setdasa.py        # Reference test: SETDASA + Read/Write
│
├── i3c_write_read_sanity.py   # 4-byte write/read sanity
├── i3c_long_write_sanity.py   # 500-byte write test
├── i3c_long_read_sanity.py    # 500-byte read test
├── i3c_immediate_write_sanity.py  # Immediate data transfers
│
├── i3c_direct_ccc_sanity.py   # Direct CCC command sequences
├── i3c_ibi_sanity.py          # In-Band Interrupt (IBI) with payload
└── i3c_error_sanity.py        # Error handling and FIFO overflow
```

### Key Components

#### tb_i3ccore.sv

**Purpose**: SystemVerilog testbench top-level that instantiates the I3C core wrapper and provides simulation infrastructure.

**Features**:

- **Clock/Reset Generation**: 100MHz clock, 10-cycle reset assertion
- **AXI4-Lite Interface**: Flattened signals for cocotb access
  - Write Address Channel: `axi_awaddr`, `axi_awprot`, `axi_awvalid`, `axi_awready`
  - Write Data Channel: `axi_wdata`, `axi_wstrb`, `axi_wvalid`, `axi_wready`
  - Write Response Channel: `axi_bresp`, `axi_bvalid`, `axi_bready`
  - Read Address Channel: `axi_araddr`, `axi_arprot`, `axi_arvalid`, `axi_arready`
  - Read Data Channel: `axi_rdata`, `axi_rresp`, `axi_rvalid`, `axi_rready`

- **I3C Bus Signals** (NUM_I3C=2 instances):
  - Open-drain modeling: `scl_i/o/oe`, `sda_i/o/oe` per instance
  - Bus aggregation: Shared SCL (controller drives), shared SDA (both can pull low)
  - Instance 0: Controller
  - Instance 1: Target

- **Interrupt Signals**: `irq[NUM_I3C-1:0]`
- **Waveform Support**: FSDB dumping when `+waves` and `+WAVE_FILE` plusargs are provided

#### i3c_api.py

**Purpose**: Core Python API providing reusable classes for all I3C operations.

**Classes**:

- `I3CHelper`: Low-level register I/O wrapper around AXI-Lite
- `I3CController`: High-level controller operations (init, CCC, private transfers, IBI)
- `I3CTarget`: High-level target operations (init, IBI transmission, descriptor management)

This API abstracts the complexity of register programming, command descriptor formatting, and FIFO management, allowing test writers to focus on protocol-level scenarios.

#### Test Modules

| File | Purpose | Complexity |
|------|---------|------------|
| `test_i3ccore.py` | Register verification, connectivity | Low |
| `test_i3c_setdasa.py` | Large private write/read with FIFO refill and drain | Medium |
| `i3c_write_read_sanity.py` | Basic 4-byte transfers | Low |
| `i3c_long_write_sanity.py` | 500-byte write test | Medium |
| `i3c_long_read_sanity.py` | 500-byte read test | Medium |
| `i3c_immediate_write_sanity.py` | Immediate data in descriptors | Medium |
| `i3c_direct_ccc_sanity.py` | CCC command sequences | Medium |
| `i3c_ibi_sanity.py` | IBI with payload | High |
| `i3c_error_sanity.py` | Error handling | High |

#### Makefile

**Purpose**: Test orchestration, compilation, waveform management.

**Key Features**:

- Single test execution: `make MODULE=<name>`
- Regression suite: `make all_tests` (runs every module in ALL_TEST_MODULES)
- Waveform control: `make WAVES=1` enables FSDB dumping
- Filelist generation: `make filelist` (from bender)
- Cleanup: `make clean` (artifacts), `make clean_all` (+ waveforms)
- Viewer launch: `make verdi`

### Hardware Configuration

**Dual-Instance Setup**:

- **Instance 0 (Controller)**: Base address `0x0000`, drives SCL, initiates transactions
- **Instance 1 (Target)**: Base address `0x1000`, responds to commands, can send IBI

**Bus Topology**:

- **SCL**: Only controller (instance 0) drives; target cannot drive SCL
- **SDA**: Open-drain shared bus; both instances can pull low for data/ACK
- **Pull-up**: Testbench models implicit pull-up (signal high when neither drives low)

**Address Space**:

- Controller registers: `0x0000` - `0x0FFF` (4KB)
- Target registers: `0x1000` - `0x1FFF` (4KB)

---

## 3. Getting Started - Running Tests

### Prerequisites

- **Simulator**: VCS with FSDB support (Verdi)
- **Python**: 3.6+ with cocotb installed
- **Environment**: Source project environment
- **Bender**: Ensure dependencies are checked out (`bender checkout`)

### Quick Start

Navigate to the testbench directory:

```bash
cd hw/ip/i3ccore_wrap/dv/tb
```

Run a single test:

```bash
make MODULE=i3c_write_read_sanity
```

Run the full regression suite:

```bash
make all_tests
```

Run a test with waveforms:

```bash
make MODULE=i3c_ibi_sanity WAVES=1
make verdi  # Open waveforms in Verdi
```

### Makefile Targets

| Command | Description |
|---------|-------------|
| `make` | Run default test (test_i3ccore) |
| `make MODULE=<name>` | Run specific test module |
| `make test_module_separate MODULE=<name>` | Run each test in module separately |
| `make WAVES=1` | Enable FSDB waveform dumping |
| `make TESTCASE=<name>` | Run single test function |
| `make filelist` | Generate RTL filelist from bender |
| `make clean` | Remove simulation artifacts |
| `make clean_all` | Remove artifacts + waveforms |
| `make verdi` | Open Verdi with FSDB waveforms |
| `make help` | Show usage information |

### Test Execution Flow

1. **Compilation**: VCS compiles RTL from `i3ccore_filelist.f` (incremental with `-Mupdate`)
2. **Elaboration**: Cocotb loads Python test module and testbench
3. **Simulation**: Python test interacts with DUT via cocotb AXI-Lite BFM
4. **Logging**: Test results printed to console; detailed logs in `/tmp/i3c_test_<module>.log`
5. **Waveforms**: FSDB files generated in `tb/` directory when `WAVES=1` is set

### Log Interpretation

**Pass Example**:

```
test_i3c_write_read_sanity.test_write_read_sanity PASS
```

**Fail Example**:

```
test_i3c_write_read_sanity.test_write_read_sanity FAIL
AssertionError: Expected 0xDEADBEEF, got 0xDEADBEE0
```

**Regression Summary** (from `make all_tests`):

```
TEST SUMMARY
========================================
Total:  <n>
Passed: <n>
Failed: 0
```

---

## 4. Software Interface - Programming the I3C Device

This section explains how to interact with the I3C core from a software perspective, covering register programming, initialization sequences, and transaction flows. This is the **most important section** for understanding how to use the I3C device.

### 4.1 Register Map Overview

The I3C core uses a HCI (Host Controller Interface) register layout defined by the MIPI I3C specification.

#### Controller Base Address: 0x0000

**Register Regions**:

| Region | Offset | Description |
|--------|--------|-------------|
| **Base Registers** | 0x000 - 0x07F | HCI version, capabilities, section offsets |
| **PIO Registers** | 0x080 - 0x0FF | Command/response ports, data FIFOs, interrupts |
| **Extended Caps** | 0x100 - 0x1FF | Timing, standby controller mode, TTI |
| **DAT Memory** | 0x400 - 0x7FF | Device Address Table (64-bit entries) |
| **DCT Memory** | 0x800 - 0xBFF | Device Characteristics Table |

**Key Controller Registers**:

| Address | Name | Purpose |
|---------|------|---------|
| 0x004 | `HC_CONTROL` | Bus enable, mode selector |
| 0x088 | `COMMAND_PORT` | Write command descriptors (64-bit) |
| 0x08C | `RESPONSE_PORT` | Read response descriptors (32-bit) |
| 0x090 | `TX_DATA_PORT` | Write transmit data (32-bit) |
| 0x094 | `RX_DATA_PORT` | Read received data (32-bit) |
| 0x098 | `IBI_PORT` | Read IBI status/data |
| 0x0A0 | `PIO_INTR_STATUS` | Interrupt status flags |
| 0x0A4 | `PIO_INTR_STATUS_ENABLE` | Interrupt status enables |
| 0x0A8 | `PIO_INTR_SIGNAL_ENABLE` | Interrupt signal enables |
| 0x09C | `QUEUE_THLD_CTRL` | Queue threshold control |
| 0x0A0 | `DATA_BUFFER_THLD_CTRL` | Data buffer threshold control |
| 0x184 | `STBY_CR_CONTROL` | Standby controller mode control |
| 0x22C+ | `T_HIGH_REG`, `T_LOW_REG`, etc. | Timing parameters |

#### Target (TTI) Base Address: 0x1000

**TTI (Target Transaction Interface) Registers**:

| Address | Name | Purpose |
|---------|------|---------|
| 0x1C4 | `TTI_CONTROL` | IBI enable (bit 12), descriptor enables |
| 0x1CC | `TTI_INTERRUPT_STATUS` | TTI status flags |
| 0x1D4 | `TTI_INTERRUPT_ENABLE` | TTI interrupt enables |
| 0x1DC | `TTI_RX_DESC_QUEUE_PORT` | Read RX descriptors |
| 0x1E0 | `TTI_RX_DATA_PORT` | Read RX data |
| 0x1E4 | `TTI_TX_DESC_QUEUE_PORT` | Write TX descriptors |
| 0x1E8 | `TTI_TX_DATA_PORT` | Write TX data |
| 0x1EC | `TTI_IBI_PORT` | Write IBI descriptors/data |
| 0x188 | `STBY_CR_DEVICE_ADDR` | Static/dynamic address |

### 4.2 Controller Initialization

The controller must be initialized before any I3C transactions can occur. This involves enabling the bus, configuring timing, and setting up interrupts.

**Step-by-Step Sequence**:

#### Step 1: Enable PIO Mode

Write to `HC_CONTROL` register (offset 0x004):

```python
# HC_CONTROL fields:
#   bit 31: bus_enable (0=disabled, 1=enabled)
#   bit 6: mode_selector (0=DMA, 1=PIO)

hc_control = (1 << 31) | (1 << 6)  # bus_enable=1, mode_selector=1
await helper.write(0x004, hc_control)
```

**Purpose**: Enables the I3C bus and selects PIO (Programmed I/O) mode for manual command/response handling.

#### Step 2: Set Active Controller Mode (ACM)

Write to `STBY_CR_CONTROL` register (offset 0x184):

```python
# STBY_CR_CONTROL fields:
#   bits [1:0]: stby_cr_enable_init
#     0b00 = Disabled
#     0b01 = ACM_INIT (Active Controller Mode - Initialization)
#     0b10 = SCM_RUNNING (Standby Controller Mode - Running)

stby_cr_control = 0x01  # ACM_INIT mode
await helper.write(0x184, stby_cr_control)
```

**Purpose**: Configures the controller as the active bus master with initialization privileges.

#### Step 3: Configure Interrupts

Enable interrupt status flags:

```python
# PIO_INTR_STATUS_ENABLE (offset 0x0A4)
# Enable: tx_thld, rx_thld, resp_ready, cmd_queue_ready
intr_status_enable = (1 << 3) | (1 << 2) | (1 << 1) | (1 << 0)
await helper.write(0x0A4, intr_status_enable)

# PIO_INTR_SIGNAL_ENABLE (offset 0x0A8)
# Enable signal generation for same interrupts
await helper.write(0x0A8, intr_status_enable)
```

**Purpose**: Enables interrupts for FIFO thresholds and command/response readiness.

#### Step 4: Enable PIO Queues

Write to `PIO_CONTROL` register (offset 0x0AC):

```python
# PIO_CONTROL fields:
#   bit 0: enable (1=enabled)
#   bit 1: rs (Resume/Suspend - 1=resume)

pio_control = (1 << 1) | (1 << 0)  # rs=1, enable=1
await helper.write(0x0AC, pio_control)
```

**Purpose**: Enables PIO queues and asserts the RS (Resume/Suspend) bit for bus ownership.

#### Step 5: Configure Timing Parameters

**Open-Drain (OD) I3C Timing**:

```python
# T_HIGH_REG (offset 0x22C): SCL high period
await helper.write(0x22C, 10)  # 10 clock cycles

# T_LOW_REG (offset 0x230): SCL low period
await helper.write(0x230, 10)  # 10 clock cycles

# T_R_REG (offset 0x234): SCL rise time
await helper.write(0x234, 8)  # 8 clock cycles

# T_F_REG (offset 0x238): SCL fall time
await helper.write(0x238, 2)  # 2 clock cycles

# T_HD_STA_REG (offset 0x23C): START condition hold time
await helper.write(0x23C, 5)

# T_SU_STA_REG (offset 0x240): START condition setup time
await helper.write(0x240, 5)

# T_SU_STO_REG (offset 0x244): STOP condition setup time
await helper.write(0x244, 5)

# T_SU_DAT_REG (offset 0x248): Data setup time
await helper.write(0x248, 5)

# T_HD_DAT_REG (offset 0x24C): Data hold time
await helper.write(0x24C, 2)

# T_FREE_REG (offset 0x250): Bus free time
await helper.write(0x250, 500)

# T_AVAL_REG (offset 0x254): Bus available time (for target IBI)
await helper.write(0x254, 1000)

# T_IDLE_REG (offset 0x258): Bus idle time
await helper.write(0x258, 2000)
```

**Purpose**: Configures timing parameters for I3C open-drain mode according to spec requirements.

**Push-Pull (PP) Timing**:

For faster push-pull transfers, write similar values to PP-specific registers (offsets 0x25C+) with shorter times.

#### Step 6: Set FIFO Thresholds

```python
# DATA_BUFFER_THLD_CTRL (offset 0x09C)
# Formula: actual_threshold = 2^(register_value + 1)
# tx_buf=1 → 2^2=4 bytes, rx_buf=1 → 2^2=4 bytes
data_buffer_thld = (1 << 8) | (1 << 0)  # tx_buf=1, rx_buf=1
await helper.write(0x09C, data_buffer_thld)

# QUEUE_THLD_CTRL (offset 0x098)
# cmd_empty_buf=1, resp_buf=1
queue_thld = (1 << 8) | (1 << 0)
await helper.write(0x098, queue_thld)
```

**Purpose**: Sets thresholds for when TX/RX FIFO interrupts fire.

**Complete Initialization Code** (from `i3c_api.py`, simplified):

```python
async def initialize(self):
    """Initialize the I3C controller"""
    # Step 1: Enable PIO mode
    hc_control = HcControl()
    hc_control.f.bus_enable = 1
    hc_control.f.mode_selector = 1
    await self.helper.write(I3CBASE_HC_CONTROL_REG_ADDR, hc_control.val)

    # Step 2: Set ACM mode
    stby_cr_control = StbyCrControl()
    stby_cr_control.f.stby_cr_enable_init = 0b01  # ACM_INIT
    await self.helper.write(I3C_EC_STDBYCTRLMODE_STBY_CR_CONTROL_REG_ADDR, stby_cr_control.val)

    # Step 3: Configure interrupts
    pio_intr_status_enable = PioIntrStatusEnable()
    pio_intr_status_enable.f.tx_thld_stat_en = 1
    pio_intr_status_enable.f.rx_thld_stat_en = 1
    pio_intr_status_enable.f.resp_ready_stat_en = 1
    pio_intr_status_enable.f.cmd_queue_ready_stat_en = 1
    await self.helper.write(PIOCONTROL_PIO_INTR_STATUS_ENABLE_REG_ADDR, pio_intr_status_enable.val)

    # Step 4: Enable PIO
    pio_control = PioControl()
    pio_control.f.enable = 1
    pio_control.f.rs = 1
    await self.helper.write(PIOCONTROL_PIO_CONTROL_REG_ADDR, pio_control.val)

    # Step 5-6: Timing and thresholds
    await self.configure_timing_od_i3c()
    await self.configure_thresholds()
```

### 4.3 Target Initialization

The target must be configured with a static address and enabled to respond to controller commands.

**Step-by-Step Sequence**:

#### Step 1: Set Static Address

Write to `STBY_CR_DEVICE_ADDR` register (offset 0x188):

```python
# STBY_CR_DEVICE_ADDR fields:
#   bits [6:0]: static_addr (7-bit I3C address)
#   bit 15: static_addr_valid (1=valid)

static_addr = 0x10  # Example: address 0x10
device_addr = (1 << 15) | static_addr
await helper.write(0x1188, device_addr)  # Target base 0x1000 + 0x188
```

**Purpose**: Assigns the target's static I3C address (used before dynamic address assignment).

#### Step 2: Configure Standby Controller Mode

Write to `STBY_CR_CONTROL` register (offset 0x184):

```python
# STBY_CR_CONTROL for target:
#   bits [1:0]: stby_cr_enable_init = 0b10 (SCM_RUNNING)
#   bit 3: daa_setdasa_enable = 1 (allow SETDASA CCC)
#   bit 4: target_xact_enable = 1 (allow private transfers)

stby_cr_control = (1 << 4) | (1 << 3) | (0b10 << 0)
await helper.write(0x1184, stby_cr_control)  # Target base 0x1000 + 0x184
```

**Purpose**: Enables target mode, allows dynamic address assignment and private transactions.

#### Step 3: Enable TTI Interrupts

```python
# TTI_INTERRUPT_ENABLE (offset 0x1D4)
# Enable: TX_DATA_THLD, RX_DATA_THLD, TX_DESC_THLD, RX_DESC_THLD, IBI_THLD, IBI_DONE
tti_intr_enable = (1 << 13) | (1 << 12) | (1 << 3) | (1 << 2) | (1 << 1) | (1 << 0)
await helper.write(0x11D4, tti_intr_enable)
```

**Purpose**: Enables interrupts for target RX/TX FIFO thresholds and IBI completion.

#### Step 4: Configure Timing and Thresholds

Use the same timing configuration as the controller (mirror the values).

**Complete Target Initialization Code** (from `i3c_api.py`, simplified):

```python
async def initialize(self, static_addr):
    """Initialize the I3C target with static address"""
    # Step 1: Set static address
    stby_cr_device_addr = StbyCrDeviceAddr()
    stby_cr_device_addr.f.static_addr = static_addr
    stby_cr_device_addr.f.static_addr_valid = 1
    await self.helper.write(I3C_EC_STDBYCTRLMODE_STBY_CR_DEVICE_ADDR_REG_ADDR, stby_cr_device_addr.val)

    # Step 2: Configure SCM mode
    stby_cr_control = StbyCrControl()
    stby_cr_control.f.stby_cr_enable_init = 0b10  # SCM_RUNNING
    stby_cr_control.f.daa_setdasa_enable = 1
    stby_cr_control.f.target_xact_enable = 1
    await self.helper.write(I3C_EC_STDBYCTRLMODE_STBY_CR_CONTROL_REG_ADDR, stby_cr_control.val)

    # Step 3: Enable interrupts
    tti_intr_enable = TtiInterruptEnable()
    tti_intr_enable.f.tx_data_thld_stat_en = 1
    tti_intr_enable.f.rx_data_thld_stat_en = 1
    # ... (other interrupts)
    await self.helper.write(I3C_EC_TTI_INTERRUPT_ENABLE_REG_ADDR, tti_intr_enable.val)

    # Step 4: Timing and thresholds
    await self.configure_timing_od_i3c()
    await self.configure_thresholds()
```

### 4.4 Basic Read/Write Operations

This section covers the core data transfer operations: address assignment (SETDASA) and private read/write.

#### Address Assignment (SETDASA)

Before private transfers can occur, the target must be assigned a dynamic address. SETDASA is a broadcast CCC that assigns addresses based on static addresses.

**Command Descriptor Format** (64-bit):

```
Lower 32 bits (cmd_lo):
  [2:0]   = attr (0x2 for AddrAssign)
  [14:7]  = ccc_code (0x87 for SETDASA)
  [15]    = cp (1=command present)
  [21:16] = dat_idx (Device Address Table index)
  [26]    = wroc (write on completion)
  [29]    = rnw (0=write, 1=read)
  [30]    = wroc
  [31]    = toc (terminate on completion)

Upper 32 bits (cmd_hi):
  [31:0] = 0 (no data for SETDASA broadcast)
```

**Flow**:

1. **Configure DAT Entry**: Write static and dynamic addresses to DAT memory

```python
# DAT entry at index 0 (offset 0x400)
# Format: {reserved[63:23], dynamic_addr[22:16], reserved[15:7], static_addr[6:0]}
dat_entry_lo = static_addr  # Static address in bits [6:0]
dat_entry_hi = dynamic_addr << 16  # Dynamic address in bits [22:16]
await helper.write(0x400, dat_entry_lo)  # DAT[0] lower 32 bits
await helper.write(0x404, dat_entry_hi)  # DAT[0] upper 32 bits
```

2. **Issue SETDASA Command**:

```python
# Build command descriptor
cmd_lo = (0x2 << 0) | (0x87 << 7) | (0 << 16) | (1 << 26) | (1 << 30) | (1 << 31)
cmd_hi = 0

# Write to COMMAND_PORT (64-bit write = 2 x 32-bit writes)
await helper.write(0x088, cmd_lo)
await helper.write(0x08C, cmd_hi)
```

3. **Poll for Response**:

```python
# Poll PIO_INTR_STATUS (offset 0x0A0) for resp_ready_stat (bit 1)
while True:
    status = await helper.read(0x0A0)
    if status & (1 << 1):  # resp_ready_stat
        break
    await ClockCycles(dut.clk, 10)
```

4. **Read Response Descriptor**:

```python
# Read RESPONSE_PORT (offset 0x08C)
response = await helper.read(0x08C)

# Extract fields:
#   bits [27:28] = err_status (0=success)
#   bits [15:0] = data_length
err_status = (response >> 27) & 0x3
data_length = response & 0xFFFF

if err_status != 0:
    print(f"SETDASA failed with error {err_status}")
```

5. **Target Receives Dynamic Address**:

The target automatically receives the dynamic address by polling the RX descriptor queue.

**Complete SETDASA Code** (from `i3c_api.py`, simplified):

```python
async def send_setdasa(self, static_addr, dynamic_addr, dat_idx=0):
    """Send SETDASA CCC to assign dynamic address"""
    # Configure DAT entry
    await self.set_dat_entry(dat_idx, static_addr, dynamic_addr)

    # Build and send command
    cmd_lo = (0x2 << 0) | (0x87 << 7) | (dat_idx << 16) | (1 << 26) | (1 << 30) | (1 << 31)
    cmd_hi = 0
    await self.helper.write(PIOCONTROL_COMMAND_PORT_REG_ADDR, cmd_lo)
    await self.helper.write(PIOCONTROL_COMMAND_PORT_REG_ADDR + 4, cmd_hi)

    # Wait for response
    await self.helper.poll_field(PIOCONTROL_PIO_INTR_STATUS_REG_ADDR,
                                   PioIntrStatus, 'resp_ready_stat')

    # Read and verify response
    response = await self.helper.read(PIOCONTROL_RESPONSE_PORT_REG_ADDR)
    err_status = (response >> 27) & 0x3

    return err_status == 0
```

#### Private Write (Controller → Target)

A private write sends data from the controller to a specific target using its dynamic address.

**Command Descriptor Format**:

```
Lower 32 bits (cmd_lo):
  [2:0]   = attr (0x0 for RegularTransfer)
  [14:7]  = 0 (no CCC)
  [15]    = cp (0=no command)
  [21:16] = dat_idx (DAT table index)
  [26]    = wroc (1)
  [29]    = rnw (0=write)
  [30]    = wroc (1)
  [31]    = toc (1)

Upper 32 bits (cmd_hi):
  [31:16] = data_length (number of bytes)
  [15:0]  = 0
```

**Flow** (Interleaved Controller TX + Target RX):

1. **Write Command Descriptor**:

```python
# Example: Write 4 bytes
data_bytes = [0xDE, 0xAD, 0xBE, 0xEF]
data_len = len(data_bytes)

cmd_lo = (0x0 << 0) | (dat_idx << 16) | (0 << 29) | (1 << 26) | (1 << 30) | (1 << 31)
cmd_hi = data_len << 16

await helper.write(0x088, cmd_lo)
await helper.write(0x08C, cmd_hi)
```

2. **Poll for Command Queue Ready**:

```python
# Wait for cmd_queue_ready_stat (bit 0)
await helper.poll_field(0x0A0, PioIntrStatus, 'cmd_queue_ready_stat')
```

3. **Write TX Data** (when `tx_thld_stat` fires):

```python
# Pack bytes into 32-bit words (little-endian)
# data_bytes = [0xDE, 0xAD, 0xBE, 0xEF] → data_word = 0xEFBEADDE
data_word = (data_bytes[3] << 24) | (data_bytes[2] << 16) | (data_bytes[1] << 8) | data_bytes[0]

# Write to TX_DATA_PORT (offset 0x090)
await helper.write(0x090, data_word)
```

4. **Target Drains RX Data** (interleaved, when `TTI_RX_DATA_THLD_STAT` fires):

```python
# Poll TTI_INTERRUPT_STATUS (offset 0x1CC) for rx_data_thld_stat (bit 1)
status = await helper.read(0x11CC)
if status & (1 << 1):
    # Read from TTI_RX_DATA_PORT (offset 0x1E0)
    rx_word = await helper.read(0x11E0)
    # Unpack: 0xEFBEADDE → [0xDE, 0xAD, 0xBE, 0xEF]
    rx_bytes = [rx_word & 0xFF, (rx_word >> 8) & 0xFF, (rx_word >> 16) & 0xFF, (rx_word >> 24) & 0xFF]
```

5. **Poll for Response Ready**:

```python
# Controller polls resp_ready_stat
await helper.poll_field(0x0A0, PioIntrStatus, 'resp_ready_stat')
```

6. **Read Response**:

```python
response = await helper.read(0x08C)
err_status = (response >> 27) & 0x3
data_length = response & 0xFFFF

if err_status != 0:
    print(f"Write failed with error {err_status}")
```

7. **Target Waits for RX Descriptor**:

```python
# Poll for rx_desc_thld_stat (bit 3)
await helper.poll_field(0x11CC, TtiIntrStatus, 'rx_desc_thld_stat')

# Read RX descriptor from TTI_RX_DESC_QUEUE_PORT (offset 0x1DC)
rx_desc = await helper.read(0x11DC)
# Extract byte count, command, etc.
```

**Complete Private Write Code** (from `i3c_api.py`, simplified):

```python
async def private_write(self, data_bytes, target, dat_idx=0):
    """Private write to target"""
    data_len = len(data_bytes)

    # Send command descriptor
    cmd_lo = (0x0 << 0) | (dat_idx << 16) | (0 << 29) | (1 << 26) | (1 << 30) | (1 << 31)
    cmd_hi = data_len << 16
    await self.helper.write(PIOCONTROL_COMMAND_PORT_REG_ADDR, cmd_lo)
    await self.helper.write(PIOCONTROL_COMMAND_PORT_REG_ADDR + 4, cmd_hi)

    # Write TX data in 4-byte chunks
    for i in range(0, data_len, 4):
        chunk = data_bytes[i:i+4]
        data_word = self.helper.pack_bytes(chunk)

        # Wait for tx_thld_stat
        await self.helper.poll_field(PIOCONTROL_PIO_INTR_STATUS_REG_ADDR,
                                       PioIntrStatus, 'tx_thld_stat')

        await self.helper.write(PIOCONTROL_TX_DATA_PORT_REG_ADDR, data_word)

    # Target drains RX (interleaved in real implementation)
    # ...

    # Wait for response
    await self.helper.poll_field(PIOCONTROL_PIO_INTR_STATUS_REG_ADDR,
                                   PioIntrStatus, 'resp_ready_stat')

    response = await self.helper.read(PIOCONTROL_RESPONSE_PORT_REG_ADDR)
    err_status = (response >> 27) & 0x3

    return err_status == 0, response, target_rx_data
```

#### Private Read (Target → Controller)

A private read retrieves data from the target. The key difference from write is that the **controller issues the read command BEFORE the target fills its TX FIFO**.

**Command Descriptor Format**:

```
Lower 32 bits (cmd_lo):
  [2:0]   = attr (0x0)
  [14:7]  = 0
  [15]    = cp (0)
  [21:16] = dat_idx
  [26]    = wroc (1)
  [29]    = rnw (1=READ)  ← Key difference
  [30]    = wroc (1)
  [31]    = toc (1)

Upper 32 bits (cmd_hi):
  [31:16] = data_length (expected bytes to read)
  [15:0]  = 0
```

**Flow**:

1. **Controller Issues Read Command**:

```python
# Example: Read 4 bytes
read_len = 4

cmd_lo = (0x0 << 0) | (dat_idx << 16) | (1 << 29) | (1 << 26) | (1 << 30) | (1 << 31)
cmd_hi = read_len << 16

await helper.write(0x088, cmd_lo)
await helper.write(0x08C, cmd_hi)
```

2. **Target Waits for TX Descriptor Ready**:

```python
# Poll for tx_desc_thld_stat (bit 2)
await helper.poll_field(0x11CC, TtiIntrStatus, 'tx_desc_thld_stat')
```

3. **Target Writes TX Descriptor**:

```python
# TX descriptor format: {data_length[15:0], ...}
tx_desc = read_len
await helper.write(0x11E4, tx_desc)  # TTI_TX_DESC_QUEUE_PORT
```

4. **Target Fills TX FIFO**:

```python
# Example: Target sends [0x11, 0x22, 0x33, 0x44]
tx_data = [0x11, 0x22, 0x33, 0x44]
tx_word = (tx_data[3] << 24) | (tx_data[2] << 16) | (tx_data[1] << 8) | tx_data[0]

# Wait for tx_data_thld_stat (bit 0)
await helper.poll_field(0x11CC, TtiIntrStatus, 'tx_data_thld_stat')

# Write to TTI_TX_DATA_PORT (offset 0x1E8)
await helper.write(0x11E8, tx_word)
```

5. **Controller Drains RX FIFO**:

```python
# Wait for rx_thld_stat (bit 2)
await helper.poll_field(0x0A0, PioIntrStatus, 'rx_thld_stat')

# Read from RX_DATA_PORT (offset 0x094)
rx_word = await helper.read(0x094)
rx_bytes = [rx_word & 0xFF, (rx_word >> 8) & 0xFF, (rx_word >> 16) & 0xFF, (rx_word >> 24) & 0xFF]
```

6. **Target Waits for TX Descriptor Complete**:

```python
# Poll for tx_desc_complete_stat (bit 14)
await helper.poll_field(0x11CC, TtiIntrStatus, 'tx_desc_complete_stat')
```

7. **Controller Reads Response**:

```python
await helper.poll_field(0x0A0, PioIntrStatus, 'resp_ready_stat')
response = await helper.read(0x08C)
err_status = (response >> 27) & 0x3
```

**Complete Private Read Code** (from `i3c_api.py`, simplified):

```python
async def private_read(self, target, tx_data, dat_idx=0):
    """Private read from target (target provides tx_data)"""
    read_len = len(tx_data)

    # Send read command
    cmd_lo = (0x0 << 0) | (dat_idx << 16) | (1 << 29) | (1 << 26) | (1 << 30) | (1 << 31)
    cmd_hi = read_len << 16
    await self.helper.write(PIOCONTROL_COMMAND_PORT_REG_ADDR, cmd_lo)
    await self.helper.write(PIOCONTROL_COMMAND_PORT_REG_ADDR + 4, cmd_hi)

    # Target fills TX (interleaved in real implementation)
    # ...

    # Controller drains RX
    rx_data = []
    for i in range(0, read_len, 4):
        await self.helper.poll_field(PIOCONTROL_PIO_INTR_STATUS_REG_ADDR,
                                       PioIntrStatus, 'rx_thld_stat')

        rx_word = await self.helper.read(PIOCONTROL_RX_DATA_PORT_REG_ADDR)
        rx_bytes = self.helper.unpack_bytes(rx_word, min(4, read_len - i))
        rx_data.extend(rx_bytes)

    # Wait for response
    await self.helper.poll_field(PIOCONTROL_PIO_INTR_STATUS_REG_ADDR,
                                   PioIntrStatus, 'resp_ready_stat')

    response = await self.helper.read(PIOCONTROL_RESPONSE_PORT_REG_ADDR)
    err_status = (response >> 27) & 0x3

    return err_status == 0, response, rx_data
```

### 4.5 CCC (Common Command Codes) Commands

CCC commands are standardized I3C protocol commands for device configuration and status retrieval.

#### Supported CCC Codes

| Code | Name | Type | Description |
|------|------|------|-------------|
| 0x8E | GETBCR | Direct GET | Get Bus Characteristics Register (1 byte) |
| 0x8B | GETMWL | Direct GET | Get Max Write Length (2 bytes) |
| 0x8C | GETMRL | Direct GET | Get Max Read Length (2-3 bytes) |
| 0x89 | SETMWL | Direct SET | Set Max Write Length (2 bytes) |
| 0x8A | SETMRL | Direct SET | Set Max Read Length (2-3 bytes) |
| 0x9A | RSTACT | Direct | Direct Reset Action (1 byte defining byte) |

#### GET CCC (Read from Target)

GET CCCs retrieve configuration or status information from the target.

**Command Descriptor Format**:

```
Lower 32 bits (cmd_lo):
  [2:0]   = attr (0x0 for RegularTransfer)
  [14:7]  = ccc_code (e.g., 0x8E for GETBCR)
  [15]    = cp (1=command present)
  [21:16] = dat_idx
  [26]    = wroc (1)
  [29]    = rnw (1=READ)
  [30]    = wroc (1)
  [31]    = toc (1)

Upper 32 bits (cmd_hi):
  [31:16] = max_data_len (expected byte count)
  [15:0]  = 0
```

**Example: GETBCR (Get Bus Characteristics Register)**

```python
async def getbcr(self, dat_idx=0):
    """Get BCR from target"""
    ccc_code = 0x8E
    max_data_len = 1  # BCR is 1 byte

    # Build command descriptor
    cmd_lo = (0x0 << 0) | (ccc_code << 7) | (1 << 15) | (dat_idx << 16) | (1 << 29) | (1 << 30) | (1 << 31)
    cmd_hi = max_data_len << 16

    # Write to COMMAND_PORT
    await self.helper.write(0x088, cmd_lo)
    await self.helper.write(0x08C, cmd_hi)

    # Wait for response
    await self.helper.poll_field(0x0A0, PioIntrStatus, 'resp_ready_stat')

    # Read response
    response = await self.helper.read(0x08C)
    err_status = (response >> 27) & 0x3
    data_length = response & 0xFFFF

    if err_status != 0:
        return None

    # Read RX data
    await self.helper.poll_field(0x0A0, PioIntrStatus, 'rx_thld_stat')
    rx_word = await self.helper.read(0x094)
    bcr_value = rx_word & 0xFF

    return bcr_value
```

**BCR Value Interpretation**:

```
BCR byte [7:0]:
  bit 7: Advanced Capabilities
  bit 6: Device Role (0=slave, 1=master capable)
  bit 5: IBI Capable
  bit 4: IBI Payload
  bit 3: Offline Capable
  bit 2: Bridge Identifier
  bits [1:0]: Max Data Speed Limitation
```

**Example: GETMWL (Get Max Write Length)**

```python
async def getmwl(self, dat_idx=0):
    """Get Max Write Length from target"""
    ccc_code = 0x8B
    max_data_len = 2  # MWL is 2 bytes (MSB first)

    ok, resp, rx_data = await self.get_ccc(ccc_code, max_data_len, dat_idx)

    if ok and len(rx_data) >= 2:
        # MSB first: [MSB, LSB] → (MSB << 8) | LSB
        mwl_value = (rx_data[0] << 8) | rx_data[1]
        return mwl_value

    return None
```

**Example: GETMRL (Get Max Read Length)**

```python
async def getmrl(self, dat_idx=0):
    """Get Max Read Length from target"""
    ccc_code = 0x8C
    max_data_len = 3  # MRL is 2 bytes + optional IBI payload size byte

    ok, resp, rx_data = await self.get_ccc(ccc_code, max_data_len, dat_idx)

    if ok and len(rx_data) >= 2:
        mrl_value = (rx_data[0] << 8) | rx_data[1]
        ibi_payload_size = rx_data[2] if len(rx_data) >= 3 else 0
        return mrl_value, ibi_payload_size

    return None, None
```

#### SET CCC (write to target)

SET CCCs configure target parameters.

**Two Paths**:

1. **Immediate Descriptor** (≤4 bytes): Data embedded in command descriptor (no TX FIFO write)
2. **Regular Descriptor** (>4 bytes): Data sent via TX_DATA_PORT

**Immediate Descriptor Format** (for ≤4 bytes):

```
Lower 32 bits (cmd_lo):
  [2:0]   = attr (0x1 for ImmediateDataTransfer)
  [14:7]  = ccc_code
  [15]    = cp (1)
  [21:16] = dat_idx
  [26:23] = dtt (data byte count, 1-4)
  [29]    = rnw (0=write)
  [30]    = wroc (1)
  [31]    = toc (1)

Upper 32 bits (cmd_hi):
  [31:0] = data bytes packed (little-endian)
```

**Example: SETMWL (Set Max Write Length)**

```python
async def setmwl(self, mwl, dat_idx=0):
    """Set Max Write Length"""
    ccc_code = 0x89

    # Pack MWL as 2 bytes MSB first: [MSB, LSB]
    data_bytes = [(mwl >> 8) & 0xFF, mwl & 0xFF]

    # Use immediate descriptor (2 bytes)
    data_word = (data_bytes[1] << 8) | data_bytes[0]  # Little-endian

    cmd_lo = (0x1 << 0) | (ccc_code << 7) | (1 << 15) | (dat_idx << 16) | (len(data_bytes) << 23) | (1 << 30) | (1 << 31)
    cmd_hi = data_word

    await self.helper.write(0x088, cmd_lo)
    await self.helper.write(0x08C, cmd_hi)

    # Wait for response
    await self.helper.poll_field(0x0A0, PioIntrStatus, 'resp_ready_stat')
    response = await self.helper.read(0x08C)
    err_status = (response >> 27) & 0x3

    return err_status == 0
```

**Example: SETMRL (Set Max Read Length with IBI Payload Size)**

```python
async def setmrl(self, mrl, ibi_payload_size=0, dat_idx=0):
    """Set Max Read Length and optional IBI payload size"""
    ccc_code = 0x8A

    # Pack: [MRL_MSB, MRL_LSB, IBI_PAYLOAD_SIZE]
    data_bytes = [(mrl >> 8) & 0xFF, mrl & 0xFF, ibi_payload_size]

    # Use immediate descriptor (3 bytes)
    data_word = (data_bytes[2] << 16) | (data_bytes[1] << 8) | data_bytes[0]

    cmd_lo = (0x1 << 0) | (ccc_code << 7) | (1 << 15) | (dat_idx << 16) | (len(data_bytes) << 23) | (1 << 30) | (1 << 31)
    cmd_hi = data_word

    await self.helper.write(0x088, cmd_lo)
    await self.helper.write(0x08C, cmd_hi)

    # Wait for response
    await self.helper.poll_field(0x0A0, PioIntrStatus, 'resp_ready_stat')
    response = await self.helper.read(0x08C)
    err_status = (response >> 27) & 0x3

    return err_status == 0
```

**Example: RSTACT (Direct Reset Action)**

```python
async def rstact(self, defining_byte, dat_idx=0):
    """Direct Reset Action

    Defining byte:
      0x01 = RSTDAA (Reset Dynamic Address Assignment)
      0x02 = Peripheral Reset
    """
    ccc_code = 0x9A
    data_bytes = [defining_byte]

    # Immediate descriptor (1 byte)
    cmd_lo = (0x1 << 0) | (ccc_code << 7) | (1 << 15) | (dat_idx << 16) | (1 << 23) | (1 << 30) | (1 << 31)
    cmd_hi = defining_byte

    await self.helper.write(0x088, cmd_lo)
    await self.helper.write(0x08C, cmd_hi)

    # Wait for response
    await self.helper.poll_field(0x0A0, PioIntrStatus, 'resp_ready_stat')
    response = await self.helper.read(0x08C)
    err_status = (response >> 27) & 0x3

    return err_status == 0
```

**Complete CCC Sequence Example** (from `i3c_direct_ccc_sanity.py`):

```python
# After SETDASA:

# 1. Get BCR
bcr = await ctrl.getbcr(dat_idx=0)
print(f"BCR: 0x{bcr:02X}")

# 2. Get MWL (before SET)
mwl_before = await ctrl.getmwl(dat_idx=0)
print(f"MWL before: {mwl_before}")

# 3. Set MWL to 16 bytes
await ctrl.setmwl(0x10, dat_idx=0)

# 4. Get MWL (after SET, verify changed)
mwl_after = await ctrl.getmwl(dat_idx=0)
assert mwl_after == 0x10, f"Expected MWL=0x10, got {mwl_after}"

# 5. Get MRL
mrl, ibi_payload = await ctrl.getmrl(dat_idx=0)
print(f"MRL: {mrl}, IBI Payload: {ibi_payload}")

# 6. Set MRL to 16 bytes with IBI payload size 16
await ctrl.setmrl(0x10, 0x10, dat_idx=0)

# 7. Get MRL (verify)
mrl_after, ibi_after = await ctrl.getmrl(dat_idx=0)
assert mrl_after == 0x10 and ibi_after == 0x10

# 8. Direct reset action (RSTDAA)
await ctrl.rstact(0x01, dat_idx=0)
```

### 4.6 IBI (In-Band Interrupt) Handling

IBI allows a target to initiate an interrupt to the controller without polling.

#### Target IBI Transmission

**Step 1: Enable IBI Mode**

Write to `TTI_CONTROL` register (offset 0x1C4):

```python
# Read current TTI_CONTROL
tti_control = await helper.read(0x11C4)

# Set bit 12 (ibi_en)
tti_control |= (1 << 12)

# Write back
await helper.write(0x11C4, tti_control)
```

**Step 2: Write IBI Descriptor and Payload**

IBI descriptor format (written to `TTI_IBI_PORT` at offset 0x1EC):

```
IBI Descriptor Header (32-bit):
  [31:24] = MDB (Mandatory Data Byte)
  [7:0]   = Payload length (number of bytes after MDB)

Payload Data (32-bit chunks):
  4 bytes per write (little-endian)
```

**Example: Send IBI with 8-byte Payload**

```python
async def write_ibi(self, mdb, payload_bytes):
    """Send IBI from target"""
    # Step 1: Wait for IBI FIFO has space (ibi_thld_stat, bit 12)
    await self.helper.poll_field(0x11CC, TtiIntrStatus, 'ibi_thld_stat')

    # Step 2: Write IBI header
    ibi_header = (mdb << 24) | len(payload_bytes)
    await self.helper.write(0x11EC, ibi_header)  # TTI_IBI_PORT

    # Step 3: Write payload in 4-byte chunks
    for i in range(0, len(payload_bytes), 4):
        chunk = payload_bytes[i:i+4]
        payload_word = self.helper.pack_bytes(chunk)

        # Wait for space
        await self.helper.poll_field(0x11CC, TtiIntrStatus, 'ibi_thld_stat')

        await self.helper.write(0x11EC, payload_word)

    # Step 4: Wait for IBI done (bit 13)
    await self.helper.poll_field(0x11CC, TtiIntrStatus, 'ibi_done_stat')
```

**Complete Target IBI Code** (from `i3c_ibi_sanity.py`):

```python
# Example: Send IBI with MDB=0xAA and 8-byte payload
mdb = 0xAA
payload = [0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88]

await tgt.write_ibi(mdb, payload)
```

#### Controller IBI Reception

**Step 1: Enable IBI Interrupts**

```python
# PIO_INTR_STATUS_ENABLE (offset 0x0A4)
# Enable ibi_status_thld_stat_en (bit varies by implementation)
intr_enable = await helper.read(0x0A4)
intr_enable |= (1 << X)  # Set IBI threshold bit
await helper.write(0x0A4, intr_enable)

# Configure IBI threshold in QUEUE_THLD_CTRL (offset 0x098)
queue_thld = await helper.read(0x098)
queue_thld |= (1 << Y)  # Set IBI threshold
await helper.write(0x098, queue_thld)
```

**Step 2: Poll for IBI Received**

```python
# Wait for ibi_status_thld_stat
await helper.poll_field(0x0A0, PioIntrStatus, 'ibi_status_thld_stat')
```

**Step 3: Read IBI Status Descriptor**

IBI status descriptor format (read from `IBI_PORT` at offset 0x098):

```
IBI Status Descriptor (32-bit):
  [31]    = ibi_sts (1=IBI received)
  [30]    = error
  [29:27] = status_type (0=RegularIbi)
  [25]    = ts (timestamp present)
  [24]    = last_status
  [23:16] = chunks (number of data chunks)
  [15:8]  = ibi_id (target address)
  [7:0]   = data_length (total bytes including MDB)
```

**Step 4: Read IBI Data**

```python
async def read_ibi(self):
    """Read IBI from controller"""
    # Read IBI status descriptor
    ibi_status = await self.helper.read(0x098)  # IBI_PORT

    # Extract fields
    error = (ibi_status >> 30) & 0x1
    ibi_id = (ibi_status >> 8) & 0xFF  # Target address
    data_length = ibi_status & 0xFF

    if error:
        return False, None, None, None

    # Read data bytes (first byte is MDB)
    ibi_data = []
    for i in range(0, data_length, 4):
        data_word = await self.helper.read(0x098)  # IBI_PORT (same address)
        bytes_in_word = self.helper.unpack_bytes(data_word, min(4, data_length - i))
        ibi_data.extend(bytes_in_word)

    # Extract MDB and payload
    mdb = ibi_data[0] if len(ibi_data) > 0 else 0
    payload = ibi_data[1:] if len(ibi_data) > 1 else []

    return True, ibi_id, mdb, payload
```

**Complete Controller IBI Reception Code** (from `i3c_ibi_sanity.py`):

```python
# Controller waits for IBI
ok, rx_ibi_id, rx_mdb, rx_payload = await ctrl.read_ibi()

# Verify
assert ok, "IBI read failed"
assert rx_mdb == 0xAA, f"Expected MDB=0xAA, got {rx_mdb}"
assert rx_payload == [0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88], "Payload mismatch"
```

**Full IBI Test Flow** (from `i3c_ibi_sanity.py`):

```python
# 1. Initialize controller and target
await ctrl.initialize()
await tgt.initialize(static_addr=0x10)

# 2. Enable IBI on target
await tgt.enable_ibi_mode()

# 3. Enable IBI interrupts on controller
await ctrl.enable_ibi_interrupts(ibi_threshold=1)

# 4. SETDASA to assign dynamic address
await ctrl.send_setdasa(0x10, 0x10, dat_idx=0)

# 5. Get BCR to verify IBI capability (bit 5)
bcr = await ctrl.getbcr(dat_idx=0)
assert (bcr & (1 << 5)), "Target not IBI capable"

# 6. Set MRL with IBI payload size
await ctrl.setmrl(0x10, 0x10, dat_idx=0)

# 7. Target sends IBI
await tgt.write_ibi(mdb=0xAA, payload_bytes=[0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88])

# 8. Controller receives IBI
ok, ibi_id, mdb, payload = await ctrl.read_ibi()

# 9. Verify
assert ok and mdb == 0xAA and payload == [0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88]
```

---

## 5. Python Test API Reference

The `i3c_api.py` file provides a high-level Python API for I3C operations. This section documents the key classes and methods.

### I3CHelper Class

**Purpose**: Low-level register I/O wrapper around AXI-Lite.

**Constructor**:

```python
helper = I3CHelper(dut, axi_master, base_addr)
```

- `dut`: Cocotb DUT object
- `axi_master`: AXI-Lite master BFM instance
- `base_addr`: Base address for this I3C instance (0x0000 or 0x1000)

**Methods**:

#### `write(addr, data)`

Write 32-bit register.

```python
await helper.write(0x004, 0x80000040)  # Write HC_CONTROL
```

#### `read(addr)`

Read 32-bit register.

```python
value = await helper.read(0x004)  # Read HC_CONTROL
```

#### `read_into(addr, reg_class)`

Read and unpack into ctypes Union for bitfield access.

```python
hc_control = await helper.read_into(0x004, HcControl)
print(f"Bus enable: {hc_control.f.bus_enable}")
```

#### `write_verify(addr, data, mask=0xFFFFFFFF)`

Write and verify readback.

```python
ok = await helper.write_verify(0x004, 0x80000040)
assert ok, "Write verification failed"
```

#### `poll_field(addr, reg_class, field_name, max_polls=10000, interval=10)`

Poll until a register field is non-zero.

```python
# Poll until resp_ready_stat is set
await helper.poll_field(0x0A0, PioIntrStatus, 'resp_ready_stat')
```

- `max_polls`: Maximum poll attempts (default 10000)
- `interval`: Clock cycles between polls (default 10)
- Raises `TimeoutError` if field doesn't become non-zero

#### `pack_bytes(byte_list)`

Pack up to 4 bytes into 32-bit word (little-endian).

```python
word = helper.pack_bytes([0xDE, 0xAD, 0xBE, 0xEF])
# Result: 0xEFBEADDE
```

#### `unpack_bytes(word, count=4)`

Unpack 32-bit word into bytes (little-endian).

```python
bytes_list = helper.unpack_bytes(0xEFBEADDE, count=4)
# Result: [0xDE, 0xAD, 0xBE, 0xEF]
```

### I3CController Class

**Purpose**: High-level controller operations.

**Constructor**:

```python
ctrl = I3CController(dut, axi_master, base_addr=0x0000)
```

**Initialization Methods**:

#### `initialize()`

Full controller initialization: HC_CONTROL, ACM_INIT, interrupts, PIO enable.

```python
await ctrl.initialize()
```

#### `configure_timing_od_i3c()`

Configure open-drain I3C timing parameters (T_HIGH, T_LOW, T_R, T_F, etc.).

```python
await ctrl.configure_timing_od_i3c()
```

#### `configure_timing_pp()`

Configure push-pull timing parameters.

```python
await ctrl.configure_timing_pp()
```

#### `configure_thresholds(tx_buf=1, tx_start=0, rx_buf=1, rx_start=0, cmd_empty_buf=1, resp_buf=1)`

Configure FIFO thresholds (formula: threshold = 2^(val+1)).

```python
await ctrl.configure_thresholds(tx_buf=2, rx_buf=2)  # 8-byte thresholds
```

**DAT Management**:

#### `set_dat_entry(idx, static_addr, dynamic_addr)`

Configure Device Address Table entry.

```python
await ctrl.set_dat_entry(idx=0, static_addr=0x10, dynamic_addr=0x10)
```

**CCC Commands**:

#### `send_setdasa(static_addr, dynamic_addr, dat_idx=0)`

Send SETDASA CCC to assign dynamic address.

```python
ok = await ctrl.send_setdasa(static_addr=0x10, dynamic_addr=0x10, dat_idx=0)
```

#### `getbcr(dat_idx=0)`

Get Bus Characteristics Register (1 byte).

```python
bcr = await ctrl.getbcr(dat_idx=0)
print(f"IBI capable: {bool(bcr & (1 << 5))}")
```

#### `getmwl(dat_idx=0)`

Get Max Write Length (2 bytes, MSB first).

```python
mwl = await ctrl.getmwl(dat_idx=0)
```

#### `getmrl(dat_idx=0)`

Get Max Read Length (2-3 bytes: MRL + optional IBI payload size).

```python
mrl, ibi_payload = await ctrl.getmrl(dat_idx=0)
```

#### `setmwl(mwl, dat_idx=0)`

Set Max Write Length (2 bytes, MSB first).

```python
await ctrl.setmwl(0x10, dat_idx=0)  # Set to 16 bytes
```

#### `setmrl(mrl, ibi_payload_size=0, dat_idx=0)`

Set Max Read Length and optional IBI payload size.

```python
await ctrl.setmrl(0x10, ibi_payload_size=0x08, dat_idx=0)
```

#### `rstact(defining_byte, dat_idx=0)`

Direct Reset Action (0x01 for RSTDAA, 0x02 for peripheral reset).

```python
await ctrl.rstact(0x01, dat_idx=0)  # Reset dynamic address
```

**Private Data Transfers**:

#### `private_write(data_bytes, target, dat_idx=0, bytes_per_entry=4)`

Private write to target (up to 1024 bytes).

```python
ok, resp, rx_data = await ctrl.private_write([0xDE, 0xAD, 0xBE, 0xEF], target, dat_idx=0)
```

Returns:

- `ok`: True if no error
- `resp`: Response descriptor (32-bit)
- `rx_data`: Data received by target

#### `private_read(target, tx_data, dat_idx=0, bytes_per_entry=4)`

Private read from target (target provides tx_data).

```python
ok, resp, ctrl_rx_data = await ctrl.private_read(target, tx_data=[0x11, 0x22, 0x33, 0x44], dat_idx=0)
```

Returns:

- `ok`: True if no error
- `resp`: Response descriptor
- `ctrl_rx_data`: Data received by controller

**IBI (In-Band Interrupt)**:

#### `enable_ibi_interrupts(ibi_threshold=1)`

Enable IBI status threshold interrupt.

```python
await ctrl.enable_ibi_interrupts(ibi_threshold=1)
```

#### `wait_ibi_received(max_polls=10000, interval=10)`

Poll for IBI_STATUS_THLD_STAT bit.

```python
await ctrl.wait_ibi_received()
```

#### `read_ibi()`

Read IBI status descriptor and payload.

```python
ok, ibi_id, mdb, payload = await ctrl.read_ibi()
```

Returns:

- `ok`: True if no error
- `ibi_id`: Target address that sent IBI
- `mdb`: Mandatory Data Byte
- `payload`: Payload bytes (list)

### I3CTarget Class

**Purpose**: High-level target operations.

**Constructor**:

```python
tgt = I3CTarget(dut, axi_master, base_addr=0x1000)
```

**Initialization Methods**:

#### `initialize(static_addr)`

Initialize target with static address, enable TTI, configure interrupts.

```python
await tgt.initialize(static_addr=0x10)
```

#### `configure_timing_od_i3c()`

Configure open-drain timing (mirror of controller).

```python
await tgt.configure_timing_od_i3c()
```

#### `configure_timing_pp()`

Configure push-pull timing.

```python
await tgt.configure_timing_pp()
```

#### `configure_thresholds(tx_buf=1, tx_start=0, rx_buf=1, rx_start=0, ibi_buf=0)`

Configure TTI thresholds.

```python
await tgt.configure_thresholds(tx_buf=1, rx_buf=1, ibi_buf=0)
```

**Address Management**:

#### `wait_dynamic_addr(max_polls=1000)`

Poll RX descriptor queue until dynamic address is assigned.

```python
dynamic_addr = await tgt.wait_dynamic_addr()
```

**IBI Transmission**:

#### `enable_ibi_mode()`

Set TTI_CONTROL[ibi_en] bit.

```python
await tgt.enable_ibi_mode()
```

#### `write_ibi(mdb, payload_bytes)`

Write IBI descriptor (header + payload) to IBI queue.

```python
await tgt.write_ibi(mdb=0xAA, payload_bytes=[0x11, 0x22, 0x33, 0x44])
```

#### `wait_ibi_done(max_polls=10000, interval=10)`

Poll TTI_IBI_DONE_BIT (bit 13) until IBI transmission completes.

```python
await tgt.wait_ibi_done()
```

---

## 6. Test Coverage

This section describes the test modules, their purpose, and what they validate.

### Test Organization

Tests are organized into 5 levels of complexity, from basic register access to advanced error handling.

### Level 1: Basic Functionality

#### test_i3ccore.py

**Purpose**: Register verification, AXI-Lite connectivity, reset value checks.

**Tests**:

1. **test_base_registers**: Verify base register reset values
   - HCI_VERSION, HC_CAPABILITIES, section offsets
   - Ensures correct HCI version and capability reporting

2. **test_pio_registers**: Verify PIO register reset values and writable bits
   - COMMAND_PORT, RESPONSE_PORT, TX/RX_DATA_PORT, interrupts
   - Dual-pattern write-read cycles (0x5A5A5A5A, 0xA5A5A5A5)

3. **test_ec_registers**: Extended capability registers
   - Timing registers, standby controller mode, TTI registers
   - Boundary testing (first/last addresses)

4. **test_dat_dct_memory**: DAT/DCT memory initialization
   - First (index 0) and last (index 127) entries
   - Verifies memory is zeroed on reset

5. **test_queue_sizes**: QUEUE_SIZE register verification
   - CMD, RESP, IBI, TX, RX queue sizes
   - Ensures FIFO sizes match spec (8 entries each)

**Registers Tested**: 100+ across 7 register regions

**Coverage**: Basic register access, reset values, writable bit masks

### Level 2: Data Transfers

#### i3c_write_read_sanity.py

**Purpose**: Basic 4-byte bidirectional transfer validation.

**Test Flow**:

1. Initialize controller and target
2. Send SETDASA to assign dynamic address
3. Private write: Controller → Target [0xDE, 0xAD, 0xBE, 0xEF]
4. Private read: Target → Controller [0x11, 0x22, 0x33, 0x44]
5. Verify data integrity on both sides

**Coverage**: Basic data path, SETDASA, private read/write

#### i3c_long_write_sanity.py

**Purpose**: 500-byte write test to validate FIFO queue handling.

**Test Flow**:

1. SETDASA
2. Generate 500-byte incremental pattern: [0x00, 0x01, ..., 0xFF, 0x00, ...]
3. Private write in 4-byte chunks (125 command descriptors)
4. Target drains RX FIFO
5. Verify all 500 bytes match

**Coverage**: Large transfer handling, TX/RX FIFO management, queue overflow prevention

#### i3c_long_read_sanity.py

**Purpose**: 500-byte read test to validate RX FIFO capacity.

**Test Flow**:

1. SETDASA
2. Controller issues read command for 500 bytes
3. Target fills TX FIFO with incremental pattern
4. Controller drains RX FIFO
5. Verify all 500 bytes match

**Coverage**: Extended reads, FIFO thresholds, descriptor management

#### i3c_immediate_write_sanity.py

**Purpose**: Immediate data transfer (data embedded in command descriptor).

**Test Flow**:

1. SETDASA
2. Private write using immediate descriptor (≤4 bytes)
3. Data sent in `cmd_hi` field (no TX FIFO write)
4. Target receives data
5. Verify data integrity

**Coverage**: Immediate transfer optimization, DTT field encoding

### Level 3: CCC Commands

#### i3c_direct_ccc_sanity.py

**Purpose**: Full CCC command sequence validation.

**Test Flow**:

1. SETDASA to assign dynamic address
2. GETBCR: Read Bus Characteristics Register (1 byte)
   - Verify IBI capability bit (bit 5)
3. GETMWL: Read Max Write Length (2 bytes)
4. SETMWL(0x10): Set Max Write Length to 16 bytes
5. GETMWL: Verify MWL changed to 0x10
6. GETMRL: Read Max Read Length (2-3 bytes)
7. SETMRL(0x10, 0x10): Set MRL to 16 bytes with IBI payload size 16
8. GETMRL: Verify MRL and IBI payload size changed
9. RSTACT(0x01): Direct Reset Action (peripheral reset)

**Coverage**: All standard CCC commands, read-write-verify patterns, CCC response parsing

### Level 4: IBI (In-Band Interrupt)

#### i3c_ibi_sanity.py

**Purpose**: IBI transmission and reception with payload.

**Test Scenarios**:

**Test 1: IBI with 8-byte Payload**

1. Initialize controller and target
2. Enable IBI mode on target (`TTI_CONTROL[ibi_en]=1`)
3. Enable IBI interrupts on controller
4. SETDASA to assign dynamic address
5. GETBCR to verify IBI capability
6. SETMRL with IBI payload size
7. Target sends IBI (MDB=0xAA, payload=[0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88])
8. Controller receives IBI via interrupt threshold
9. Verify IBI ID, MDB, and payload bytes
10. Target waits for IBI_DONE interrupt

**Test 2: IBI During Broadcast CCC**

1. Setup as above
2. Controller issues broadcast CCC
3. Target sends IBI during broadcast
4. Verify IBI takes priority
5. Broadcast completes after IBI

**Coverage**: IBI enable, descriptor formatting, payload transmission, interrupt handling, priority over broadcasts

### Level 5: Error Handling

#### i3c_error_sanity.py

**Purpose**: Error condition validation and recovery.

**Test Scenarios**:

**Test 1: Wrong Target Address (NACK Detection)**

1. SETDASA to assign real target at DAT index 0 (address 0x10)
2. Configure DAT entry 1 with non-existent address (0x50)
3. Send immediate write to DAT index 1
4. Verify controller receives NACK on 9th SCL edge
5. Check TRANSFER_ERR_STAT and TRANSFER_ABORT_STAT bits
6. Verify response error status is non-zero

**Test 2: Target TX FIFO Overflow**

1. Target TX FIFO size is 8 entries (32 bytes)
2. Attempt to queue more than 8 TX descriptors
3. Trigger TX_DESC_COMPLETE interrupt
4. Verify overflow handling
5. Check for error status in TTI_INTERRUPT_STATUS

**Coverage**: Error detection (NACK), FIFO overflow, error status reporting, interrupt-based error handling

---

## 7. Corner Cases and Error Conditions

### Protocol Corner Cases

#### Address Range Boundaries

- **First Address (0x000)**: Base register region start
- **Last Address (0x7FC)**: Before DAT memory region
- **Boundary Testing**: Verifies no address aliasing or decode errors
- **Tests**: `test_i3ccore.py` writes and reads first/last addresses in each region

#### DAT Entry Boundaries

- **First Entry (index 0)**: Primary target device
- **Last Entry (index 127)**: Maximum DAT table size
- **Tests**: `test_i3ccore.py` writes/reads DAT[0] and DAT[127]
- **Coverage**: DAT memory decode, index range validation

#### FIFO Thresholds

- **Threshold Formula**: `actual_threshold = 2^(register_value + 1)`
- **Tested Values**: 0, 1, 2, 3 (2, 4, 8, 16 byte thresholds)
- **Tests**: `configure_thresholds()` in all test modules
- **Coverage**: TX/RX threshold interrupts, queue management

#### Large Transfers

- **500-byte Write**: Tests TX FIFO refill, command descriptor chaining
- **500-byte Read**: Tests RX FIFO drain, response queue capacity
- **Pattern**: Incremental 0x00-0xFF repeating pattern
- **Tests**: `i3c_long_write_sanity.py`, `i3c_long_read_sanity.py`
- **Coverage**: Multi-descriptor transfers, FIFO overflow prevention, data integrity

#### Interleaved Operations

- **Controller TX + Target RX**: Simultaneous FIFO operations
- **Flow**: Controller writes TX while target drains RX
- **Tests**: `private_write()` in `i3c_api.py`
- **Coverage**: Race conditions, FIFO synchronization, interrupt timing

### Error Scenarios

#### Non-existent Target

- **Setup**: Configure DAT entry with address 0x50 (no target responds)
- **Action**: Send immediate write to DAT index pointing to 0x50
- **Expected**: NACK on 9th SCL edge (no slave ACK)
- **Verification**: TRANSFER_ERR_STAT and TRANSFER_ABORT_STAT bits set
- **Tests**: `i3c_error_sanity.py::i3c_error_wrong_addr`
- **Coverage**: NACK detection, error status reporting, transaction abort

#### FIFO Overflow

- **TX FIFO Overflow**: Queue more than 8 TX descriptors
- **RX FIFO Overflow**: Read more than FIFO capacity without draining
- **Expected**: Overflow interrupt, error status set
- **Tests**: `i3c_error_sanity.py::i3c_fifo_overflow`
- **Coverage**: FIFO capacity limits, overflow detection, error recovery

#### Response Error Codes

- **Error Status Field**: Bits [27:28] in response descriptor
- **Codes**:
  - 0x0: Success
  - 0x1: CRC error
  - 0x2: Parity error
  - 0x3: Frame error
- **Tests**: All tests verify `err_status == 0` in responses
- **Coverage**: Error code extraction, error propagation

### Timing and Configuration

#### Open-Drain Timing

**Parameters Tested**:

| Parameter | Value | Description |
|-----------|-------|-------------|
| T_HIGH | 10 cycles | SCL high period |
| T_LOW | 10 cycles | SCL low period |
| T_R | 8 cycles | SCL rise time |
| T_F | 2 cycles | SCL fall time |
| T_HD_STA | 5 cycles | START hold time |
| T_SU_STA | 5 cycles | START setup time |
| T_SU_STO | 5 cycles | STOP setup time |
| T_SU_DAT | 5 cycles | Data setup time |
| T_HD_DAT | 2 cycles | Data hold time |
| T_FREE | 500 cycles | Bus free time |
| T_AVAL | 1000 cycles | Bus available (for IBI) |
| T_IDLE | 2000 cycles | Bus idle time |

**Tests**: All tests use `configure_timing_od_i3c()`

**Coverage**: Timing parameter configuration, I3C spec compliance

#### Push-Pull Timing

**Faster Parameters**:

| Parameter | Value |
|-----------|-------|
| T_HIGH_PP | 3 cycles |
| T_LOW_PP | 3 cycles |
| T_R_PP | 1 cycle |
| T_F_PP | 1 cycle |
| T_SU_PP | 1 cycle |
| T_HD_PP | 1 cycle |

**Tests**: `configure_timing_pp()` in every bring-up; `i3c_pp_timing_transfer.py`, `i3c_od_pp_mode_switch.py`

**Coverage**: Push-pull mode configuration

#### Bus Free/Idle Times

- **T_FREE (500 cycles)**: Minimum bus free time between transactions
- **T_AVAL (1000 cycles)**: Bus available time for target IBI requests
- **T_IDLE (2000 cycles)**: Bus idle time before sleep
- **Tests**: All tests configure these parameters
- **Coverage**: Bus state transitions, IBI arbitration timing

### Summary of Corner Cases

| Category | Corner Case | Test Coverage |
|----------|-------------|---------------|
| **Addressing** | First/last register addresses | test_i3ccore.py |
| **Addressing** | First/last DAT entries | test_i3ccore.py |
| **FIFO** | Threshold values (2, 4, 8, 16 bytes) | All tests |
| **FIFO** | TX FIFO overflow (>8 entries) | i3c_error_sanity.py |
| **FIFO** | RX FIFO overflow | i3c_error_sanity.py |
| **Transfers** | 500-byte write | i3c_long_write_sanity.py |
| **Transfers** | 500-byte read | i3c_long_read_sanity.py |
| **Transfers** | Immediate write (≤4 bytes) | i3c_immediate_write_sanity.py |
| **Transfers** | Interleaved TX/RX | All transfer tests |
| **Errors** | Wrong target address (NACK) | i3c_error_sanity.py |
| **Errors** | Non-zero error status | All tests verify |
| **Timing** | Open-drain parameters | All tests |
| **Timing** | Push-pull parameters | i3c_pp_timing_transfer.py |
| **IBI** | IBI with payload | i3c_ibi_sanity.py |
| **IBI** | IBI during broadcast | i3c_ibi_sanity.py |

---

## 8. Key Operational Details

### Command Descriptor Format (64-bit)

All Command descriptors are 64 bits

There are a few different types of Command Descriptors (They are all type defs of each other): See i3c_pkg.sv

Immediate Command Descriptor: Should be used in Controller writes, when the data to be sent <= 4 bytes (Data is embedded within the command)
Regular Command Descriptor: Can be used for any write/read
Command descriptors are written to the COMMAND_PORT (offset 0x088) as two 32-bit writes.

**Structure**:

```
Lower 32 bits (cmd_lo):
  [2:0]   = attr (Attribute)
    0x0 = RegularTransfer
    0x1 = ImmediateDataTransfer
    0x2 = AddrAssign (SETDASA)
  [14:7]  = ccc_code (CCC command code, if cp=1)
  [15]    = cp (Command Present)
  [21:16] = dat_idx (Device Address Table index)
  [26:23] = dtt (Data Transfer Type / byte count for immediate)
  [29]    = rnw (Read/Write: 0=write, 1=read)
  [30]    = wroc (Write Response On Completion)
  [31]    = toc (Terminate On Completion)

Upper 32 bits (cmd_hi):
  [31:16] = data_length (for regular transfers)
  [31:0]  = data_bytes (for immediate transfers, packed little-endian)
```

**Examples**:

**SETDASA Broadcast**:

```
cmd_lo = 0x8000_0287  (attr=2, ccc=0x87, toc=1, wroc=1)
cmd_hi = 0x0000_0000
```

**Private Write (4 bytes)**:

```
cmd_lo = 0xC400_0000  (attr=0, rnw=0, toc=1, wroc=1)
cmd_hi = 0x0004_0000  (data_length=4)
```

**Private Read (4 bytes)**:

```
cmd_lo = 0xE400_0000  (attr=0, rnw=1, toc=1, wroc=1)
cmd_hi = 0x0004_0000  (data_length=4)
```

**Immediate Write (2 bytes, data=0xAB, 0xCD)**:

```
cmd_lo = 0xC180_0001  (attr=1, dtt=2, toc=1, wroc=1)
cmd_hi = 0x0000_CDAB  (data packed little-endian)
```

### Response Descriptor Format (32-bit)

Response descriptors are read from the RESPONSE_PORT (offset 0x08C).

**Structure**:

```
[31]    = response_port_valid (1=valid)
[30]    = reserved
[29:28] = response_port_data_length_valid
[27:26] = err_status
  0x0 = Success
  0x1 = CRC error
  0x2 = Parity error
  0x3 = Frame error
[25:16] = tid (Transaction ID)
[15:0]  = data_length (bytes read/written)
```

**Example**:

```
response = 0x8000_0004
  err_status = 0 (success)
  data_length = 4 bytes
```

**Error Example**:

```
response = 0x8C00_0000
  err_status = 3 (frame error)
  data_length = 0
```

### IBI Status Descriptor Format (32-bit)

IBI status descriptors are read from the IBI_PORT (offset 0x098).

**Structure**:

```
[31]    = ibi_sts (IBI status valid)
[30]    = error
[29:27] = status_type
  0x0 = RegularIbi
  0x1 = MasterRequest
  0x2 = HotJoin
[26]    = reserved
[25]    = ts (timestamp present)
[24]    = last_status
[23:16] = chunks (number of data chunks)
[15:8]  = ibi_id (target address)
[7:0]   = data_length (total bytes including MDB)
```

**Example**:

```
ibi_status = 0x8001_1009
  ibi_sts = 1 (valid)
  status_type = 0 (RegularIbi)
  ibi_id = 0x10 (target address)
  data_length = 9 (1 MDB + 8 payload)
```

### FIFO Sizes

**Controller FIFO Sizes** (all 8 entries = 32 bytes):

| FIFO | Entries | Bytes | Purpose |
|------|---------|-------|---------|
| CMD | 8 | 64 | Command descriptors (8 bytes each) |
| RESP | 8 | 32 | Response descriptors (4 bytes each) |
| IBI | 8 | 32 | IBI status descriptors (4 bytes each) |
| TX | 8 | 32 | Transmit data (4 bytes each) |
| RX | 8 | 32 | Receive data (4 bytes each) |

**Target FIFO Sizes**:

| FIFO | Entries | Bytes | Purpose |
|------|---------|-------|---------|
| RX_DESC | 8 | 64 | RX descriptors (8 bytes each) |
| TX_DESC | 8 | 64 | TX descriptors (8 bytes each) |
| RX | 8 | 32 | RX data (4 bytes each) |
| TX | 8 | 32 | TX data (4 bytes each) |
| IBI | 8 | 32 | IBI descriptors (4 bytes each) |

**Threshold Calculation**:

```
For TX/RX/IBI FIFOS: actual_threshold_bytes = 2^(register_value + 1)

Examples:
  register_value = 0 → threshold = 2 bytes
  register_value = 1 → threshold = 4 bytes
  register_value = 2 → threshold = 8 bytes
  register_value = 3 → threshold = 16 bytes
```

For Command/Response (or TX/RX Descriptors for TTI): actual_threshold_bytes = register value

See HCI 7.5.5 and 7.5.6

---

## 9. Test Execution Examples

### Running Individual Tests

**Basic Write/Read Test**:

```bash
cd hw/ip/i3ccore_wrap/dv/tb
make MODULE=i3c_write_read_sanity
```

**Expected Output**:

```
Running test: i3c_write_read_sanity.test_write_read_sanity
Test PASSED
```

**With Waveforms**:

```bash
make MODULE=i3c_write_read_sanity WAVES=1
```

Waveforms saved to `test.fsdb`.

**View Waveforms**:

```bash
make verdi
```

### Running Full Regression

**All Tests**:

```bash
make all_tests
```


**Progress Output**: each module runs in its own simulation; the Makefile prints
`[PASS] <module> (TESTS=.. PASS=.. FAIL=.. SKIP=..)` or `[FAIL] <module>` per
module, then a `TEST SUMMARY` block with `Total`, `Passed` and `Failed` counts.

### Running Specific Test Function

**Test a Single Function**:

```bash
make test_module_separate MODULE=test_i3ccore TESTCASE=test_base_registers
```

This runs only `test_base_registers` from `test_i3ccore.py`.

### Debugging with Waveforms

**Run Test with Waveforms**:

```bash
make MODULE=i3c_ibi_sanity WAVES=1
```

**Open in Verdi**:

```bash
make verdi
```

**Key Signals to Monitor**:

**I3C Bus**:

- `tb_i3ccore.scl_i[0]`, `tb_i3ccore.scl_o[0]` (controller SCL)
- `tb_i3ccore.sda_i[0]`, `tb_i3ccore.sda_o[0]` (controller SDA)
- `tb_i3ccore.sda_i[1]`, `tb_i3ccore.sda_o[1]` (target SDA)

**AXI-Lite**:

- `tb_i3ccore.axi_awaddr`, `tb_i3ccore.axi_awvalid`, `tb_i3ccore.axi_awready`
- `tb_i3ccore.axi_wdata`, `tb_i3ccore.axi_wvalid`, `tb_i3ccore.axi_wready`
- `tb_i3ccore.axi_rdata`, `tb_i3ccore.axi_rvalid`, `tb_i3ccore.axi_rready`

**Interrupts**:

- `tb_i3ccore.irq[0]` (controller interrupt)
- `tb_i3ccore.irq[1]` (target interrupt)

### Cleaning Up

**Remove Simulation Artifacts**:

```bash
make clean
```

Removes `sim_build/`, `__pycache__/`, `.vcd`, `.fst`, `.wlf` files.

**Remove Waveforms Too**:

```bash
make clean_all
```

Also removes `.fsdb` waveform files.

---

## 10. Limitations

### Tested

The testbench provides solid coverage of core I3C functionality:

- **Basic I3C Protocol (SDR Mode)**: Standard data rate transfers validated
- **Standard CCC Commands**: GETBCR, GETMWL, GETMRL, SETMWL, SETMRL, RSTACT
- **Private Transfers**: Read and write operations up to 500 bytes
- **IBI with Payload**: Target-initiated interrupts with up to 8-byte payload
- **Error Handling**: Wrong address (NACK detection), FIFO overflow
- **Register Interface**: 100+ registers verified across controller and target modes
- **Dual-Instance Testing**: Controller and target tested simultaneously

### Not Tested

The following features are not covered by the testbench:

#### HDR Modes (High Data Rate)

- **HDR-DDR**: Double Data Rate mode (data on both clock edges)
- **HDR-TSL**: Ternary Symbol Legacy mode (3-level signaling)
- **HDR-BT**: Bulk Transfer mode (higher throughput)
- **Impact**: HDR modes provide faster data rates for performance-critical applications

#### Multi-Master Arbitration

- **Bus Ownership**: Multiple controllers competing for bus access
- **Arbitration**: Resolving conflicts when multiple controllers try to initiate transfers
- **Master Request**: Target requesting controller role
- **Impact**: Multi-master scenarios are common in complex systems

#### Hot-Join Sequences

- **Hot-Join**: New devices joining the I3C bus after initialization
- **Dynamic Address Assignment**: Assigning addresses to newly joined devices
- **Impact**: Allows plug-and-play device discovery

#### Legacy I2C Compatibility Mode

- **I2C Compatibility**: I3C controller communicating with legacy I2C devices
- **Mixed Bus**: I3C and I2C devices on the same bus
- **Impact**: Important for systems with existing I2C peripherals

#### Vendor-Specific CCC Commands

- **Extended CCCs**: Vendor-defined CCC codes beyond standard MIPI spec
- **Custom Configuration**: Device-specific configuration and status commands
- **Impact**: Allows custom features beyond standard I3C

#### Power Mode Transitions

- **Low-Power Modes**: Bus sleep, device suspend/resume
- **Power State Transitions**: Entering and exiting low-power states
- **Impact**: Critical for battery-powered systems

#### Randomized CCC Sequences

- **Random CCC Order**: Non-deterministic command sequences
- **Stress Testing**: Back-to-back CCCs with varying targets
- **Impact**: Validates state machine robustness

#### Recovery Interface

- **Recovery Payload**: Secure firmware recovery image activation
- **Recovery Signals**: `reset_payload_avail`, `image_activated`
- **Impact**: Critical for secure boot and firmware updates

---

## Conclusion

This I3C DV Guide provides a comprehensive reference for understanding and using the I3C core testing infrastructure. Key takeaways:

- **Software Interface**: Detailed register programming sequences for controller and target initialization, CCC commands, private transfers, and IBI
- **Python API**: High-level API (`I3CHelper`, `I3CController`, `I3CTarget`) simplifies test writing
- **Test Coverage**: test modules covering basic functionality, data transfers, CCC commands, IBI, and error handling
- **Corner Cases**: Validates address boundaries, FIFO thresholds, large transfers, and error conditions
- **Execution**: Simple Makefile targets for running individual tests or full regression

The testbench covers the core I3C functionality listed above and runs as a regression via `make all_tests`.

---

## Appendix: Quick Reference

### Makefile Commands

```bash
make MODULE=<name>              # Run specific test
make all_tests                  # Run full regression
make WAVES=1                    # Enable waveforms
make verdi                      # Open waveforms
make clean                      # Remove artifacts
make clean_all                  # Remove artifacts + waveforms
```

### Test Modules

| Module | Purpose |
|--------|---------|
| test_i3ccore | Register verification |
| test_i3c_setdasa | SETDASA + basic read/write |
| i3c_write_read_sanity | 4-byte transfers |
| i3c_long_write_sanity | 500-byte write |
| i3c_long_read_sanity | 500-byte read |
| i3c_immediate_write_sanity | Immediate data transfer |
| i3c_direct_ccc_sanity | CCC command sequence |
| i3c_ibi_sanity | IBI with payload |
| i3c_error_sanity | Error handling |

### Key Register Addresses

| Address | Register | Purpose |
|---------|----------|---------|
| 0x004 | HC_CONTROL | Bus enable, mode selector |
| 0x088 | COMMAND_PORT | Write command descriptors |
| 0x08C | RESPONSE_PORT | Read response descriptors |
| 0x090 | TX_DATA_PORT | Write TX data |
| 0x094 | RX_DATA_PORT | Read RX data |
| 0x098 | IBI_PORT | Read IBI status/data |
| 0x0A0 | PIO_INTR_STATUS | Interrupt status flags |
| 0x184 | STBY_CR_CONTROL | Controller mode control |
| 0x1C4 | TTI_CONTROL | Target IBI enable |
| 0x1EC | TTI_IBI_PORT | Write IBI descriptors |

### CCC Codes

| Code | Name | Type | Bytes |
|------|------|------|-------|
| 0x87 | SETDASA | Broadcast | N/A |
| 0x8E | GETBCR | Direct GET | 1 |
| 0x8B | GETMWL | Direct GET | 2 |
| 0x8C | GETMRL | Direct GET | 2-3 |
| 0x89 | SETMWL | Direct SET | 2 |
| 0x8A | SETMRL | Direct SET | 2-3 |
| 0x9A | RSTACT | Direct | 1 |

