# ocah_spi_vip — OCAH SPI Flash VIP

SPDX-License-Identifier: Apache-2.0

Stable, OCAH-flavoured Python components for a single-SPI NOR-flash link in
cocotb testbenches: a flash device model, a controller engine for benches
without an SPI host IP, a passive bus monitor, and a checker that rebuilds the
flash array and the write-enable latch from the wire and judges the exchange.

This is a **behavioural model**.  It is not silicon-accurate and is not
affiliated with any flash manufacturer.  No vendor or brand names appear
in class or method names.

---

## Purpose

OCAH cocotb tests that exercise SPI-attached flash (SMC SPI peripherals and
the SEP xSPI path) need a single, versioned flash device model so that:

1. Tests do not depend on any proprietary flash vendor simulation model.
2. The API is stable across changes to the underlying implementation.
3. The model is deterministic by default (fixed JEDEC ID, preloaded contents).
4. A test's verdict rests on named checker evidence, not on in-leaf asserts.

---

## Supported personalities

| Mode    | Description                                           | Data phase  |
|---------|-------------------------------------------------------|-------------|
| single  | Standard 1-bit SPI (MOSI/MISO), Mode 0 (CPOL=0/CPHA=0) | 1-bit on MOSI/MISO |
| quad    | 4-bit data bus (QSPI); command/address 1-bit         | 1-bit on DQ0 (see note below) |
| octal   | 8-bit data bus (OSPI/xSPI); SDR only                 | 1-bit on DQ0 (see note below) |

**Quad/Octal note:** Command and address bytes are always received in 1-bit
mode, and the data phase uses the same 1-bit engine on DQ0, so the quad and
octal personalities differ from single only in pin binding. JEDEC ID, page
program, and read work on QSPI/OSPI paths under that model; multi-bit data
lanes and the bidirectional turnaround are not modeled.

DDR (Double Data Rate) octal mode is out of scope.

---

## Supported NOR-flash commands

| Opcode | Command              | Scope    |
|--------|----------------------|----------|
| 0x9F   | READ JEDEC ID        | In scope |
| 0x03   | READ                 | In scope |
| 0x0B   | FAST READ            | In scope |
| 0x05   | READ STATUS REG 1    | In scope |
| 0x35   | READ STATUS REG 2    | In scope |
| 0x06   | WRITE ENABLE         | In scope |
| 0x04   | WRITE DISABLE        | In scope |
| 0x02   | PAGE PROGRAM         | In scope |
| 0x20   | SECTOR ERASE (4 KB)  | In scope |

`OcahSpiOpcode` names these nine opcodes and `IN_SCOPE_OPCODES` is their set.
An opcode outside the set is drained by the device to the end of the frame
and recorded with `ok=False`, decoded by the monitor as `UNKNOWN(0xNN)` with
empty data fields, and counted by the checker under `unsupported`, never
credited.  Out of scope: dual/quad-output reads (0x3B, 0x6B), block and chip
erase (0xD8, 0xC7), 4-byte address mode entry (0xB7), suspend/resume,
OTP/security registers, ECC, SFDP, and all silicon-specific commands.

---

## Package layout

```
ocah_spi_vip/
  __init__.py                           — re-exports the cocotb public API
  cocotb/ocah_spi_types.py              — OcahSpiOpcode, SpiMode, page/sector geometry, SR1 bits
  cocotb/ocah_spi_flash.py              — OcahSpiFlash (generic SPI/QSPI/OSPI device)
  cocotb/ocah_sep_spi_flash.py          — OcahSepSpiFlash (SEP xSPI pin set)
  cocotb/ocah_spi_master_bfm.py         — OcahSpiMasterBfm (Mode-0 controller engine)
  cocotb/ocah_spi_master_sequence.py    — OcahSpiMasterSequence (test-facing controller operations)
  cocotb/ocah_spi_monitor.py            — OcahSpiMonitor (passive bus observer)
  cocotb/ocah_spi_flash_checker.py      — OcahSpiFlashChecker + OcahSpiFlashRefModel
  cocotb/examples/
    example_jedec_id.py                 — device, controller, monitor, and checker on one link
  dv/                                   — `--dut ocah_spi_vip` wire-harness selftests
  README.md                             — this file
```

