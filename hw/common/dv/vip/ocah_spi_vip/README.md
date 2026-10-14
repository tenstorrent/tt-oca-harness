# ocah_spi_vip — OCAH SPI Flash VIP

SPDX-License-Identifier: Apache-2.0

Stable, OCAH-flavoured Python components for a single-SPI NOR-flash link in
cocotb testbenches: a flash device model, a controller engine for benches
without an SPI host IP, a passive bus monitor, and a checker that rebuilds the
flash array and the write-enable latch from the wire and judges the exchange.

This is a **behavioural model**.  It is not silicon-accurate and is not
affiliated with any flash manufacturer.  No manufacturer or brand names appear
in class or method names.

---

## Purpose

OCAH cocotb tests that exercise SPI-attached flash (SMC SPI peripherals and
the SEP octal-SPI path) need a single, versioned flash device model so that:

1. Tests do not depend on an external flash simulation model.
2. The API is stable across changes to the underlying implementation.
3. The model is deterministic by default (fixed JEDEC ID, preloaded contents).
4. A test's verdict rests on named checker evidence, not on in-leaf asserts.

---

## Supported personalities

| Mode    | Description                                           | Data phase  |
|---------|-------------------------------------------------------|-------------|
| single  | Standard 1-bit SPI (MOSI/MISO), Mode 0 (CPOL=0/CPHA=0) | 1-bit on MOSI/MISO |
| quad    | 4-bit data bus (QSPI); command/address 1-bit         | 1-bit on DQ0 (see note below) |
| octal   | 8-bit data bus (octal SPI); SDR only                 | 1-bit on DQ0 (see note below) |
| quad_io | Four data lanes: `dq_out[3:0]` from the controller, `dq_in[3:0]` to it | 1-bit (lane 0 out, lane 1 in), 2-bit or 4-bit per command (see below) |

**Quad/Octal note:** Command and address bytes are always received in 1-bit
mode, and the data phase uses the same 1-bit engine on DQ0, so the quad and
octal personalities differ from single only in pin binding. JEDEC ID, page
program, and read work on QSPI/OSPI paths under that model.

**quad_io note:** The command byte and every single-lane phase take lane 0 of
`dq_out` and drive lane 1 of `dq_in` (standard SPI on the four-lane pins). The
dual and quad commands below run their address, dummy and data phases at the
widths of their command format. On a dual or quad phase the most significant
bits go first, and the least significant bit of each pair or nibble is on
lane 0 (the order of the SPI host).

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
| 0x3B   | DUAL OUTPUT READ     | In scope, `quad_io` only |
| 0x6B   | QUAD OUTPUT READ     | In scope, `quad_io` only |
| 0xBB   | DUAL I/O READ        | In scope, `quad_io` only |
| 0xEB   | QUAD I/O READ        | In scope, `quad_io` only |
| 0x32   | QUAD PAGE PROGRAM    | In scope, `quad_io` only |

`command_format(opcode)` (`ocah_spi_types.OcahSpiCommandFormat`) gives the
phases after the single-lane command byte of each command with a response or
a payload.  The five lane commands (`LANE_OPCODES`):

| Opcode | Address lanes | Dummy clocks | Data lanes | Data direction |
|--------|---------------|--------------|------------|----------------|
| 0x3B   | 1             | 8            | 2          | Device to controller |
| 0x6B   | 1             | 8            | 4          | Device to controller |
| 0xBB   | 2             | 4            | 2          | Device to controller |
| 0xEB   | 4             | 6            | 4          | Device to controller |
| 0x32   | 1             | 0            | 4          | Controller to device |

The dummy clocks carry no data.  QUAD PAGE PROGRAM
follows the PAGE PROGRAM rules (latch gate, complete address, at least one
complete payload byte).  `lanes_to_bytes(values, lanes)` packs per-clock lane
samples into bytes in the same bit order.  The lane commands need
`mode="quad_io"`: on the other bindings the device refuses them as
`unknown_opcode` and the checker counts them under `unsupported`.

`OcahSpiOpcode` names these fourteen opcodes and `IN_SCOPE_OPCODES` is their
set.  An opcode outside the set is drained by the device to the end of the
frame and recorded with `ok=False`, decoded by the monitor as `UNKNOWN(0xNN)`
with empty data fields, and counted by the checker under `unsupported`, never
credited.  Out of scope: block and chip erase (0xD8, 0xC7), 4-byte address
mode entry (0xB7), suspend/resume, OTP/security registers, ECC, SFDP, and all
silicon-specific commands.

---

## Package layout

