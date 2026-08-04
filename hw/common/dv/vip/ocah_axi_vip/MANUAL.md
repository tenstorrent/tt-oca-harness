# OCAH AXI VIP Manual

SPDX-License-Identifier: Apache-2.0

This manual describes the released OCAH AXI wrapper API for OSS cocotb tests.
Use this package for AXI4, AXI4-Lite, and memory-backed AXI responders instead
of importing backend BFMs directly.

## Supported Backends

The released master and responder classes use `cocotbext-axi`:

| OCAH class | Backend |
|---|---|
| `OcahAxiMaster` | `cocotbext.axi.AxiMaster` |
| `OcahAxiLiteMaster` | `cocotbext.axi.AxiLiteMaster` |
| `OcahAxiSlave` / `OcahAxiRam` | OCAH RAM wrapper over `cocotbext-axi` AXI channels |
| `OcahAxiLiteSlave` / `OcahAxiLiteRam` | OCAH RAM wrapper over `cocotbext-axi` AXI-Lite channels |
| `OcahAxiMonitor` / `OcahAxiLiteMonitor` | OCAH passive samplers that emit item dataclasses |
| `OcahAxiChecker` | OCAH item-level checker |

## Package Shape

The VIP follows the OCAH cocotb VIP taxonomy:

| File | Purpose |
|---|---|
| `cocotb/ocah_axi_master.py` | AXI4 full master agent |
| `cocotb/ocah_axi_lite_master.py` | AXI4-Lite master agent |
| `cocotb/ocah_axi_slave.py` | AXI4 memory-backed slave/RAM responder |
| `cocotb/ocah_axi_lite_slave.py` | AXI4-Lite memory-backed slave/RAM responder |
| `cocotb/ocah_axi_item.py` | Generic AXI/AXI-Lite transaction items |
| `cocotb/ocah_axi_monitor.py` | Passive item-producing monitors |
| `cocotb/ocah_axi_checker.py` | Item-level protocol checker |
| `ocah_axi_cov.sv` | Commercial-simulator functional coverage hook |

## Import Pattern

```python
from ocah_axi_vip import (
    OcahAxiMaster,
    OcahAxiLiteMaster,
    OcahAxiRam,
    OcahAxiLiteRam,
    OcahAxiMonitor,
    OcahAxiChecker,
    OcahFaultAxiLiteRam,
    RESP_OKAY,
    RESP_SLVERR,
    RESP_DECERR,
)
```

Do not import `cocotbext.axi.AxiMaster`, `AxiLiteMaster`, `AxiRam`, or backend
response enums in new OCAH tests. Add missing behavior to this wrapper instead.

## AXI4-Lite Master

Use `OcahAxiLiteMaster` for register-style AXI4-Lite accesses.

```python
master = OcahAxiLiteMaster.from_prefix(
    dut,
    "cfg_axil",
    dut.clk_i,
    dut.rst_ni,
    reset_active_level=False,
    data_width=32,
    timeout_ns=50_000,
)

await master.wait_for_reset()
await master.write(0x0000_0000, 0x1)
value = await master.read(0x0000_0000)
```

Compatibility helpers:

| Method | Return | Use |
|---|---|---|
| `await write(addr, data, ...)` | `int` response code | Existing tests that only need BRESP |
| `await read(addr, ...)` | `int` data | Existing tests that expect OKAY reads |

Result helpers:

| Method | Return | Use |
|---|---|---|
| `await write_result(addr, data, ...)` | `OcahAxiWriteResult` | Negative writes, exact response checks |
| `await read_result(addr, ...)` | `OcahAxiReadResult` | Negative reads, data plus RRESP checks |

Event helpers:

| Method | Return | Use |
|---|---|---|
| `init_write(address=..., data=...)` | cocotb event | Explicit timeout flows |
| `init_read(address=..., length=...)` | cocotb event | SEP-style event handling |

## AXI4 Master

Use `OcahAxiMaster` for full AXI4 single-beat or burst traffic.

```python
master = OcahAxiMaster.from_prefix(
    dut,
    "s_axi",
    dut.clk_i,
    dut.rst_ni,
    reset_active_level=False,
    data_width=64,
)

resp = await master.write(0x1000, 0xDEAD_BEEF, size=3)
assert resp == RESP_OKAY

data = await master.burst_read(0x2000, length=4, size=3)
```

`size` is AXI `AxSIZE`, the log2 transfer size in bytes. For example, `size=2`
is a 4-byte beat and `size=3` is an 8-byte beat. The compatibility API accepts
`id` as an alias for `awid`/`arid`.

## Result Object Semantics

`OcahAxiWriteResult` fields:

| Field | Meaning |
|---|---|
| `address` | Address reported by the backend |
| `length` | Completed byte count |
| `resp` | Worst response code, or `-1` for timeout/unreadable |
| `resp_list` | One response code per backend response element |
| `ok` | True only for OKAY/EXOKAY |
| `timed_out` | True only when `allow_timeout=True` absorbed a timeout |
| `raw` | Backend object for debug only |

