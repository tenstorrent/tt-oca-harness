# Key Manager Testbench

This directory contains the cocotb-based testbench for the Key Manager subsystem.

## Prerequisites

- VCS simulator (or other cocotb-compatible simulator)
- Python 3.8+
- cocotb (`pip install cocotb`)
- Bender dependencies updated (`bender update`)
- RISC-V toolchain for firmware compilation

## Directory Structure

```
hw/ip/key_manager/dv/
├── tb/                       # This directory – testbench, run and regression targets
│   ├── Makefile              # Build and run tests
│   ├── bender-targets.mk     # Bender filelist generation targets
│   ├── tb.f                  # Testbench file list (generated)
│   ├── rtl.f                 # RTL file list (generated)
│   ├── tb_key_manager.sv     # Top-level testbench wrapper
│   ├── test_firmware.py      # Generic firmware test runner
│   ├── cycle_counts/         # Recorded per-test cycle counts (orders the regression)
│   └── README.md             # This file
├── fw/                       # Firmware under test
│   ├── fw.mk                 # Sources, includes and link modes for the shared build engine
│   ├── toolchain.mk          # Architecture, ABI and compiler/linker flags
│   ├── include/              # Public headers (rom_*.h, irq_common.h)
│   ├── drivers/              # Runtime sources (rom_*.c, rom_*.S)
│   ├── startup/              # crt0.s
│   ├── link/                 # Linker scripts; link/modes/ holds one script per link mode
│   │   └── modes/            #   vrom.ld (default, VROM split), rom.ld (all-in-ROM)
│   ├── scripts/              # add_rom_parity.py, km_stack_analyze.py
│   ├── tests/                # One directory per test
│   │   ├── common/           # Test-only headers (test_common.h, vuart.h)
│   │   └── test_*/           #   auto-discovered by regression; must use test_common.h protocol
│   ├── sep_images/           # KM ROM images for the SEP UVM testbench (not run by this regression)
│   ├── production/           # rom_main, the production ROM entry (all-in-ROM, not run by this regression)
│   ├── build/                # Generated (git-ignored): *.o, *.elf, *.rom.hex, *.vrom.hex, *.dis, *.map, *.sym
│   └── README.md             # Firmware layout and build notes
└── cocotb/                   # Cocotb support code (env, seq_lib, assertions)
```

## Running Tests

### Quick Start

```bash
cd hw/ip/key_manager/dv/tb

# Build firmware and run it in the cocotb/VCS testbench (recommended)
make run_fw FW_TEST=test_rom_crc
make run_fw FW_TEST=test_rom_crc_pcpi_bench VUART_PRINT=1

# Run a cocotb hardware test
make run TEST=test_rom_parity

# Run all firmware tests (automatically discovers tests in ../fw/tests/)
make regression
```

### Building firmware vs running it

- `hw/ip/key_manager/dv/tb/Makefile` owns `run_fw`: it builds the firmware, launches simulation, and writes logs to `sim/logs/<test>/`
- `make -f ocah.mk ocah-dv-fw-tests TARGET=key_manager TEST=<name>` builds one image and nothing else; it does **not** run the cocotb/VCS testbench. `dv/fw/fw.mk` and `dv/fw/toolchain.mk` configure that build but are includes, not entry points

If you want to run any firmware-driven test in simulation, run it from
`hw/ip/key_manager/dv/tb`:

```bash
cd hw/ip/key_manager/dv/tb
make run_fw FW_TEST=test_myfeature
```

### With Waveforms

When `WAVES=1`, VCD is produced by default. Use `FSDB=1` with `WAVES=1` to generate FSDB instead.

```bash
make run_fw FW_TEST=test_rom_crc WAVES=1
make run TEST=test_rom_parity WAVES=1
make run TEST=test_rom_parity WAVES=1 FSDB=1   # FSDB instead of VCD
```

### View Results

Test results are saved in `sim/logs/<test_name>/`:
- `vcs.log` - Compilation and simulation log
- `cocotb_<test_name>.log` - cocotb log
- `sim_output_<test_name>.log` - **Complete simulation output** (all stdout/stderr from test run)
- `results_<test_name>.xml` - JUnit test results
- `tb_key_manager.vcd` - VCD waveform file (if WAVES=1)
- `tb_key_manager.fsdb` - FSDB waveform file (if WAVES=1 FSDB=1)

**Note:** The `sim_output_<test_name>.log` file contains the complete output from the test run, including all VUART output, testbench messages, and simulation logs. This allows you to review test output without rerunning the test. Use `grep`, `less`, or your editor to search through the log file.

## Firmware-Driven Testing

