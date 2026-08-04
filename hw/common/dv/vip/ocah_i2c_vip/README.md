# ocah_i2c_vip — OCAH I2C Bus Wrapper

SPDX-License-Identifier: Apache-2.0

Stable, OCAH-flavored Python wrappers for driving and monitoring I2C bus
traffic in cocotb testbenches.  Covers SMC I2C top-level tests and EEPROM-style
device emulation.

---

## Purpose

OCAH cocotb tests need a single, versioned API for I2C transactions so that:

1. Tests do not break when the underlying VIP is updated.
2. New test authors have one place to look for I2C bus-access primitives.
3. Upstream API changes (`cocotbext-i2c`) are absorbed at the wrapper
   boundary, not scattered across test files.

---

## Pinned Dependency

```
cocotbext-i2c == 0.1.2   (MIT)
```

Repository: <https://github.com/alexforencich/cocotbext-i2c>

Install with:

```bash
pip install cocotbext-i2c==0.1.2
```

When `cocotbext-i2c` is **not** installed, constructing any class in this
package raises `OcahI2cImportError` with an actionable install message.  No
other import-time side-effects occur.  This mirrors the `ocah_axi_vip`
migration-plan pattern.

---

## Package Layout

```
ocah_i2c_vip/
  __init__.py              — exports OcahI2cMaster, OcahI2cDevice,
                             OcahI2cMemory, OcahI2cMonitor
  cocotb/ocah_i2c_master.py       — OcahI2cMaster (active master driver)
  cocotb/ocah_i2c_device.py       — OcahI2cDevice (custom callback device emulator)
  cocotb/ocah_i2c_memory.py       — OcahI2cMemory (EEPROM-style memory device)
  cocotb/ocah_i2c_monitor.py      — OcahI2cMonitor (passive bus observation)
  examples/
    example_i2c_eeprom.py  — annotated usage snippets
```

---

## Protocol

- **Addressing**: 7-bit device addresses (0x00–0x7F).  10-bit addressing is
  out of scope.
- **Speeds**: Standard mode (100 kHz) and Fast mode (400 kHz).  High-speed
  mode (3.4 MHz) is not supported.
- **Transfer types**:
  - Write: START + ADDR(W) + data bytes + STOP
  - Read: START + ADDR(R) + data bytes + STOP
  - Combined (write-then-read): START + ADDR(W) + register address +
    RESTART + ADDR(R) + data bytes + STOP

---

## Plusargs

All plusargs are optional.

| Plusarg                    | Type   | Default   | Description |
|---|---|---|---|
| `+i2c_speed_hz=<N>`        | int    | 100000    | Override I2C bus speed for all `OcahI2cMaster` instances |
| `+i2c_default_addr=<N>`    | int    | (none)    | Override default 7-bit device address (accepts hex: `0x50`) |

Set the environment variables directly:

```bash
export COCOTB_PLUSARG_i2c_speed_hz=400000
export COCOTB_PLUSARG_i2c_default_addr=0x50
```

Or pass them via the simulator:

```
SIM_ARGS += +i2c_speed_hz=400000 +i2c_default_addr=0x50
```

---

## Public API Reference

### OcahI2cMaster — active I2C master

```python
from ocah_i2c_vip import OcahI2cMaster

master = OcahI2cMaster(
    dut.i2c_scl,        # SCL signal handle
    dut.i2c_sda,        # SDA signal handle
    dut.clk,            # clock handle
    name="i2c_master",  # used in log messages
    speed=100_000,      # 100 kHz Standard mode; 400_000 for Fast mode
    default_addr=0x50,  # optional default 7-bit device address
    timeout_us=10_000,  # default per-transaction timeout
    raise_on_nack=True, # raise OcahI2cError on NACK or timeout
)
```

| Method | Returns | Notes |
|---|---|---|
| `master.init_signals()` | `None` | Drive SCL/SDA to idle; call before first clock edge |
| `master.set_address(addr)` | `None` | Set default 7-bit device address |
| `await master.write(addr, data, *, timeout_us)` | `None` | Write bytes to device |
| `await master.read(addr, length, *, timeout_us)` | `bytes \| None` | Read bytes from device |
| `await master.combined(addr, write_data, read_length, *, timeout_us)` | `bytes \| None` | Write then read (repeated START) |
| `master.get_statistics()` | `dict` | Cumulative counters |
| `master.reset_statistics()` | `None` | Zero all counters |

`addr` defaults to `default_addr` when `None`.  Data arguments accept
`bytes`, `bytearray`, or `list[int]`.  Return values are always `bytes`.

#### Statistics dict keys

| Key | Description |
|---|---|
| `write_transactions` | Completed write transactions |
| `read_transactions` | Completed read transactions |
| `combined_transactions` | Completed combined write-read transactions |
| `nacks` | NACK events |
| `timeouts` | Timeout events |

---

### OcahI2cDevice — custom callback device emulator