```
ocah_spi_vip/
  __init__.py                           — re-exports the cocotb public API
  cocotb/ocah_spi_types.py              — OcahSpiOpcode, SpiMode, command formats, lanes_to_bytes, page/sector geometry, SR1 bits
  cocotb/ocah_spi_flash.py              — OcahSpiFlash (generic SPI/QSPI/OSPI device)
  cocotb/ocah_sep_spi_flash.py          — OcahSepSpiFlash (SEP octal-SPI pin set)
  cocotb/ocah_spi_master_bfm.py         — OcahSpiMasterBfm (controller engine, all four SPI modes)
  cocotb/ocah_spi_master_sequence.py    — OcahSpiMasterSequence (test-facing controller operations)
  cocotb/ocah_spi_monitor.py            — OcahSpiMonitor (passive bus observer and wire checker)
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
    mode     = "single",        # "single" | "quad" | "octal" | "quad_io"
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
| `await flash.stop()`                | `None`  | Stop; the transaction history survives. Raises `OcahSpiFlashError` when the protocol engine raised while it ran |
| `flash.get_transactions()`          | `list`  | Completed frame records (below) |
| `flash.clear_transactions()`        | `None`  | Discard history |
| `flash.read_memory(addr, length)`   | `bytes` | Direct memory read (no SPI) |
| `flash.write_memory(addr, data)`    | `None`  | Direct memory write (no SPI) |
| `flash.register_command_callback(opcode, fn)` | `None` | Override or extend command handling |
| `flash.unregister_command_callback(opcode)` | `None` | Restore the built-in handling |
| `flash.jedec_id`, `.flash_size`, `.addr_bytes`, `.status_reg1`, `.status_reg2`, `.write_enabled` | read-only | The configuration and state a checker predicts against |

Frame record keys: `opcode` (the command byte; -1 when no complete byte
arrived), `addr`, `data_out` (complete bytes the controller sampled from the
device), `data_in` (complete payload bytes the device received), `ok` (the
device accepted the frame), `reason`, `input_clocks` (SCK clocks the device
sampled as controller input: the whole frame for a command without a response
phase, the command, address and dummy phases for one with a response phase),
`input_bits` (the bits those clocks carried; the dummy clocks of a dual or
quad read carry none, and on a single-lane frame the count equals
`input_clocks`), and `tail_bits` (input bits after the last complete input
byte).  Every
chip-select frame gives one record, malformed frames included.

The device takes the whole controller-output frame before it changes the
write-enable latch or memory; a refused frame changes neither:

| `reason` | The frame |
|----------|-----------|
| `""` | Accepted |
| `"partial_opcode"` | Ended 1 to 7 bits into the command byte |
| `"partial_address"` | Ended before the last address bit |
| `"partial_dummy"` | A read with dummy clocks ended before the last one |
| `"wel_clear"` | A program or SECTOR ERASE with the latch clear |
| `"partial_byte"` | A program or a callback frame ended inside a payload byte |
| `"no_payload"` | A program carried no payload byte |
| `"unexpected_payload"` | WRITE ENABLE, WRITE DISABLE or SECTOR ERASE carried a bit after its last command or address bit |
| `"unknown_opcode"` | Command outside the supported set, or a lane command on a binding other than `quad_io` |

WRITE ENABLE and WRITE DISABLE are exactly one command byte; SECTOR ERASE is
one command byte and exactly `addr_bytes` address bytes; PAGE PROGRAM is one
command byte, `addr_bytes` address bytes and at least one complete payload
byte.  A PAGE PROGRAM or SECTOR ERASE with the latch clear is refused as
`wel_clear` whatever its length: the address is decoded when complete, no
payload is taken, and the frame is not graded for its shape.  A registered
callback runs only on a frame with a complete command byte, complete address
and a payload that ends on a byte boundary; PAGE PROGRAM handled by a
callback keeps the latch gate and needs a payload byte.  A read (READ, FAST
READ, the dual and quad reads, JEDEC ID, status) is graded for its command, address and dummy phases
only: once the device drives its response, chip-select may rise at any bit,
and the frame is accepted with the complete bytes sent.
`FRAME_SHAPE_REASONS` names the reasons a frame is refused for its shape.
The device is instant-ready: the BUSY bit never sets and a program or erase
completes when chip-select rises.

---

### OcahSepSpiFlash — SEP octal-SPI pin set

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
the package drives the link itself.  `OcahSpiMasterBfm` is the bit-banging
engine (`from_prefix(dut, "spi")` binds `spi_cs_n`, `spi_sclk`, `spi_mosi`,
`spi_miso`), in Mode 0 unless `cpol`/`cpha` or `set_mode` select another;
`OcahSpiMasterSequence` is the surface tests call.  `bfm.drive(cs_n=, sclk=,
mosi=)` sets pins directly for wire-level stimulus.
With the four-lane handles (`sd_out`, `sd_oe`, `sd_in`, `cs_oe`, `sck_oe`)
the engine drives single-lane frames on lane 0 with output enable 0b0001,
samples lane 1, and holds the chip-select and clock output enables on;
`bfm.lane_frame(segments)` drives one frame of segments on one, two or four
lanes.
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
| `raw_command(opcode, *, addr, dummy_bytes, tx, rx_len, tail_bits)` | `bytes` | Any opcode, for out-of-scope probes; `tail_bits` (0 to 7) ends the frame that many bits into a further byte |
| `raw_frame(bits)` | `list[int]` | One frame of exactly these MOSI bits; it may end in any phase. Returns the MISO bits |
| `bfm.lane_frame(segments)` | `list[bytes]` | Four-lane handles only. One frame of `(lanes, kind, arg)` segments: `lanes` 1, 2 or 4; `kind` `"tx"` (bytes to send), `"rx"` (byte count to receive) or `"dummy"` (clock count). A single-lane segment keeps lane 0 driven; a dual or quad receive or dummy segment drives no lane. Bytes go most significant bits first, the least significant bit of each pair or nibble on lane 0. Returns the bytes of each receive segment |
| `responses(opcode)` | `list[bytes]` | Every response the controller received for that opcode |

---

### OcahSpiMonitor — passive bus observer and wire checker

```python
from ocah_spi_vip import OcahSpiMonitor