---

## Dependencies

This package is a self-contained cocotb-native implementation and requires no
external cocotb extension package.  The checker composes the shared
`ocah_checker` evidence core; the harness uses `ocah_lib` for knobs and seeds.

---

## Public API reference

### OcahSpiFlash — generic NOR-flash device BFM

```python
from ocah_spi_vip import OcahSpiFlash

flash = OcahSpiFlash(
    cs_n     = dut.spi_cs_n,   # active-low chip-select (DUT → flash)
    sclk     = dut.spi_sclk,   # serial clock (DUT → flash)
    mosi     = dut.spi_mosi,   # required for mode="single"
    miso     = dut.spi_miso,   # required for mode="single"
    # OR for quad/octal:
    # dq_out = dut.spi_dq_out,  # DQ bus driven by DUT
    # dq_in  = dut.spi_dq_in,   # DQ bus driven by flash BFM
    name     = "flash0",
    mode     = "single",        # "single" | "quad" | "octal"
    jedec_id = 0x20BA18,        # 3-byte JEDEC ID
    flash_size = 16*1024*1024,  # bytes
    addr_bytes = 3,             # 24-bit addressing
    status_reg2 = 0x00,         # value READ STATUS REG 2 returns
)
```

| Method                              | Returns | Notes |
|-------------------------------------|---------|-------|
| `flash.init_signals()`              | `None`  | Drive MISO / DQ to idle; call before first clock edge |
| `flash.preload(source)`             | `None`  | Load raw bytes from file path or bytes-like object |
| `flash.set_jedec_id(id)`            | `None`  | Override JEDEC ID at runtime |
| `await flash.start()`               | `None`  | Start background protocol engine |
| `await flash.stop()`                | `None`  | Stop; the transaction history survives |
| `flash.get_transactions()`          | `list`  | Completed frame records (below) |
| `flash.clear_transactions()`        | `None`  | Discard history |
| `flash.read_memory(addr, length)`   | `bytes` | Direct memory read (no SPI) |
| `flash.write_memory(addr, data)`    | `None`  | Direct memory write (no SPI) |
| `flash.register_command_callback(opcode, fn)` | `None` | Override or extend command handling |
| `flash.unregister_command_callback(opcode)` | `None` | Restore the built-in handling |
| `flash.jedec_id`, `.flash_size`, `.addr_bytes`, `.status_reg1`, `.status_reg2`, `.write_enabled` | read-only | The configuration and state a checker predicts against |

Frame record keys: `opcode`, `addr`, `data_out` (complete bytes the device
sent), `data_in` (payload bytes the device accepted), `ok`, `reason`
(`""`, `"wel_clear"`, or `"unknown_opcode"`).  A PAGE PROGRAM or SECTOR ERASE
issued with the write-enable latch clear is refused: the address is decoded,
no payload is taken, memory is unchanged, and the record carries `ok=False`.
The device is instant-ready: the BUSY bit never sets and a program or erase
completes when chip-select rises.

---

### OcahSepSpiFlash — SEP xSPI pin set

```python
from ocah_spi_vip import OcahSepSpiFlash

flash = OcahSepSpiFlash(
    cs_n     = dut.spi_cs_n_o,
    sclk     = dut.spi_clk_o,
    dq_out   = dut.spi_txd_o,           # DUT → flash, 8-bit
    dq_in    = dut.spi_rxd_i,           # flash → DUT, 8-bit
    dq_oe_n  = dut.spi_dq_oe_n_o,      # optional: OE from DUT
    rebar_o  = dut.spi_mem_rebar_opad_o, # optional: REBAR from DUT
    rebar_i  = dut.spi_mem_rebar_ipad_i, # optional: REBAR to DUT
    name     = "sep_flash",
    mode     = "quad",                  # or "single" / "octal"
    jedec_id = 0x20BA18,
)
```

Inherits all `OcahSpiFlash` methods, plus:

| Additional behaviour        | Notes |
|-----------------------------|-------|
| REBAR reset handling        | Falling edge on `rebar_o` resets WEL and state machine; does not clear memory |
| OE-aware DQ drive           | When `dq_oe_n` provided, BFM skips driving DQ0 during controller-output phases |
| `rebar_i` driven high       | `init_signals()` drives `rebar_i` = 1 (flash not in reset) |

