# OCAH JTAG VIP Manual

SPDX-License-Identifier: Apache-2.0

This manual describes the released OCAH IEEE 1149.1 JTAG TAP VIP for OSS
cocotb tests.

## Design Boundary

Tests should import `ocah_jtag_vip` classes, not backend classes:

```python
from ocah_jtag_vip import OcahJtagTap, OcahJtagMonitor, OcahJtagChecker
```

The package uses `cocotbext-jtag` for bus/device compatibility and owns the raw
TAP stepping/scanning semantics needed by DTP. This avoids leaking backend state
machine internals while preserving deterministic one-cycle TMS control.

## TAP Construction

For flattened signal prefixes:

```python
tap = OcahJtagTap.from_prefix(
    dut,
    "ptap",
    name="ptap",
    ir_width=6,
    tck_period_ns=10,
)
```

For custom signal maps:

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

Default logical signal names are `tck`, `tms`, `tdi`, `tdo`, and optional
`trst`. `tdo_oen` can be present in the signal map for consistency, but the
active driver does not require it.

## TAP Reset And State Navigation

`reset_tap()` asserts active-low TRST when present and drives TMS high for at
least five TCK cycles. It leaves the tracked state at `TEST_LOGIC_RESET`.

```python
await tap.reset_tap()
await tap.step_tms(0)  # enter RUN_TEST_IDLE
```

Use `goto_state()` for deterministic shortest-path navigation:

```python
from ocah_jtag_vip import OcahJtagState

await tap.goto_state(OcahJtagState.SHIFT_DR)
```

Use `random_tms_walk(cycles, rng)` only with a dedicated seeded `random.Random`
object so replay remains deterministic.

## IR And DR Scans

`shift_ir()` and `shift_dr()` accept and return plain integers. Bits are shifted
LSB first.

Each bit cycle drives TMS/TDI while TCK is low and samples TDO before raising
TCK. The rising edge then captures TMS/TDI and advances the TAP state. This
ordering is especially important for the final bit, whose rising edge exits
`SHIFT_IR` or `SHIFT_DR`; TDO sampled afterward is no longer guaranteed to
belong to that scan bit. Cocotb performs the low-phase read in `ReadOnly` and
returns to a writable phase on the next timestep before raising TCK, making the
sample deterministic across event schedulers.

```python
captured_ir = await tap.shift_ir(0x01, width=6, back_to_rti=False)
idcode = await tap.shift_dr(0, width=32, back_to_rti=True)
```

When `back_to_rti=False`, scans leave the TAP in `SELECT_DR_SCAN`, which lets a
raw IR scan be followed immediately by a DR scan. When `back_to_rti=True`, the
scan ends in `RUN_TEST_IDLE`.

## IDCODE And BYPASS

```python
idcode = await tap.read_idcode()
fields = tap.decode_idcode(idcode)
await tap.bypass()
```

`read_idcode()` raises `OcahJtagTapError` for all-ones readback, which usually
means the chain is in BYPASS or no TAP device responded.

## Device Register Maps

Use `OcahJtagDevice` for named register reads/writes:

```python
device = OcahJtagDevice(name="dtp", idcode=0x0000_0001, ir_width=6, idle_delay=64)
device.add_reg("IDCODE", 32, 0x01)
device.add_reg("SMC_AXI_SINGLE_OP", 98, 0x28, write=True)
tap.add_device(device)

value = await tap.read("IDCODE")
await tap.write("SMC_AXI_SINGLE_OP", payload)
```

The shared VIP only owns generic scan mechanics. DTP-specific TDR payload
packing, polling, and scoreboard publication stay in DTP code.

## Monitor And Checker

`OcahJtagMonitor` passively samples TCK/TMS/TDI/TDO and emits
`OcahJtagScanItem` records.

```python
monitor = OcahJtagMonitor(dut, signal_map={"tck": "jtag_tck", "tms": "jtag_tms"})
checker = OcahJtagChecker(ir_width=6)
checker.attach_monitor(monitor)

items = []
monitor.add_item_callback(items.append)
await monitor.start()

# Run traffic.

await monitor.stop()
checker.assert_clean()
```

`OcahJtagScanItem` fields include `kind`, `tdi_value`, `tdo_value`,
`bit_count`, `instruction`, `start_time_ns`, `end_time_ns`, `start_state`,
`end_state`, and `source`.

