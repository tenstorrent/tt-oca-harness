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
10. [Limitations and Future Work](#10-limitations-and-future-work)

---

## 1. Introduction

### Purpose

This document provides a comprehensive guide to the I3C core testing infrastructure for Design Verification (DV) engineers. It explains how the I3C controller and target devices are tested, covering everything from basic initialization to advanced features like In-Band Interrupts (IBI) and Common Command Codes (CCC).

The testbench validates an I3C core wrapper that implements the MIPI I3C specification, supporting both controller and target modes with a full register-based software interface.

### Key Features Tested

The I3C testbench validates the following capabilities:

- **Controller Mode**: Bus mastering, device addressing, private transfers, CCC command generation
- **Target Mode**: Static/dynamic address assignment, private read/write responses, IBI transmission
- **Direct CCC**: GETBCR, GETMWL, GETMRL, SETMWL, SETMRL, RSTACT, SETDASA, SETNEWDA
- **Broadcast CCC**: ENEC (0x00), DISEC (0x01), RSTDAA (0x06)
- **Private Transfers**: Immediate (in-descriptor) data through to multi-hundred-byte
  payloads, including the target-TX queue capacity boundary above 256 bytes
- **In-Band Interrupts (IBI)**: Target-initiated interrupts across payload sizes,
  plus the suppressed case when IBI generation is disabled
- **Bus Timing**: Open-drain and push-pull timing banks and the OD→PP switch
- **Error Handling**: Address NACK, FIFO overflow/underflow, T-bit parity
  injection, and short reads under both settings of the descriptor's SRE field
  (the `sre=0` leg is a known fail — see section 6 and `BRINGUP_STATUS.md`)
- **Reset and Recovery**: Reset asserted mid-transaction, and RSTACT arming
  without spurious reset assertion
- **Register Interface**: 100+ registers, swept against generated reset values
- **Integration**: AXI-Lite response checking and address-decode isolation
  between the two I3C instances

### Technology Stack

- **Simulation**: Verilator by default; VCS and Xcelium are also configured
- **Launcher**: `tools/dv/run_dv.py`, driven by `i3ccore_wrap_sim_cfg.toml`
- **Test Framework**: Cocotb (Python-based testbench)
- **Randomization**: shared constrained-random layer (`env/constrained_random.py`,
  `env/i3c_rand.py`), seeded from `+seed` / `SEED` so seeds can be swept
- **Bus Interface**: AXI4-Lite for register access
- **I3C Bus**: Open-drain SDA/SCL with dual-instance modeling (controller + target)
- **Language**: SystemVerilog (RTL/TB), Python (tests)

---

## 2. Testbench Architecture

### Directory Structure

The testbench lives at `hw/ip/i3ccore_wrap/dv/`, with SystemVerilog separated
from the cocotb Python:

```
dv/
├── tb/
│   ├── tb_i3ccore.sv              # SystemVerilog testbench top-level
│   └── i3c_coverage_if.sv         # Functional-coverage interface
│
├── cocotb/
│   ├── env/
│   │   ├── i3c_api.py             # Core test infrastructure & API classes
│   │   ├── i3c_test_base.py       # TB wrapper, AXI master, env construction
│   │   ├── i3c_rand.py            # I3C constrained-random generators
│   │   └── constrained_random.py  # IP-agnostic randomization primitives
│   └── tests/
│       ├── test_i3ccore.py        # Main test: reset, registers, basic checks
│       ├── i3c_write_read_sanity.py       # 4-byte write/read sanity
│       ├── i3c_long_write_sanity.py       # 500-byte write test
│       ├── i3c_long_read_sanity.py        # 500-byte read test
│       ├── i3c_immediate_write_sanity.py  # Immediate data transfers
│       ├── i3c_direct_ccc_sanity.py       # Direct CCC command sequences
│       ├── i3c_ibi_sanity.py              # In-Band Interrupt with payload
│       ├── i3c_error_sanity.py            # Error handling and FIFO overflow
│       └── ...                            # see testlists/block.toml
│
├── docs/                          # This guide and bring-up notes
├── testlists/                     # all.toml + block.toml
├── build/                         # generated filelists, compiled model,
│                                  #   per-run logs and waves (gitignored)
└── i3ccore_wrap_sim_cfg.toml      # Launcher configuration
```

The bender filelist and DUT compile list are generated into `build/`
(`i3ccore_wrap_bender.f`, `i3ccore_wrap_dut_compile.f`) by the `flist` stage.
An older `tb/i3ccore_filelist.f` may still be present from the pre-launcher
flow; nothing regenerates or reads it, and it can be deleted.

Test modules reach the shared layers through the `env` package, for example
`from env.i3c_test_base import make_env, bring_up_and_assign`. The launcher puts
both `cocotb/` and `cocotb/tests/` on `PYTHONPATH`, so tests import each other
by bare module name.

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

- **I3C Bus Signals** (NumI3c=2 instances):
  - Open-drain modeling: `scl_i/o/oe`, `sda_i/o/oe` per instance
  - Bus aggregation: Shared SCL (controller drives), shared SDA (both can pull low)
  - Instance 0: Controller
  - Instance 1: Target

- **Interrupt Signals**: `irq[NumI3c-1:0]`
- **Error Injection Hook**: `sda_corrupt`, XOR-ed into the shared SDA so a test
  can flip a single bus bit. It needs to be a TB signal with no continuous
  driver, because `sda_shared` is a continuous assign and a cocotb deposit on it
  would be overwritten at the next evaluation.
- **Waveform Support**: none in the TB itself. Dumping is driven entirely by the
  launcher's `--waves` / `--waves-on-fail`, which the cocotb runner turns into
  simulator-native dumping.

#### i3c_api.py

**Purpose**: Core Python API providing reusable classes for all I3C operations.

**Classes**:
- `I3CHelper`: Low-level register I/O wrapper around AXI-Lite
- `I3CController`: High-level controller operations (init, CCC, private transfers, IBI)
- `I3CTarget`: High-level target operations (init, IBI transmission, descriptor management)

This API abstracts the complexity of register programming, command descriptor formatting, and FIFO management, allowing test writers to focus on protocol-level scenarios.

#### i3c_test_base.py

**Purpose**: Removes the boilerplate every test would otherwise repeat.

- `TB`: wraps the DUT handle and starts the clock
- `make_env(dut)`: builds the AXI-Lite master and waits for reset release,
  returning `(tb, helper, ctrl, tgt)`
- `init_controller` / `init_target`: register-level bring-up of each instance
- `bring_up_and_assign(ctrl, tgt)`: the full sequence up to a target holding an
  assigned dynamic address, which is where most tests begin

Note that `make_env()` alone runs *no* controller or target configuration. That
is what makes it usable by `i3c_reg_reset_value_full`, which needs every
register to still hold its true post-reset value.

#### constrained_random.py / i3c_rand.py

**Purpose**: The randomization layer. `constrained_random.py` is IP-agnostic;
`i3c_rand.py` adds I3C-specific generators (legal dynamic addresses, transfer
lengths, CCC selection by weight, event-defining bytes).

The seed resolves from `+seed=<n>`, then `SEED=<n>`, then a fixed default, and
is logged on every run. Local runs are therefore reproducible while a regression
can sweep seeds and accumulate coverage.

#### Test Modules

`cocotb/tests/` holds 30 modules. 29 of them are in `testlists/block.toml` and
run under `--items all`, together contributing 38 cocotb test functions.
Section 6 documents each one.

The exception is `i3c_ibi_diag`, a diagnostic probe for the IBI receive path
rather than a pass/fail verdict test. It is not selectable through `--items`,
since the launcher only accepts names that appear in the testlist.

#### Launcher configuration

**Purpose**: `i3ccore_wrap_sim_cfg.toml` describes the build and run to
`tools/dv/run_dv.py`, which orchestrates compilation, simulation and artifact
collection. There is no per-TB Makefile.

**Key entries**:
- `[build]`: top module, filelist paths and the bender target set
- `[cocotb]`: `python_root` and `test_dir`, which become `PYTHONPATH`
- `[testlist]`: points at `testlists/all.toml` for the selectable groups
- `[targets.default.tools.<tool>]`: per-simulator compile flags

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

- **Simulator**: Verilator (default), or VCS/Xcelium
- **Toolchain**: g++ ≥10 for the C++20 cocotb runtime
- **Python**: the uv `dv` group, which the launcher bootstraps itself
- **Bender**: Ensure dependencies are checked out (`bender checkout`)

### Quick Start

Everything runs from the repository root through the launcher:

```bash
PY=tools/dv/run_dv.py
```

List the available tests and groups:

```bash
python3 $PY --dut i3ccore_wrap --list
```

Run a single test module:

```bash
python3 $PY --dut i3ccore_wrap --items i3c_write_read_sanity --tool verilator --stage sim
```

Run the full regression suite:

```bash
python3 $PY --dut i3ccore_wrap --items all --tool verilator --stage flist --stage sim
```

Run a test with waveforms:

```bash
python3 $PY --dut i3ccore_wrap --items i3c_ibi_sanity --tool verilator --stage sim --waves
```

### Launcher Options

| Command | Description |
|---------|-------------|
| `--items <name>` | Run a specific test module |
| `--items smoke` / `--items all` | Run a group from `testlists/all.toml` |
| `--list` | Show the configured tests and groups |
| `--waves [format]` | Dump waves for every selected test |
| `--waves-on-fail [format]` | Rerun only the non-passing tests with waves |
| `--stage flist` | Regenerate the RTL filelist from bender |
| `--stage clean` | Remove the run directory and `dv/build` |
| `--tool <name>` | Select verilator (default), vcs or xcelium |
| `--dry-run` | Print the commands and artifacts without running them |

Stages accumulate, so `--stage flist --stage sim` rebuilds the filelist and then
simulates. Omitting `--stage` runs the configured default set.

### Test Execution Flow

1. **Filelist**: bender emits `i3ccore_filelist.f` from the configured targets
2. **Compilation**: the simulator builds the RTL plus `tb_i3ccore.sv`
3. **Elaboration**: cocotb loads the selected Python test module
4. **Simulation**: the test drives the DUT through the cocotb AXI-Lite BFM
5. **Artifacts**: per-test logs, `results.xml` and any waves land under
   `dv/build/runs/<timestamp>__<tool>__<items>/<test>/`

### Log Interpretation

Each test module's own log ends with a cocotb tally, where `TESTS` counts the
test functions that ran inside that module:

```
i3c_write_read_sanity.test_write_read_sanity passed
** TESTS=1 PASS=1 FAIL=0 SKIP=0 **
```

A failure names the module, the test function and the assertion:

```
i3c_write_read_sanity.test_write_read_sanity failed
AssertionError: Expected 0xDEADBEEF, got 0xDEADBEE0
```

**Regression Summary** (from `--items all`): the launcher prints one line per
module and then a roll-up, where `total` counts modules, not test functions.

```
regression done index=2/29 status=PASS item=i3c_write_read_sanity seed=1530441552 attempt=0 elapsed=33.6s
...
summary    passing=<n> total=29 failing=<m> skipped=0 elapsed=...
```

The `all` group holds 29 modules totalling 38 cocotb test functions.

**A plain `--items all` does not come back fully green**:
`i3c_error_target_abort` fails its `sre=0` test function against an open
suspected DUT issue. Section 9 and Test Gaps item 9 have the detail. Compare a
fresh run against the previous run's numbers rather than against a fixed
expected tally.

---

## 4. Software Interface - Programming the I3C Device

This section explains how to interact with the I3C core from a software perspective, covering register programming, initialization sequences, and transaction flows. This is the **most important section** for understanding how to use the I3C device.

### 4.1 Register Map Overview

The I3C core uses a HCI (Host Controller Interface) register layout defined by the MIPI I3C specification.

#### Controller Base Address: 0x0000

**Register Regions**:

Every offset in this section is the `_REG_ADDR` value from the generated register
map, `hw/ip/i3ccore_wrap/regs/gen/py/oca_i3c_wrap_reg.py`, which is the same
module the tests import (as `_csr` in `cocotb/env/i3c_api.py`). The block
testbench uses the `I3C_CSR_0__` address symbols for its 4 KB instance-0 window.
Prefer the symbol over the literal in new code so addresses cannot drift when
the register map is regenerated.

| Region | Offset | Description |
|--------|--------|-------------|
| **Base Registers** | 0x000 - 0x07F | HCI version, capabilities, section offsets (`I3CBASE_*`, populated to 0x068) |
| **PIO Registers** | 0x080 - 0x0FF | Command/response ports, data FIFOs, interrupts (`PIOCONTROL_*`, populated to 0x0B0) |
| **Extended Caps: Secure FW Recovery** | 0x100 - 0x17F | OCP recovery interface (`I3C_EC_SECFWRECOVERYIF_*`) |
| **Extended Caps: Standby Controller** | 0x180 - 0x1FF | Standby/active controller mode (`I3C_EC_STDBYCTRLMODE_*`, populated to 0x1C0) |
| **Extended Caps: TTI** | 0x200 - 0x2FF | Target Transaction Interface (`I3C_EC_TTI_*`, populated to 0x290) |
| **Extended Caps: SoC Management** | 0x300 - 0x397 | Bus timing parameters (`I3C_EC_SOCMGMTIF_*`, populated to 0x390) |
| **Extended Caps: Controller Config** | 0x398 - 0x3FF | Controller configuration (`I3C_EC_CTRLCFG_*`) |
| **DAT Memory** | 0x400 - 0x7FF | Device Address Table (64-bit entries, `DAT_MEM_BASE_ADDR`) |
| **DCT Memory** | 0x800 - 0xBFF | Device Characteristics Table |

**Key Controller Registers**:

| Address | Name | Purpose |
|---------|------|---------|
| 0x004 | `HC_CONTROL` | Bus enable, mode selector |
| 0x080 | `COMMAND_PORT` | Write command descriptors (64-bit, two 32-bit writes) |
| 0x084 | `RESPONSE_PORT` | Read response descriptors (32-bit) |
| 0x088 | `TX_DATA_PORT` | Write transmit data (32-bit) |
| 0x088 | `RX_DATA_PORT` | Read received data (32-bit) — same address, direction selects the FIFO |
| 0x08C | `IBI_PORT` | Read IBI status/data |
| 0x090 | `QUEUE_THLD_CTRL` | Queue threshold control (command/response/IBI) |
| 0x094 | `DATA_BUFFER_THLD_CTRL` | Data buffer threshold control (TX/RX) |
| 0x098 | `QUEUE_SIZE` | Queue capacities (read-only) |
| 0x09C | `ALT_QUEUE_SIZE` | Alternate queue capacities (read-only) |
| 0x0A0 | `PIO_INTR_STATUS` | Interrupt status flags |
| 0x0A4 | `PIO_INTR_STATUS_ENABLE` | Interrupt status enables |
| 0x0A8 | `PIO_INTR_SIGNAL_ENABLE` | Interrupt signal enables |
| 0x0B0 | `PIO_CONTROL` | PIO queue enable / resume-suspend |
| 0x184 | `STBY_CR_CONTROL` | Standby controller mode control |
| 0x300+ | `T_HIGH_REG`, `T_LOW_REG`, etc. | Timing parameters (see section 4.2 step 5) |

#### Target (TTI) Base Address: 0x1000

The testbench instantiates two copies of the core (see section 2). Instance 0 is
the controller at `CTRL_BASE = 0x0000`; instance 1 is the target at
`TGT_BASE = 0x1000`. The offsets below are register offsets *within* an instance,
so a target access goes to `TGT_BASE + offset` — e.g. `TTI_CONTROL` is at 0x1204
on the AXI bus. `cocotb/env/i3c_test_base.py` defines both bases.

**TTI (Target Transaction Interface) Registers**:

| Offset | Name | Purpose |
|--------|------|---------|
| 0x204 | `TTI_CONTROL` | IBI enable (bit 12), descriptor enables |
| 0x220 | `TTI_INTERRUPT_STATUS` | TTI status flags |
| 0x224 | `TTI_INTERRUPT_ENABLE` | TTI interrupt enables |
| 0x270 | `TTI_RX_DESC_QUEUE_PORT` | Read RX descriptors |
| 0x274 | `TTI_RX_DATA_PORT` | Read RX data |
| 0x278 | `TTI_TX_DESC_QUEUE_PORT` | Write TX descriptors |
| 0x27C | `TTI_TX_DATA_PORT` | Write TX data |
| 0x280 | `TTI_IBI_PORT` | Write IBI descriptors/data |
| 0x284 | `TTI_QUEUE_SIZE` | TTI queue capacities (read-only) |
| 0x28C | `TTI_QUEUE_THLD_CTRL` | TTI queue thresholds |
| 0x290 | `TTI_DATA_BUFFER_THLD_CTRL` | TTI data buffer thresholds |
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

Write to `PIO_CONTROL` register (offset 0x0B0):

```python
# PIO_CONTROL fields:
#   bit 0: enable (1=enabled)
#   bit 1: rs (Resume/Suspend - 1=resume)

pio_control = (1 << 1) | (1 << 0)  # rs=1, enable=1
await helper.write(0x0B0, pio_control)
```

**Purpose**: Enables PIO queues and asserts the RS (Resume/Suspend) bit for bus ownership.

#### Step 5: Configure Timing Parameters

**Open-Drain (OD) I3C Timing**:

These are the values `I3CController.configure_timing_od_i3c()` actually programs;
they mirror the upstream `boot_init` sequence. The OD-specific registers
(`T_HIGH_OD`, `T_LOW_OD`, `T_HIGH_INIT_OD`) are required to drive SCL at all —
omitting them leaves the bus stuck.

```python
# Rise/fall are zero in simulation (ideal edges)
await helper.write(0x32C, 0)      # T_R_REG:           SCL rise time
await helper.write(0x330, 0)      # T_F_REG:           SCL fall time

await helper.write(0x334, 2)      # T_SU_DAT_REG:      data setup time
await helper.write(0x33C, 2)      # T_HD_DAT_REG:      data hold time

await helper.write(0x340, 14)     # T_HIGH_REG:        SCL high period
await helper.write(0x344, 20)     # T_HIGH_OD_REG:     SCL high, open-drain
await helper.write(0x348, 70)     # T_HIGH_INIT_OD_REG: SCL high during bus init
await helper.write(0x350, 14)     # T_LOW_REG:         SCL low period
await helper.write(0x354, 70)     # T_LOW_OD_REG:      SCL low, open-drain

await helper.write(0x35C, 13)     # T_HD_STA_REG:      START hold time
await helper.write(0x368, 9)      # T_SU_STA_REG:      START setup time
await helper.write(0x370, 8)      # T_SU_STO_REG:      STOP setup time
await helper.write(0x364, 9)      # T_HD_RSTA_REG:     repeated-START hold time
await helper.write(0x378, 24)     # T_DS_OD_REG:       open-drain data slew

await helper.write(0x37C, 13)     # T_FREE_REG:        bus free time
await helper.write(0x384, 333)    # T_AVAL_REG:        bus available (target IBI)
await helper.write(0x388, 66600)  # T_IDLE_REG:        bus idle time
```

**Purpose**: Configures timing parameters for I3C open-drain mode according to spec requirements.

**Push-Pull (PP) Timing**:

There is no separate PP register bank to program. Push-pull timing derives from
`T_HIGH_REG`/`T_LOW_REG`, which is why `configure_timing_pp()` exists only to keep
call sites compatible and returns immediately.

#### Step 6: Set FIFO Thresholds

```python
# DATA_BUFFER_THLD_CTRL (offset 0x094)
# Data buffer threshold = 2^(register_value + 1) ENTRIES of 4 bytes each.
# tx_buf=1 → 2^2 = 4 entries = 16 bytes; likewise rx_buf=1.
# Fields: tx_buf_thld [2:0], rx_buf_thld [10:8],
#         tx_start_thld [18:16], rx_start_thld [26:24]
data_buffer_thld = (1 << 8) | (1 << 0)  # tx_buf=1, rx_buf=1
await helper.write(0x094, data_buffer_thld)

# QUEUE_THLD_CTRL (offset 0x090)
# Queue threshold = register_value + 1 entries (not a power of two).
# Fields: cmd_empty_buf_thld [7:0], resp_buf_thld [15:8],
#         ibi_data_segment_size [23:16], ibi_status_thld [31:24]
queue_thld = (1 << 8) | (1 << 0)  # cmd_empty_buf=1, resp_buf=1
await helper.write(0x090, queue_thld)
```

**Purpose**: Sets thresholds for when TX/RX FIFO interrupts fire.

Note the two registers use *different* scales — the data buffer threshold is
exponential (`2^(v+1)` entries) while the queue threshold is linear (`v+1`
entries). Section 6's `i3c_threshold_sweep` write-up depends on the exponential
form, and `configure_thresholds()` in `i3c_api.py` documents both.

**Complete Initialization Code** (from `i3c_api.py` lines 204-290):

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
# TTI_INTERRUPT_ENABLE (offset 0x224)
# Enable: TX_DATA_THLD, RX_DATA_THLD, TX_DESC_THLD, RX_DESC_THLD, IBI_THLD, IBI_DONE
tti_intr_enable = (1 << 13) | (1 << 12) | (1 << 3) | (1 << 2) | (1 << 1) | (1 << 0)
await helper.write(0x1224, tti_intr_enable)
```

**Purpose**: Enables interrupts for target RX/TX FIFO thresholds and IBI completion.

#### Step 4: Configure Timing and Thresholds

Use the same timing configuration as the controller (mirror the values).

**Complete Target Initialization Code** (from `i3c_api.py` lines 1062-1138):

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
await helper.write(0x080, cmd_lo)
await helper.write(0x080, cmd_hi)  # same FIFO address, pushed twice
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
# Read RESPONSE_PORT (offset 0x084)
response = await helper.read(0x084)

# Extract fields:
#   bits [31:28] = err_status (0=success)
#   bits [15:0] = data_length
err_status = (response >> 28) & 0xF
data_length = response & 0xFFFF

if err_status != 0:
    print(f"SETDASA failed with error {err_status}")
```

5. **Target Receives Dynamic Address**:

The target automatically receives the dynamic address by polling the RX descriptor queue.

**Complete SETDASA Code** (from `i3c_api.py` lines 419-436):

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
    err_status = (response >> 28) & 0xF

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

await helper.write(0x080, cmd_lo)
await helper.write(0x080, cmd_hi)  # same FIFO address, pushed twice
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

# Write to TX_DATA_PORT (offset 0x088)
await helper.write(0x088, data_word)
```

4. **Target Drains RX Data** (interleaved, when `TTI_RX_DATA_THLD_STAT` fires):

```python
# Poll TTI_INTERRUPT_STATUS (offset 0x220) for rx_data_thld_stat (bit 1)
status = await helper.read(0x1220)
if status & (1 << 1):
    # Read from TTI_RX_DATA_PORT (offset 0x274)
    rx_word = await helper.read(0x1274)
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
response = await helper.read(0x084)
err_status = (response >> 28) & 0xF
data_length = response & 0xFFFF

if err_status != 0:
    print(f"Write failed with error {err_status}")
```

7. **Target Waits for RX Descriptor**:

```python
# Poll for rx_desc_thld_stat (bit 3)
await helper.poll_field(0x1220, TtiIntrStatus, 'rx_desc_thld_stat')

# Read RX descriptor from TTI_RX_DESC_QUEUE_PORT (offset 0x270)
rx_desc = await helper.read(0x1270)
# Extract byte count, command, etc.
```

**Complete Private Write Code** (from `i3c_api.py` lines 438-576, simplified):

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
    err_status = (response >> 28) & 0xF

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

await helper.write(0x080, cmd_lo)
await helper.write(0x080, cmd_hi)  # same FIFO address, pushed twice
```

2. **Target Waits for TX Descriptor Ready**:

```python
# Poll for tx_desc_thld_stat (bit 2)
await helper.poll_field(0x1220, TtiIntrStatus, 'tx_desc_thld_stat')
```

3. **Target Writes TX Descriptor**:

```python
# TX descriptor format: {data_length[15:0], ...}
tx_desc = read_len
await helper.write(0x1278, tx_desc)  # TTI_TX_DESC_QUEUE_PORT
```

4. **Target Fills TX FIFO**:

```python
# Example: Target sends [0x11, 0x22, 0x33, 0x44]
tx_data = [0x11, 0x22, 0x33, 0x44]
tx_word = (tx_data[3] << 24) | (tx_data[2] << 16) | (tx_data[1] << 8) | tx_data[0]

# Wait for tx_data_thld_stat (bit 0)
await helper.poll_field(0x1220, TtiIntrStatus, 'tx_data_thld_stat')

# Write to TTI_TX_DATA_PORT (offset 0x27C)
await helper.write(0x127C, tx_word)
```

5. **Controller Drains RX FIFO**:

```python
# Wait for rx_thld_stat (bit 2)
await helper.poll_field(0x0A0, PioIntrStatus, 'rx_thld_stat')

# Read from RX_DATA_PORT (offset 0x088)
rx_word = await helper.read(0x088)
rx_bytes = [rx_word & 0xFF, (rx_word >> 8) & 0xFF, (rx_word >> 16) & 0xFF, (rx_word >> 24) & 0xFF]
```

6. **Target Waits for TX Descriptor Complete**:

```python
# Poll for tx_desc_complete_stat (bit 14)
await helper.poll_field(0x1220, TtiIntrStatus, 'tx_desc_complete_stat')
```

7. **Controller Reads Response**:

```python
await helper.poll_field(0x0A0, PioIntrStatus, 'resp_ready_stat')
response = await helper.read(0x084)
err_status = (response >> 28) & 0xF
```

**Complete Private Read Code** (from `i3c_api.py` lines 578-713, simplified):

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
    err_status = (response >> 28) & 0xF

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

#### GET CCCs (Read from Target)

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
    await self.helper.write(0x080, cmd_lo)
    await self.helper.write(0x080, cmd_hi)  # same FIFO address, pushed twice

    # Wait for response
    await self.helper.poll_field(0x0A0, PioIntrStatus, 'resp_ready_stat')

    # Read response
    response = await self.helper.read(0x084)
    err_status = (response >> 28) & 0xF
    data_length = response & 0xFFFF

    if err_status != 0:
        return None

    # Read RX data
    await self.helper.poll_field(0x0A0, PioIntrStatus, 'rx_thld_stat')
    rx_word = await self.helper.read(0x088)
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

#### SET CCCs

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

    await self.helper.write(0x080, cmd_lo)
    await self.helper.write(0x080, cmd_hi)  # same FIFO address, pushed twice

    # Wait for response
    await self.helper.poll_field(0x0A0, PioIntrStatus, 'resp_ready_stat')
    response = await self.helper.read(0x084)
    err_status = (response >> 28) & 0xF

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

    await self.helper.write(0x080, cmd_lo)
    await self.helper.write(0x080, cmd_hi)  # same FIFO address, pushed twice

    # Wait for response
    await self.helper.poll_field(0x0A0, PioIntrStatus, 'resp_ready_stat')
    response = await self.helper.read(0x084)
    err_status = (response >> 28) & 0xF

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

    await self.helper.write(0x080, cmd_lo)
    await self.helper.write(0x080, cmd_hi)  # same FIFO address, pushed twice

    # Wait for response
    await self.helper.poll_field(0x0A0, PioIntrStatus, 'resp_ready_stat')
    response = await self.helper.read(0x084)
    err_status = (response >> 28) & 0xF

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

Write to `TTI_CONTROL` register (offset 0x204):

```python
# Read current TTI_CONTROL
tti_control = await helper.read(0x1204)

# Set bit 12 (ibi_en)
tti_control |= (1 << 12)

# Write back
await helper.write(0x1204, tti_control)
```

**Step 2: Write IBI Descriptor and Payload**

IBI descriptor format (written to `TTI_IBI_PORT` at offset 0x280):

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
    await self.helper.poll_field(0x1220, TtiIntrStatus, 'ibi_thld_stat')

    # Step 2: Write IBI header
    ibi_header = (mdb << 24) | len(payload_bytes)
    await self.helper.write(0x1280, ibi_header)  # TTI_IBI_PORT

    # Step 3: Write payload in 4-byte chunks
    for i in range(0, len(payload_bytes), 4):
        chunk = payload_bytes[i:i+4]
        payload_word = self.helper.pack_bytes(chunk)

        # Wait for space
        await self.helper.poll_field(0x1220, TtiIntrStatus, 'ibi_thld_stat')

        await self.helper.write(0x1280, payload_word)

    # Step 4: Wait for IBI done (bit 13)
    await self.helper.poll_field(0x1220, TtiIntrStatus, 'ibi_done_stat')
```

**Complete Target IBI Code** (from `i3c_ibi_sanity.py` lines 199-203):

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

# Configure IBI threshold in QUEUE_THLD_CTRL (offset 0x090)
queue_thld = await helper.read(0x090)
queue_thld |= (1 << Y)  # Set IBI threshold
await helper.write(0x090, queue_thld)
```

**Step 2: Poll for IBI Received**

```python
# Wait for ibi_status_thld_stat
await helper.poll_field(0x0A0, PioIntrStatus, 'ibi_status_thld_stat')
```

**Step 3: Read IBI Status Descriptor**

IBI status descriptor format (read from `IBI_PORT` at offset 0x08C):

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
    ibi_status = await self.helper.read(0x08C)  # IBI_PORT

    # Extract fields
    error = (ibi_status >> 30) & 0x1
    ibi_id = (ibi_status >> 8) & 0xFF  # Target address
    data_length = ibi_status & 0xFF

    if error:
        return False, None, None, None

    # Read data bytes (first byte is MDB)
    ibi_data = []
    for i in range(0, data_length, 4):
        data_word = await self.helper.read(0x08C)  # IBI_PORT (same address)
        bytes_in_word = self.helper.unpack_bytes(data_word, min(4, data_length - i))
        ibi_data.extend(bytes_in_word)

    # Extract MDB and payload
    mdb = ibi_data[0] if len(ibi_data) > 0 else 0
    payload = ibi_data[1:] if len(ibi_data) > 1 else []

    return True, ibi_id, mdb, payload
```

**Complete Controller IBI Reception Code** (from `i3c_ibi_sanity.py` lines 212-221):

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

The regression (`--items all`) runs 29 modules containing 38 cocotb test
functions. One further module, `i3c_ibi_diag`, sits outside the regression;
section 2 explains why. This section groups the 29 by what they exercise, and
names each module's test functions so a log line can be traced back to its
source.

Most modules layer constrained-random stimulus on directed cases rather than
replacing them: the known corners are always exercised, and randomization from
`env/i3c_rand.py` widens the value space on top. The seed is logged on every
run, so a failure is reproducible.

### Registers and Integration

#### test_i3ccore

**Tests**: `test_basic_compilation`, `test_register_access`,
`test_register_write_read`, `test_address_range_boundaries`

Reset release, AXI-Lite connectivity and register access across the whole map,
including the first and last DAT/DCT entries and the address-range boundaries.

This module reads un-written DAT/DCT SRAM and reset-X registers by design. Real
SRAM powers up undefined and cocotb raises on reading an X bit, so it needs
`COCOTB_RESOLVE_X=ZEROS`. The module sets that variable before importing cocotb,
and the `xresolve` group exists to select exactly this module. Its full register
sweep passes on Verilator.

#### i3c_reg_reset_value_full

**Tests**: `test_reg_reset_value_full`

Reads the real config and status registers after reset and compares each against
the reset value published by the generated register map. Both halves of every
row — the offset *and* the expected value — are resolved by symbol from
`oca_i3c_wrap_reg`, never hand-copied, so a stale symbol raises `AttributeError`
at import and a regenerated map moves offsets and reset values together.

It deliberately avoids two regions: the FIFO and data ports
(COMMAND/RESPONSE/TX_DATA/RX_DATA/IBI), because reading those pops the queue or
returns X when empty and they are not reset-valued registers; and DAT/DCT memory
at 0x400+, which is external SRAM and X until written. The test depends on
`make_env()` running no controller or target configuration, so every value read
is a true post-reset value.

#### i3c_axi_protocol

**Tests**: `test_axi_protocol`

Three legs: a mapped write/read round-trip where BRESP and RRESP must both be
OKAY, a mapped HC_CONTROL read checked against its exact reset default, and a
deliberate `expect_resp` mismatch that is required to fail. The last leg is what
proves the checker is actually sensitive rather than vacuously passing.

It uses QUEUE_THLD_CTRL, a confirmed RW register. Its threshold fields clamp
values to `<= 7`, so the random pattern is generated with every byte in 0..7 and
non-zero, which guarantees an exact read-back — the AXI round-trip is the
scoreboard. The DAT region is not used here: it is external 64-bit SRAM, not a
plain 32-bit scratch register.

#### i3c_multi_instance_indep

**Tests**: `test_multi_instance_indep`

Confirms the wrapper's AXI-Lite address decode isolates the two instances:
writing instance 0's register space must not disturb instance 1's, and each
retains its own value. Isolation is checked by giving the two instances distinct
values and swapping them.

### Private Transfers

#### i3c_write_read_sanity

**Tests**: `test_write_read_sanity`

SETDASA followed by a 4-byte private write and a 4-byte private read. The
smallest end-to-end proof that the bus works.

#### i3c_immediate_write_sanity

**Tests**: `test_immediate_write_sanity`

Immediate data transfer, where up to 4 bytes ride directly in the command
descriptor instead of being written to the TX FIFO.

#### i3c_long_write_sanity / i3c_long_read_sanity

**Tests**: `test_long_write_sanity`, `test_long_read_sanity`

500-byte private write and read (125 full dwords, 125 entries), which exercises
FIFO refill across many descriptor entries.

#### i3c_max_length_transfer

**Tests**: `test_max_length_transfer`

Private write/read at boundary lengths around the FIFO capacity and above it,
after raising MWL/MRL, validating multi-descriptor and FIFO-refill handling at
the boundaries. The fixed boundary list always runs, with a few random lengths
added on top; data is randomized every iteration and the built-in scoreboard
checks each one.

#### i3c_tx_capacity_512

**Tests**: `test_tx_capacity_512`

A transfer can only start once the complete response fits in the 64-word TX
queue plus the width converter's pending word. The test covers the 256-byte
control case, the 260-byte boundary, and larger word-aligned and unaligned
responses. Every response must complete with its full byte-exact payload.

#### i3c_back_to_back

**Tests**: `test_back_to_back`

A stream of transactions with minimal inter-transaction gap, stressing
command/response queue turnaround and bus-free timing. Direction, length, data
and the (often zero) gap are randomized to vary queue-turnaround timing, and the
sent-equals-received scoreboard checks every one.

#### i3c_random_transfer_stress

**Tests**: `test_random_transfer_stress`

Directed-random private write/read with random direction, length and data,
integrity-checked each iteration. Intended to be run across several seeds with
coverage merged.

### CCC Commands

#### i3c_direct_ccc_sanity

**Tests**: `i3c_direct_ccc_sanity`

SETDASA followed by a read-write-read chain that proves each SET actually
changed state: GETBCR → GETMWL → SETMWL(0x10) → GETMWL → GETMRL →
SETMRL(0x10, 0x10) → GETMRL → RSTACT(0x01).

#### i3c_full_ccc_matrix

**Tests**: `test_full_ccc_matrix`

The supported CCC set with read-back verification wherever a GET counterpart
exists: GETBCR, GET/SET MWL, GET/SET MRL, RSTACT. The SET values for MWL, MRL
and IBI payload size are drawn from the full legal range and verified by the GET
counterpart each time, so the SET/GET round-trip is the scoreboard and
randomizing the value is free coverage of the length-limit datapath. RSTACT stays
directed, since its defining-byte semantics are fixed.

#### i3c_broadcast_ccc

**Tests**: `test_broadcast_ccc`

Broadcast CCCs per MIPI I3C Basic Table 16/17: ENEC (0x00), DISEC (0x01) and
RSTDAA (0x06). Bring-up still uses SETDASA so the target holds a dynamic address
before RSTDAA, and the test then asserts DYNAMIC_ADDR_VALID clears.

The ENEC/DISEC *event defining byte* is randomized instead of fixed at 0x01. The
defined event bits are ENINT/IBI (bit 0), ENCR (bit 1) and ENHJ (bit 3), so a
random subset of only those legal bits, with at least one set, exercises the
defining-byte datapath across the legal event-mask space. DISEC mirrors whatever
ENEC enabled, keeping the pair symmetric.

#### i3c_setnewda

**Tests**: `test_setnewda`

Assigns a dynamic address via SETDASA, re-assigns it with SETNEWDA (CCC 0x88),
then confirms a private transfer still works on the new address. The new address
is randomized within the legal, non-reserved 7-bit space and constrained to
differ from the original, widening what the DAT `dynamic_address` field and the
target address-match logic see. The private write on the re-assigned address is
the scoreboard.

#### i3c_random_ccc_stress

**Tests**: `test_random_ccc_stress`

Repeatedly picks a CCC from the supported set in random order to stress the
command FSM, with SET values from the full legal range and SET/GET round-trips
self-checking. CCCs are picked by weight, GET-heavy to resemble real read-mostly
traffic, which biases the command-FSM ordering.

#### i3c_multi_target_dat

**Tests**: `test_multi_target_dat`

Programs multiple Device Address Table entries and addresses the real target via
index 0 while index 1 points at a non-responding address, mirroring the
error-sanity NACK path on a second DAT entry. DAT[0] keeps the target's assigned
dynamic address from bring-up; the absent address is constrained to be legal and
distinct from it.

### In-Band Interrupts

#### i3c_ibi_sanity

**Tests**: `i3c_ibi_sanity`, `i3c_ibi_during_broadcast`

The full IBI path: configure bus timing (T_AVAL, T_IDLE), SETDASA, GETBCR to
confirm IBI capability, SETMRL to set the IBI payload size, target sends an IBI
with payload, controller receives it and the data is verified. The second test
repeats this while broadcast traffic is in flight.

#### i3c_ibi_payload_variants

**Tests**: `test_ibi_payload_variants`

IBIs across payload sizes, with the controller verifying the received MDB and
payload each time. The directed boundary sizes (0, 1, and full) are covered
first, then random MDB and payload length/bytes are added within the configured
IBI payload size.

#### i3c_ibi_nack_disabled

**Tests**: `test_ibi_nack_disabled`

With target IBI generation disabled, a real IBI attempt must not be serviced:
the controller's `PIO_INTR_STATUS.ibi_status_thld_stat` has to stay clear. The
test pairs that negative case with a positive control that enables IBI mode and
confirms the IBI *is* serviced — without which a permanently dead IBI path would
look identical to correctly-suppressed generation. Since `TTI_CONTROL.ibi_en`
resets asserted, the test explicitly clears and verifies the bit first.

### Bus Timing and Thresholds

#### i3c_pp_timing_transfer

**Tests**: `test_pp_timing_transfer`

A private write/read using the push-pull timing bank (`configure_timing_pp`),
with randomized length and data.

#### i3c_od_pp_mode_switch

**Tests**: `test_od_pp_mode_switch`

Back-to-back transfers that exercise the controller muxing between the
open-drain bank (broadcast/address phase) and the push-pull bank (payload).
Every transfer begins OD then switches to PP, so randomized lengths and data
exercise the mux across a variety of payload sizes.

#### i3c_threshold_sweep

**Tests**: `test_threshold_sweep`

Sweeps TX/RX FIFO threshold register values and runs a 32-byte transfer at each
setting, confirming the threshold interrupts drive the data path.

The RTL threshold is in FIFO *entries* of 4 bytes each, mapping register value
`t` to `1 << (t+1)` entries: t=0 → 2 entries (8 B), t=1 → 4 (16 B), t=2 → 8
(32 B), t=3 → 16 (64 B). The sweep covers t=0..2 only. A 32-byte transfer is
exactly 8 entries, so those three thresholds are reachable and the RX-data
threshold interrupt fires as intended, whereas t=3 needs at least 16 entries
(64 B) before it can fire at all.

### Errors, Reset and Recovery

#### i3c_error_sanity

**Tests**: `i3c_error_wrong_addr`, `i3c_fifo_overflow`,
`i3c_tx_fifo_underflow`, `i3c_ibi_fifo_overflow`

Error reporting when the controller addresses a non-existent target, plus the
FIFO boundary conditions. The address case assigns a dynamic address to the real
target at DAT index 0, sets up DAT index 1 with a wrong address, issues an
immediate write to it, and requires the transaction to abort with a non-zero
error status in the response.

#### i3c_error_parity_inject

**Tests**: `test_error_status_baseline`, `test_error_parity_inject`

`test_error_status_baseline` is the negative control: a clean private write must
report ERR_STATUS exactly 0x0 SUCCESS with no transfer-error interrupt latched,
proving the error reporting reads clean when nothing is wrong.

`test_error_parity_inject` does real bus-level bit-flip injection. In I3C SDR
every data byte is followed by a T-bit carrying, for a controller-to-target
write, that byte's odd parity — so flipping any single data bit makes the
target's recomputed parity disagree and its TE2 check must fire. The flip needs
the `sda_corrupt` TB hook because `sda_shared` is a continuous assign and a
cocotb deposit on it would be overwritten at the next evaluation.

Two independent checkers validate the result: TARGET_ERR_CNT_TE2 (offset 0x244)
must increment by exactly 1, and the corrupted byte plus every byte after it in
the same transfer must *not* reach the target RX FIFO, because `parity_err`
suppresses RX FIFO writes until the target returns idle. Injecting into byte `k`
must therefore leave exactly `k` bytes received.

On attribution: `te2_err_o = te2_err_ccc | te2_err_priv_wr`, so the counter also
advances on CCC data-parity errors. No CCC traffic is issued inside the
injection window, which is what makes the +1 attributable to the private write.

#### i3c_error_target_abort

**Tests**: `test_short_read_permitted`, `test_short_read_error`

The controller requests `requested_len` bytes but the target supplies fewer and
then ends the data phase with its T-bit. Both values of the command descriptor's
SRE field are exercised, because SRE is what decides whether that short receive
is an error:

- `sre=0` — a short read is permitted, so per MIPI I3C HCI v1.2 Table 146 the
  outcome is ERR_STATUS 0x0 SUCCESS with DATA_LENGTH equal to the *received*
  length. DATA_LENGTH is how software learns the read was short.
- `sre=1` — a short read is not permitted, so the same stimulus must yield
  ERR_STATUS 0x7 I3C_SHORT_READ_ERR.

A response is mandatory in both cases. HCI v1.2 requires a response descriptor
for any command with WROC set, for any read-type transfer, and whenever the
transfer phase hit an error; this command sets `wroc=1` and is a read, so either
clause alone requires one. Only successful *write*-type transfers are exempt
from the 1:1 command/response mapping.

Both lengths are randomized with `supplied < requested` and both dword-aligned,
so the short-read datapath sees a range of gaps, and the response status plus
received length distinguish a short read from an address NACK.

> **Known fail — `test_short_read_permitted` (`sre=0`) does not pass.** The DUT
> produces no response descriptor at all on the permitted-short-read path:
> `resp_ready` never asserts and no error status is raised, even though the
> target completed its side. The `sre=1` leg passes, so short-read *detection*
> works and only the `sre=0` *reporting* path is affected. This is an open,
> unresolved **suspected DUT issue** — the expectation above is the spec-correct
> one and has deliberately not been weakened to match the DUT. See the
> "Open item" section of `BRINGUP_STATUS.md` for the failure log and the three
> options under consideration (known-fail sentinel / skip with reason / file
> against the vendored i3c-core). Running both legs is what isolates the
> reporting gate from the detection logic, which is why both are kept.

#### i3c_reset_mid_transaction

**Tests**: `test_reset_mid_transaction`

Asserts reset during an active transaction stream and confirms clean recovery: a
fresh transfer succeeds after re-init and SETDASA. A random number of pre-reset
transfers run first, then reset is asserted after a *random* cycle delay so it
lands at a random bus phase — considerably stronger than always resetting at the
same point.

#### i3c_recovery_reset_iface

**Tests**: `test_rstact_arm_no_spurious_reset`

RSTACT alone only *arms* an action: neither `peripheral_reset` nor
`escalated_reset` may assert until a Target Reset Pattern appears on the bus.
Defining byte 0x01 arms peripheral reset and 0x02 arms whole-target (escalated)
reset. `recovery_payload_available` and `recovery_image_activated` are sampled as
must-stay-idle outputs, since arming must not disturb the reset or recovery
outputs.

Scope: RSTACT and Target Reset are I3C protocol (I3C Basic v1.1.1 §5.1.9.3.26,
Tables 52-53) and are verified here. The OCP Secure Firmware Recovery image flow
is not in scope.

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

- **Threshold Formula**: register value `t` maps to `1 << (t+1)` FIFO *entries*,
  each entry being 4 bytes: t=0 → 2 entries (8 B), t=1 → 4 (16 B), t=2 → 8
  (32 B), t=3 → 16 (64 B)
- **Tested Values**: t=0..2, swept by `i3c_threshold_sweep` with a 32-byte
  transfer (exactly 8 entries, so all three thresholds are reachable). t=3 needs
  at least 64 bytes before it can fire and is not covered.
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

- **Error Status Field**: Bits [31:28] in response descriptor
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

**Tests**: `i3c_pp_timing_transfer` runs transfers on this bank, and
`i3c_od_pp_mode_switch` exercises the mux from open-drain into push-pull

**Coverage**: Push-pull mode configuration and the OD→PP switch

#### Bus Free/Idle Times

- **T_FREE (500 cycles)**: Minimum bus free time between transactions
- **T_AVAL (1000 cycles)**: Bus available time for target IBI requests
- **T_IDLE (2000 cycles)**: Bus idle time before sleep
- **Tests**: All tests configure these parameters
- **Coverage**: Bus state transitions, IBI arbitration timing

### Summary of Corner Cases

| Category | Corner Case | Test Coverage |
|----------|-------------|---------------|
| **Addressing** | First/last register addresses | test_i3ccore |
| **Addressing** | First/last DAT entries | test_i3ccore |
| **Addressing** | Register-space isolation between instances | i3c_multi_instance_indep |
| **Addressing** | Absent address in a second DAT entry | i3c_multi_target_dat |
| **Addressing** | Dynamic address re-assignment | i3c_setnewda |
| **FIFO** | Threshold entries t=0..2 (8/16/32 bytes) | i3c_threshold_sweep |
| **FIFO** | TX/RX FIFO overflow | i3c_error_sanity |
| **FIFO** | TX FIFO underflow | i3c_error_sanity |
| **FIFO** | IBI FIFO overflow | i3c_error_sanity |
| **Transfers** | 500-byte write / read | i3c_long_write_sanity, i3c_long_read_sanity |
| **Transfers** | Immediate write (≤4 bytes) | i3c_immediate_write_sanity |
| **Transfers** | Boundary lengths around FIFO capacity | i3c_max_length_transfer |
| **Transfers** | Target-TX queue boundary above 256 bytes | i3c_tx_capacity_512 |
| **Transfers** | Minimal-gap back-to-back stream | i3c_back_to_back |
| **Errors** | Wrong target address (NACK) | i3c_error_sanity |
| **Errors** | Clean-path error status baseline | i3c_error_parity_inject |
| **Errors** | SDA single-bit parity injection (TE2) | i3c_error_parity_inject |
| **Errors** | Short read under SRE=1 (SRE=0 leg is a known fail) | i3c_error_target_abort |
| **Timing** | Open-drain parameters | All transfer tests |
| **Timing** | Push-pull parameters | i3c_pp_timing_transfer |
| **Timing** | OD→PP mux | i3c_od_pp_mode_switch |
| **IBI** | IBI with payload | i3c_ibi_sanity |
| **IBI** | IBI during broadcast | i3c_ibi_sanity |
| **IBI** | Payload sizes, empty through full | i3c_ibi_payload_variants |
| **IBI** | Suppressed when disabled, with positive control | i3c_ibi_nack_disabled |
| **Reset** | Reset at a random bus phase mid-transaction | i3c_reset_mid_transaction |
| **Reset** | RSTACT arming without spurious reset | i3c_recovery_reset_iface |

---

## 8. Key Operational Details

### Command Descriptor Format (64-bit)

All Command descriptors are 64 bits

There are a few different types of Command Descriptors (They are all type defs of each other): See i3c_pkg.sv

Immediate Command Descriptor: Should be used in Controller writes, when the data to be sent <= 4 bytes (Data is embedded within the command)
Regular Command Descriptor: Can be used for any write/read
Command descriptors are written to the COMMAND_PORT (offset 0x080) as two 32-bit writes to that same FIFO address.

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

Response descriptors are read from the RESPONSE_PORT (offset 0x084).

**Structure** — `i3c_response_desc_t` in
`vendor/chipsalliance/i3c-core/upstream/src/i3c_pkg.sv:293` (TCRI 7.1.3 Table 11):

```
[31:28] = err_status  (4 bits)
[27:24] = tid         (Transaction ID)
[23:16] = reserved
[15:0]  = data_length (bytes read/written)
```

`err_status` values, from `i3c_resp_err_status_e`
(`i3c_pkg.sv:259`, TCRI 6.4.1 Table 1):

| Value | Name | Meaning |
|-------|------|---------|
| 0x0 | `Success` | No error |
| 0x1 | `Crc` | CRC error (HDR modes only) |
| 0x2 | `Parity` | Parity error |
| 0x3 | `Frame` | Frame error |
| 0x4 | `AddrHeader` | Address header error |
| 0x5 | `Nack` | Address or DAA was NACK'ed |
| 0x6 | `Ovl` | Receive overflow or transfer underflow |
| 0x7 | `I3cShortReadErr` | Target returned fewer bytes than requested and short read was not permitted |
| 0x8 | `HcAborted` | Terminated by the host controller (internal error or Abort) |
| 0x9 | `I2cDataNackOrI3cBusAborted` | I2C write data NACK, or I3C bus aborted |
| 0xA | `NotSupported` | Command not supported by this implementation |
| 0xB | `AbortedWithCRC` | Aborted in HDR-BT mode; also the RTL's default/fallback status |
| 0xF | `ErrorF` | Reserved error code |

Extract it with `(response >> 28) & 0xF` — this is what `cocotb/env/i3c_api.py`
does at every response-checking site.

**Example** (success, 4 bytes read, TID 0):

```
response = 0x0000_0004
  err_status  = 0x0 (Success)
  tid         = 0
  data_length = 4 bytes
```

**Error Example** (frame error, no data, TID 0):

```
response = 0x3000_0000
  err_status  = 0x3 (Frame)
  tid         = 0
  data_length = 0
```

### IBI Status Descriptor Format (32-bit)

IBI status descriptors are read from the IBI_PORT (offset 0x08C).

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
python3 tools/dv/run_dv.py --dut i3ccore_wrap \
    --items i3c_write_read_sanity --tool verilator --stage sim
```

**Expected Output**:

```
Running test: i3c_write_read_sanity.test_write_read_sanity
Test PASSED
```

**With Waveforms**:

```bash
python3 tools/dv/run_dv.py --dut i3ccore_wrap \
    --items i3c_write_read_sanity --tool verilator --stage sim --waves
```

Waves land beside the test's log under the run directory the launcher prints.

### Running Full Regression

**All Tests**:

```bash
python3 tools/dv/run_dv.py --dut i3ccore_wrap \
    --items all --tool verilator --stage flist --stage sim
```

**Progress Output**: one line per module as it finishes, then a roll-up. Each
module's own cocotb log holds the per-test detail.

```
regression start total=29 sim_jobs=1 executor=local seeds=1 retry=0
regression done index=1/29 status=PASS item=test_i3ccore seed=<seed> attempt=0 elapsed=<s>
regression done index=2/29 status=PASS item=i3c_immediate_write_sanity seed=<seed> attempt=0 elapsed=<s>
...
summary    passing=<n> total=29 failing=<m> skipped=0 elapsed=...
```

`i3c_error_target_abort` is expected not to pass under Verilator today: its
`sre=0` test function fails against the open suspected DUT issue in Test Gaps
item 9.

Compare a fresh run against the previous run's tally rather than against a fixed
expected result.

Artifacts for each module land under
`dv/build/runs/<timestamp>__<tool>__<items>/<module>/`, with the log in `logs/`
and `results.xml` in `results/`.

### Running a Specific Test Function

The launcher selects whole modules; cocotb narrows to individual test functions
through `COCOTB_TEST_FILTER`, which the launcher forwards to the simulation:

```bash
COCOTB_TEST_FILTER=test_register_access python3 tools/dv/run_dv.py \
    --dut i3ccore_wrap --items test_i3ccore --tool verilator --stage sim
```

This runs only `test_register_access` from `test_i3ccore.py`. The value is a
regex matched against `<module>.<test>`, so a prefix selects a family of tests.
Section 6 lists the test function names for every module.

Note the filter selects tests *within a single simulation*; the tests still
share one elaborated model and one reset sequence. The old Makefile's
`test_module_separate` target, which launched a separate simulation per test
function, has no launcher equivalent. If you need that isolation — for instance
to rule out cross-test state leakage, which is what
`i3c_error_sanity`'s per-test reset problem turned out to be — loop over the
filter yourself:

```bash
for t in i3c_error_wrong_addr i3c_fifo_overflow \
         i3c_tx_fifo_underflow i3c_ibi_fifo_overflow; do
    COCOTB_TEST_FILTER=$t python3 tools/dv/run_dv.py \
        --dut i3ccore_wrap --items i3c_error_sanity --tool verilator --stage sim
done
```

### Debugging with Waveforms

**Run Test with Waveforms**:

```bash
python3 tools/dv/run_dv.py --dut i3ccore_wrap \
    --items i3c_ibi_sanity --tool verilator --stage sim --waves
```

To capture only the failures in a longer run, use `--waves-on-fail`, which
reruns the non-passing tests instead of dumping every one of them.

**Viewing the Dump**: Verilator writes FST, so open it with a viewer that reads
FST — `gtkwave`, or `surfer`. The launcher records a ready-made command in the
run's `result.json` under `stages[].metadata.waves.viewer_commands`; the dump
itself is at `<run_dir>/<module>/waves/<module>.fst`:

```bash
gtkwave hw/ip/i3ccore_wrap/dv/build/runs/<run>/<module>/waves/<module>.fst
```

The old Makefile's `make verdi` target is gone along with the Makefile, and the
TB no longer contains the `$fsdbDump*` calls that Verdi needed. Verdi on an FSDB
would require re-adding those calls behind a define and building with the Verdi
PLI under VCS.

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
python3 tools/dv/run_dv.py --dut i3ccore_wrap --stage clean
```

Removes the run directory and `dv/build/`, which holds the generated filelists,
the compiled model and every per-run log, `results.xml` and waveform.

---

## 10. Limitations and Future Work

### Currently Tested

The testbench provides solid coverage of core I3C functionality:

- **Basic I3C Protocol (SDR Mode)**: Standard data rate transfers validated
- **Direct CCC Commands**: GETBCR, GETMWL, GETMRL, SETMWL, SETMRL, RSTACT,
  SETDASA, SETNEWDA, including SET/GET round-trip checking
- **Broadcast CCC Commands**: ENEC, DISEC and RSTDAA, with a randomized event
  defining byte
- **Randomized CCC Ordering**: Weighted random CCC sequences stress the command FSM
- **Private Transfers**: Immediate (in-descriptor) data through to transfers past
  the 256-byte target-TX queue boundary, including unaligned lengths
- **IBI**: Payload sizes from empty to full, plus the suppressed case when target
  IBI generation is disabled, checked against a positive control
- **Bus Timing**: Open-drain and push-pull banks and the OD→PP mux; FIFO
  threshold settings t=0..2
- **Error Handling**: Address NACK, TX/RX/IBI FIFO overflow and underflow,
  single-bit SDA parity injection verified through the TE2 counter, and short
  reads under the `sre=1` (not-permitted) setting of the descriptor SRE field.
  The `sre=0` (permitted) leg is stimulated but **currently fails** — see Test
  Gaps item 9
- **Reset**: Reset asserted at a randomized bus phase mid-transaction, with
  recovery proven by a subsequent transfer
- **Target Reset Arming**: RSTACT arms without asserting reset or disturbing the
  recovery outputs until a Target Reset Pattern appears
- **Register Interface**: 100+ registers swept against generated reset values
- **Integration**: AXI-Lite response codes and address-decode isolation between
  the two instances
- **Dual-Instance Testing**: Controller and target tested simultaneously

### Not Currently Tested

The following features are not yet validated and represent opportunities for expanding test coverage:

#### HDR Modes (High Data Rate)

- **HDR-DDR**: Double Data Rate mode (data on both clock edges)
- **HDR-TSL**: Ternary Symbol Legacy mode (3-level signaling)
- **HDR-BT**: Bulk Transfer mode (higher throughput)
- **Impact**: HDR modes provide faster data rates for performance-critical applications
- **Recommendation**: Add HDR mode tests if the I3C core supports these modes

#### Multi-Master Arbitration

- **Bus Ownership**: Multiple controllers competing for bus access
- **Arbitration**: Resolving conflicts when multiple controllers try to initiate transfers
- **Master Request**: Target requesting controller role
- **Impact**: Multi-master scenarios are common in complex systems
- **Recommendation**: Add tests with multiple active controllers if the design supports multi-master

#### Hot-Join Sequences

- **Out of scope**: this wrapper / vendored core does not support hot-join
  (`hotjoin_done` is tied off). No DV coverage is planned.

#### Legacy I2C Compatibility Mode

- **I2C Compatibility**: I3C controller communicating with legacy I2C devices
- **Mixed Bus**: I3C and I2C devices on the same bus
- **Impact**: Important for systems with existing I2C peripherals
- **Recommendation**: Add I2C compatibility tests if legacy support is required

#### Vendor-Specific CCC Commands

- **Extended CCCs**: Vendor-defined CCC codes beyond standard MIPI spec
- **Custom Configuration**: Device-specific configuration and status commands
- **Impact**: Allows custom features beyond standard I3C
- **Recommendation**: Add vendor CCC tests if custom commands are implemented

#### Power Mode Transitions

- **Low-Power Modes**: Bus sleep, device suspend/resume
- **Power State Transitions**: Entering and exiting low-power states
- **Impact**: Critical for battery-powered systems
- **Recommendation**: Add power mode tests for low-power designs

#### Secure Firmware Recovery Image Flow

- **Out of scope for now**: `i3c_recovery_reset_iface` verifies the I3C-protocol
  half (RSTACT arming and the absence of spurious reset), and samples
  `recovery_payload_available` / `recovery_image_activated` only as
  must-stay-idle outputs. The OCP Secure Firmware Recovery image activation flow
  itself is not exercised.
- **Impact**: Critical for secure boot and firmware updates
- **Recommendation**: Add image-activation tests when that flow is required

### Test Gaps

Based on code review, these specific gaps were identified:

1. **Clock Stretching**: I3C targets cannot stretch clocks, so not applicable
2. **Arbitration Loss**: Single controller tested; no arbitration loss scenarios
3. **Multi-Instance Bus Contention**: `i3c_multi_instance_indep` proves the
   AXI-Lite register spaces are decoded independently, but the two instances are
   never driven into simultaneous contention on the shared I3C bus
4. **Timeout Scenarios**: No explicit timeout/watchdog tests
5. **Secondary Controller**: No tests for standby controller promotion to active
6. **CRC Errors**: SDR T-bit parity injection is covered by
   `i3c_error_parity_inject`, but HDR-mode CRC error injection is not
7. **Highest FIFO Threshold**: `i3c_threshold_sweep` covers t=0..2; t=3 needs a
   transfer of at least 64 bytes before the threshold can fire and is untested
8. **Functional Coverage Collection**: `tb/i3c_coverage_if.sv` exists but its
   covergroups are guarded by `I3C_COVERAGE`, which no build currently defines,
   and the launcher has no `[coverage.<tool>]` section for this DUT — so no
   functional coverage is collected today
9. **Permitted Short-Read Reporting (`sre=0`)**: `i3c_error_target_abort`
   stimulates it, but `test_short_read_permitted` **fails** — the DUT produces no
   response descriptor on this path. Suspected DUT issue, unresolved and
   deliberately not worked around; the `sre=1` detection leg passes. See the
   "Open item" section of `BRINGUP_STATUS.md`

### Recommendations for Production

For production-grade verification, consider adding:

1. **Coverage Metrics**: Wire up code and functional coverage. The covergroup
   interface is already written and bound; it needs the `I3C_COVERAGE` define and
   a `[coverage.<tool>]` section before `--cov` can collect anything.
2. **Multi-Seed Regression**: The random modules take a seed from `+seed`/`SEED`
   but a single run uses one seed. Sweeping seeds and merging is what turns them
   into real coverage.
3. **Formal Verification**: Property checking for protocol compliance
4. **Performance Tests**: Throughput, latency, bus utilization measurements
5. **Corner Case Expansion**: More error injection, edge case timing
6. **Compliance Suite**: MIPI I3C conformance test suite integration

---

## Conclusion

This I3C DV Guide provides a comprehensive reference for understanding and using the I3C core testing infrastructure. Key takeaways:

- **Software Interface**: Detailed register programming sequences for controller and target initialization, CCC commands, private transfers, and IBI
- **Python API**: High-level API (`I3CHelper`, `I3CController`, `I3CTarget`) simplifies test writing
- **Test Coverage**: 29 regression modules (38 cocotb tests) spanning registers,
  private transfers, direct and broadcast CCC, IBI, bus timing, error injection
  and reset recovery
- **Corner Cases**: Validates address boundaries, FIFO thresholds, transfers past
  the target-TX queue boundary, and error conditions
- **Execution**: A single launcher (`tools/dv/run_dv.py`) runs individual modules or the full regression

The testbench demonstrates **solid coverage of core I3C functionality** suitable for regression testing. For production deployment, consider expanding coverage to include HDR modes, multi-master scenarios, and formal verification.

---

## Appendix: Quick Reference

### Launcher Commands

All commands run from the repository root with `PY=tools/dv/run_dv.py`.

```bash
python3 $PY --dut i3ccore_wrap --list                     # Show tests and groups
python3 $PY --dut i3ccore_wrap --items <name> --stage sim  # Run specific module
python3 $PY --dut i3ccore_wrap --items all --stage sim     # Run full regression
python3 $PY --dut i3ccore_wrap --items <name> --stage sim --waves          # Waves
python3 $PY --dut i3ccore_wrap --items all --stage sim --waves-on-fail     # Waves on failures
python3 $PY --dut i3ccore_wrap --stage flist              # Regenerate filelist
python3 $PY --dut i3ccore_wrap --stage clean              # Remove artifacts
```

Verilator is the default tool; add `--tool vcs` or `--tool xcelium` to switch.

### Test Modules

The 29 modules in the `all` group, in testlist order. `Tests` is the number of
cocotb test functions in the module (38 in total).

| Module | Tests | Purpose |
|--------|-------|---------|
| test_i3ccore | 4 | Register access across the map; resolves reset-X reads to zero and passes on Verilator |
| i3c_immediate_write_sanity | 1 | Data embedded in the command descriptor |
| i3c_write_read_sanity | 1 | 4-byte private write + read |
| i3c_long_write_sanity | 1 | 500-byte private write |
| i3c_long_read_sanity | 1 | 500-byte private read |
| i3c_direct_ccc_sanity | 1 | Direct CCC chain with SET/GET verification |
| i3c_ibi_sanity | 2 | IBI with payload, and IBI during broadcast |
| i3c_error_sanity | 4 | Address NACK, FIFO overflow and underflow |
| i3c_reg_reset_value_full | 1 | Reset values swept against the generated map |
| i3c_full_ccc_matrix | 1 | Supported CCC set with GET read-back |
| i3c_setnewda | 1 | SETNEWDA re-assignment (CCC 0x88) |
| i3c_pp_timing_transfer | 1 | Push-pull timing bank |
| i3c_od_pp_mode_switch | 1 | Open-drain to push-pull mux |
| i3c_threshold_sweep | 1 | FIFO threshold settings t=0..2 |
| i3c_max_length_transfer | 1 | Boundary lengths around FIFO capacity |
| i3c_back_to_back | 1 | Minimal-gap transaction stream |
| i3c_broadcast_ccc | 1 | ENEC, DISEC, RSTDAA |
| i3c_ibi_payload_variants | 1 | IBI payload sizes, empty through full |
| i3c_ibi_nack_disabled | 1 | IBI suppressed when disabled, with positive control |
| i3c_error_parity_inject | 2 | Clean-path baseline, and SDA bit-flip caught by TE2 |
| i3c_error_target_abort | 2 | Short read under SRE=0 (known fail) and SRE=1 |
| i3c_multi_target_dat | 1 | Multiple DAT entries, one absent address |
| i3c_multi_instance_indep | 1 | AXI address-decode isolation |
| i3c_axi_protocol | 1 | AXI-Lite response codes and checker sensitivity |
| i3c_recovery_reset_iface | 1 | RSTACT arms without spurious reset |
| i3c_reset_mid_transaction | 1 | Reset at a random bus phase, then recovery |
| i3c_random_ccc_stress | 1 | Weighted random CCC ordering |
| i3c_random_transfer_stress | 1 | Random direction, length and data |
| i3c_tx_capacity_512 | 1 | Target-TX queue capacity boundary |

Not in the regression: `i3c_ibi_diag`, an IBI receive diagnostic.

### Key Register Addresses

| Address | Register | Purpose |
|---------|----------|---------|
Offsets within one core instance; add `TGT_BASE` (0x1000) for target accesses.

| Address | Register | Purpose |
|---------|----------|---------|
| 0x004 | HC_CONTROL | Bus enable, mode selector |
| 0x080 | COMMAND_PORT | Write command descriptors |
| 0x084 | RESPONSE_PORT | Read response descriptors |
| 0x088 | TX_DATA_PORT | Write TX data |
| 0x088 | RX_DATA_PORT | Read RX data (same address) |
| 0x08C | IBI_PORT | Read IBI status/data |
| 0x090 | QUEUE_THLD_CTRL | Queue thresholds |
| 0x094 | DATA_BUFFER_THLD_CTRL | Data buffer thresholds |
| 0x0A0 | PIO_INTR_STATUS | Interrupt status flags |
| 0x0B0 | PIO_CONTROL | PIO queue enable |
| 0x184 | STBY_CR_CONTROL | Controller mode control |
| 0x204 | TTI_CONTROL | Target IBI enable |
| 0x280 | TTI_IBI_PORT | Write IBI descriptors |

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

---

**Document Version**: 2.0
**Last Updated**: 2026-09-09
**Original Author**: Anshul Shah
**Contact**: DV Team

Version 2.0 revised the guide for the `dv/cocotb/` layout and the `run_dv.py`
launcher (the per-TB Makefile is gone), rewrote section 6 to cover every
regression module, and corrected the register offsets and response-descriptor
field definitions in sections 4 and 8 against
`hw/ip/i3ccore_wrap/regs/gen/py/oca_i3c_wrap_reg.py` and
`vendor/chipsalliance/i3c-core/upstream/src/i3c_pkg.sv`.

---