**Pad roles** (the pad each parameter binds):

| This BFM parameter | Pad                       | Direction (from DUT) |
|--------------------|---------------------------|----------------------|
| `cs_n`             | `spi_cs_n_o`              | DUT → flash          |
| `sclk`             | `spi_clk_o`               | DUT → flash          |
| `dq_out`           | `spi_txd_o[7:0]`          | DUT → flash          |
| `dq_in`            | `spi_rxd_i[7:0]`          | flash → DUT          |
| `dq_oe_n`          | `spi_dq_oe_n_o[7:0]`      | DUT output enable    |
| `rebar_o`          | `spi_mem_rebar_opad_o`    | DUT → flash          |
| `rebar_i`          | `spi_mem_rebar_ipad_i`    | flash → DUT          |

---

### OcahSpiMasterBfm and OcahSpiMasterSequence — controller side

For a bench whose DUT is the flash side, or a harness with no SPI host IP,
the package drives the link itself.  `OcahSpiMasterBfm` is the Mode-0
bit-banging engine (`from_prefix(dut, "spi")` binds `spi_cs_n`, `spi_sclk`,
`spi_mosi`, `spi_miso`); `OcahSpiMasterSequence` is the surface tests call.
A bench whose DUT is an SPI host drives that host and attaches only the
device and the checker.

```python
from ocah_spi_vip import OcahSpiMasterBfm, OcahSpiMasterSequence

host = OcahSpiMasterBfm.from_prefix(dut, "spi", name="host0", half_period_ns=10)
host.init_signals()
seq = OcahSpiMasterSequence(host, checker)
ident = await seq.jedec_id()
await seq.write_enable()
await seq.page_program(0x1000, b"\x12\x34")
data = await seq.read(0x1000, 2)
seq.check_host_responses()        # CHK-SPI-HOST-*: the controller received what the device sent
```

| Operation | Returns | Frame |
|-----------|---------|-------|
| `jedec_id()` | `int` | 0x9F, three response bytes |
| `read_status1()`, `read_status2()` | `int` | 0x05 / 0x35, one response byte |
| `write_enable()`, `write_disable()` | `None` | 0x06 / 0x04 |
| `page_program(addr, data)` | `None` | 0x02, address, payload |
| `sector_erase(addr)` | `None` | 0x20, address |
| `read(addr, n)`, `fast_read(addr, n)` | `bytes` | 0x03 / 0x0B (one dummy byte), address, `n` response bytes |
| `raw_command(opcode, *, addr, dummy_bytes, tx, rx_len)` | `bytes` | Any opcode, for out-of-scope probes |
| `responses(opcode)` | `list[bytes]` | Every response the controller received for that opcode |

---

### OcahSpiMonitor — passive bus observer

```python
from ocah_spi_vip import OcahSpiMonitor

mon = OcahSpiMonitor(
    cs_n = dut.spi_cs_n,
    sclk = dut.spi_sclk,
    mosi = dut.spi_mosi,
    miso = dut.spi_miso,
    name = "spi_mon",
    addr_bytes = 3,
)

mon.add_transaction_callback(lambda txn: print(txn))
await mon.start()
# ... run traffic ...
await mon.stop()

txns  = mon.get_transactions()   # list of plain-int/bytes dicts
stats = mon.get_statistics()
mon.clear_history()
```

Transaction record keys: `opcode`, `addr`, `has_addr`, `data_mosi` (payload
bytes after the address, PAGE PROGRAM only), `data_miso` (response bytes
after the command, address, and dummy phases), `bit_count`, `start_ns`,
`end_ns`.  A command without a response or payload phase carries empty data.

---

### OcahSpiFlashChecker — flash reference model and evidence

