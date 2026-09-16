# ocah_uart_vip — OCAH UART VIP

SPDX-License-Identifier: Apache-2.0

Stable, OCAH-flavoured Python components for an asynchronous serial (UART)
link in cocotb testbenches: a console host, the line driver and frame sampler
behind it, a passive two-line tap, and a checker that judges driven frames
against sampled frames and records `CHK-UART-*` evidence. The primary use is
a firmware-visible console (8-N-1, configurable baud rate); the engines model
5..9 data bits, none, even, or odd parity, and 1, 1.5, or 2 stop bits.

---

## Purpose

OCAH cocotb tests need a single, versioned API for UART console interactions so
that:

1. Tests do not break when the underlying implementation is updated.
2. New test authors have one place to look for UART-access primitives.
3. A test's verdict rests on named checker evidence, not on in-leaf asserts.

---

## Backend

The backend is native to this package; no external UART library is involved:

- `OcahUartMasterDriver` (`ocah_uart_master_driver.py`): active line driver.
  The console host is the master side: it initiates traffic into the DUT's
  receive pad. It also injects faults (bad stop bit, inverted parity, break,
  glitch) at a deterministic place in the byte stream.
- `OcahUartLineMonitor` (`ocah_uart_monitor.py`): passive frame sampler over
  one line. Side-neutral: a UART line is a symmetric point-to-point wire and
  the sampler reconstructs whatever traffic appears on it, VIP-driven or
  DUT-driven, classifying every frame.

`OcahUartImportError` is exported but never raised by the native backend.

---

## Package Layout

```text
ocah_uart_vip/
  __init__.py                          — re-exports the cocotb public API
  cocotb/ocah_uart_types.py            — OcahUartFrame, OcahUartParity, timing helpers
  cocotb/ocah_uart_console.py          — OcahUartConsole (active host)
  cocotb/ocah_uart_master_driver.py    — OcahUartMasterDriver (line driver, fault injection)
  cocotb/ocah_uart_monitor.py          — OcahUartLineMonitor (frame sampler),
                                         OcahUartMonitor (passive two-line tap)
  cocotb/ocah_uart_checker.py          — OcahUartChecker (CHK-UART-* evidence)
  cocotb/examples/
    example_loopback.py                — annotated usage snippets
  dv/                                  — `--dut ocah_uart_vip` wire-harness selftests
```

---

## Frame Format and Timing

A frame is one start bit (low), `bits` data bits LSB first, an optional parity
bit, and `stop_bits` periods at the idle level (high). The bit period is
`round(1e9 / baud)` ns on both sides; the sampler resynchronizes on every
start edge and samples each bit at its centre, so the rounding error never
accumulates. Any positive integer baud rate is accepted; a rate at or above
1 Mbaud depends on the DUT clock and the simulation time resolution.

The sampler classifies every frame it reconstructs (`OcahUartFrame`):

| Observation | Classification |
|---|---|
| Stop bit sampled high, parity agrees | clean frame |
| Stop bit sampled low, data or parity not all low | `framing_error` |
| Stop bit low, data bits and parity bit all low | `is_break` (and `framing_error`); the sampler waits for the line to return high before resynchronizing |
| Parity bit disagrees with the data | `parity_error` |
| Any data bit unresolvable (X or Z, four-state simulators) | `framing_error` |
| Line back high by the centre of the start bit | glitch: counted, no frame |

Each frame carries the simulation time of its start edge and of the first
rising edge after it, so `OcahUartFrame.measured_bit_ns` gives the wire's
bit period for any frame whose data is not zero.

---

## Plusargs

All plusargs are optional. They are read from the cocotb `COCOTB_PLUSARG_*`
environment variable convention.

| Plusarg | Type | Default | Description |
|---|---|---|---|
| `+uart_baud=<N>` | int | 115200 | Override the baud rate of every `OcahUartConsole` constructed afterwards |
| `+uart_log=<file>` | string | (disabled) | Append every received line to this file (UTF-8) |

