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

## Pin Timing

The active cocotb and UVM drivers use the same IEEE 1149.1 cycle contract:
drive TMS/TDI while TCK is low, sample TDO in that low phase before the rising
edge, then raise TCK so the target captures inputs and advances its TAP state.
Sampling after the rising edge is invalid on the final scan bit because that
edge also exits `SHIFT_IR` or `SHIFT_DR`. The cocotb driver samples in the
`ReadOnly` phase and advances to the next timestep before driving TCK, avoiding
simulator-dependent stale reads.

## Cocotb Checker Evidence

`OcahJtagChecker` retains its IEEE 1149.1 item checks and composes the shared
`ocah_checker` evidence/finalization core:

```python
from ocah_jtag_vip import OcahJtagChecker

checker = OcahJtagChecker(
    required_ids={"CHK-IDCODE-RAW", "CHK-IDCODE-MARKER"},
)
checker.expect_equal(
    "CHK-IDCODE-RAW",
    observed=idcode,
    expected=expected_idcode,
    context="tap=primary",
)
checker.expect_equal(
    "CHK-IDCODE-MARKER",
    observed=idcode & 1,
    expected=1,
    context=f"raw={idcode:#x}",
)
checker.finalize()
```

`check_item()` continues to check scan width, IDCODE marker shape, and BYPASS
record shape. `expect_equal()`/`expect_true()` add named exact-value evidence.
`finalize()` fails on retained protocol errors, failed evidence, zero checks, or
missing required IDs.

Monitors deliberately log and catch callback exceptions. An attached checker
therefore retains its protocol error before raising, and the owning test or
scoreboard must call `finalize()` after traffic. The first adopter is the DTP
`dtp_jtag_idcode_test` sequence.

## Package Layout

```text
ocah_jtag_vip/
  __init__.py            - public exports
  cocotb/ocah_jtag_tap.py       - active TAP driver
  cocotb/ocah_jtag_device.py    - device/register map
  cocotb/ocah_jtag_item.py      - scan/state item dataclasses
  cocotb/ocah_jtag_monitor.py   - passive item-producing monitor
  cocotb/ocah_jtag_checker.py   - item-level checker
  cocotb/ocah_jtag_state.py     - TAP state enum and TMS path helpers
  cocotb/examples/
    example_idcode.py    - PTAP/STAP/CPU TAP usage examples
  interface/
    ocah_jtag_if.sv      - shared pin-level IEEE 1149.1 interface (JTAG pins only)
  uvm/
    ocah_jtag_uvm_pkg.sv - SV-UVM agent package (see below)
```

## SV-UVM Agent (`uvm/`)

`ocah_jtag_uvm_pkg` provides a reusable SV-UVM agent over `ocah_jtag_if`:

| Component | Role |
|---|---|
| `ocah_jtag_item` | Stimulus item: `TAP_RESET`, `IR_SCAN`, `DR_SCAN`, `RAW_TMS`; driver fills observed TDO in-place |
| `ocah_jtag_cfg` | vif, `is_active`, TCK half-period, TRST reset cycles |
| `ocah_jtag_driver` | Pin-level TCK bit-bang; scans navigate RTI -> scan leg -> RTI |
| `ocah_jtag_monitor` | Passive: per-TCK `STEP` events (published on the falling edge) + async `TRST` events via `event_ap` |
| `ocah_jtag_sequencer` | `uvm_sequencer #(ocah_jtag_item)` |
| `ocah_jtag_agent` | Standard bundle; monitor when `en_monitor`, driver/sequencer when active |
| `ocah_jtag_env` | VIP-level env: what DUTs instantiate and commercial integrations override |

