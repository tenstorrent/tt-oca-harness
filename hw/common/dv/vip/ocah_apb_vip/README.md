# ocah_apb_vip — OCAH APB VIP

`ocah_apb_vip` provides OCAH-stable APB master, slave, monitor, checker, and
coverage helpers for cocotb tests. All addresses, data values, byte-enable
masks, and response indicators are plain Python values; no internal VIP types
leak out.

## Backend

`cocotbext-axi` provides a full APB suite (`ApbMaster`, `ApbBus`, `ApbSlave`,
`ApbRam`), so `ocah_apb_vip` targets `cocotbext-axi` just like `ocah_axi_vip`
does — same backend library, different protocol surface. APB lives in its own
package only because it is a distinct protocol (one package per protocol). The
public API mirrors `OcahAxiLiteMaster` so tests can switch between APB and
AXI4-Lite register interfaces without restructuring driver code.

## Package Layout

```
ocah_apb_vip/
  __init__.py          — exports public APB VIP symbols
  cocotb/ocah_apb_master.py   — OcahApbMaster
  cocotb/ocah_apb_slave.py    — OcahApbSlave / OcahApbRam
  cocotb/ocah_apb_item.py     — OcahApbItem transaction record
  cocotb/ocah_apb_monitor.py  — OcahApbMonitor passive sampler
  cocotb/ocah_apb_checker.py  — OcahApbChecker item checker
  ocah_apb_cov.sv      — commercial-simulator functional coverage hook
```

## Usage

```python
from ocah_apb_vip import OcahApbMaster

master = OcahApbMaster(
    dut.apb_if,
    dut.pclk,          # APB clock handle (separate from intf)
    name="apb_host",
    timeout_cycles=200,
    data_width=32,
    raise_on_error=True,
)
master.init_signals()
await master.wait_for_reset()

await master.write(0x0000_0000, 0x1)
val = await master.read(0x0000_0000)
```

| Method | Returns | Notes |
|---|---|---|
| `master.init_signals()` | `None` | |
| `await master.wait_for_reset()` | `None` | Waits for PRESETN deassertion |
| `await master.write(addr, data, *, strb, prot)` | `bool` (True = OKAY) | Compatibility helper |
| `await master.read(addr, *, prot)` | `int` (data) | Compatibility helper |
| `await master.write_result(addr, data, ...)` | `OcahApbWriteResult` | Inspect `pslverr`, `ok`, and raw response |
| `await master.read_result(addr, ...)` | `OcahApbReadResult` | Inspect data plus `pslverr` |
| `master.init_write(...)` / `master.init_read(...)` | cocotb event | Event-style access for explicit timeout flows |
| `master.configure(timeout_cycles, timeout_ns)` | `None` | Stores wrapper timeout settings |
| `master.get_statistics()` | `dict` | |
| `master.reset_statistics()` | `None` | |

## Slave / RAM Responder

```python
from ocah_apb_vip import OcahApbRam, RESP_SLVERR

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

## Monitor And Checker

```python
from ocah_apb_vip import OcahApbChecker, OcahApbMonitor

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

## Result Inspection

Use result APIs when a test expects PSLVERR or needs to distinguish an error
response from a wedged bus:

```python
master = OcahApbMaster(dut.apb_if, dut.pclk, raise_on_error=False)
result = await master.read_result(0x1000, check_response=False)
assert result.pslverr
```

Use `allow_timeout=True` with `timeout_ns=<n>` only for tests that explicitly
accept a non-completing access. The result then has `timed_out=True`, `ok=False`,
and `resp=-1`.

## Detailed Manual

See `MANUAL.md` in this folder for construction rules, item/result semantics,
PSLVERR handling, monitor/checker usage, coverage hooks, and migration guidance.

## Hierarchical VIP Layout

This package follows the OCAH hierarchical VIP convention (see
`hw/common/dv/README.md` and the 1_vip layout guide): all cocotb (Python)
code lives in `cocotb/`, and the root `__init__.py` is a thin shim
re-exporting the stable public API — always import
`from ocah_apb_vip import <Class>`, never from the subfolders.
`cov/` holds this package's framework-neutral commercial-simulator
functional-coverage model (`cov/ocah_apb_cov.sv` — plain covergroup/bind SV
with no UVM phasing, so the cocotb commercial-sim flow compiles it and the
UVM flow binds the same file). `interface/` (shared SV interfaces) and `uvm/`
(SV-UVM agent + env) are added as they land for this protocol. The SV-UVM
template and the commercial-VIP plug-in contract (env-level factory
override, user-implemented API wrapper, monitor closing, nested vendor
interface) are documented in `../ocah_jtag_vip/README.md`
("Template Contract") — the reference implementation for all OCAH SV-UVM
VIPs.
