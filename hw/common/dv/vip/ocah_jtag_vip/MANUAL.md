# OCAH JTAG VIP Manual

SPDX-License-Identifier: Apache-2.0

This manual describes the OCAH IEEE 1149.1 JTAG TAP VIP for cocotb tests.

## Design Boundary

Tests should import `ocah_jtag_vip` classes, not backend classes:

```python
from ocah_jtag_vip import OcahJtagMasterDriver, OcahJtagMasterMonitor, OcahJtagChecker
```

The package uses `cocotbext-jtag` for bus/device compatibility and owns the raw
TAP stepping/scanning semantics needed by DTP. This avoids leaking backend state
machine internals while preserving deterministic one-cycle TMS control.

## TAP Construction

For flattened signal prefixes:

```python
tap = OcahJtagMasterDriver.from_prefix(
    dut,
    "ptap",
    name="ptap",
    ir_width=6,
    tck_period_ns=10,
)
```

For custom signal maps:

```python
tap = OcahJtagMasterDriver(
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

`assert_trst(tck_cycles=1, tms=1)` asserts the bound TRST net and holds TMS at
`tms` for `tck_cycles`, re-baselining the tracked state to `TEST_LOGIC_RESET`.
TMS high is the Test-Logic-Reset self-loop; TMS low never enters
Test-Logic-Reset, so a test that wants Test-Logic-Reset reached by the reset
alone clocks with `tms=0`. `release_trst(tck_cycles=0, tms=1)` releases the net.
After a reset applied outside the TAP pins (a power-on reset, a reset pin
that is not bound as TRST), declare the resulting state with
`sync_model(OcahJtagState.TEST_LOGIC_RESET)` so `goto_state()` plans from the
true controller state. `step(tms, tdi)` drives one TCK cycle with both bits
for bit-serial shifting under the tracked state.

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

`read_idcode()` raises `OcahJtagMasterDriverError` for all-ones readback, which usually
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

`OcahJtagMasterMonitor` passively samples TCK/TMS/TDI/TDO and emits
`OcahJtagScanItem` records.

```python
monitor = OcahJtagMasterMonitor(dut, signal_map={"tck": "jtag_tck", "tms": "jtag_tms"})
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

`OcahJtagMasterConfig` is a plain dataclass describing one TAP connection; explicit
keyword arguments always override its fields. `OcahJtagMasterAgent` bundles driver,
monitor, and checker from one DUT handle, and `OcahJtagMasterSequence` provides
checked scenario operations that emit the same `CHK-*` named evidence as
hand-wired checker calls:

```python
from ocah_jtag_vip import OcahJtagMasterAgent, OcahJtagMasterConfig, OcahJtagMasterSequence

config = OcahJtagMasterConfig(name="ptap", ir_width=6, tck_period_ns=10,
                        signal_map={"tck": "jtag_tck", "tms": "jtag_tms",
                                    "tdi": "jtag_tdi", "tdo": "jtag_tdo",
                                    "trst": "jtag_trst"})
agent = OcahJtagMasterAgent(dut, config=config)
await agent.start()

seq = OcahJtagMasterSequence(agent.tap, agent.checker, monitor=agent.monitor)
await seq.reset_to_tlr()
await seq.read_idcode_checked(expected_idcode)
await seq.check_bypass_latency(pattern, width=64)
seq.check_last_scan_length(is_ir=False, expected_width=64)

await agent.stop()
seq.finalize()
```

`OcahJtagMasterSequence` is the VIP's test-facing stimulus surface: tests drive the
TAP through it (or a DUT sequence layer built on it), never through the raw
driver. Besides the checked operations above it exposes the pass-through scan
API (`step`, `step_tms`, `goto_state`, `shift_ir`, `shift_dr`, `assert_trst`,
`release_trst`, `sync_model`); missing operations
get added here first, never inlined in tests. The checker argument is
optional — one is constructed when omitted.

