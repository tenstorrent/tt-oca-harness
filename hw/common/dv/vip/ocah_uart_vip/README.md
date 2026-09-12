# ocah_uart_vip — OCAH UART Console Wrapper

SPDX-License-Identifier: Apache-2.0

Stable, OCAH-flavored Python wrappers for driving and monitoring UART serial
traffic in cocotb testbenches.  The primary use-case is the SMC
firmware-visible console (8N1, configurable baud rate).

---

## Purpose

OCAH cocotb tests need a single, versioned API for UART console interactions so
that:

1. Tests do not break when the underlying VIP is updated.
2. New test authors have one place to look for UART-access primitives.
3. Backend changes are absorbed at the wrapper boundary, not scattered
   across test files.

---

## Backend

The backend is native to this package — no external UART library:

- `OcahUartMasterDriver` (`ocah_uart_master_driver.py`) — active host-side
  8-N-1 line driver.  The console host is the master side: it initiates
  traffic into the DUT's RX pad.
- `OcahUartLineMonitor` (`ocah_uart_monitor.py`) — passive wire-level 8-N-1
  byte sampler over one line.  Side-neutral: a UART line is a symmetric
  point-to-point wire and the sampler reconstructs whatever traffic appears
  on it (VIP-driven or DUT-driven).

`OcahUartImportError` is exported but never raised by the native backend.

---

## Package Layout

```
ocah_uart_vip/
  __init__.py                          — re-exports the cocotb public API
  cocotb/ocah_uart_console.py          — OcahUartConsole (active host)
  cocotb/ocah_uart_master_driver.py    — OcahUartMasterDriver (native TX engine)
  cocotb/ocah_uart_monitor.py          — OcahUartLineMonitor (native RX engine),
                                         OcahUartMonitor (passive tap)
  cocotb/examples/
    example_loopback.py                — annotated usage snippets
```

---

## Protocol

- **Format**: Standard 8N1 — 8 data bits, no parity, 1 stop bit.
- **Baud rate**: Configurable; default 115200.  Any positive integer is
  accepted; the bit period is `round(1e9 / baud)` ns, so rates at or above
  1 Mbaud depend on the DUT clock and the simulation time resolution, which
  are the caller's responsibility.

---

## Plusargs

All plusargs are optional.  They are read from the cocotb `COCOTB_PLUSARG_*`
environment variable convention.

| Plusarg           | Type   | Default       | Description                                         |
|---|---|---|---|
| `+uart_baud=<N>`  | int    | 115200        | Override baud rate for all `OcahUartConsole` instances constructed without an explicit `baud` argument. |
| `+uart_log=<file>`| string | (disabled)    | Append every received line to this file.  Created or appended in UTF-8 mode. |

Read them in your testbench runner or Makefile:

```
SIM_ARGS += +uart_baud=115200
SIM_ARGS += +uart_log=/tmp/smc_uart.log
```

Or set the environment variables directly:

```bash
export COCOTB_PLUSARG_uart_baud=115200
export COCOTB_PLUSARG_uart_log=/tmp/smc_uart.log
```

---

## Public API Reference

### OcahUartConsole — active UART host

```python
from ocah_uart_vip import OcahUartConsole

console = OcahUartConsole(
    dut.uart_txd,       # TX signal handle (console drives this)
    dut.uart_rxd,       # RX signal handle (console reads this)
    dut.clk,            # clock handle
    name="smc_console", # used in log messages
    baud=115200,        # initial baud rate
    timeout_us=1000,    # default per-byte timeout in µs
    log_file=None,      # optional console log path
    raise_on_timeout=True,
)
```

| Method | Returns | Notes |
|---|---|---|
| `console.init_signals()` | `None` | Drive TXD to idle (MARK=1); call before first clock edge |
| `await console.set_baud(rate)` | `None` | Reconfigure baud rate; no transaction must be in progress |
| `await console.send_byte(b)` | `None` | Send one byte (0–255) |
| `await console.send_bytes(data)` | `None` | Send ``bytes``, ``bytearray``, or ``list[int]`` |
| `await console.send_string(s, encoding="ascii")` | `None` | Encode and send string |
| `await console.read_byte(timeout_us=None)` | `int \| None` | Next received byte |
| `await console.read_bytes(n, timeout_us=None)` | `bytes \| None` | Exactly ``n`` bytes |
| `await console.read_line(timeout_us=None, encoding="ascii")` | `str \| None` | Read until `\n`; returns line without newline |
| `await console.expect(pattern, timeout_us=None, encoding="ascii")` | `str` | Read lines until one matches regex; raises `OcahUartError` on timeout |
| `console.get_statistics()` | `dict` | Cumulative counters |
| `console.reset_statistics()` | `None` | Zero all counters |