The recommended approach for new tests is **firmware-driven testing**. This allows
tests to be written entirely in C, running on the PicoRV32 CPU, with results
reported through a standardized protocol.

### Benefits

- Tests run on actual hardware (CPU, memory, peripherals)
- No need to write separate cocotb Python code for each test
- Printf debugging via Virtual UART
- Standard pass/fail reporting

### Writing a Firmware Test

Create a directory under `../fw/tests/` named after the test, holding a source file of the
same name (e.g. `../fw/tests/test_myfeature/test_myfeature.c`):

```c
#include "test_common.h"

int main(void)
{
    TEST_INIT();

    TEST_SUBTEST_START("First check");
    uint32_t value = test_read32(SOME_REGISTER);
    TEST_ASSERT_EQ(value, EXPECTED_VALUE, "register value");
    TEST_SUBTEST_PASS();

    TEST_SUBTEST_START("Second check");
    // ... more tests ...
    TEST_SUBTEST_PASS();

    TEST_PASS();
    return 0;
}
```

### Running Firmware Tests

```bash
# Build firmware and run it in the RTL simulation
make run_fw FW_TEST=test_myfeature

# Build firmware only (no simulation)
make build_fw FW_TEST=test_myfeature

# With waveforms
make run_fw FW_TEST=test_myfeature WAVES=1

# With custom timeout (default 100000 cycles)
make run_fw FW_TEST=test_myfeature SIM_ARGS="+TIMEOUT_CYCLES=500000"
```

### Test Protocol (test_common.h)

`test_common.h` includes `irq_common.h` (under `hw/ip/key_manager/dv/fw/include/`) after `key_manager_regs.h` and the PicoRV32 helpers. Tests therefore see the `KMCSR_IRQ_*_REG` and `MBOX_IRQ_*_REG` macros and the `rom_kmcsr_irq_*` / `rom_mailbox_irq_*` declarations; do not redefine those macros in individual tests.

The test framework provides these macros:

| Macro | Description |
|-------|-------------|
| `TEST_INIT()` | Initialize test infrastructure (call at start of main()). Sets test result to 0, signature to RUNNING, clears error code and subtest counter, initializes testbench command interface. |
| `TEST_PASS()` | Mark test as passed and halt CPU |
| `TEST_FAIL(fmt, ...)` | Mark test as failed with printf-style message and halt CPU |
| `TEST_ASSERT(cond, fmt, ...)` | Assert condition, fail if false (calls TEST_FAIL if condition is false) |
| `TEST_ASSERT_EQ(actual, expected, name)` | Assert two values are equal (prints expected vs actual on failure) |
| `TEST_ASSERT_NE(actual, not_expected, name)` | Assert two values are not equal |
| `TEST_LOG(fmt, ...)` | Log message via VUART (printf wrapper with newline) |
| `TEST_SUBTEST_START(name)` | Start a named subtest (increments subtest counter, prints "[N] name...") |
| `TEST_SUBTEST_PASS()` | Mark current subtest as passed (prints "  OK") |
| `TEST_SET_ERROR(code)` | Set error code for debugging (stores in TB_ERRCODE register) |

### Helper Functions

```c
test_read32(addr)      // Read 32-bit value from address
test_write32(addr, val) // Write 32-bit value to address
test_delay(cycles)     // Simple delay loop
test_halt()            // Halt CPU (called by TEST_PASS/FAIL)
```

### Interrupt Support (irq_common.h)

The `irq_common.h` header in `hw/ip/key_manager/dv/fw/include/` defines KMCSR and mailbox IRQ register accessors. Most tests include it through `test_common.h`; the firmware Makefile adds `-I$(KM_FIRMWARE_DIR)/include` if you include `irq_common.h` directly.

```c
#include "irq_common.h"

// PicoRV32 interrupt mask control
uint32_t old_mask = picorv32_maskirq(0);  // Enable all interrupts
picorv32_maskirq(old_mask);               // Restore previous mask

// KMCSR interrupt control (irq_common.c)
rom_kmcsr_irq_status_clear(mask);   // W1C clear selected bits
rom_kmcsr_irq_enable_write(enable_mask);
rom_kmcsr_irq_set(sw_trigger_mask); // IRQ_SET pulse sets sticky status bits

// Struct fields: KMCSR_IRQ_STATUS_REG / KMCSR_IRQ_ENABLE_REG; see irq_common.h
// and key_manager_regs.h for bit names.

// Interrupt vector constants
PICORV32_IRQ_KMCSR   // KMCSR aggregated sticky errors (bit 3)
PICORV32_IRQ_MBOX    // Mailbox inbound data available (bit 4)
PICORV32_IRQ_EBREAK  // EBREAK instruction IRQ (bit 1)
PICORV32_IRQ_BUSERR  // Bus error IRQ (bit 2)
```