---

## Public API Reference

### OcahUartConsole — active UART host

```python
from ocah_uart_vip import OcahUartConsole, OcahUartParity

console = OcahUartConsole(
    dut.uart_rx,            # line the console drives (the DUT's receive line)
    dut.uart_tx,            # line the console samples (the DUT's transmit line)
    dut.clk,                # accepted for call-site symmetry; frames are timed from the baud rate
    name="smc_console",
    baud=115200,
    bits=8,                 # 5..9
    parity=OcahUartParity.NONE,
    stop_bits=1,            # 1, 1.5, or 2
    timeout_us=1000,        # default per-operation timeout
    log_file=None,
    raise_on_timeout=True,
    raise_on_frame_error=False,
)
console = OcahUartConsole.from_prefix(dut, "uart", baud=115200)   # binds uart_rx / uart_tx
```

| Method | Returns | Notes |
|---|---|---|
| `console.init_signals()` | `None` | Logs the format; the driver holds the line at idle from construction |
| `await console.set_baud(rate)` | `None` | Both directions; no frame may be in flight |
| `console.configure(bits=, parity=, stop_bits=)` | `None` | Both directions; lands on the next frame |
| `await console.send_byte(b)`, `send_bytes(data)`, `send_string(s, encoding="ascii")` | `None` | Queue frames; return once queued |
| `await console.flush()` | `None` | Wait until every queued frame has left the wire |
| `await console.send_framing_error(b)`, `send_parity_error(b)`, `send_break(periods=None)`, `send_glitch(width_ns)` | `None` | Fault injection toward the DUT, in stream order |
| `await console.read_byte(timeout_us=None)` | `int \| None` | Next received value |
| `await console.read_frame(timeout_us=None)` | `OcahUartFrame \| None` | Next received frame with its flags |
| `await console.read_bytes(n, timeout_us=None)` | `bytes \| None` | Exactly `n` values, each awaited under `timeout_us` |
| `await console.read_line(timeout_us=None, encoding="ascii")` | `str \| None` | Values up to a newline, which is stripped |
| `await console.expect(pattern, timeout_us=None, encoding="ascii")` | `str` | Lines until one matches the regular expression; raises on timeout |
| `console.tx_frames()`, `console.rx_frames()` | `list[OcahUartFrame]` | Driven and sampled frame histories |
| `console.source`, `console.sink` | engines | The line driver and the sampler |
| `console.raise_on_timeout`, `console.raise_on_frame_error` | `bool` | Public attributes, changeable between operations |
| `console.get_statistics()`, `console.reset_statistics()` | `dict` | Cumulative counters |

A timed-out `read_bytes` or `read_line` leaves the frames it had taken
readable by the next read. A frame with a framing, parity, or break flag is
delivered as data and counted under `frame_errors`, or raised as
`OcahUartError` when `raise_on_frame_error` is set; either way it is
consumed.

Statistics keys: `bytes_sent`, `bytes_received`, `lines_received`,
`timeouts`, `frame_errors`.

---

### OcahUartMasterDriver — line driver (console TX engine)

```python
from ocah_uart_vip import OcahUartMasterDriver

tx = OcahUartMasterDriver(dut.uart_rx, name="host_tx", baud=115200, bits=8, parity="even", stop_bits=1)
await tx.write(b"\x55\xaa")
await tx.inject_framing_error(0x3C)
await tx.send_break()
await tx.wait()
frames = tx.get_frames()
```