#### Statistics dict keys

| Key | Description |
|---|---|
| `bytes_sent` | Total bytes transmitted |
| `bytes_received` | Total bytes received |
| `lines_received` | Lines returned by `read_line` / `expect` |
| `timeouts` | Times a read operation hit the timeout |

---

### OcahUartMonitor — passive tap

```python
from ocah_uart_vip import OcahUartMonitor

monitor = OcahUartMonitor(
    dut.uart_txd,
    dut.uart_rxd,
    dut.clk,
    name="uart_mon",
    baud=115200,
    max_history=4096,
)

monitor.add_tx_callback(lambda b: print(f"TX: 0x{b:02X}"))
monitor.add_rx_callback(lambda b: print(f"RX: 0x{b:02X}"))
await monitor.start()

# ... run traffic ...

await monitor.stop()

tx_bytes = monitor.get_tx_bytes()   # list[int]
rx_bytes = monitor.get_rx_bytes()   # list[int]
stats    = monitor.get_statistics() # dict
```

| Method | Returns | Notes |
|---|---|---|
| `monitor.add_tx_callback(fn)` | `None` | `fn(byte: int) -> None` |
| `monitor.add_rx_callback(fn)` | `None` | `fn(byte: int) -> None` |
| `await monitor.start()` | `None` | Start passive observation |
| `await monitor.stop()` | `None` | Stop; buffered bytes retained |
| `monitor.get_tx_bytes()` | `list[int]` | TX history (oldest first) |
| `monitor.get_rx_bytes()` | `list[int]` | RX history (oldest first) |
| `monitor.clear_history()` | `None` | Discard all retained bytes |
| `monitor.get_statistics()` | `dict` | `tx_bytes_observed`, `rx_bytes_observed` |

---

## Error Handling

```python
from ocah_uart_vip import OcahUartError, OcahUartImportError
```

| Exception | When raised |
|---|---|
| `OcahUartError` | Timeout, framing error, or unexpected data |
| `OcahUartImportError` | never raised by the native backend |

To receive `None` on timeout instead of raising:

```python
console = OcahUartConsole(..., raise_on_timeout=False)
line = await console.read_line(timeout_us=1000)
if line is None:
    cocotb.log.warning("no line received in time")
```

---

## Determinism

By default the wrapper is deterministic:

- Baud rate is a fixed integer; no jitter.
- No random delays or random data generation.
- The line engines drive and sample bits at exact baud-period boundaries,
  resynchronising on every start-bit edge.

To stress-test framing or timing, adjust the DUT-side clock or use a
non-standard baud rate; do not add randomness in the wrapper layer.

---

## Examples

See `cocotb/examples/example_loopback.py` for four annotated examples:

1. Basic loopback (send string, read back).
2. Pattern matching with `expect()`.
3. Passive monitoring with `OcahUartMonitor` alongside a console driver.
4. Mid-test baud-rate reconfiguration.

## Limitations

| Limitation | Note |
|---|---|
| Frame format | `OcahUartConsole` is 8-N-1 only. The line engines accept `bits` and `stop_bits` (1, 1.5, or 2) but model no parity bit |
| Flow control | No RTS/CTS or XON/XOFF modeling |
| Break | A break condition is neither generated nor classified; a low stop bit counts as a framing error |
| Checker evidence | The package emits no `CHK-*` evidence; the owning test compares console bytes and emits its own evidence |
| High baud rates | The bit period is `round(1e9 / baud)` ns, so rates at or above 1 Mbaud depend on the DUT clock and the simulation time resolution |
| Maturity | Experimental: SMC `smc_uart_loopback_test` is the consumer. Promotion requires `CHK-*` evidence in that test and a timeout/no-data negative case |

## Validation

Validate changes against the SMC consumer:

```bash
python3 tools/dv/run_dv.py --doctor --dut smc
python3 tools/dv/run_dv.py --dut smc --items smc_uart_loopback_test --tool verilator
```

The shared DV maintainers own this package; SMC owns the pad binding in
`hw/sys/smc/dv/cocotb/seq_lib/smc_uart_protocol_vip.py`.

## Hierarchical VIP Layout

This package follows the OCAH hierarchical VIP convention (see
`hw/common/dv/README.md`): all cocotb (Python)
code lives in `cocotb/`, and the root `__init__.py` is a thin shim
re-exporting the stable public API — always import
`from ocah_uart_vip import <Class>`, never from the subfolders.
This package has no `interface/` or `uvm/` realization. The SV-UVM
template and the commercial-VIP plug-in contract (env-level factory
override, user-implemented API wrapper, monitor closing, nested vendor
interface) are documented in `../ocah_jtag_vip/README.md`
("Template Contract") — the reference implementation for all OCAH SV-UVM
VIPs.