#### Programmable IRQ entry (`rom_kmcsr`)

`rom_kmcsr.h` / `rom_kmcsr.c` expose `rom_kmcsr_irq_entry_addr_read`, `rom_kmcsr_irq_entry_addr_write`, `rom_kmcsr_irq_entry_lock_read`, and `rom_kmcsr_irq_entry_lock_set` for `IRQ_ENTRY_ADDR` and `IRQ_ENTRY_LOCK` (see KMCSR register definitions). Firmware test: `test_rom_kmcsr_irq_entry`.

**Interrupt Architecture Notes:**
- The PicoRV32 uses a custom interrupt controller with `maskirq`/`retirq` instructions
- Bits 0-2 are latched (edge-triggered) for internal CPU interrupts
- Bit 3 (KMCSR): aggregated sticky error sources, non-latched (level-sensitive)
- Bit 4 (Mailbox): direct from mailbox hardware, non-latched (level-sensitive)
- Non-latched bits track the live level; the CPU re-enters the ISR after `retirq` if the level is still high

### Printf Support (vuart.h)

Firmware can use standard I/O functions that output via the Virtual UART:

```c
#include "vuart.h"  // Included by test_common.h

printf("Value: 0x%08X\n", value);
puts("Hello world");
putchar('A');
```

The testbench captures VUART output and displays it in the simulation log.

#### VUART Printing Control

VUART printing is **disabled by default** to save simulation time during regressions. To enable printing for debugging:

```bash
# Enable VUART printing
make run_fw FW_TEST=test_vuart VUART_PRINT=1

# Disable VUART printing (default - faster simulation)
make run_fw FW_TEST=test_vuart
```

**Performance Impact:**
- With printing **disabled** (default): Tests run ~5-6x faster
- With printing **enabled**: Full printf output available for debugging

The `PRINT_ENABLE` bit in `VUART_STATUS` register (bit 2) controls whether firmware actually sends characters. When disabled, `printf()` return immediately without processing, saving significant CPU cycles.

## Memory Map

| Region | Address Range | Description |
|--------|---------------|-------------|
| ROM | 0x0000_0000 - 0x0000_3FFF | 16KB instruction ROM |
| SRAM | 0x0000_4000 - 0x0000_7FFF | 16KB data SRAM |
| Reserved | 0x0000_8000 - 0x0000_CFFF | Reserved (20KB) |
| KPV | 0x0000_D000 - 0x0000_DFFF | Key and Policy Vault (4KB) |
| KMCSR | 0x0000_E000 - 0x0000_EFFF | Control/Status registers (4KB) |
| DRBG Sampler | 0x0000_F000 - 0x0000_FFFF | DRBG data/config/status (4KB) |
| Mailbox KM | 0x0001_0000 - 0x0001_0FFF | Mailbox KM-side interface (4KB decode; registers in lower 2KB) |
| **OTP/eFuse** | **0x0001_1000 - 0x0001_1FFF** | **eFuse AXI-Lite responder model (testbench only; see below)** |
| Reserved | 0x0001_2000 - 0x0001_7FFF | Reserved (24KB) |
| OTBN | 0x0001_8000 - 0x0001_8FFF | OTBN accelerator port (4KB) |
| AES | 0x0001_9000 - 0x0001_9FFF | AES accelerator port (4KB) |
| KMAC | 0x0001_A000 - 0x0001_AFFF | KMAC accelerator port (4KB) |
| HMAC | 0x0001_B000 - 0x0001_BFFF | HMAC accelerator port (4KB) |
| **VROM** | **0x1000_0000 - 0x1000_FFFF** | **64KB Virtual ROM (testbench only; main code + rodata)** |

### eFuse AXI-Lite Responder Model (OTP/eFuse window)

The testbench includes a behavioral AXI-Lite register-file model wired to the DUT's `efuse_req_o` / `efuse_resp_i` ports (the OTP/eFuse crossbar master port, index 8).

**Behavior:**
- Decodes addresses in `[OTP_EFUSE_REMAP_BASE : OTP_EFUSE_REMAP_BASE+0xFFF]` (the *remapped* SEP eFuse absolute window). The responder derives this window directly from the DUT's `OTP_EFUSE_REMAP_BASE` parameter, so overriding the parameter at elaboration time is automatically reflected.
- Responds `OKAY` with a 1 KB word array, using `addr[11:2]` as the index. Writes are stored and read back.
- Returns `SLVERR` for any address outside the `0x1093_0xxx` window — a broken address remap would land outside the window and fail the test.

**Test:** `test_efuse_axil` exercises this path (see test table below).