## Config, Agent, And Sequence API

`OcahJtagConfig` is a plain dataclass describing one TAP connection; explicit
keyword arguments always override its fields. `OcahJtagAgent` bundles driver,
monitor, and checker from one DUT handle, and `OcahJtagSequence` provides
checked scenario operations that emit the same `CHK-*` named evidence as
hand-wired checker calls:

```python
from ocah_jtag_vip import OcahJtagAgent, OcahJtagConfig, OcahJtagSequence

config = OcahJtagConfig(name="ptap", ir_width=6, tck_period_ns=10,
                        signal_map={"tck": "jtag_tck", "tms": "jtag_tms",
                                    "tdi": "jtag_tdi", "tdo": "jtag_tdo",
                                    "trst": "jtag_trst"})
agent = OcahJtagAgent(dut, config=config)
await agent.start()

seq = OcahJtagSequence(agent.tap, agent.checker, monitor=agent.monitor)
await seq.reset_to_tlr()
await seq.read_idcode_checked(expected_idcode)
await seq.check_bypass_latency(pattern, width=64)
seq.check_last_scan_length(is_ir=False, expected_width=64)

await agent.stop()
seq.finalize()
```

Sequence checks are pin-level (driven TDI/TMS vs captured TDO plus
monitor-reconstructed scan shapes). Checks that need a DUT-side TAP-state
observable stay in DUT-level sequences that can sample it.

## TAP Reference Model And Named TAP Checks

`OcahJtagTapRefModel` is a pure-Python IEEE 1149.1 TAP controller model with
no simulator handles. Every `OcahJtagChecker` owns one (or accepts a shared
instance via `ref_model=`) and exposes reference-model-backed named evidence:

```python
checker = OcahJtagChecker(
    required_ids={"CHK-TAP-RESET-TLR", "CHK-TAP-STATE", "CHK-TAP-TLR-TMS5"},
)

# TAP reset must land in Test-Logic-Reset.
checker.check_reset_to_tlr(observed_state)

# Every raw TMS step must match the reference FSM prediction.
checker.check_state_step(tms, observed_state)

# Five or more TMS-high TCK cycles must force TLR from any state.
checker.check_tms_ones_to_tlr(ones_count, observed_state)

# BYPASS must delay TDI to TDO by exactly one TCK.
checker.check_bypass_latency(observed_tdo, pattern=pattern, width=width)

# Monitor-observed scan bit counts must equal the driven widths.
checker.check_scan_length(scan_item, expected_width=width)

checker.finalize()
```

`check_state_step()` predicts from the model's tracked state. Scan helpers
that navigate internally (for example back-to-RTI legs) move the TAP without
per-step visibility; call `checker.sync_state(state)` at those landing points
so the next prediction starts from the true controller state. On a mismatch
in aggregate mode the model re-aligns to the observed state so later steps
stay meaningful.

The DTP `dtp_jtag_base_test_seq.attach_tap_checker()` hook wires these checks
into TAP navigation automatically; `DTP_JTAG_TAP_CHECKER_NEGATIVE=1` runs the
documented negative validation (a deliberately desynced model must FAIL the
`dtp_jtag_tlr_reset_test` run).

## Backend And License Status

The package depends on `cocotbext-jtag>=0.4.0,<0.5`. The installed 0.4.0 package
metadata reports license `MIT`. The active OCAH driver does not expose backend
transaction objects; advanced users may inspect `backend_bus` or call
`create_backend_driver()`, but those are debug-only escape hatches.

## DTP Validation

Run in a Python 3.11-3.13 OSS DV environment:

```bash
python3 tools/dv/run_dv.py --doctor --dut dtp
python3 tools/dv/run_dv.py --dut dtp --items dtp_sanity_test --tool verilator
python3 tools/dv/run_dv.py --dut dtp --items dtp_jtag_idcode_test --tool verilator
python3 tools/dv/run_dv.py --dut dtp --items dtp_jtag_bypass_test --tool verilator
python3 tools/dv/run_dv.py --dut dtp --items dtp_jtag_sample_preload_test --tool vcs
```

For broader coverage, run the full `basic_jtag` group:

```bash
python3 tools/dv/run_dv.py --dut dtp --items basic_jtag --tool verilator
```