| Method | Notes |
|---|---|
| `baud`, `bits`, `parity`, `stop_bits`, `bit_ns` | Properties; the first four reassignable between frames, `configure(...)` sets several at once |
| `await write(data)`, `write_nowait(data)` | Queue frame values (each below `2**bits`) |
| `await inject_framing_error(data)` | Frame whose stop bit is low, then one idle period |
| `await inject_parity_error(data)` | Frame whose parity bit is inverted; needs a parity format |
| `await send_break(periods=None)` | Line low for `periods` bit periods (default one frame plus one), then one idle period |
| `await send_glitch(width_ns)` | Low pulse shorter than half a bit, then one idle period |
| `await wait()`, `count()`, `empty()`, `idle()`, `clear()` | Queue control |
| `get_frames()`, `clear_history()` | Bounded history of driven frames with their start times (glitches excluded) |
| `get_statistics()` | `bytes_driven`, `framing_faults`, `parity_faults`, `breaks`, `glitches` |

---

### OcahUartLineMonitor — frame sampler (console RX engine)

```python
from ocah_uart_vip import OcahUartLineMonitor

rx = OcahUartLineMonitor(dut.uart_tx, name="dut_tx", baud=115200)
frame = await rx.read_frame()
data = await rx.read(4)
```

| Method | Notes |
|---|---|
| `baud`, `bits`, `parity`, `stop_bits`, `bit_ns`, `configure(...)` | As the driver; a change lands on the next start edge |
| `start()`, `stop()`, `running` | Sampling runs from construction unless `autostart=False` |
| `await read_frame()`, `await read_frames(n)`, `read_frames_nowait(n=-1)` | Frame queue |
| `await read(n=-1)`, `read_nowait(n=-1)` | The same queue as bytes (a 9-bit value truncated to its low byte) |
| `await wait(timeout=0, timeout_unit="ns")`, `count()`, `empty()`, `clear()` | Queue control |
| `add_frame_callback(fn)` | `fn(frame)` for every reconstructed frame; an exception is logged and counted |
| `get_frames()`, `clear_history()`, `initial_level` | Bounded history independent of the queue; the level seen at the first sample |
| `get_statistics()` | `bytes_sampled`, `framing_errors`, `parity_errors`, `breaks`, `glitches`, `callback_errors` |

---

### OcahUartMonitor — passive two-line tap

```python
from ocah_uart_vip import OcahUartMonitor

monitor = OcahUartMonitor(dut.uart_rx, dut.uart_tx, dut.clk, name="uart_mon", baud=115200)
monitor.add_tx_callback(lambda b: print(f"TX: 0x{b:02X}"))
monitor.add_rx_frame_callback(lambda frame: print(frame.to_record()))
await monitor.start()
# ... run traffic ...
await monitor.stop()
tx_frames = monitor.get_tx_frames()
```

`txd` is the line the console host drives and `rxd` the line it samples.
Methods: `add_tx_callback`, `add_rx_callback`, `add_tx_frame_callback`,
`add_rx_frame_callback`, `await start()`, `await stop()`, `configure(...)`,
`get_tx_bytes()`, `get_rx_bytes()`, `get_tx_frames()`, `get_rx_frames()`,
`clear_history()`, `get_statistics()` (`tx_bytes_observed`,
`rx_bytes_observed`, `tx_frame_errors`, `rx_frame_errors`, `callback_errors`).

---

### OcahUartFrame and OcahUartParity

`OcahUartFrame` is a frozen dataclass: `data`, `bits`, `parity`, `stop_bits`,
`framing_error`, `parity_error`, `is_break`, `start_ns`, `end_ns`,
`first_rise_ns`, `line`, with the properties `clean`, `flags`, and
`measured_bit_ns` and the plain-value view `to_record()`.
`OcahUartParity` is `NONE`, `EVEN`, or `ODD`; every constructor also accepts
the member name or value as a string. `bit_period_ns(baud)`,
`frame_periods(bits, parity, stop_bits)`, and `parity_bit(data, bits, parity)`
are the shared timing helpers.

---

### OcahUartChecker — frame evidence