mon = OcahSpiMonitor(
    cs_n = dut.spi_cs_n,
    sclk = dut.spi_sclk,
    mosi = dut.spi_mosi,
    miso = dut.spi_miso,
    name = "spi_mon",
    addr_bytes = 3,
    cpol = 0,                    # the SPI mode the controller is programmed to
    cpha = 0,
    # optional four-lane taps:
    # sd_out = dut.spi_sd_o,     # data lanes from the controller
    # sd_oe  = dut.spi_sd_oe_o,  # their output enables (bit n enables lane n)
    # sd_in  = dut.spi_sd_i,     # data lanes to the controller
    # cs_oe  = dut.spi_cs_oe_o,  # chip-select output enable
    # sck_oe = dut.spi_sck_oe_o, # clock output enable
)

mon.add_transaction_callback(lambda txn: print(txn))
await mon.start()
# ... run traffic; mon.set_mode(cpol, cpha) before the controller changes mode ...
await mon.stop()                 # raises OcahSpiMonitorError on a wire-check violation

txns  = mon.get_transactions()   # list of plain-int/bytes dicts
stats = mon.get_statistics()
mon.clear_history()
```

Transaction record keys: `opcode`, `addr`, `has_addr`, `data_mosi` (payload
bytes after the address, PAGE PROGRAM only), `data_miso` (response bytes
after the command, address, and dummy phases), `bit_count`, `input_bits`
(command, address and dummy bits of a single-lane command with a response
phase; `bit_count` otherwise), `input_clocks` (clocks of the command, address
and dummy phases of a command with a response phase at its lane widths;
`bit_count` otherwise), `opcode_complete`, `cpol`, `cpha`, `wire_errors`,
`beats`, `start_ns`, `end_ns`.  A command without a response or payload
phase carries empty data.  `data_mosi` and `data_miso` are the single-lane
decode (lane 0 out, lane 1 in).  With `sd_out`, `beats` holds one
`(lanes out, output enables, lanes in)` tuple per sample edge (`None` for
X/Z), and `lanes_to_bytes` decodes a dual or quad phase from it; with
`sd_out` and no `mosi`/`miso`, the single-lane decode reads lane 0 out and
lane 1 in.

The monitor samples on the sample edge of its mode (the rising SCK edge when
CPOL equals CPHA, the falling edge otherwise) and grades the controller's
pins:

| Check | Contract |
|-------|----------|
| `idle_at_cs_fall` | SCK is at the CPOL level when chip-select falls |
| `idle_at_cs_rise` | SCK is at the CPOL level when chip-select rises |
| `mosi_edge` | While chip-select is low, MOSI does not change on a sample edge, nor after a sample edge and before the next shift edge of the running clock (within 1.5 half periods of the sample edge) |
| `sck_while_idle` | While chip-select is high, SCK moves only to the CPOL level |
| `xz` | Chip-select resolves to 0 or 1 at its edges; SCK and MOSI (with `sd_out`, every driven lane) resolve to 0 or 1 while chip-select is low |
| `oe_idle` | With `sd_oe`: no data lane output enable rises, or is on at an SCK edge, while chip-select is high |
| `oe_lanes` | With `sd_oe`: at each sample edge the data lane output enables are none, lane 0, lanes 1:0 or lanes 3:0 |
| `oe_ctrl` | With `cs_oe`/`sck_oe`: both are on at each sample edge |

With `sd_out`, `mosi_edge` applies to every lane whose output enable is on
before and after a change.

`get_wire_errors()` lists every violation.  `stop()` raises
`OcahSpiMonitorError` after a violation, after a callback raised
`AssertionError`, or after the monitor itself raised; other callback
exceptions are counted in `get_statistics()["callback_errors"]`.

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
| `CHK-SPI-FRAME-BYTES` | A PAGE PROGRAM or QUAD PAGE PROGRAM sent with the latch set carried a complete address and at least one payload byte and ended on a payload byte boundary |
| `CHK-SPI-FRAME-SHAPE` | Every other frame had a complete command byte and the exact length of its command: one byte for WRITE ENABLE and WRITE DISABLE, the command and address bytes for SECTOR ERASE with the latch set, complete command, address and dummy phases for a read at its lane widths; an accepted frame's `input_clocks` equals that length in clocks |
| `CHK-SPI-LEDGER` | `check_ledger(monitor_frames)`: the device recorded every frame the monitor saw, in order, with the same command byte and input clock count |
| `CHK-SPI-READ-DATA` | A read (READ, FAST READ, or a dual or quad read) streamed the model's bytes at that address |
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

Example:

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
`ocah_checker.OcahCheckerError`.  An exception inside the flash protocol
engine is logged and kept, and `flash.stop()` raises it as the cause of an
`OcahSpiFlashError`; `OcahSpiMonitor.stop()` raises `OcahSpiMonitorError` in
the same way.

---

## Limitations

| Limitation | Note |
|-----|------|
| Multi-bit data phase | Dual and quad phases only with `mode="quad_io"`; `quad` and `octal` run single-bit data timing on DQ0; no octal lanes |
| Lane turnaround | Not modeled: the device drives `dq_in` and the controller drives `dq_out` on separate buses; the monitor grades the output-enable patterns |
| DDR (double data rate) octal | Out of scope |
| Block and chip erase, 4-byte address mode entry | Out of scope; drained, recorded refused, never credited |
| 4-byte (32-bit) address mode | Default is 3-byte; set `addr_bytes=4` in the constructor |
| SPI Mode 1/2/3 (CPOL/CPHA variants) | The flash device answers Mode 0 only; the monitor and the controller engine run all four modes |
| Wire timing | The monitor grades edge order, not setup, hold or clock-period values |
| Program and erase timing | Instant-ready: the BUSY bit never sets; no device-specific timing |
| Device-specific commands and registers | None; status register 2 is a constant the bench configures |
| Addresses at or beyond `flash_size` | Read as 0xFF and take no program; a read address wraps at 24 bits, not at the device size |
| SEP-named pad-bundle class | `OcahSepSpiFlash` carries the octal-SPI pad-bundle binding (chip-select, clock, DQ out/in, DQ output-enable, REBAR) under the SEP name; SMC binds the same class to its lifted SPI pads |
| SV collateral | None: no interface, SVA, coverage model, or SV-UVM realization ships; the package is cocotb only |
| Simulators | Verilator and the optional backends reported by `run_dv.py --list` |

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
`ocah_spi_erase_test`, `ocah_spi_ordering_test`, `ocah_spi_unsupported_test`,
`ocah_spi_partial_byte_test`, `ocah_spi_frame_shape_test`,
`ocah_spi_wire_check_test`, `ocah_spi_lanes_test`)
prove the device, the controller engine, the monitor, and the checker against
each other. `ocah_spi_jedec_test`, `ocah_spi_program_readback_test`,
`ocah_spi_erase_test`, `ocah_spi_ordering_test`, `ocah_spi_partial_byte_test`
and `ocah_spi_frame_shape_test` carry an in-band probe that hands a fail-fast checker a
wrong identifier, pattern, order, vacuous erase, unprotected program, or
malformed frame and records that it was rejected (`CHK-SPI-NEG-*`). The wire
and lane selftests drive each violation they grade on the pins and require
exactly that violation.
`ocah_spi_lanes_test` programs and reads a page through every lane command on
the four-lane link, compares the controller, the device record and the
monitor's lane decode, refuses lane phases cut short, and drives each
output-enable violation once.
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
template and the optional-backend plug-in contract (env-level factory
override, user-implemented API wrapper, monitor closing, nested vendor
interface) are documented in `../ocah_jtag_vip/README.md`
("Template Contract") — the reference implementation for all OCAH SV-UVM
VIPs.