```python
from ocah_i2c_vip import OcahI2cDevice

device = OcahI2cDevice(
    dut.i2c_scl, dut.i2c_sda, dut.clk,
    name="my_device",
    addr=0x55,
    speed=100_000,
)

def my_handler(addr: int, rw: str, data: bytes) -> bytes:
    if rw == "write":
        ...
        return None      # no read response needed
    if rw == "read":
        return b"\\x42"  # data to supply to the master

device.register_handler(my_handler)
await device.start()
# ... run traffic ...
await device.stop()

writes = device.get_write_data()   # list[bytes]
```

| Method | Returns | Notes |
|---|---|---|
| `device.set_address(addr)` | `None` | Change I2C address; must be called before `start()` |
| `device.register_handler(cb)` | `None` | Register handler; multiple allowed |
| `await device.start()` | `None` | Begin listening on bus |
| `await device.stop()` | `None` | Stop listening |
| `device.get_write_data()` | `list[bytes]` | Received write payloads (oldest first) |
| `device.clear_history()` | `None` | Discard retained records |
| `device.get_statistics()` | `dict` | `write_transactions`, `read_transactions` |

Handler signature: `cb(addr: int, rw: str, data: bytes) -> bytes`

---

### OcahI2cMemory — EEPROM-style memory device

```python
from ocah_i2c_vip import OcahI2cMemory

eeprom = OcahI2cMemory(
    dut.i2c_scl, dut.i2c_sda, dut.clk,
    name="eeprom",
    addr=0x50,
    mem_size=256,    # AT24C02 equivalent
    addr_bytes=1,    # 1-byte register address
    speed=100_000,
)

eeprom.preload(b"\\xFF" * 256)            # preload from bytes
eeprom.preload("/path/to/eeprom.bin")    # preload from file

await eeprom.start()
# ... run I2C transactions ...
await eeprom.stop()

snapshot = eeprom.dump()                # bytes: full memory snapshot
val = eeprom.read_mem(0x10, 4)          # bytes: direct read, 4 bytes at offset 0x10
eeprom.write_mem(0x10, b"\\xAA\\xBB")  # direct write
```

| Method | Returns | Notes |
|---|---|---|
| `eeprom.preload(source)` | `None` | Load from file path (str) or bytes; truncates at `mem_size` |
| `eeprom.dump()` | `bytes` | Snapshot of all `mem_size` bytes |
| `eeprom.read_mem(offset, length)` | `bytes` | Direct read bypassing I2C |
| `eeprom.write_mem(offset, data)` | `None` | Direct write bypassing I2C |
| `await eeprom.start()` | `None` | Begin responding to I2C |
| `await eeprom.stop()` | `None` | Stop responding |
| `eeprom.get_statistics()` | `dict` | Transaction and byte counters |

Memory is initialised to `0xFF` (erased EEPROM convention) before any
`preload` call.

---

### OcahI2cMonitor — passive bus observation

```python
from ocah_i2c_vip import OcahI2cMonitor

monitor = OcahI2cMonitor(
    dut.i2c_scl, dut.i2c_sda, dut.clk,
    name="i2c_mon",
    speed=100_000,
    max_history=2000,
)

monitor.add_write_callback(lambda addr, data: ...)
monitor.add_read_callback(lambda addr, length, data: ...)

await monitor.start()
# ... run traffic ...
await monitor.stop()

txns  = monitor.get_transactions()   # list[dict]
stats = monitor.get_statistics()     # dict
```

| Method | Returns | Notes |
|---|---|---|
| `monitor.add_write_callback(fn)` | `None` | `fn(addr: int, data: bytes) -> None` |
| `monitor.add_read_callback(fn)` | `None` | `fn(addr: int, length: int, data: bytes) -> None` |
| `await monitor.start()` | `None` | Start passive observation |
| `await monitor.stop()` | `None` | Stop; history retained |
| `monitor.get_transactions()` | `list[dict]` | All observed transactions |
| `monitor.clear_history()` | `None` | Discard all records |
| `monitor.get_statistics()` | `dict` | `write_transactions`, `read_transactions` |

Transaction dict keys: `rw`, `addr`, `data`, `length` (read only).

**Note on passive monitoring**: `OcahI2cMonitor` uses direct SCL/SDA edge
observation (bit-bang) rather than a library device slave, so it does not
assert ACK on the bus and is truly non-intrusive.

---

## Error Handling

```python
from ocah_i2c_vip import OcahI2cError, OcahI2cImportError
```

| Exception | When raised |
|---|---|
| `OcahI2cError` | NACK, timeout, or bus-protocol violation |
| `OcahI2cImportError` | `cocotbext-i2c` not installed |

To receive `None` on NACK/timeout instead of raising:

```python
master = OcahI2cMaster(..., raise_on_nack=False)
data = await master.read(0x50, length=4)
if data is None:
    cocotb.log.warning("device did not respond")
```

---

## Determinism

All behavior is deterministic by default:

- Bus timing is governed by the `speed` parameter (no jitter).
- The `OcahI2cMemory` initial state is always `0xFF` until `preload` is
  called.
- No random data is generated anywhere in the wrapper.

---

## Examples

See `examples/example_i2c_eeprom.py` for four annotated examples:

1. EEPROM write + combined read.
2. Preload from bytes/file + readback.
3. Custom device handler callback.
4. Passive monitoring with `OcahI2cMonitor`.