Sequence checks are pin-level (driven TDI/TMS vs captured TDO plus
monitor-reconstructed scan shapes). Checks that need a DUT-side TAP-state
observable stay in DUT-level sequences that can sample it.

## Slave Side (Reactive TAP Device)

When the DUT is the JTAG **host**, instantiate the slave side: a behavioral
TAP device that responds on TDO. Configure its identity and register map,
start it, and judge the host's traffic through the slave sequence API:

```python
from ocah_jtag_vip import (
    OcahJtagSlaveAgent, OcahJtagSlaveConfig, OcahJtagSlaveSequence,
)

config = OcahJtagSlaveConfig(
    name="stap0", idcode=0x1B34_C0D1, ir_width=5,
    registers={
        "IDCODE": (32, 0x01),
        "CTRL":   (16, 0x02, True),   # writable: latches on Update-DR
        "STATUS": (8,  0x03),         # read-only: presents backdoor value
    },
)
agent = OcahJtagSlaveAgent(dut.stap0_if, config=config)
await agent.start()

seq = OcahJtagSlaveSequence(agent.responder, agent.checker)
seq.set_register("STATUS", 0xA5)      # value the host will read
# ... DUT host traffic runs ...
seq.check_last_update("CTRL", 0xBEEF) # CHK-SLAVE-DR-UPDATE evidence
seq.check_update_count(1, reg_name="CTRL")
seq.finalize()
```

Behavior implemented from the public IEEE Std 1149.1 clause descriptions:
Test-Logic-Reset selects IDCODE (BYPASS when none), IR capture presents `01`
in the LSBs, unknown instructions behave as BYPASS, BYPASS delays TDI to TDO
by one TCK, TDO changes on the falling edge with `tdo_oen` asserted only
while shifting. Registers are limited to 64 bits. The pure-logic engine is
validated standalone by `examples/example_slave_selftest.py`.

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
documented negative validation (a desynced model must FAIL the
`dtp_jtag_tlr_reset_test` run).

## SystemVerilog Layer (interface / sva / cov / uvm)

The SV side of this package compiles through the VIP-owned ordered manifest
`uvm/sources.toml` (incdirs + sources): a consuming DUT lists that manifest in
its `[frameworks.uvm.build].source_lists` and the runner expands it ahead of
the DUT's own sources — never hand-copy these paths into a DUT sim config, and
never add them to Bender filelists. The one entry a cocotb/Verilator build
lists directly in its `[build].sources` is `sva/ocah_jtag_sva.sv`, whose
two-state rules run there. The package's own `dv/` harness binds it in both
shapes: the cocotb shape mirrors the reactive device's TAP state onto the
one-hot input so the state rules run; the SV-UVM shape ties that input off
and runs the pin rules. Its contents:

- `interface/ocah_jtag_if.sv` — shared pin-level IEEE 1149.1 interface
  (JTAG pins only; reused by any DUT).
- `cov/ocah_jtag_cov.sv` — optional-backend functional-coverage
  collateral.
- `sva/ocah_jtag_sva.sv` — SVA protocol rules derived from IEEE 1149.1.
  Two trees by simulator capability: the TDO-timing and TAP-state rules use
  `OCAH_SVA_RULE` (`hw/common/assert/ocah_sva_macros.svh`) and run on every
  simulator, Verilator included under `--assert`, and on licensed formal
  backends under `FORMAL`; the X-hygiene rules and the covers use
  `OCAH_RULE` / `OCAH_COVER` and run on four-state simulators and licensed
  backends only. Each rule belongs to the side that drives its signals, the
  host (TMS, TDI) or the TAP (TDO, its enable, the state), and
  `ASSUME_MASTER_RULES` / `ASSUME_SLAVE_RULES` emit that side's rules as
  assumptions; both default to assertions.