The package also ships an encoding-agnostic IEEE 1149.1 TAP model
(`ocah_jtag_tap_state_e`, `ocah_jtag_next_state()`; state values match the
conventional 0..15 numbering, i.e. the bit index of one-hot RTL encodings)
for DUT-side checkers. Protocol-legality checking, scoreboarding, and
coverage live in subscribers, not in the monitor; IR/DR scan-level
reconstruction is a documented follow-up once a scoreboard consumer exists.
First user: the DTP SV-UVM flow (`--dut dtp_uvm`), whose
`dtp_tap_fsm_checker` pairs monitor steps with the DUT's decoded TAP state.
Like all SV-UVM collateral, compile sign-off is gated on a Linux VCS run.

## Template Contract (per-protocol VIPs and commercial plug-ins)

This VIP is the TEMPLATE for OCAH SV-UVM VIPs. DUT environments instantiate
`ocah_<proto>_env` — the VIP-level environment is the reuse AND override
unit, matching the delivery granularity of commercial VIPs (e.g. Synopsys
`svt_axi_system_env` is an env, not an agent). Its frozen surface is:

| Surface | Role |
|---|---|
| `m_sequencer` | scenario handle: DUT sequences issue `ocah_<proto>_item`s here |
| `event_ap` | `ocah_<proto>_event` observation stream (silent when `cfg.en_monitor=0`) |
| `cfg` | `ocah_<proto>_cfg`, incl. opaque `vendor_cfg` extension hook |

Everything above that surface (DUT sequences, tests, checkers, testlists)
depends only on the item and event types, never on driver/monitor internals.

**Using a commercial VIP is a user-implemented integration** — the template
does not hide that work, it gives it exactly one home per protocol:

1. **Inherit the env (and agent if needed).** Subclass `ocah_<proto>_env`;
   build the vendor system env (e.g. `svt_axi_system_env` +
   `svt_axi_system_configuration` via `cfg.vendor_cfg`) instead of the OCAH
   agent path. Select it with a single factory override:
   `ocah_jtag_env::type_id::set_type_override(<vendor>_jtag_env::get_type())`.
2. **Implement the API wrapper.** The vendor env owns all driving and
   monitoring. The integration implements translation (WR/RD-style tasks or
   a translator driver): convert each incoming `ocah_<proto>_item` into the
   vendor's transactions (e.g. `svt_axi_master_transaction`), start them on
   the vendor sequencer, and fill the item's response fields before
   `item_done`. The OCAH driver's protocol tasks are `virtual` for
   fine-grained reuse where helpful.
3. **Close the OCAH monitor.** Set `cfg.en_monitor = 0`: the vendor env's
   monitors/protocol checkers take over observation, and the OCAH agent
   builds no monitor. Subscribers keyed to `ocah_<proto>_event` (FSM
   checkers, scoreboards) must be re-pointed to vendor analysis streams or
   fed by an adapter subscriber — part of the integration.
4. **Nest the vendor interface inside `ocah_<proto>_if`.** The vendor VIP
   brings its own SV interface; instantiate it INSIDE the OCAH interface
   (guarded `ifdef OCAH_<PROTO>_VENDOR_IF` hook), wired from the OCAH
   interface's boundary signals, and publish the nested instance with one
   `uvm_config_db::set`. DUT tb_tops never touch vendor collateral.
5. **Flow.** Vendor compile/setup args ride the existing per-DUT
   `[build.vcs]` `analyze_args`/`compile_args`/`elab_args` and `sources`
   keys (e.g. `-ntb_opts svt`, DesignWare incdirs); license-env gating is
   already part of the commercial profile contract.

Not yet exercised: no Synopsys VIP is integrated today, so this contract is
architecture-verified (env-level override point, monitor-disable knob,
vendor-cfg hook, and interface-nesting hook all exist) but not
integration-tested against a real VC VIP installation.

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
python3 tools/dv/run_dv.py --dut dtp --items dtp_jtag_sample_preload_test --tool vcs
```

## Scope

This package covers IEEE 1149.1 TAP behavior. IJTAG (IEEE 1687),
boundary-scan-specific models, and DTP JTAG2AXI TDR packing remain outside the
shared protocol VIP.
