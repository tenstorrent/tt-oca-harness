# ocah_i3c_vip — OCAH I3C Bus BFM Wrapper

SPDX-License-Identifier: Apache-2.0

Stable, OCAH-flavored Python wrappers for driving and monitoring I3C bus
traffic in cocotb testbenches.  Built on top of
[antmicro/cocotbext-i3c](https://github.com/antmicro/cocotbext-i3c)
(Apache-2.0).

---

## Purpose

OCAH tests that touch the SMC I3C interface need a stable, versioned Python
API for bus-controller and bus-target operations.  This package provides that
API so that:

1. Tests do not break when `cocotbext-i3c` is updated upstream.
2. New test authors have one place to find I3C bus-access primitives.
3. No `cocotbext_i3c` types leak into test files — all arguments and return
   values are plain Python `int` or `bytes`.

This package is the Task #15 counterpart to `ocah_axi_vip` (Task #14) and
is how cocotb tests drive I3C activity against the SMC I3C stub (Task #6 RTL
shim).

---

## Pinned Dependency

| Package | Version | License | Location |
|---|---|---|---|
| `cocotbext-i3c` | **1.1.0** | Apache-2.0 | `vendor/chipsalliance/i3c-core/upstream/third_party/cocotbext-i3c/` |

The local copy is used by default.  To make it importable, add it to
`PYTHONPATH`:

```bash
export PYTHONPATH=$PYTHONPATH:<repo>/vendor/chipsalliance/i3c-core/upstream/third_party/cocotbext-i3c/src
```

Or install it from the checked-in source:

```bash
pip install <repo>/vendor/chipsalliance/i3c-core/upstream/third_party/cocotbext-i3c/
```

If `cocotbext_i3c` is not importable, `OcahI3cBus` and `OcahI3cTarget` raise
`OcahI3cImportError` at construction time with the above instructions.

To check what is installed:

```bash
pip show cocotbext-i3c
```

---

## Scope

This wrapper covers **SDR (Single Data Rate)** mode only.

| Feature | Supported |
|---|---|
| SDR private write | Yes |
| SDR private read | Yes |
| CCC RSTDAA (0x06) broadcast | Yes |
| CCC ENTDAA (0x07) broadcast | Yes (via helper) |
| CCC SETDASA (0x87) directed | Yes |
| CCC GETSTATUS (0x90) directed | Yes |
| CCC GETPID (0x8D) directed | Yes |
| IBI listen (controller ACK) | Yes |
| IBI initiation (target) | Partial — see notes |
| HDR-DDR | Out of scope |
| HDR-BT | Out of scope |
| Legacy I2C transfer mode | Out of scope |

---

## When to use this wrapper

| Scenario | Recommended class |
|---|---|
| DUT is an I3C target stub (Task #6) and test drives bus | `OcahI3cBus` |
| DUT is an I3C controller (SMC cdni3c) and test emulates a target | `OcahI3cTarget` |
| Passive observation without driving the bus | `OcahI3cMonitor` |
| HDR-DDR / HDR-BT traffic | Not supported — use cocotbext-i3c directly |

Do not import `cocotbext_i3c` types directly in test files.  Always go
through this package.

---

## Package Layout

```
ocah_i3c_vip/
  __init__.py            — package exports: OcahI3cBus, OcahI3cTarget,
                           OcahI3cMonitor
  cocotb/ocah_i3c_bus.py        — OcahI3cBus  (controller mode)
  cocotb/ocah_i3c_target.py     — OcahI3cTarget  (target mode)
  cocotb/ocah_i3c_monitor.py    — OcahI3cMonitor  (passive monitor)
  examples/
    example_priv_rw.py   — annotated API usage snippets
```

---

## Public API Reference

### OcahI3cBus — controller mode

```python
from ocah_i3c_vip import OcahI3cBus

bus = OcahI3cBus(
    sda_i=dut.i3c_sda_i,     # SDA input (DUT -> testbench)
    sda_o=dut.i3c_sda_o,     # SDA output (testbench -> DUT)
    scl_i=dut.i3c_scl_i,     # SCL input
    scl_o=dut.i3c_scl_o,     # SCL output
    name="i3c_ctrl",          # used in log messages
    speed_hz=12.5e6,          # 12.5 MHz SDR full speed
    timeout_ns=100_000,       # per-transaction timeout
    raise_on_nack=True,       # raise OcahI3cBusError on NACK
)
```

| Method | Returns | Notes |
|---|---|---|
| `bus.init_signals()` | `None` | Drive SCL=1, SDA=1; call before first clock edge |
| `await bus.wait_for_reset(rst_signal)` | `None` | Block until active-low reset deasserts |
| `await bus.priv_write(addr, data)` | `None` | SDR private write; `data` is `bytes` |
| `await bus.priv_read(addr, length)` | `bytes` | SDR private read; returns `length` bytes |
| `await bus.send_ccc(cmd, *, broadcast, payload)` | `bytes` or `None` | CCC frame; see table below |
| `bus.ibi_listen(callback)` | `None` | Register IBI callback; enables IBI ACK-ing |
| `await bus.entdaa(static_addrs)` | `list[int]` | RSTDAA + register targets |

#### send_ccc — payload convention

| CCC | Code | broadcast | payload | Returns |
|---|---|---|---|---|
| RSTDAA | 0x06 | True | None | None |
| ENTDAA | 0x07 | True | None | None |
| SETDASA | 0x87 | False | `bytes([dyn_addr_byte, static_addr])` | None |
| GETSTATUS | 0x90 | False | `bytes([target_addr])` | 2 bytes |
| GETPID | 0x8D | False | `bytes([target_addr])` | 6 bytes |

---

### OcahI3cTarget — target mode

```python
from ocah_i3c_vip import OcahI3cTarget

tgt = OcahI3cTarget(
    sda_i=dut.i3c_sda_i,
    sda_o=dut.i3c_sda_o,
    scl_i=dut.i3c_scl_i,
    scl_o=dut.i3c_scl_o,
    name="i3c_target_0",
    static_addr=0x12,
    speed_hz=12.5e6,
)
```

| Method | Notes |
|---|---|
| `tgt.set_static_address(addr)` | Update the 7-bit static address |
| `tgt.register_ibi(mdb, *, payload)` | Queue an IBI; `mdb` is the Mandatory Data Byte |
| `tgt.set_response(data)` | Pre-load bytes for the next private read |
| `tgt.clear_response()` | Discard pre-loaded response data |

---

### OcahI3cMonitor — passive observation

```python
from ocah_i3c_vip import OcahI3cMonitor

mon = OcahI3cMonitor(
    sda_i=dut.i3c_sda_i,  # read-only; does NOT drive the bus
    scl_i=dut.i3c_scl_i,
    name="i3c_mon",
)

def on_event(record):
    print(record["kind"], record["sim_time_ns"])

mon.add_transfer_callback(on_event)
await mon.start()
# ... run traffic ...
await mon.stop()

events = mon.get_transfers()    # list of plain-int dicts
stats  = mon.get_statistics()
```

Transfer record keys: `kind` (`"bus_start"`, `"bus_stop"`, `"ibi"`),
`addr` (int), `data` (bytes), `sim_time_ns` (float).

---

## Plusargs

The following optional plusargs can be passed to the simulator to tune wrapper
behaviour.  All are optional and default to deterministic / non-verbose mode.

| Plusarg | Type | Default | Description |
|---|---|---|---|
| `+OCAH_I3C_SPEED_HZ` | float | 12500000 | Override I3C bus speed for all instances |
| `+OCAH_I3C_TIMEOUT_NS` | float | 100000 | Per-transaction timeout in nanoseconds |
| `+OCAH_I3C_VERBOSE` | 0 or 1 | 0 | Set logging level to DEBUG for all ocah_i3c_vip loggers |

Read them in your test:

```python
import os
speed = float(os.environ.get("COCOTB_PLUSARG_OCAH_I3C_SPEED_HZ", "12500000"))
bus = OcahI3cBus(sda_i=..., sda_o=..., scl_i=..., scl_o=..., speed_hz=speed)
```

---

## Determinism

This wrapper is **deterministic by default**:

- No `random` module calls with wall-clock seeds.
- I3C timing is governed by `I3cControllerTimings` defaults from MIPI I3C
  Basic Specification v1.1.1 (Tables 86/87).
- To vary timing or inject faults, access `bus._ctrl` directly and document
  the non-determinism explicitly.

---

## Signal Convention

The `sda_i / sda_o / scl_i / scl_o` split follows the cocotbext-i3c
convention and maps to the OCAH I3C interface as follows:

When the testbench is the **controller** (DUT is the target):

```
testbench          DUT (I3C target stub)
  bus.scl_o  ───►  scl_i  (TB drives clock)
  bus.scl_i  ◄───  scl_o  (TB reads clock, for clock stretching)
  bus.sda_o  ───►  sda_i  (TB drives data)
  bus.sda_i  ◄───  sda_o  (TB reads data + T-bit)
```

When the testbench is the **target** (DUT is the controller):

```
testbench          DUT (SMC I3C controller)
  tgt.scl_i  ◄───  scl_o  (DUT drives clock)
  tgt.scl_o  ───►  scl_i  (target may hold clock low for stretching)
  tgt.sda_i  ◄───  sda_o  (DUT drives data)
  tgt.sda_o  ───►  sda_i  (target drives T-bit / ACK / read data)
```

---

## Error Handling

| Exception | When raised |
|---|---|
| `OcahI3cBusError` | Target NACKs and `raise_on_nack=True` (default) |
| `OcahI3cTargetError` | Target model configuration error |
| `OcahI3cImportError` | `cocotbext_i3c` is not importable |

To inspect NACKs without raising:

```python
bus = OcahI3cBus(..., raise_on_nack=False)
await bus.priv_write(addr=0x08, data=b"\x01")   # NACK is silently ignored
```

---

## Known Limitations and TODOs

1. **Full ENTDAA state machine**: the `entdaa()` helper issues RSTDAA and
   registers target dynamic addresses but does not drive the full ENTDAA
   arbitration (reading 48-bit PID/BCR/DCR per target).  Upstream
   `cocotbext-i3c` does not expose a first-class `ENTDAA` coroutine in
   v1.1.0.  Use `send_ccc(0x07, broadcast=True)` with manual SETDASA
   if full DAA is needed.

2. **OcahI3cMonitor frame decode**: the passive monitor detects START/STOP
   conditions on the bus but does not decode byte-level private-read/write
   frame content.  Full frame decode requires protocol-level hooks not
   exposed in `cocotbext-i3c` v1.1.0.  Couple the monitor with `OcahI3cBus`
   logging (`logging.DEBUG`) for byte-level visibility.

3. **OcahI3cTarget IBI initiation**: `register_ibi()` queues the IBI payload
   into the target memory buffer.  The IBI trigger mechanism depends on
   internal `I3CTarget` details that may change in future `cocotbext-i3c`
   versions.  Verify against the actual upstream release when upgrading.

4. **HDR modes**: HDR-DDR and HDR-BT are out of scope.  Tests requiring HDR
   should access `bus._ctrl` directly and document the bypass.

---

## Examples

See `examples/example_priv_rw.py` for five annotated snippets:

1. SDR private write and read-back.
2. CCC RSTDAA broadcast and GETSTATUS directed read.
3. IBI listen with callback.
4. Target-mode model (testbench emulates a target device).
5. Passive monitor alongside an active controller.

---

## Migration from direct cocotbext-i3c usage

| Legacy call | Replacement |
|---|---|
| `I3cController.i3c_write(addr, data)` | `OcahI3cBus.priv_write(addr, bytes(data))` |
| `I3cController.i3c_read(addr, count)` | `OcahI3cBus.priv_read(addr, count)` |
| `I3cController.i3c_ccc_write(ccc, broadcast_data)` | `OcahI3cBus.send_ccc(cmd, broadcast=True, payload=bytes(bd))` |
| `I3cController.i3c_ccc_read(ccc, addr, count)` | `OcahI3cBus.send_ccc(cmd, payload=bytes([addr]))` |
| `I3CTarget(sda_i, ..., target_address=x)` | `OcahI3cTarget(sda_i, ..., static_addr=x)` |

---

## License

Copyright 2025 Tenstorrent Inc.
SPDX-License-Identifier: Apache-2.0

The wrapped library `cocotbext-i3c` is copyright Antmicro
(https://github.com/antmicro/cocotbext-i3c) and is also Apache-2.0.

## Hierarchical VIP Layout

This package follows the OCAH hierarchical VIP convention (see
`hw/common/dv/README.md` and the 1_vip layout guide): all cocotb (Python)
code lives in `cocotb/`, and the root `__init__.py` is a thin shim
re-exporting the stable public API — always import
`from ocah_i3c_vip import <Class>`, never from the subfolders.
`interface/` (shared SV interfaces) and `uvm/`
(SV-UVM agent + env) are added as they land for this protocol. The SV-UVM
template and the commercial-VIP plug-in contract (env-level factory
override, user-implemented API wrapper, monitor closing, nested vendor
interface) are documented in `../ocah_jtag_vip/README.md`
("Template Contract") — the reference implementation for all OCAH SV-UVM
VIPs.