### Virtual ROM (VROM)

The **Virtual ROM (VROM)** is a testbench-only memory region used for main program code (`.text`) and read-only data (`.rodata`). The physical 16KB ROM holds only a small bootstrap (reset, IRQ vector, IRQ handler); the `vrom` link mode (`dv/fw/link/modes/vrom.ld`) places the rest in VROM so test images are not limited by ROM size.

**Key Features:**
- **Address Range**: 0x1000_0000 - 0x1000_FFFF (64KB)
- **Testbench Only**: Not available in real hardware - only exists in simulation
- **Purpose**: Stores `.text` and `.rodata` (main code, string constants, const arrays, etc.)
- **Access**: Read-only, accessed via CPU memory bus (same interface as ROM/SRAM)
- **Always used**: All firmware tests use VROM; build always generates a non-empty VROM hex file

**Firmware Build Process:**
1. Linker script (`link/modes/vrom.ld`) places `.text` and `.rodata` in VROM at 0x1000_0000
2. Build process generates `firmware/build/<test>/<test>.vrom.hex` containing code and rodata
3. Testbench automatically loads VROM hex file if present (via `+VROM_HEX_FILE` plusarg)
4. If VROM hex file is missing or empty, testbench initializes VROM with zeros

**Usage in Firmware:**
```c
// String constants automatically go to VROM
const char *msg = "Hello, World!";  // Stored in VROM at 0x1000_0000+

// Const arrays also go to VROM
const uint32_t lookup_table[] = {0, 1, 2, 3};  // Stored in VROM

// Regular variables go to SRAM
uint32_t counter = 0;  // Stored in SRAM at 0x0000_4000+
```

**Testbench Loading:**
- VROM hex file is automatically passed to simulation via `+VROM_HEX_FILE=<path>` plusarg
- If file is missing, testbench prints: `"No VROM_HEX_FILE provided, using default zero pattern"`
- VROM is initialized with zeros if hex file is not provided or is empty

### Key KMCSR Registers

| Address | Register | Description |
|---------|----------|-------------|
| 0xE000 | VERSION | IP version (read-only, 0x0001_0000 = 1.0.0) |
| 0xE004 | CTRL | Control register (currently reserved) |
| 0xE008 | SOFT_RST_CODE | Write `0x53525354` (`SRST`) to trigger soft reset |
| 0xE00C | IRQ_STATUS | Interrupt status (sticky error bits) |
| 0xE010 | IRQ_ENABLE | Interrupt enable mask |
| 0xE014 | SCRAMBLER_KEY | SRAM scrambler key (32-bit) |
| 0xE018 | SCRAMBLER_CTRL | Scrambler enable and lock control |
| 0xE020 | IRQ_SET | Software interrupt trigger (write-only) |
| 0xE038 | SRAM_EXEC_MODE | Execute-permission whitelist mode |
| 0xE0B8 | IRQ_ENTRY_ADDR | Programmable IRQ handler address (`km_csr.rdl`; ADDR field gated when locked) |
| 0xE0BC | IRQ_ENTRY_LOCK | Lock for IRQ entry programming (write-one-set) |
| 0xE100 | VUART_TX | Virtual UART transmit register |
| 0xE104 | VUART_RX | Virtual UART receive register |
| 0xE108 | VUART_STATUS | Virtual UART status register |
| 0xE1FC | DEBUG | Debug register (read-only, 0xCAFEBEEF) |

#### VUART_STATUS Register (0xE108)

| Bit | Name | Description |
|-----|------|-------------|
| 0 | TX_READY | TX ready to accept data (always 1 in simulation) |
| 1 | RX_VALID | RX has valid data available |
| 2 | PRINT_ENABLE | Enable VUART printing (testbench-controlled, disabled by default) |
| 31:3 | RSVD | Reserved |

#### IRQ_STATUS Register (0xE00C)

| Bit | Name | Description |
|-----|------|-------------|
| 0 | ROM_PARITY_ERR | ROM parity error detected (sticky, W1C) |
| 1 | SRAM_PARITY_ERR | SRAM parity error detected (sticky, W1C) |
| 2 | ROM_WRITE_ERR | ROM write attempt detected (sticky, W1C) |
| 3 | SRAM_WRITE_LOCK_ERR | SRAM write to locked region (sticky, W1C) |
| 4 | AXI_SLVERR | AXI SLVERR error detected (sticky, W1C) |
| 5 | AXI_DECERR | AXI DECERR error detected (sticky, W1C) |
| 6 | DRBG_ERR | DRBG Sampler error -- timeout or stream error (sticky, W1C) |
| 7 | WIPE_STATE | Wipe state rising edge detected (sticky, W1C) |
| 8 | OTP_CHANGE | OTP change event detected (sticky, W1C) |
| 9 | OTP_SIGINT | OTP dual-rail encoding integrity violation (sticky, W1C) |
| 10 | EXEC_VIOLATION | Instruction fetch from a non-whitelisted memory region (sticky, W1C) |