`OcahAxiReadResult` adds:

| Field | Meaning |
|---|---|
| `data` | First data beat as an integer |
| `data_bytes` | Raw read payload as bytes |
| `data_words` | One integer per beat |

Use `check_response=False` and `raise_on_error=False` when a negative test
expects a non-OKAY response:

```python
master = OcahAxiLiteMaster.from_prefix(
    dut, "j_axi", dut.clk_i, dut.rst_ni,
    reset_active_level=False,
    raise_on_error=False,
)
result = await master.read_result(0xFFFF_0000, check_response=False)
assert result.resp == RESP_DECERR
```

Use `timeout_ns=<n>` and `allow_timeout=True` only when a scenario explicitly
accepts a non-completing access. The returned result has `timed_out=True`,
`ok=False`, and `resp=-1`.

## Fault-Capable Responders

`OcahAxiRam` is memory-backed and also exposes fault controls:

```python
ram = OcahAxiRam.from_prefix(
    dut,
    "m_axi",
    dut.clk_i,
    dut.rst_ni,
    reset_active_level=False,
    size=2**20,
)

ram.write64(0x40, 0x0123_4567_89AB_CDEF)
ram.inject_error(0x80, RESP_SLVERR, read=True, write=False)
ram.enable_backpressure(channels=("aw", "w", "ar"), stall_cycles=2)
```

Responder methods:

| Method | Behavior |
|---|---|
| `read(addr, length)` / `write(addr, data)` | Backdoor byte access |
| `read32/read64` / `write32/write64` | Little-endian integer helpers |
| `inject_error(addr, resp, read=True, write=True)` | Program one-shot non-OKAY response |
| `clear_errors()` | Clear all programmed errors |
| `enable_backpressure(channels, stall_cycles)` | Repeating bounded READY stalls |
| `disable_backpressure()` | Clear READY stalls |

`OcahAxiLiteRam` and `OcahFaultAxiLiteRam` provide the same fault-control API
for AXI4-Lite responder ports.

```python
axil_ram = OcahAxiLiteRam.from_prefix(
    dut,
    "cfg_axil",
    dut.clk_i,
    dut.rst_ni,
    reset_active_level=False,
)
axil_ram.write32(0x10, 0x5A5A_1234)
axil_ram.inject_error(0x20, RESP_DECERR, read=True, write=False)
```

## Items, Monitors, And Checkers

Monitors emit immutable `OcahAxiItem` records. Callbacks receive the item object,
not backend transaction classes.

```python
monitor = OcahAxiLiteMonitor.from_prefix(dut, "cfg_axil", dut.clk_i)
checker = OcahAxiChecker()
checker.attach_monitor(monitor)

observed = []
monitor.add_item_callback(observed.append)
await monitor.start()

# Run traffic here.

await monitor.stop()
checker.assert_clean()
```

Item fields include `protocol`, `direction`, `address`, `data_words`,
`strobes`, `size`, `burst`, `transaction_id`, `prot`, `resp_list`, `ok`, and
`timed_out`.

## Functional Coverage Hook

`ocah_axi_cov.sv` is commercial-simulator-only collateral. It provides:

- `ocah_axi_cov_if` with `sample_write()` and `sample_read()` tasks.
- `ocah_axi_cov` module wrapper with scalar sample ports for bind-friendly flows.

Do not add this file to Verilator default filelists.

## DTP Usage

DTP JTAG2AXI responders should use the shared OCAH fault APIs. The DTP-local
`dtp_fault_axi.py` file only preserves compatibility names; it no longer owns
backend subclassing.

## SEP Compatibility Reference

Do not modify SEP code as part of this release. Existing SEP cocotbext usage is
the compatibility checklist for the wrapper:

| SEP pattern | OCAH wrapper support |
|---|---|
| `init_read` / `init_write` | Provided by `OcahAxiMaster` and `OcahAxiLiteMaster` |
| Explicit timeout around event wait | `timeout_ns` and event helpers |
| `allow_timeout` negative checks | `read_result` / `write_result` support `allow_timeout=True` |
| Exact response-code assertions | `resp`, `resp_list`, and `ok` fields |
| Error-expected probes | Use `raise_on_error=False`, `check_response=False` |

Future SEP migration can be planned separately after wrapper parity is proven by
DTP and import/smoke validation.

## Migration Notes

| Legacy/backend pattern | OCAH wrapper pattern |
|---|---|
| `AxiLiteMaster(...).read(...)` | `OcahAxiLiteMaster(...).read_result(...)` |
| `AxiMaster(...).init_read(...)` | `OcahAxiMaster(...).init_read(...)` |
| Backend response enum imports | `RESP_OKAY`, `RESP_SLVERR`, `RESP_DECERR` |
| DTP-local fault RAM subclasses | `OcahAxiRam` / `OcahFaultAxiLiteRam` fault APIs |

If a test needs an AXI sideband or non-contiguous strobe pattern that the wrapper
does not expose, extend this package first so the public API stays stable.