```python
from ocah_uart_vip import OcahUartChecker

checker = OcahUartChecker(name="uart_checker", required_ids=("CHK-UART-DATA", "CHK-UART-CLEAN"))
checker.check_line(sent_values, console.rx_frames(), baud=115200, label="dut_tx")
checker.check_classification(console.rx_frames(), console.source.get_frames(), label="loop")
checker.check_timeout(timed_out=True, elapsed_ns=elapsed, timeout_us=500, label="read_byte")
checker.finalize()                          # UART_CHECKER_SUMMARY, CHECKER_SUMMARY; raises on failure
```

The checker holds no simulator handles: it takes frame sequences, plain
integers, and statistics mappings, so it judges VIP-to-VIP traffic on the
selftest harness and DUT traffic on a bench alike. The rules and their
identifiers:

| Identifier | Method | Contract |
|---|---|---|
| `CHK-UART-DATA` | `check_data`, `check_line` | The values sampled on a line equal, in order, the values sent |
| `CHK-UART-CLEAN` | `check_clean`, `check_line` | No sampled frame carries a framing, parity, or break flag |
| `CHK-UART-BAUD` | `check_baud`, `check_line` | The wire bit period measured from the start edge to the first rising edge equals `round(1e9 / baud)` ns on every measurable frame |
| `CHK-UART-NONVAC` | `check_nonvacuous`, `check_line` | At least the required number of frames arrived and one carries both 0 and 1 data bits |
| `CHK-UART-IDLE-HIGH` | `check_idle_high` | The line rested at the idle level when sampling began |
| `CHK-UART-CLASSIFY` | `check_classification` | The per-frame `(data, framing, parity, break)` sequence equals the injected one |
| `CHK-UART-FRAMING-ERROR`, `-PARITY-ERROR`, `-BREAK` | `check_classification` | The sampler flagged exactly the injected faults of each kind present |
| `CHK-UART-GLITCH` | `check_glitches` | Sub-half-bit pulses were counted and produced no frame |
| `CHK-UART-ERROR-COUNT` | `check_error_counts` | The sampler's error counters equal the injected fault counts |
| `CHK-UART-BAUD-DETECT` | `check_baud_mismatch` | A sampler at the wrong rate does not deliver the sent values as clean frames |
| `CHK-UART-TIMEOUT`, `CHK-UART-TIMEOUT-BOUND` | `check_timeout` | A read on a silent line reported its timeout, and took exactly the declared time |
| `CHK-UART-NO-TIMEOUT` | `check_completed` | A read with data present completed under its bound |
| `CHK-UART-STATS` | `check_statistics` | Observed counters equal the expected ones |

`expect_equal()` and `expect_true()` add named exact-value evidence.
`finalize()` fails on any failed record, any required identifier never
recorded, or zero records. With `raise_on_error=True` (the default) the first
failed record raises at once. A failed record raises
`ocah_checker.OcahCheckerError`.

---

## Error Handling

```python
from ocah_uart_vip import OcahUartError
```

| Exception | When raised |
|---|---|
| `OcahUartError` | A read timed out (`raise_on_timeout`), or a received frame carries a flag (`raise_on_frame_error`) |
| `ValueError` | A frame value, baud rate, format, break length, or glitch width outside the contract |
| `OcahUartImportError` | never raised by the native backend |

To receive `None` on a timeout instead of raising:

```python
console = OcahUartConsole(..., raise_on_timeout=False)
line = await console.read_line(timeout_us=1000)
if line is None:
    cocotb.log.warning("no line received in time")
```

---

## Determinism

- The bit period is a fixed integer; no jitter, no random delays, no random
  data in the package.
- A read on a silent line ends exactly `timeout_us` microseconds of
  simulation time after it started.
- Faults land at the queued position in the byte stream.

To stress framing or timing, drive the DUT-side clock or a non-standard baud
rate from the test; the package adds no randomness of its own.

---

## Examples

See `cocotb/examples/example_loopback.py` for four annotated examples: a
console loopback judged by the checker, pattern matching with `expect()`, a
passive tap beside the console, and a mid-test baud change.

## Supported behavior and limitations

