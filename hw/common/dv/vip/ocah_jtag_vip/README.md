# ocah_jtag_vip - OCAH JTAG TAP VIP

SPDX-License-Identifier: Apache-2.0

`ocah_jtag_vip` provides OCAH-stable IEEE 1149.1 TAP helpers for cocotb
testbenches. Tests import OCAH classes and plain dataclasses; backend
`cocotbext-jtag` objects stay inside the wrapper boundary.

## Backend

| OCAH class | Backend / implementation |
|---|---|
| `OcahJtagTap` | `cocotbext-jtag` `JTAGBus` plus OCAH raw TAP stepping/scanning |
| `OcahJtagDevice` | Plain wrapper convertible to `cocotbext-jtag` `JTAGDevice` |
| `OcahJtagMonitor` | OCAH passive sampler that emits `OcahJtagScanItem` |
| `OcahJtagChecker` | OCAH item-level checker |

`cocotbext-jtag` is pinned in `pyproject.toml` as `>=0.4.0,<0.5`. Installed
package metadata for version 0.4.0 reports license `MIT`.

## Package Layout

```text
ocah_jtag_vip/
  __init__.py            - public exports
  ocah_jtag_tap.py       - active TAP driver
  ocah_jtag_device.py    - device/register map
  ocah_jtag_item.py      - scan/state item dataclasses
  ocah_jtag_monitor.py   - passive item-producing monitor
  ocah_jtag_checker.py   - item-level checker
  ocah_jtag_state.py     - TAP state enum and TMS path helpers
  examples/
    example_idcode.py    - PTAP/STAP/CPU TAP usage examples
```

## Quick Start

```python
from ocah_jtag_vip import OcahJtagTap

tap = OcahJtagTap.from_prefix(
    dut,
    "jtag",
    name="ptap",
    ir_width=6,
    tck_period_ns=10,
)

tap.init_signals()
await tap.reset_tap()
idcode = await tap.read_idcode()
```

For flattened signals with non-standard names, pass `signal_map` to the direct
constructor:

```python
tap = OcahJtagTap(
    dut,
    name="dtp_ptap",
    ir_width=6,
    signal_map={
        "tck": "jtag_tck",
        "tms": "jtag_tms",
        "tdi": "jtag_tdi",
        "tdo": "jtag_tdo",
        "trst": "jtag_trst",
    },
)
```

## Public API

| Method | Purpose |
|---|---|
| `from_prefix(dut, prefix, ...)` | Construct from flattened JTAG signals |
| `from_bus(bus, ...)` | Construct from an existing `JTAGBus` |
| `init_signals()` | Drive idle values before traffic |
| `await reset_tap(cycles=10)` | Drive TAP to Test-Logic-Reset |
| `await step_tms(tms)` / `await tms_step(tms)` | Drive one raw TMS cycle |
| `await shift_ir(value, width=None, back_to_rti=False)` | Shift IR, return captured TDO |
| `await shift_dr(value, width, back_to_rti=False)` | Shift DR, return captured TDO |
| `await read_idcode()` | Read 32-bit IDCODE |
| `await bypass()` | Load all-ones BYPASS |
| `await goto_state(state)` | Navigate using shortest TMS path |
| `get_statistics()` | Return plain counters and tracked state |

`reset_tap()` intentionally leaves the tracked TAP state in
`TEST_LOGIC_RESET`. This matches DTP sanity sequences, which then step `TMS=0`
to observe `RUN_TEST_IDLE`.

## Device Maps

Use `OcahJtagDevice` when a test wants named `read()` / `write()` register
access:

```python
from ocah_jtag_vip import OcahJtagDevice

device = OcahJtagDevice(name="dtp", idcode=0x0000_0001, ir_width=6, idle_delay=64)
device.add_reg("IDCODE", 32, 0x01)
device.add_reg("SMC_AXI_SINGLE_OP", 98, 0x28, write=True)

tap.add_device(device)
value = await tap.read("IDCODE")
```

DTP-specific TDR packing and polling remain in the DTP agent/sequence layer.

## Monitor And Checker

```python
from ocah_jtag_vip import OcahJtagChecker, OcahJtagMonitor

monitor = OcahJtagMonitor(dut, signal_map={"tck": "jtag_tck", "tms": "jtag_tms"})
checker = OcahJtagChecker(ir_width=6)
checker.attach_monitor(monitor)

items = []
monitor.add_item_callback(items.append)
await monitor.start()

# Run TAP traffic here.

await monitor.stop()
checker.assert_clean()
```

Callbacks receive `OcahJtagScanItem` objects. The item also supports
`to_record()` for older dict-shaped callback code.

## Validation

GH #3289 acceptance should use DTP as the proof point:

```bash
python3 tools/dv/run_dv.py --doctor --dut dtp
python3 tools/dv/run_dv.py --dut dtp --items dtp_sanity_test --tool verilator
python3 tools/dv/run_dv.py --dut dtp --items dtp_jtag_idcode_test --tool verilator
python3 tools/dv/run_dv.py --dut dtp --items dtp_jtag_bypass_test --tool verilator
```

## Scope

This package covers IEEE 1149.1 TAP behavior. IJTAG (IEEE 1687),
boundary-scan-specific models, and DTP JTAG2AXI TDR packing remain outside the
shared protocol VIP.