The error bits (parity, ROM write, SRAM write-lock, AXI errors, DRBG, wipe, exec_violation) are **sticky**: once set by hardware,
they remain set until firmware writes 1 to clear them (W1C = write-1-to-clear).

#### IRQ_SET Register (0xE020)

| Bit | Name | Description |
|-----|------|-------------|
| 0 | ROM_PARITY_ERR_SET | Set ROM parity error sticky bit |
| 1 | SRAM_PARITY_ERR_SET | Set SRAM parity error sticky bit |
| 2 | ROM_WRITE_ERR_SET | Set ROM write error sticky bit |
| 3 | SRAM_WRITE_LOCK_ERR_SET | Set SRAM write-lock error sticky bit |
| 4 | AXI_SLVERR_SET | Set AXI SLVERR error sticky bit |
| 5 | AXI_DECERR_SET | Set AXI DECERR error sticky bit |
| 6 | DRBG_ERR_SET | Set DRBG Sampler error sticky bit |
| 7 | WIPE_STATE_SET | Set wipe state sticky bit |
| 8 | OTP_CHANGE_SET | Set OTP change sticky bit |
| 9 | OTP_SIGINT_SET | Set OTP dual-rail integrity error sticky bit |
| 10 | EXEC_VIOLATION_SET | Set execute-permission violation sticky bit |

The IRQ_SET register allows firmware to manually trigger interrupts for testing.
Sticky bits (parity errors, ROM write error, SRAM write-lock, AXI errors, DRBG, wipe, exec_violation) remain set until cleared via IRQ_STATUS W1C.

### Test Protocol Registers (KMCSR)

The test framework uses dedicated KMCSR registers for firmware-testbench communication:

| Address | Register | Description |
|---------|----------|-------------|
| 0xE110 | TB_RESULT | Test result: 0=fail, 1=pass |
| 0xE114 | TB_SIGNATURE | Completion signature: 0x600D600D (pass) or 0xBADBADBA (fail) |
| 0xE118 | TB_ERRCODE | Optional error code for debugging |
| 0xE11C | TB_SUBTEST | Current subtest number |
| 0xE120 | TB_CMD | Command to testbench (write triggers action) |
| 0xE124 | TB_CMD_ARG | Argument for testbench command |
| 0xE128 | TB_CMD_STATUS | Status from testbench (0=idle, 1=ack, 2=error) |
| 0xE12C | TB_CMD_RESULT | Result from testbench command (read-only) |

### Testbench Commands

Firmware can send commands to the testbench to control error injection and other features:

| Command | Value | Description |
|---------|-------|-------------|
| TB_CMD_NOP | 0x00 | No operation |
| TB_CMD_ROM_PARITY_ENABLE | 0x01 | Enable ROM parity error injection |
| TB_CMD_ROM_PARITY_DISABLE | 0x02 | Disable ROM parity error injection |
| TB_CMD_SRAM_PARITY_ENABLE | 0x03 | Enable SRAM parity error injection |
| TB_CMD_SRAM_PARITY_DISABLE | 0x04 | Disable SRAM parity error injection |
| TB_CMD_SRAM_READ_RAW | 0x05 | Read raw SRAM data (bypass scrambling) |
| TB_CMD_SEP_MBOX_WRITE | 0x06 | Write data to SEP mailbox outbound FIFO |
| TB_CMD_MONITOR_EN | 0x07 | Enable CPU/memory monitoring |
| TB_CMD_MONITOR_DIS | 0x08 | Disable CPU/memory monitoring |
| TB_CMD_SEP_MBOX_IRQ_ENABLE | 0x09 | Enable/disable SEP mailbox IRQ |
| TB_CMD_SEP_MBOX_READ | 0x0A | Read data from SEP mailbox outbound FIFO |
| TB_CMD_SEP_MBOX_IRQ_CHECK | 0x0B | Check SEP mailbox IRQ status |
| TB_CMD_SEP_MBOX_WRITE_WITH_RESP | 0x0C | Write to SEP mailbox and return AXI response |
| TB_CMD_KM_MBOX_READ_WITH_RESP | 0x0D | Read from KM mailbox and return AXI response |
| TB_CMD_TIMEOUT_SET | 0x0E | Set testbench timeout value (cycles) |
| TB_CMD_SEP_MBOX_READ_WITH_RESP | 0x0F | Read from SEP mailbox and return AXI response |
| TB_CMD_SEP_MBOX_STATUS_READ | 0x10 | Read SEP mailbox STATUS register |
| TB_CMD_SEP_MBOX_STATUS_WRITE | 0x11 | Write SEP mailbox STATUS register (W1C) |
| TB_CMD_SEP_MBOX_CTRL_WRITE | 0x12 | Write SEP mailbox CTRL register |
| TB_CMD_VUART_VERIFY | 0x13 | Verify VUART received expected string (arg = SRAM byte address) |
| TB_CMD_CHECK_RECOVERABLE_ERR | 0x1F | Testbench samples recoverable_err; result = 1 if set, 0 if clear |
| TB_CMD_CHECK_UNRECOVERABLE_RESTART | 0x20 | Ask TB: was CPU restarted due to unrecoverable fault? result = 1 if yes, 0 if no |
| TB_CMD_UNRECOVERABLE_WATCH_CTRL | 0x27 | Arm or disarm the unrecoverable-fault watcher from firmware |
| TB_CMD_GET_CYCLE_COUNT | 0x28 | Snapshot the testbench-maintained cycle counter |
| TB_CMD_KM_ASYNC_RESET | 0x29 | Pulse top-level `rst_n` (async reset); see `test_irq_entry_reset_restore` |
| TB_CMD_OTP_WRITE | 0x21 | Drive `otp_data_i` with known dual-rail pattern (life-cycle=0x12, chiplet/sip/sys/class UIDs) |
| TB_CMD_WIPE_TRIGGER | 0x22 | Assert `wipe_state_i` for one cycle (triggers WIPE_STATE fault) |
| TB_CMD_KEY_SHARE_READ | 0x24 | Read crypto engine key share word via `hwif_out`; arg `[11:8]`=engine, `[4]`=share, `[3:0]`=word |
| TB_CMD_KM_WARM_RESET | 0x2C | Pulse `warm_rst_n` for ≥22 cycles; firmware restarts from ROM |
| TB_CMD_OTP_WRITE_CHANGED | 0x2D | Drive `otp_data_i` with a *different* dual-rail pattern (triggers `OTP_CHANGE` IRQ) |
| TB_CMD_OTP_WRITE_SIGINT | 0x2E | Drive `otp_data_i` with a *corrupted* dual-rail on `chiplet_uid` (triggers `OTP_SIGINT` IRQ) |

The full command codes and C macro names are in `firmware/common/test_common.h`. This table uses descriptive names; the headers use short names (for example `TB_CMD_ROM_PARITY_EN` instead of `TB_CMD_ROM_PARITY_ENABLE`).

### Testbench Command Helper Functions

The test framework provides convenient helper functions for common testbench operations:

#### Parity Error Injection

```c
// ROM parity error injection
tb_rom_parity_inject_enable();   // Enable ROM parity errors
tb_rom_parity_inject_disable();  // Disable ROM parity errors

// SRAM parity error injection
tb_sram_parity_inject_enable();   // Enable SRAM parity errors
tb_sram_parity_inject_disable();  // Disable SRAM parity errors
```

#### SRAM Raw Read (Bypass Scrambling)

```c
// Read raw SRAM data (before descrambling)
// Note: Must calculate scrambled address if scrambler is enabled
uint32_t raw_data = tb_sram_read_raw(physical_word_addr);
```

#### SEP Mailbox Operations

```c
// Write to SEP mailbox inbound FIFO (SEP->KM direction)
tb_sep_mbox_write(data, timeout_cycles);

// Read from SEP mailbox outbound FIFO (KM->SEP direction)
uint32_t data;
tb_sep_mbox_read(&data, timeout_cycles);

// Read with AXI response code (for underflow testing)
uint32_t data, resp;
tb_sep_mbox_read_with_resp(&data, &resp, timeout_cycles);

// Write with AXI response code (for overflow testing)
uint32_t resp;
tb_sep_mbox_write_with_resp(data, &resp, timeout_cycles);

// Control SEP mailbox IRQ
tb_sep_mbox_irq_enable(enable_value, timeout_cycles);

// Check SEP mailbox IRQ status
uint32_t irq_status;
tb_sep_mbox_irq_check(&irq_status, timeout_cycles);

// Read/write SEP mailbox STATUS register
uint32_t status;
tb_sep_mbox_status_read(&status, timeout_cycles);
tb_sep_mbox_status_write(status_value, timeout_cycles);

// Write SEP mailbox CTRL register
tb_sep_mbox_ctrl_write(ctrl_value, timeout_cycles);
```

#### KM Mailbox Operations

```c
// Read from KM mailbox with AXI response code (for underflow testing)
uint32_t data, resp;
tb_km_mbox_read_with_resp(&data, &resp, timeout_cycles);
```