| Area | This package provides | Outside this package |
|---|---|---|
| Frame format | 5..9 data bits, none/even/odd parity, 1, 1.5, or 2 stop bits, idle-high, LSB first | Mark/space (sticky) parity; a 9-bit value above 255 truncates to its low byte in `bytes` results |
| Timing | `round(1e9 / baud)` ns per bit; resynchronization on every start edge; centre sampling | Fractional bit periods below 1 ns; DUT clock-to-baud tolerance modeling |
| Stop bits | The idle level is judged at the centre of the first stop bit | Judging the second stop bit or a 1.5-bit stop length on the wire |
| Faults | Bad stop bit, inverted parity, break (a whole number of bit periods, one frame plus one by default), sub-half-bit glitch, each classified by the sampler | Noise or jitter models; a break shorter than one frame time is sampled as a character |
| Flow control | — | RTS/CTS, DTR/DSR, XON/XOFF |
| Timeout | Per-operation `timeout_us`, exact in simulation time, raising or returning `None`; taken frames stay readable | — |
| Errors and evidence | `OcahUartChecker` (`CHK-UART-*`); `finalize()` fails on a failed check, zero checks, or a missing required ID; every harness selftest carries an in-band negative probe, and `OCAH_UART_SELFTEST_NEGATIVE` forces a failing run | Register-level checks of a DUT's UART (line status, FIFO levels) stay in the DUT tree |
| Protocol checking | The sampler's classification and the checker's frame rules; X on a data bit is a framing error on four-state simulators | SVA collateral: none ships |
| Coverage | Rule coverage through the `CHK-UART-*` identifiers of the harness selftests | Covergroups: no SV coverage model ships |
| Simulators | Verilator, VCS, and Xcelium (the `dv/` harness); Verilator (the SMC bench) | — |
| SV collateral | None: no interface, SVA, coverage model, or SV-UVM realization ships; the package is cocotb only | — |

## Validation

Validate changes on the package's own wire harness first, then against the
SMC consumer:

```bash
python3 tools/dv/run_dv.py --dut ocah_uart_vip --items smoke --tool verilator
python3 tools/dv/run_dv.py --dut ocah_uart_vip --items smoke --tool verilator --regress --reseed 3
python3 tools/dv/run_dv.py --doctor --dut smc
python3 tools/dv/run_dv.py --dut smc --items smc_uart_loopback_test --tool verilator
```

The harness selftests (`ocah_uart_data_test`, `ocah_uart_format_test`,
`ocah_uart_error_test`, `ocah_uart_timeout_test`) prove the console, the
line engines, the tap, and the checker against each other on two bare nets:
full-duplex data with wire-measured bit periods, a seeded sweep of frame
formats and standard baud rates plus a mismatched-rate sampler, fault
classification and the raising read mode, and exact timeouts without data
loss. Each carries an in-band probe that hands a fail-fast checker a wrong
expectation and records that it was rejected (`CHK-UART-NEG-*`).
`smc_uart_loopback_test` is the gating SMC regression: it programs UART0
through its CSRs and captures the DUT's transmit byte with the console.

Must-fail checks; each command exits non-zero:

```bash
# harness: the expected host-to-device burst is corrupted (CHK-UART-DATA fails)
OCAH_UART_SELFTEST_NEGATIVE=1 python3 tools/dv/run_dv.py --dut ocah_uart_vip --items ocah_uart_data_test --tool verilator
# harness: a clean frame is claimed as a break (CHK-UART-CLASSIFY fails)
OCAH_UART_SELFTEST_NEGATIVE=1 python3 tools/dv/run_dv.py --dut ocah_uart_vip --items ocah_uart_error_test --tool verilator
# harness: the declared timeout bound is one microsecond short (CHK-UART-TIMEOUT-BOUND fails)
OCAH_UART_SELFTEST_NEGATIVE=1 python3 tools/dv/run_dv.py --dut ocah_uart_vip --items ocah_uart_timeout_test --tool verilator
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
