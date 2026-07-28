# OCAH APB VIP Manual

SPDX-License-Identifier: Apache-2.0

This manual describes the released OCAH APB wrapper API for OSS cocotb tests.
Use this package for APB register traffic instead of importing backend BFMs
directly.

## Supported Backend

APB uses `cocotbext-axi` for active master/slave behavior and OCAH code for
items, monitors, checkers, and coverage hooks:

| OCAH class | Backend |
|---|---|
| `OcahApbMaster` | `cocotbext.axi.ApbMaster` |
| `OcahApbSlave` / `OcahApbRam` | `cocotbext.axi.ApbSlave` plus OCAH memory target |
| `OcahApbMonitor` | OCAH passive sampler |
| `OcahApbChecker` | OCAH item-level checker |

APB remains in a separate package from AXI because it is a distinct protocol,
but the public API mirrors `OcahAxiLiteMaster` where practical.

## Import Pattern

```python
from ocah_apb_vip import (
    OcahApbMaster,
    OcahApbRam,
    OcahApbMonitor,
    OcahApbChecker,
    OcahApbReadResult,
    OcahApbWriteResult,
    RESP_OKAY,
    RESP_SLVERR,
)
```

Do not import `cocotbext.axi.ApbMaster`, `ApbSlave`, `ApbBus`, or backend
response enums in new OCAH tests. Add missing behavior to this wrapper instead.

## Package Shape

| File | Purpose |
|---|---|
| `ocah_apb_master.py` | APB master agent |
| `ocah_apb_slave.py` | APB memory-backed slave/RAM responder |
| `ocah_apb_item.py` | Generic APB transaction item |
| `ocah_apb_monitor.py` | Passive item-producing monitor |
| `ocah_apb_checker.py` | Item-level protocol checker |
| `ocah_apb_cov.sv` | Commercial-simulator functional coverage hook |

## Construction

Construct from an APB interface handle plus clock:

```python
master = OcahApbMaster(
    dut.apb_if,
    dut.pclk,
    dut.presetn,
    reset_active_level=False,
    name="apb_host",
    data_width=32,
    timeout_ns=50_000,
)
```

Or construct from flattened signals:

```python
master = OcahApbMaster.from_prefix(
    dut,
    "cfg_apb",
    dut.pclk,
    dut.presetn,
    reset_active_level=False,
)
```

Call `await master.wait_for_reset()` before the first transaction when the test
starts traffic after reset release.

## Slave / RAM Responder

Use `OcahApbRam` for a memory-backed APB responder:

```python
ram = OcahApbRam.from_prefix(
    dut,
    "cfg_apb",
    dut.pclk,
    dut.presetn,
    reset_active_level=False,
    size=2**16,
)
ram.write32(0x10, 0xA5A5_5A5A)
ram.inject_error(0x20, RESP_SLVERR, read=True, write=False)
```

Responder helpers include `read()`, `write()`, `read32()`, `write32()`,
`inject_error()`, `clear_errors()`, `enable_backpressure()`, and
`disable_backpressure()`.

## Compatibility Helpers

| Method | Return | Use |
|---|---|---|
| `await write(addr, data, ...)` | `bool` | True when PSLVERR was not asserted |
| `await read(addr, ...)` | `int` | PRDATA as a plain integer |
| `configure(timeout_ns=...)` | `None` | Store wrapper timeout settings |
| `get_statistics()` | `dict` | Wrapper transaction counters |

These helpers are for positive register-access paths.

## Result Helpers

Use result helpers for negative tests and PSLVERR inspection:

| Method | Return | Use |
|---|---|---|
| `await write_result(addr, data, ...)` | `OcahApbWriteResult` | Write response inspection |
| `await read_result(addr, ...)` | `OcahApbReadResult` | Read data plus response inspection |

`OcahApbWriteResult` fields:

| Field | Meaning |
|---|---|
| `address` | Address reported by the backend |
| `length` | Completed byte count |
| `pslverr` | True when PSLVERR was asserted |
| `ok` | True when PSLVERR was not asserted |
| `resp` | Plain response code (`0` OKAY, `2` SLVERR) |
| `timed_out` | True only when `allow_timeout=True` absorbed a timeout |
| `raw` | Backend object for debug only |

`OcahApbReadResult` adds:

| Field | Meaning |
|---|---|
| `data` | PRDATA as an integer |
| `data_bytes` | Raw read payload bytes |

Example negative read:

```python
master = OcahApbMaster(
    dut.apb_if,
    dut.pclk,
    dut.presetn,
    reset_active_level=False,
    raise_on_error=False,
)

result = await master.read_result(0xFFFF_0000, check_response=False)
assert result.pslverr
assert result.resp == RESP_SLVERR
```

## Timeout Handling

Use `timeout_ns=<n>` and `allow_timeout=True` only for a scenario that explicitly
accepts a non-completing APB access. The returned result has:

| Field | Value |
|---|---|
| `timed_out` | `True` |
| `ok` | `False` |
| `pslverr` | `True` |
| `resp` | `-1` |

If `allow_timeout=False`, timeout is reported as an assertion failure so a wedged
bus does not silently pass as an error response.

## Strobe and Sideband Notes

The current `cocotbext-axi` APB master API accepts full-width byte transfers and
does not expose arbitrary sparse `PSTRB` control. `OcahApbMaster.write()` raises
`ValueError` when a non-full strobe is requested. Extend this package before
adding tests that require sparse APB byte strobes.

`prot` is passed through as `PPROT` when that sideband exists on the bus.

## Items, Monitors, And Checkers

`OcahApbMonitor` emits immutable `OcahApbItem` records. Callbacks receive the
item object.

```python
monitor = OcahApbMonitor.from_prefix(dut, "cfg_apb", dut.pclk)
checker = OcahApbChecker()
checker.attach_monitor(monitor)

items = []
monitor.add_item_callback(items.append)
await monitor.start()

# Run APB traffic here.

await monitor.stop()
checker.assert_clean()
```

Item fields include `direction`, `address`, `data`, `strobe`, `prot`,
`pslverr`, `ok`, `timed_out`, and `wait_cycles`.

## Functional Coverage Hook

`ocah_apb_cov.sv` is commercial-simulator-only collateral. It provides:

- `ocah_apb_cov_if` with a `sample_access()` task.
- `ocah_apb_cov` module wrapper with scalar sample ports for bind-friendly flows.

Do not add this file to Verilator default filelists.

## Migration Notes

| Backend/local pattern | OCAH wrapper pattern |
|---|---|
| `ApbMaster(...).read(...)` | `OcahApbMaster(...).read_result(...)` |
| Backend response enum imports | `RESP_OKAY`, `RESP_SLVERR` |
| Manual PSLVERR parsing | `result.pslverr` and `result.ok` |
| Custom timeout wrapper around event | `timeout_ns` / `allow_timeout` |

Keep APB traffic behind `ocah_apb_vip` so backend changes remain isolated at the
wrapper boundary.