#### Testbench Control

```c
// Set testbench timeout value (cycles)
tb_set_timeout(timeout_cycles);

// Control the unrecoverable-fault watcher
tb_set_unrecoverable_watch(enable, timeout_cycles);

// Snapshot current testbench cycle count
uint32_t cycles;
tb_get_cycle_count(&cycles, timeout_cycles);

// Verify VUART received expected string (string must be in SRAM)
// sram_byte_addr: SRAM byte address of null-terminated string
int verified = tb_vuart_verify(sram_byte_addr, timeout_cycles);
```

### CRC benchmark notes

`test_rom_crc_pcpi_bench` uses `TB_CMD_GET_CYCLE_COUNT` instead of PicoRV32 internal
performance counters, because the Key Manager PicoRV32 wrapper keeps those counters
disabled. The benchmark measures `256` updates for each of:

- CRC-32C word updates
- CRC-32C byte updates
- CRC-8/ROHC byte updates

Use `VUART_PRINT=1` when running the benchmark so the per-workload software and PCPI
cycle totals are visible in the simulation log:

```bash
make run_fw FW_TEST=test_rom_crc_pcpi_bench VUART_PRINT=1
```

The unrecoverable-fault watcher is armed explicitly from firmware with
`tb_set_unrecoverable_watch(...)` instead of relying on test-name-specific behavior in
the Python testbench.

#### Generic Command Interface

For advanced use cases, you can send commands directly:

```c
// Send a command with optional argument
// Returns 1 if acknowledged, 0 on timeout/error
int success = tb_send_cmd(TB_CMD_ROM_PARITY_EN, 0, 1000);

// Read result from TB_CMD_RESULT register after command completes
uint32_t result = TB_CMD_RESULT;
```

## Available Tests

The firmware-driven tests are the `test_*` directories under `dv/fw/tests/`,
auto-discovered by the shared build engine. Each test's header comment
documents what it covers.

To see the list and run one:

```bash
# from hw/ip/key_manager/dv/tb
ls -d ../fw/tests/test_*          # the authoritative list
make run_fw FW_TEST=<test_name>   # e.g. FW_TEST=test_sram_parity
```

See "Running Tests" above for the full set of `run_fw` options (waveforms,
timeouts, build-only).

### SEP UVM vs KM block-level firmware images

Tests under `dv/fw/tests/` are auto-discovered by the KM regression and must follow the
`test_common.h` protocol (call `TEST_INIT()`, report pass/fail via KMCSR registers). They
run inside the KM block-level cocotb testbench (`tb_key_manager.sv`).

Files under `dv/fw/sep_images/` are KM ROM images intended for the **SEP UVM testbench**
(`nonfree/hw/sys/sep/dv/tb/`), which loads them with `+KM_ROM_HEX_FILE`. They report to the
SEP host over the hardware mailbox rather than through KMCSR registers, and they need a live
SEP host (a UVM sequence driving the EL2 CPU) to drive or drain them — each one free-runs or
parks in an infinite loop rather than ending on its own. That is why they sit outside
`tests/`: the KM regression enumerates `dv/fw/tests/test_*`, so a test placed there would be
run without a host and burn its whole cycle budget.

| Image | Purpose |
|-------|---------|
| `test_efuse_km_axil` | Routing/remap correctness for KM CPU accesses to the real eFuse controller; reports a 6-word result frame |
| `test_efuse_km_perm` | Generic UVM-driven eFuse access agent, used to prove KM and SEP host are subject to the same permission policy |
| `test_efuse_km_coexist` | Free-running eFuse writer that contends with concurrent SEP host reads at the eFuse mux |

`production/rom_main` is loaded the same way and by the most SEP tests, but it is not a test
image: it is the real ROM entry (`rom_boot_init()` then the `rom_main_step()` mailbox loop),
used wherever a SEP test needs the KM running its actual firmware rather than a directed
agent.

All of them are built by the normal firmware targets — no separate flag. Because the SEP
testbench loads only the physical KM ROM and provides no VROM, `fw.mk` gives these images the
`rom` link mode (all-in-ROM, production geometry) instead of the default `vrom` mode:

```bash
# one image, from the repo root
make -f ocah.mk ocah-dv-fw-tests TARGET=key_manager TEST=rom_main

# or all firmware, including these images
cd hw/ip/key_manager/dv/tb && make build_all_fw
```

Each produces `dv/fw/build/tests/<name>/<name>.rom.parhex` (the full parity-protected ROM
image) plus `<name>.sym`, which the SEP UVM reads alongside the hex to resolve firmware
symbols by name.

### Running Firmware Regression

