# ocah_spi_vip — OCAH SPI/QSPI/OSPI Flash BFM

SPDX-License-Identifier: Apache-2.0

Stable, OCAH-flavoured Python wrappers for emulating SPI NOR-flash devices
and passively monitoring SPI bus traffic in cocotb testbenches.

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

---

## Supported personalities

| Mode    | Description                                           | Status      |
|---------|-------------------------------------------------------|-------------|
| single  | Standard 1-bit SPI (MOSI/MISO), Mode 0 (CPOL=0/CPHA=0) | Full        |
| quad    | 4-bit data bus (QSPI); command/address still 1-bit   | Partial (see note below) |
| octal   | 8-bit data bus (OSPI/xSPI); SDR only                 | Stub (see note below)    |

**Quad/Octal note:** Command and address bytes are always received in 1-bit
mode.  The data phase uses the same 1-bit engine until a full multi-bit
turnaround implementation is added.  The `OCTAL_TODO` comment in
`ocah_spi_flash.py` marks the code path.  Tests that only need JEDEC ID, page
program, and read on QSPI/OSPI paths will work correctly with the current
implementation.

DDR (Double Data Rate) octal mode is out of scope for this revision.

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

Out of scope: suspend/resume, OTP/security registers, 4-byte addressing
(default is 3-byte / 24-bit), larger erase variants, ECC, SFDP, and all
silicon-specific commands.

---

## Package layout

```
ocah_spi_vip/
  __init__.py                    — exports all public symbols
  cocotb/ocah_spi_flash.py              — OcahSpiFlash (generic SPI/QSPI/OSPI)
  cocotb/ocah_sep_spi_flash.py          — OcahSepSpiFlash (SEP xSPI pin set)
  cocotb/ocah_spi_monitor.py            — OcahSpiMonitor (passive bus observer)
  examples/
    example_jedec_id.py          — annotated JEDEC-ID read snippet
  README.md                      — this file
```

---

## External dependency: cocotbext-spi

This package currently uses a **self-contained cocotb-native implementation**
and does NOT require any external cocotb extension package.

When `cocotbext-spi` (schang412/cocotbext-spi, MIT) is added to the project
Python environment, the internal implementation can delegate to it while
keeping this public API unchanged.  Pin the version as shown below.

### Migration plan

1. Add to `requirements.txt` or `pyproject.toml`:
   ```
   cocotbext-spi==0.1.7    # or later pinned stable release
   ```
2. Replace the `_recv_byte_single` / `_send_byte_single` internals in
   `ocah_spi_flash.py` with calls to `cocotbext_spi.SpiDeviceBus` /
   `SpiDevice` from that package.
3. Verify the public API (`init_signals`, `preload`, `set_jedec_id`,
   `start`, `stop`) remains unchanged — no test changes should be needed.

For quad/octal support, `cocotbext-qspi` and `cocotbext-ospi` candidates are
listed in the SEP shim inventory but their licenses and APIs have not been
confirmed.  Do not add them as hard dependencies until reviewed.

### To check the current environment

```bash
pip show cocotbext-spi
```

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
)
```

| Method                              | Returns | Notes |
|-------------------------------------|---------|-------|
| `flash.init_signals()`              | `None`  | Drive MISO / DQ to idle; call before first clock edge |
| `flash.preload(source)`             | `None`  | Load raw bytes from file path or bytes-like object |
| `flash.set_jedec_id(id)`            | `None`  | Override JEDEC ID at runtime |
| `await flash.start()`               | `None`  | Start background protocol engine |
| `await flash.stop()`                | `None`  | Stop and drain |
| `flash.get_transactions()`          | `list`  | Completed transaction records |
| `flash.clear_transactions()`        | `None`  | Discard history |
| `flash.read_memory(addr, length)`   | `bytes` | Direct memory read (no SPI) |
| `flash.write_memory(addr, data)`    | `None`  | Direct memory write (no SPI) |
| `flash.register_command_callback(opcode, fn)` | `None` | Override or extend command handling |

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

**SEP port mapping** (from `hw/sep/sep_wrapper.sv`):

| This BFM parameter | SEP wrapper port          | Direction (from DUT) |
|--------------------|---------------------------|----------------------|
| `cs_n`             | `spi_cs_n_o`              | DUT → flash          |
| `sclk`             | `spi_clk_o`               | DUT → flash          |
| `dq_out`           | `spi_txd_o[7:0]`          | DUT → flash          |
| `dq_in`            | `spi_rxd_i[7:0]`          | flash → DUT          |
| `dq_oe_n`          | `spi_dq_oe_n_o[7:0]`      | DUT output enable    |
| `rebar_o`          | `spi_mem_rebar_opad_o`    | DUT → flash          |
| `rebar_i`          | `spi_mem_rebar_ipad_i`    | flash → DUT          |

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

Transaction record keys: `opcode`, `addr`, `has_addr`, `data_mosi`,
`data_miso`, `bit_count`, `start_ns`, `end_ns`.

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
works for both flash types.

---

## Known gaps and TODOs

| Gap | Location | Note |
|-----|----------|------|
| Full quad/octal multi-bit data phase | `ocah_spi_flash.py` `OCTAL_TODO` | Single-bit I/O used for all modes |
| DDR (double data rate) octal         | `ocah_sep_spi_flash.py` `DDR_TODO` | Out of scope; needs PHY timing spec |
| 4-byte (32-bit) address mode         | `ocah_spi_flash.py` | Default is 3-byte; set `addr_bytes=4` in constructor |
| Dual-SPI (1-1-2 read)                | not implemented | MOSI returns at read-data phase; out of scope |
| SPI Mode 1/2/3 (CPOL/CPHA variants) | not implemented | Only Mode 0 (CPOL=0 CPHA=0) |
| cocotbext-spi delegation             | README migration plan | Pending package availability in project env |

## Hierarchical VIP Layout

This package follows the OCAH hierarchical VIP convention (see
`hw/common/dv/README.md` and the 1_vip layout guide): all cocotb (Python)
code lives in `cocotb/`, and the root `__init__.py` is a thin shim
re-exporting the stable public API — always import
`from ocah_spi_vip import <Class>`, never from the subfolders.
`interface/` (shared SV interfaces) and `uvm/`
(SV-UVM agent + env) are added as they land for this protocol. The SV-UVM
template and the commercial-VIP plug-in contract (env-level factory
override, user-implemented API wrapper, monitor closing, nested vendor
interface) are documented in `../ocah_jtag_vip/README.md`
("Template Contract") — the reference implementation for all OCAH SV-UVM
VIPs.