```python
from ocah_spi_vip import OcahSpiFlashChecker, OcahSpiOpcode

checker = OcahSpiFlashChecker(
    name="spi_checker",
    flash=flash,                       # expected JEDEC ID, SR2, size, and the array to compare
    required_ids=("CHK-SPI-JEDEC-ID", "CHK-SPI-MEM-GOLDEN"),
)
# ... traffic ...
checker.replay()                                   # device records through the reference model
checker.check_host_responses(OcahSpiOpcode.READ, host_reads)
checker.check_command_order([OcahSpiOpcode.WRITE_ENABLE, OcahSpiOpcode.PAGE_PROGRAM, OcahSpiOpcode.READ])
checker.check_memory(source=image, addr=0x1000)    # device array vs model; model vs the source image
checker.check_nonvacuous()
checker.finalize()                                 # SPI_CHECKER_SUMMARY, CHECKER_SUMMARY; raises on failure
```

`OcahSpiFlashRefModel` rebuilds the array and the write-enable latch from the
commands the device recorded on the wire and never reads the device's array,
so a device that stores or streams the wrong bytes disagrees with it.  The
rules and their identifiers:

| Identifier | Contract |
|------------|----------|
| `CHK-SPI-JEDEC-ID` | READ JEDEC ID streamed the configured identifier |
| `CHK-SPI-STATUS-WEL` | READ STATUS REGISTER 1 reported the latch the model predicts (set after WRITE ENABLE, clear after WRITE DISABLE, consumed by a program or erase) |
| `CHK-SPI-STATUS-SR2` | READ STATUS REGISTER 2 reported the configured register |
| `CHK-SPI-WREN-ORDER` | A program or erase was accepted only with the latch set, and refused (no payload taken) only with it clear |
| `CHK-SPI-READ-DATA` | READ and FAST READ streamed the model's bytes at that address |
| `CHK-SPI-HOST-JEDEC`, `-STATUS`, `-READBACK` | The controller received, frame by frame, what the device sent |
| `CHK-SPI-CMD-ORDER` | The in-scope opcode sequence equals the expected one |
| `CHK-SPI-MEM-GOLDEN` | The device array equals the model over every programmed or erased byte |
| `CHK-SPI-MEM-SOURCE` | The model equals the source image the scenario meant to program |
| `CHK-SPI-NONVAC-PROGRAM` | An accepted program cleared at least one bit |
| `CHK-SPI-NONVAC-READ` | A read returned at least one byte that is not 0xFF |
| `CHK-SPI-NONVAC-ERASE` | An accepted erase returned at least one programmed byte to 0xFF |
| `CHK-SPI-UNSUPPORTED` | The out-of-scope opcodes seen are exactly the expected ones and drew no response or payload |

`finalize()` fails on any failed record, any required identifier never
recorded, or zero records.  With `raise_on_error=True` (the default) the
first failed record raises at once.

---

## Plusargs

The following simulation plusargs are recognised.  They map to environment
variables with the `COCOTB_PLUSARG_` prefix that cocotb sets from `+arg=value`
simulator arguments.

| Plusarg                       | Type     | Default   | Description |
|-------------------------------|----------|-----------|-------------|
| `+spi_flash_jedec_id=<hex>`   | hex int  | none      | Override JEDEC ID (e.g. `+spi_flash_jedec_id=20BA18`) |
| `+spi_flash_preload=<file>`   | path     | none      | Load flash memory from raw binary file before simulation |

Both plusargs apply to instances created after the plusarg is processed.
Multiple flash instances in the same test will all receive the same override
unless `set_jedec_id()` or `preload()` is called individually after
construction.

Example (VCS):

```
+spi_flash_jedec_id=EF4018 +spi_flash_preload=/path/to/firmware.bin
```

---

## Determinism

By default this model is fully deterministic:

- Flash memory initialises to 0xFF (erased state).
- JEDEC ID is the constructor-supplied constant.
- No random delays or random data.

To enable non-deterministic preload sizes or alternate JEDEC IDs, use the
`preload()` and `set_jedec_id()` methods explicitly, or supply plusargs.

---

## Error handling

```python
from ocah_spi_vip import OcahSpiFlashError

try:
    flash.preload("/nonexistent.bin")
except OcahSpiFlashError as exc:
    cocotb.log.error(f"preload failed: {exc}")
```

`OcahSepSpiFlashError` is a subclass of `OcahSpiFlashError`; catching either
works for both flash types.  A failed checker record raises
`ocah_checker.OcahCheckerError`.

---

## Limitations

