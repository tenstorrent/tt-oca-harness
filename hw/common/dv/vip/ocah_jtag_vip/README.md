# ocah_jtag_vip - OCAH JTAG TAP VIP

SPDX-License-Identifier: Apache-2.0

`ocah_jtag_vip` provides OCAH-stable IEEE 1149.1 TAP helpers for cocotb
testbenches. Tests import OCAH classes and plain dataclasses; backend
`cocotbext-jtag` objects stay inside the wrapper boundary.

## Backend

| OCAH class | Backend / implementation |
|---|---|
| `OcahJtagMasterDriver` | `cocotbext-jtag` `JTAGBus` plus OCAH raw TAP stepping/scanning |
| `OcahJtagDevice` | Plain wrapper convertible to `cocotbext-jtag` `JTAGDevice` |
| `OcahJtagMasterMonitor` | OCAH passive sampler that emits `OcahJtagScanItem` |
| `OcahJtagSlaveDriver` | Pure OCAH reactive TAP device (no backend dependency) |
| `OcahJtagChecker` | OCAH item-level checker |

`cocotbext-jtag` is pinned in `pyproject.toml` as `>=0.4.0,<0.5`.

## Pin Timing

The active cocotb and UVM drivers use the same IEEE 1149.1 cycle contract:
drive TMS/TDI while TCK is low, sample TDO in that low phase before the rising
edge, then raise TCK so the target captures inputs and advances its TAP state.
Sampling after the rising edge is invalid on the final scan bit because that
edge also exits `SHIFT_IR` or `SHIFT_DR`. The cocotb driver samples in the
`ReadOnly` phase and advances to the next timestep before driving TCK, avoiding
simulator-dependent stale reads.

## Cocotb Checker Evidence

`OcahJtagChecker` carries the IEEE 1149.1 item checks and composes the shared
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

`check_item()` checks scan width, IDCODE marker shape, and BYPASS record
shape. `expect_equal()`/`expect_true()` add named exact-value evidence.
`finalize()` fails on retained protocol errors, failed evidence, zero checks, or
missing required IDs.

The checker also carries an `OcahJtagTapRefModel` (a pure-Python IEEE 1149.1
TAP controller model) and exposes reference-model-backed named checks for the
core TAP contracts:

| Method | Check ID | Contract |
|---|---|---|
| `check_reset_to_tlr(observed)` | `CHK-TAP-RESET-TLR` | A TAP reset lands in Test-Logic-Reset |
| `check_state_step(tms, observed)` | `CHK-TAP-STATE` | Each TMS step matches the reference FSM |
| `check_tms_ones_to_tlr(n, observed)` | `CHK-TAP-TLR-TMS5` | >= 5 TMS-high cycles force TLR from any state |
| `check_bypass_latency(tdo, ...)` | `CHK-BYPASS-LATENCY` | BYPASS delays TDI to TDO by exactly one TCK |
| `check_scan_length(item, ...)` | `CHK-SCAN-IR-LEN` / `CHK-SCAN-DR-LEN` | Monitor-observed bit count equals the driven width |

`check_state_step()` predicts from the model's tracked state; after
BFM-internal navigation (for example a scan that returns to Run-Test/Idle),
call `sync_state()` so predictions restart from the true controller state.

Monitors log and catch callback exceptions, so an attached checker retains its
protocol error before raising, and the owning test or scoreboard must call
`finalize()` after traffic. For worked integrations, see
the DTP `dtp_jtag_idcode_test`, `dtp_jtag_bypass_test`,
`dtp_jtag_tlr_reset_test`, and `dtp_jtag_trst_test` sequences (via
`dtp_jtag_base_test_seq.attach_tap_checker`).

## Package Layout

The package follows the OCAH VIP component contract — Agent (`_agent`),
Configuration (`_config`), Driver (`_driver`), Monitor (`_monitor`),
Reference Model (`_ref_model`), Coverage (`_cov`), SVA (`_sva`), Sequence API
(`_sequence`), and Sequencer (`_sequencer`, UVM only) — with at least one
file per component and the canonical suffix in each filename:

```text
ocah_jtag_vip/
  __init__.py            - public exports
  cocotb/ocah_jtag_master_agent.py     - composed driver/monitor/checker bundle
  cocotb/ocah_jtag_master_config.py    - plain configuration dataclass
  cocotb/ocah_jtag_master_driver.py    - active TAP driver (OcahJtagMasterDriver)
  cocotb/ocah_jtag_device.py    - device/register map
  cocotb/ocah_jtag_item.py      - scan/state item dataclasses
  cocotb/ocah_jtag_master_monitor.py   - passive item-producing monitor
  cocotb/ocah_jtag_checker.py   - item-level checker with named TAP evidence
  cocotb/ocah_jtag_ref_model.py - pure-Python IEEE 1149.1 TAP reference model
  cocotb/ocah_jtag_master_sequence.py  - checked scenario operations (sequence API)
  cocotb/ocah_jtag_slave_agent.py      - slave (device-side) agent bundle
  cocotb/ocah_jtag_slave_config.py     - slave device configuration
  cocotb/ocah_jtag_slave_driver.py     - reactive TAP device engine + pin pump
  cocotb/ocah_jtag_slave_monitor.py    - slave-side passive monitor
  cocotb/ocah_jtag_slave_sequence.py   - slave test-facing API (configure/inspect)
  cocotb/ocah_jtag_state.py     - TAP state enum and TMS path helpers
  cocotb/examples/
    example_idcode.py         - PTAP/STAP/CPU TAP usage examples
    example_slave_selftest.py - standalone slave-engine selftest (runnable)
  interface/
    ocah_jtag_if.sv      - shared pin-level IEEE 1149.1 interface (JTAG pins only)
  cov/
    ocah_jtag_cov.sv     - covergroup interface for optional backends
  sva/
    ocah_jtag_sva.sv     - protocol assertions derived from IEEE 1149.1
    ocah_jtag_fv.sv      - the TAP state, TDO and phase rules in the boolean
                           subset formal environments bind; both checkers assert
                           or assume each side by parameter
  uvm/
    ocah_jtag_uvm_pkg.sv - SV-UVM agent package (see below)
  dv/                    - simulated VIP selftests on a wire harness (the shared
                           master against the shared reactive TAP device, the
                           protocol SVA on the nets), one scenario set for both
                           frameworks:
                           python3 tools/dv/run_dv.py --dut ocah_jtag_vip --items smoke
                           python3 tools/dv/run_dv.py --dut ocah_jtag_vip --items all --cov
                           python3 tools/dv/run_dv.py --dut ocah_jtag_vip \
                               --framework uvm --items smoke --skip-unimplemented
```

## SV-UVM Agent (`uvm/`)

`ocah_jtag_uvm_pkg` provides a reusable SV-UVM agent over `ocah_jtag_if`:

| Component | Role |
|---|---|
| `ocah_jtag_item` | Stimulus item: `TAP_RESET`, `TRST_LEVEL`, `IR_SCAN`, `DR_SCAN`, `RAW_TMS`; driver fills observed TDO in-place |
| `ocah_jtag_master_config` | vif, `is_active`, TCK half-period, TRST reset cycles, `en_cov` (file: `ocah_jtag_master_config.svh`) |
| `ocah_jtag_ref_model` | IEEE 1149.1 TAP controller reference model (state tracking, BYPASS TDO prediction, one-hot helpers) |
| `ocah_jtag_master_sequence` | VIP-level stimulus API: raw steps/walks, IR/DR scans (incl. wide), TAP reset, TRST level control (`assert_trst`/`release_trst`), and tracked-state navigation (`goto_state`, `goto_random_state`, `random_tms_walk`, `current_state`, `sync_model`) — DUT sequence libraries extend it |
| `ocah_jtag_master_driver` | Pin-level TCK bit-bang; scans navigate RTI -> scan leg -> RTI |
| `ocah_jtag_master_monitor` | Passive: per-TCK `STEP` events (published on the falling edge) + async `TRST` events via `event_ap` |
| `ocah_jtag_scan_builder` | Subscriber reconstructing IR/DR scans from the step stream (reference-FSM walk); publishes `ocah_jtag_scan_item` on `scan_ap` with bounded history |
| `ocah_jtag_checker` | Named-evidence checker (`CHK-*`/`CHECKER_SUMMARY`, same grammar as `ocah_axi_checker`) over the reference model: `check_reset_to_tlr`, `check_state_step`, `check_tms_ones_to_tlr`, `check_bypass_latency` (`predict_bypass_tdo`), `check_scan_length` |
| `ocah_jtag_cov` | Optional coverage subscriber (`cfg.en_cov`): samples `cov/ocah_jtag_cov.sv` covergroups from the step stream; `scan_export` accepts a scan builder's items |
| `ocah_jtag_master_sequencer` | `uvm_sequencer #(ocah_jtag_item)` |
| `ocah_jtag_master_agent` | Standard bundle; monitor when `en_monitor`, driver/sequencer when active |
| `ocah_jtag_master_env` | VIP-level env: what DUTs instantiate and optional backend integrations override |
| `ocah_jtag_slave_config` | Slave device configuration: IDCODE, IR width, register map (`add_reg`), `drive_tdo_oen` |
| `ocah_jtag_slave_driver` | Reactive TAP device responder: capture/shift/update per IEEE 1149.1, Update-DR latches recorded in `updates` |
| `ocah_jtag_slave_monitor` | Slave-side passive observer (same `ocah_jtag_event` stream as the master monitor) |
| `ocah_jtag_slave_sequence` | Slave test-facing API: `set_register`/`get_register`, `check_last_update`, `check_update_count`, `check_register` (a value still held, independent of the update history), `check_state` (the device's TAP controller state) |
| `ocah_jtag_slave_agent` | Slave bundle (reactive: no sequencer — the external host supplies all stimulus) |

`sva/ocah_jtag_sva.sv` is the pin-level protocol assertion module (X-hygiene,
TDO falling-edge timing, and — when a DUT exports its one-hot TAP state —
state-encoding/transition legality, TRST/TMS-walk reset behavior, and the
TDO-enable shift-only window, each citing its IEEE Std 1149.1 clause). It is
instantiated at TB scope next to flattened nets or bound into a hierarchy,
with a runtime `en_i` suppress knob; the DTP integration wires it to the
primary TAP with `dtp_tb_if.jtag_sva_en`. The TDO-timing and TAP-state rules
run on every simulator (Verilator under `--assert`); the X-hygiene rules run
on four-state simulators only.

The package also ships an encoding-agnostic IEEE 1149.1 TAP model
(`ocah_jtag_tap_state_e`, `ocah_jtag_next_state()`, and the shortest-path
planner `ocah_jtag_tms_path()`; state values match the conventional 0..15
numbering, i.e. the bit index of one-hot RTL encodings) for DUT-side
checkers. The base sequence tracks the predicted TAP state through an owned
reference model, so `goto_state()` plans from wherever the previous
operation ended — the same navigation semantics as the cocotb
`OcahJtagMasterDriver.goto_state()`. Per-cycle pairing of monitor steps with a DUT's
decoded TAP state stays DUT-side (DTP's `dtp_tap_fsm_checker`, which reports
an aggregate `CHK-TAP-STATE` through the shared `ocah_jtag_checker`);
scan-level reconstruction and the named TAP-contract evidence are VIP-owned,
mirroring the cocotb checker's check IDs. For a full integration example, see
the DTP SV-UVM flow's (`--dut dtp --framework uvm`) `dtp_sanity_test`, which requires
`CHK-TAP-RESET-TLR`, `CHK-TAP-TLR-TMS5`, `CHK-TAP-GOTO`,
`CHK-TAP-TLR-IDCODE`, `CHK-IDCODE-RAW/STABLE/MARKER`, `CHK-BYPASS-LATENCY`,
and `CHK-SCAN-IR-LEN/DR-LEN`, and arms the must-FAIL negative validation via
`+DTP_JTAG_TAP_CHECKER_NEGATIVE`. SV-UVM collateral compiles on the optional
backends reported for that framework and is excluded from Verilator builds.

## Slave Side (Reactive TAP Device)

The slave side is a behavioral IEEE 1149.1 TAP device for testing DUTs that
act as JTAG **hosts** (e.g. downstream STAP host ports): it tracks the
controller from TCK/TMS, implements IR capture (LSBs `01`), IDCODE, BYPASS,
unknown-instruction-as-BYPASS, and a user data-register map, and responds on
TDO (plus `tdo_oen` while shifting). Writable registers latch on Update-DR
and every latch is recorded for test inspection; read-only registers present
backdoor-set values on Capture-DR. Data registers are limited to 64 bits.

The device is reactive — the external host supplies all TCK/TMS/TDI
stimulus — so the slave agent has no sequencer; tests configure and judge it
through the `_slave_sequence` API. The protocol engine
(`OcahJtagSlaveEngine`) holds no simulator handles and is validated
standalone against the master-side reference model by
`cocotb/examples/example_slave_selftest.py` (runnable with plain Python).
The DTP testbench consumes it: its STAP-selection scenarios splice
one slave device behind each `jtag_stap_*_host` port (cocotb
`hw/sys/dtp/dv/cocotb/env/dtp_stap_ds_agent.py`, SV-UVM `dtp_env`) and judge
selection, gating, and recovery through `check_last_update`,
`check_update_count`, `check_register`, and `check_state`.

## Template Contract (per-protocol VIPs and optional backends)

This VIP is the template for OCAH SV-UVM VIPs. DUT environments instantiate
`ocah_<proto>_env`; the VIP-level environment is the reuse and override unit.
Its frozen surface is:

| Surface | Role |
|---|---|
| `m_sequencer` | scenario handle: DUT sequences issue `ocah_<proto>_item`s here |
| `event_ap` | `ocah_<proto>_event` observation stream (silent when `cfg.en_monitor=0`) |
| `cfg` | `ocah_<proto>_cfg`, incl. opaque `vendor_cfg` extension hook |

Everything above that surface (DUT sequences, tests, checkers, testlists)
depends only on the item and event types, never on driver/monitor internals.

The open tree carries the opaque `vendor_cfg` extension, the
`cfg.en_monitor` knob, the guarded vendor-interface nest, and the
factory-overridable environment. An optional backend integration follows
these rules:

1. **Inherit the environment.** Subclass `ocah_<proto>_env`, carry the
   backend configuration object through `cfg.vendor_cfg`, and select the
   subclass with one factory override.
2. **Implement the API wrapper.** Convert incoming `ocah_<proto>_item`
   objects into backend operations and fill the item response fields before
   `item_done`. Keep the public item and result surfaces unchanged.
3. **Select one observation path.** Set `cfg.en_monitor = 0` when the backend
   owns monitoring. Feed `ocah_<proto>_event` subscribers through an adapter
   so DUT scoreboards remain backend-independent.
4. **Bind the vendor interface.** Supply the guarded interface include from
   an adopter overlay, wire it from the OCAH interface boundary signals, and
   publish the nested instance through `uvm_config_db`. DUT tops remain
   backend-neutral.
5. **Keep deployment external.** The adopter overlay carries backend sources,
   include directories, defines, simulator flags, and factory overrides.
   The open tree remains runnable without the overlay.

## Quick Start

```python
from ocah_jtag_vip import OcahJtagMasterDriver

tap = OcahJtagMasterDriver.from_prefix(
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

## Public API

| Method | Purpose |
|---|---|
| `from_prefix(dut, prefix, ...)` | Construct from flattened JTAG signals |
| `from_bus(bus, ...)` | Construct from an existing `JTAGBus` |
| `init_signals()` | Drive idle values before traffic |
| `await reset_tap(cycles=10)` | Drive TAP to Test-Logic-Reset |
| `await assert_trst(tck_cycles=1)` / `await release_trst(tck_cycles=0)` | Drive the bound TRST net, then hold TMS high for `tck_cycles`; asserting re-baselines the tracked state to Test-Logic-Reset |
| `await step(tms, tdi=0)` / `await step_tms(tms)` | Drive one TCK cycle with the given TMS and TDI and return sampled TDO |
| `sync_model(state, instruction=None)` | Declare the TAP state after movement the driver did not drive (a power-on reset, a reset pin outside the bound TAP) |
| `await shift_ir(value, width=None, back_to_rti=False)` | Shift IR, return captured TDO |
| `await shift_dr(value, width, back_to_rti=False)` | Shift DR, return captured TDO |
| `await read_idcode()` | Read 32-bit IDCODE |
| `await bypass()` | Load all-ones BYPASS |
| `await goto_state(state)` | Navigate using shortest TMS path |
| `get_statistics()` | Return plain counters and tracked state |

`reset_tap()` leaves the tracked TAP state in `TEST_LOGIC_RESET`; step
`TMS=0` afterwards to reach `RUN_TEST_IDLE`.

No driver operation waits on the DUT: every reset, step, walk, and scan runs
a fixed number of TCK cycles, so the driver carries no timeout bound.

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
from ocah_jtag_vip import OcahJtagChecker, OcahJtagMasterMonitor

monitor = OcahJtagMasterMonitor(dut, signal_map={"tck": "jtag_tck", "tms": "jtag_tms"})
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
`to_record()` for dict-shaped callback code.

## Validation

Validate changes on the package's own wire harness first, then against the
DTP, SMC, and SMU consumers:

```bash
python3 tools/dv/run_dv.py --dut ocah_jtag_vip --items smoke --tool verilator
python3 tools/dv/run_dv.py --dut ocah_jtag_vip --items all --tool verilator --cov
python3 tools/dv/run_dv.py --dut ocah_jtag_vip --framework uvm --items smoke --skip-unimplemented --cov
python3 tools/dv/run_dv.py --doctor --dut dtp
python3 tools/dv/run_dv.py --dut dtp --items dtp_sanity_test dtp_jtag_idcode_test dtp_jtag_bypass_test --tool verilator
python3 tools/dv/run_dv.py --dut dtp --items basic_jtag --tool verilator --cov
python3 tools/dv/run_dv.py --dut dtp --framework uvm --items smoke --skip-unimplemented
python3 tools/dv/run_dv.py --dut smc --items smc_jtag_dmi_smoke_test smc_ijtag_basic_test --tool verilator
python3 tools/dv/run_dv.py --dut smu --items smu_dtp_jtag_smoke_test smu_jtag_chain_enhanced_test --tool verilator
```

Must-fail checks; each command exits non-zero:

```bash
# harness, both flows: the reference model is desynchronized before the TMS
# walk (cocotb) or a wrong expected IDCODE is armed (SV-UVM).
OCAH_JTAG_SELFTEST_NEGATIVE=1 python3 tools/dv/run_dv.py --dut ocah_jtag_vip --items ocah_jtag_tap_reset_test --tool verilator
python3 tools/dv/run_dv.py --dut ocah_jtag_vip --framework uvm --items ocah_jtag_idcode_test \
    --skip-unimplemented --plusarg=+OCAH_JTAG_SELFTEST_NEGATIVE
# cocotb: the TAP reference model is desynchronized, so CHK-TAP-STATE fails.
DTP_JTAG_TAP_CHECKER_NEGATIVE=1 python3 tools/dv/run_dv.py --dut dtp --items dtp_jtag_tlr_reset_test --tool verilator
# SV-UVM: a wrong expected IDCODE is armed, so CHK-TAP-TLR-IDCODE fails.
python3 tools/dv/run_dv.py --dut dtp --framework uvm --items dtp_jtag_tlr_reset_test \
    --skip-unimplemented --plusarg=+DTP_JTAG_TAP_CHECKER_NEGATIVE
```

The reactive slave device is judged by the master-side model without a
simulator:

```bash
PYTHONPATH=hw/common/dv/vip python3 hw/common/dv/vip/ocah_jtag_vip/cocotb/examples/example_slave_selftest.py
```

## Supported behavior and limitations

| Area | This package provides | Outside this package |
|---|---|---|
| TAP control | `reset_tap()` (TMS walk into Test-Logic-Reset), `assert_trst()` / `release_trst()` on a bound TRST net, `goto_state()` along the shortest legal TMS path, `step()` for one raw TCK, `sync_model()` to re-seat the tracked state | TAP state changes the driver did not cause (a DUT-side reset); the test re-seats the model with `sync_model()` |
| Scans | `shift_ir()` / `shift_dr()` at any width, returning the captured bits; SV-UVM wide scans through `ocah_jtag_scan_item`; IDCODE and BYPASS helpers; named registers through `OcahJtagDevice` | iJTAG (IEEE 1687) networks, boundary-scan cell models, DTP TDR packing and polling (DUT-local) |
| Timing | TMS and TDI driven while TCK is low, TDO sampled in that low phase; `tck_period_ns` per driver | TCK-to-TDO skew or hold-time modeling |
| Reset semantics | Optional TRST with `trst_active_high`; every reset lands the tracked state in Test-Logic-Reset and clears the current instruction | — |
| Timeout | No operation waits on the DUT, so none can time out; the driver carries no timeout knob | — |
| Errors and evidence | Monitors hold callback exceptions and re-raise them; `OcahJtagChecker.finalize()` fails on a held error, a failed check, zero checks, or a missing required ID; every harness selftest carries an in-band negative probe (cocotb), and `OCAH_JTAG_SELFTEST_NEGATIVE` (harness) or `DTP_JTAG_TAP_CHECKER_NEGATIVE` (DTP bench) forces a failing run in both flows | — |
| Slave side | Reactive TAP device with IDCODE, BYPASS, undefined instructions as BYPASS, and a register map that latches on Update-DR, holding its shift registers across Pause-x and latching the captured value on a scan with no Shift-x cycle; simulator-free selftest | A DUT-specific register decode beyond the map |
| Protocol checking | `sva/ocah_jtag_sva.sv` (TDO falling-edge timing, TLR via TMS and TRST, one-hot state legality with an exported state, X-hygiene on four-state simulators), bound in the `dv/` harness (state rules from the device's mirrored state in the cocotb shape, pin rules in the SV-UVM shape) and in the DTP, SMU, and SMC benches; `sva/ocah_jtag_fv.sv` carries the state, TDO and phase rules in the boolean subset a formal environment binds, the host side and the TAP side each asserted or assumed by parameter | State rules in the SV-UVM harness shape, where the device state stays inside the slave driver |
| Coverage | `cov/ocah_jtag_cov.sv` covergroups through the SV-UVM `ocah_jtag_cov` subscriber (`en_cov`), sampled by the SV-UVM harness (`--dut ocah_jtag_vip --framework uvm --cov`); SVA cover properties on four-state simulators; Verilator line and branch coverage of the SVA through `--dut ocah_jtag_vip --cov`, graded by `dv/cov/config/verilator/coverage_policy.toml`, and through the DTP bench | Covergroups on Verilator |
| Simulators | Verilator and the optional backends reported by `run_dv.py --list` | Backends outside the selected framework's allowlist |

## Scope

This package covers IEEE 1149.1 TAP behavior. IJTAG (IEEE 1687),
boundary-scan-specific models, and DTP JTAG2AXI TDR packing remain outside the
shared protocol VIP.