- `sva/ocah_jtag_fv.sv` — the TAP state, TDO and phase rules written in the
  boolean subset the open-source formal frontend reads (`OCAH_FV_RULE`,
  `hw/common/assert/ocah_fv_macros.svh`), with the port list of
  `ocah_jtag_sva` and the same two side parameters; the DTP's formal
  environment binds it on the primary TAP
  (`hw/common/dv/docs/formal-property-style.adoc`, Shared protocol checkers).
- `uvm/ocah_jtag_uvm_pkg.sv` — the SV-UVM VIP: item/config/driver/monitor/
  sequencer/agent plus the encoding-agnostic TAP reference model;
  `ocah_jtag_master_env` is the optional-backend override unit that DUT envs
  instantiate (see the DTP SV-UVM flow for a consuming integration).

## UVM Env Surface Convention

The OCAH VIPs with an SV-UVM layer (`ocah_jtag_vip`, `ocah_axi_vip`) follow one
surface convention, with the JTAG master env as the reference template:

- **Side tokens.** Side-specific components — config, driver, sequencer,
  sequence, agent, env, and agent-attached monitors — carry the side token
  (`_master_*` / `_slave_*`). Wire-level observation classes — items, bus
  monitors, reference models, scoreboards, checkers, coverage subscribers,
  and the passive observation env — are side-neutral: they observe
  DUT-generated traffic regardless of which VIP side, if any, is active.
- **config_db fields.** An env-wrapped unit resolves its config from field
  `cfg` and republishes the same object to its children as `cfg`. A
  standalone reactive agent (the slave stacks) resolves the side-tokened
  field `slave_cfg` instead.
- **Payload-named analysis ports.** An observation port is named
  `<kind>_ap` after the class it streams, mirroring the cocotb monitor
  callback names: `event_ap` (`ocah_jtag_event`), `scan_ap`
  (`ocah_jtag_scan_item`), `item_ap` (`ocah_axi_item`). Port names differ
  across VIPs because the payloads differ, and the name tells a DUT env what
  it is subscribing to.
- **Frozen surface is env-top-level handles only.** Everything a DUT env,
  test, or sequence may depend on is a direct member of the VIP env — the
  env promotes child handles (`m_sequencer` on `ocah_jtag_master_env` and
  `ocah_axi_master_env`, `m_checker` on `ocah_axi_env`) rather than
  letting consumers reach through its children.

## Backend Boundary

The package depends on `cocotbext-jtag>=0.4.0,<0.5`. The active OCAH driver
does not expose backend transaction objects; `backend_bus` and
`create_backend_driver()` are debug-only escape hatches.

## DTP Validation

Run in a Python 3.11-3.13 OSS DV environment:

```bash
python3 tools/dv/run_dv.py --doctor --dut dtp
python3 tools/dv/run_dv.py --dut dtp --items dtp_sanity_test --tool verilator
python3 tools/dv/run_dv.py --dut dtp --items dtp_jtag_idcode_test --tool verilator
python3 tools/dv/run_dv.py --dut dtp --items dtp_jtag_bypass_test --tool verilator
python3 tools/dv/run_dv.py --dut dtp --items dtp_jtag_sample_preload_test --tool verilator
```

For broader coverage, run the full `basic_jtag` group:

```bash
python3 tools/dv/run_dv.py --dut dtp --items basic_jtag --tool verilator
```

`DTP_JTAG_TAP_CHECKER_NEGATIVE` is the must-fail hook of both flows: as an
environment variable it desynchronizes the cocotb TAP reference model so
`CHK-TAP-STATE` fails; as a plusarg (`--plusarg=+DTP_JTAG_TAP_CHECKER_NEGATIVE`)
it arms a wrong expected IDCODE in the SV-UVM `dtp_jtag_tlr_reset_test` and
`dtp_sanity_test` so `CHK-TAP-TLR-IDCODE` fails. `cocotb/examples/example_slave_selftest.py`
judges the reactive slave device by the master-side model with no simulator.