| Limitation | Note |
|-----|------|
| Quad/octal multi-bit data phase | Single-bit data timing on DQ0 for all modes; no lane turnaround |
| DDR (double data rate) octal | Out of scope |
| Dual/quad-output read opcodes (0x3B, 0x6B) | Out of scope; drained, recorded refused, never credited |
| Block and chip erase, 4-byte address mode entry | Out of scope; drained, recorded refused, never credited |
| 4-byte (32-bit) address mode | Default is 3-byte; set `addr_bytes=4` in the constructor |
| SPI Mode 1/2/3 (CPOL/CPHA variants) | Only Mode 0 (CPOL=0 CPHA=0) |
| Program and erase timing | Instant-ready: the BUSY bit never sets; no vendor timing |
| Vendor commands and registers | None; status register 2 is a constant the bench configures |
| Addresses at or beyond `flash_size` | Read as 0xFF and take no program; a read address wraps at 24 bits, not at the device size |
| SEP-named pad-bundle class | `OcahSepSpiFlash` carries the xSPI pad-bundle binding (chip-select, clock, DQ out/in, DQ output-enable, REBAR) under the SEP name; SMC binds the same class to its lifted SPI pads |
| SV collateral | None: no interface, SVA, coverage model, or SV-UVM realization ships; the package is cocotb only |
| Simulators | Verilator, VCS, and Xcelium run the cocotb `dv/` harness; Verilator runs the SEP and SMC benches |

## Validation

Validate changes on the package's own wire harness first, then against the
DUT consumers:

```bash
python3 tools/dv/run_dv.py --dut ocah_spi_vip --items smoke --tool verilator
python3 tools/dv/run_dv.py --dut ocah_spi_vip --items smoke --tool verilator --regress --reseed 3
python3 tools/dv/run_dv.py --doctor --dut sep
python3 tools/dv/run_dv.py --dut sep --items sep_spi_flash_jedec_smoke_test --tool verilator
python3 tools/dv/run_dv.py --dut sep --items sep_spi_ot_flash_cmd_rand_test --tool verilator
python3 tools/dv/run_dv.py --dut smc --items smc_spi_pad_bfm_test --tool verilator
```

The harness selftests (`ocah_spi_jedec_test`, `ocah_spi_program_readback_test`,
`ocah_spi_erase_test`, `ocah_spi_ordering_test`, `ocah_spi_unsupported_test`)
prove the device, the controller engine, the monitor, and the checker against
each other; each carries an in-band probe that hands a fail-fast checker a
wrong identifier, pattern, order, vacuous erase, or unprotected program and
records that it was rejected (`CHK-SPI-NEG-*`).
`sep_spi_flash_jedec_smoke_test` is the gating SEP regression and needs no
firmware. `sep_spi_ot_flash_cmd_rand_test` runs in the `cpu` mode with its
firmware image, so it needs the RISC-V toolchain described in
`hw/sys/sep/dv/README.md`.

Must-fail checks; each command exits non-zero:

```bash
# harness: the source image handed to the checker is corrupted (CHK-SPI-MEM-SOURCE fails)
OCAH_SPI_SELFTEST_NEGATIVE=1 python3 tools/dv/run_dv.py --dut ocah_spi_vip --items ocah_spi_program_readback_test --tool verilator
# harness: the device programs without WRITE ENABLE (CHK-SPI-WREN-ORDER fails)
OCAH_SPI_SELFTEST_NEGATIVE=1 python3 tools/dv/run_dv.py --dut ocah_spi_vip --items ocah_spi_ordering_test --tool verilator
```

The shared DV maintainers own this package; SEP and SMC own their pad
bindings.

## Hierarchical VIP Layout

This package follows the OCAH hierarchical VIP convention (see
`hw/common/dv/README.md`): all cocotb (Python)
code lives in `cocotb/`, and the root `__init__.py` is a thin shim
re-exporting the stable public API — always import
`from ocah_spi_vip import <Class>`, never from the subfolders.
This package has no `interface/` or `uvm/` realization. The SV-UVM
template and the commercial-VIP plug-in contract (env-level factory
override, user-implemented API wrapper, monitor closing, nested vendor
interface) are documented in `../ocah_jtag_vip/README.md`
("Template Contract") — the reference implementation for all OCAH SV-UVM
VIPs.