The top-level `make regression` target lives in `hw/ip/key_manager/dv/tb/Makefile`. It runs every `test_*` directory under `dv/fw/tests/`. To build the images without running them, use `make build_all_fw`.

#### Basic Regression

From `hw/ip/key_manager/dv/tb`:

```bash
make regression
```

Each full run does the following in order:

1. `clean` - Remove prior build outputs so RDL regeneration and simulation do not race stale files.
2. `build_all_fw` - Discover tests, order them using `cycle_counts/` when present, then build ROM/VROM hex for each test in parallel (`FW_BUILD_JOBS`, default 16).
3. `compile_first` - Build firmware for the first test in the ordered list (or `test_rom_crc` if none), then compile the VCS `test_firmware` image once so `simv` exists.
4. `run_regression_<name>` - One target per test, in parallel up to `PARALLEL_JOBS` (default 16). Each run depends on `compile_first` and `build_fw_for_<name>`, invokes `run_no_compile`, and logs to `sim/logs/<name>/regression_run.log`. A test passes if that log contains `PASSED` or a cocotb line with `PASS=1` and `FAIL=0` (see the `grep` in `tb/Makefile`).
5. Record `Cycles:` from `regression_run.log` into `cycle_counts/<name>.txt` when possible.
6. Print a summary from `regression_result.txt` per test; exit with failure if any test failed.

This tree has no standalone firmware `Makefile`: `dv/fw/fw.mk` and `dv/fw/toolchain.mk` are consumed by the shared build engine in `hw/common/dv/fw/`, which links the ELF and post-processes it into the ROM and VROM hex images. See `dv/fw/README.md` for that flow.

#### Regression with Options

```bash
make regression DEBUG=1
make regression PARALLEL_JOBS=12 FW_BUILD_JOBS=6
```

Waveform dumps are not supported during full regression (`WAVES=1` / `FSDB=1` are rejected) because all jobs share one `simv`. Run individual tests with `make run_fw FW_TEST=<name> WAVES=1` when you need waves.

#### Regression Output

Regression output includes:
- Test configuration (SIM, WAVES, DEBUG settings)
- List of discovered tests
- Per-test status (✓ PASSED or ✗ FAILED)
- Final summary with pass/fail counts

Individual test logs are stored in `sim/logs/<test_name>/`:
- `fw_build.log` - Firmware build output for that test
- `regression_run.log` - Full regression sub-make output for that test
- `regression_result.txt` - PASS/FAIL marker consumed by summary
- `sim_output_<test_name>.log` - Complete simulation output
- `vcs.log` - Compilation log
- `cocotb_<test_name>.log` - cocotb log
- `results_<test_name>.xml` - JUnit test results
- `tb_key_manager.vcd` - VCD waveform file (if WAVES=1)
- `tb_key_manager.fsdb` - FSDB waveform file (if WAVES=1 FSDB=1)

Cycle-count cache files are stored under `cycle_counts/` as one file per test
(for example `cycle_counts/test_kmcsr_access.txt`).

## Filelist Generation

Filelists are automatically generated from Bender before compilation.

### Manual Regeneration

```bash
cd hw/ip/key_manager/dv/tb
rm -f rtl.f tb.f
make filelist
```

## Troubleshooting

### Compilation Errors

If you see compilation errors about missing files:
1. Ensure Bender dependencies are updated: `bender update`
2. Check RTL files exist: `ls hw/ip/key_manager/rtl/`
3. Regenerate registers: `cd hw/ip/key_manager/regs && make all_rtl`

### Firmware Build Errors

If firmware fails to compile:
1. Ensure RISC-V toolchain is in PATH
2. Check for syntax errors in your test
3. Verify headers are present: `firmware/common/test_common.h`, `firmware/common/vuart.h` for tests; `irq_common.h`, `rom_memcpy` (and memcpy alias), and startup come from `hw/ip/key_manager/dv/fw/` (see that directory’s README.md).

### Test Timeout

If tests timeout waiting for completion:
1. Check firmware compiles without errors
2. Verify ROM hex file is loaded (check for `[KM TB] ROM loaded` message)
3. Increase timeout: `SIM_ARGS="+TIMEOUT_CYCLES=500000"`
4. Enable waves and check CPU execution

### No VUART Output

If printf output doesn't appear:
1. **Check if VUART printing is enabled**: By default, VUART printing is disabled to save simulation time. Enable it with `VUART_PRINT=1`:
   ```bash
   make run_fw FW_TEST=test_vuart VUART_PRINT=1
   ```
2. Ensure `#include "test_common.h"` is present
3. Check firmware is actually running (not stuck)
4. Verify VUART registers are accessible (run `test_kmcsr_access`)
