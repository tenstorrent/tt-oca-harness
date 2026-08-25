# OCAH AXI VIP Manual

SPDX-License-Identifier: Apache-2.0

This manual describes the released OCAH AXI wrapper API for OSS cocotb tests.
Use this package for AXI4, AXI4-Lite, and memory-backed AXI responders instead
of importing backend BFMs directly.

## Supported Backends

The released master and responder classes use `cocotbext-axi`:

| OCAH class | Backend |
|---|---|
| `OcahAxiMasterAgent` | `cocotbext.axi.AxiMaster` |
| `OcahAxiLiteMasterAgent` | `cocotbext.axi.AxiLiteMaster` |
| `OcahAxiSlaveAgent` | OCAH RAM wrapper over `cocotbext-axi` AXI channels |
| `OcahAxiLiteSlaveAgent` | OCAH RAM wrapper over `cocotbext-axi` AXI-Lite channels |
| `OcahAxiMonitor` / `OcahAxiLiteMonitor` | OCAH passive samplers that emit item dataclasses |
| `OcahAxiChecker` | OCAH item-level checker |

## Package Shape

The VIP follows the OCAH VIP taxonomy with per-side naming: side-specific
components carry the side token (`_master_*` / `_slave_*`, per protocol stem
`ocah_axi` / `ocah_axi_lite`); wire-level shared collateral (items, monitors,
checker, reference model, scoreboard, watchers, coverage, SVA) is
side-neutral and carries no token.

| File | Purpose |
|---|---|
| `cocotb/ocah_axi[_lite]_master_agent.py` | Master bundle: builds driver + sequence (+ optional monitor) |
| `cocotb/ocah_axi[_lite]_master_config.py` | Master construction/timing/policy knobs |
| `cocotb/ocah_axi[_lite]_master_driver.py` | cocotbext-axi initiator engine binding |
| `cocotb/ocah_axi[_lite]_master_sequence.py` | Test-facing master API (write/read/burst/results) |
| `cocotb/ocah_axi[_lite]_slave_agent.py` | Responder bundle: builds driver + sequence |
| `cocotb/ocah_axi[_lite]_slave_config.py` | Responder memory/reset/backend knobs |
| `cocotb/ocah_axi[_lite]_slave_driver.py` | Fault-capable RAM responder engine |
| `cocotb/ocah_axi[_lite]_slave_sequence.py` | Test-facing responder API (backdoor/inject/backpressure) |
| `cocotb/ocah_axi_item.py` | Generic AXI/AXI-Lite transaction items (side-neutral) |
| `cocotb/ocah_axi_monitor.py` | Passive item-producing bus monitors (side-neutral) |
| `cocotb/ocah_axi_checker.py` | Item-level protocol checker (side-neutral) |
| `cocotb/ocah_axi_results.py` | Result dataclasses and response-code helpers |
| `cov/ocah_axi_cov.sv` | Commercial-simulator functional coverage hook |

Tests always drive a side through its `*Sequence` class — usually
`agent.sequence` — never through the raw driver; missing operations get
added to the sequence layer first.

## Import Pattern

```python
from ocah_axi_vip import (
    OcahAxiMasterAgent,
    OcahAxiLiteMasterAgent,
    OcahAxiSlaveAgent,
    OcahAxiLiteSlaveAgent,
    OcahAxiMonitor,
    OcahAxiChecker,
    RESP_OKAY,
    RESP_SLVERR,
    RESP_DECERR,
)
```

Do not import `cocotbext.axi.AxiMaster`, `AxiLiteMaster`, `AxiRam`, or backend
response enums in new OCAH tests. Add missing behavior to this wrapper instead.

## AXI4-Lite Master

Use `OcahAxiLiteMasterAgent` for register-style AXI4-Lite accesses.

```python
master = OcahAxiLiteMasterAgent.from_prefix(
    dut,
    "cfg_axil",
    dut.clk_i,
    dut.rst_ni,
    reset_active_level=False,
    data_width=32,
    timeout_ns=50_000,
).sequence

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

Use `OcahAxiMasterAgent` for full AXI4 single-beat or burst traffic.

```python
master = OcahAxiMasterAgent.from_prefix(
    dut,
    "s_axi",
    dut.clk_i,
    dut.rst_ni,
    reset_active_level=False,
    data_width=64,
).sequence

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
| `issued_id` | The AWID/ARID the master drove (`0` when the caller used the default) |
| `observed_id` | BID/RID sampled from the live response handshake, or `None` (see below) |
| `raw` | Backend object for debug only |

`OcahAxiReadResult` adds:

| Field | Meaning |
|---|---|
| `data` | First data beat as an integer |
| `data_bytes` | Raw read payload as bytes |
| `data_words` | One integer per beat |

### Response-ID observation

Every blocking AXI4 result carries the issued request ID and a response ID
sampled independently from the live B/R handshake (`OcahAxiIdCapture` inside
the master driver) — never a copy of the issued ID, so an `observed_id ==
issued_id` check is non-tautological. Reads sample on the completing (RLAST)
beat. The `id_match` property returns `True`/`False` when both IDs are known
and `None` otherwise.

`observed_id` is `None` on AXI4-Lite results (the protocol has no ID
signals), on absorbed timeouts, and on a capture miss (an unresolvable ID on
a completing beat — logged as a warning, never raised). Tests that gate on
IDs must assert `observed_id is not None` explicitly.

Capture is scoped to one blocking transaction: it samples the first
completing response beat between issue and completion, which is that
transaction's beat whenever the caller serializes transactions (the normal
use of the blocking result API). Event-style `init_read`/`init_write` flows
that overlap transactions should use
`driver.start_response_id_capture("b"|"r")` around the window they own.

The cocotbext backend itself polices response-ID pairing and fails on an ID
it never issued, so a responder that returns a wrong ID is fatal to the
transaction either way; `observed_id` supplies the wire-truth evidence for
the passing case and for wire-level scenarios (see the
`--dut ocah_axi_vip` selftests under `dv/`).

Use `check_response=False` and `raise_on_error=False` when a negative test
expects a non-OKAY response:

```python
master = OcahAxiLiteMasterAgent.from_prefix(
    dut, "j_axi", dut.clk_i, dut.rst_ni,
    reset_active_level=False,
    raise_on_error=False,
).sequence
result = await master.read_result(0xFFFF_0000, check_response=False)
assert result.resp == RESP_DECERR
```

Use `timeout_ns=<n>` and `allow_timeout=True` only when a scenario explicitly
accepts a non-completing access. The returned result has `timed_out=True`,
`ok=False`, and `resp=-1`.

## Fault-Capable Responders

`OcahAxiSlaveAgent` is memory-backed and also exposes fault controls:

```python
ram = OcahAxiSlaveAgent.from_prefix(
    dut,
    "m_axi",
    dut.clk_i,
    dut.rst_ni,
    reset_active_level=False,
    size=2**20,
).sequence

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
| `inject_id_corruption(mask=0x1, read=True, write=True)` | Arm one-shot response-ID corruption: the next selected transaction answers with `request_id ^ mask` (ID-width truncated); data path and response code stay untouched (AXI4 responder only) |
| `clear_errors()` | Clear all programmed errors and armed ID corruption |
| `enable_backpressure(channels, stall_cycles)` | Repeating bounded READY stalls |
| `disable_backpressure()` | Clear READY stalls |

`OcahAxiLiteSlaveAgent` provides the same fault-control API for AXI4-Lite
responder ports.

```python
axil_ram = OcahAxiLiteSlaveAgent.from_prefix(
    dut,
    "cfg_axil",
    dut.clk_i,
    dut.rst_ni,
    reset_active_level=False,
).sequence
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
`timed_out`. Monitors pair outstanding transactions by ID (per-ARID address
queues, per-RID beat accumulation; write bursts matched to BID), stamp
`start_time_ns`/`end_time_ns`, and expose:

- `get_request_activity() -> {"aw": n, "w": n, "ar": n}` — request-channel
  VALID-high CYCLE counters (matching the DTP tb pulse counters) for
  no-activity evidence; back-to-back requests with VALID held continuously
  still count every cycle.
- `pending_transactions() -> {"write": n, "read": n}` — in-flight requests
  awaiting completion, retained across `stop()`; `orphan_responses` counts
  B/R completions that had no request phase (logged as errors, never
  published as transactions). Both are enforced at scoreboard finalize via
  `CHK-AXI-DRAIN`.
- `arm_expected_resp(resp, count=1, direction=None)` — passive credits: the
  next matching non-OKAY completions publish with
  `metadata["expected_resp"]`; monitors never raise, classification authority
  stays with the scoreboard.

`OcahAxiChecker` composes the common `ocah_checker.OcahChecker` evidence core:
it retains item-level protocol findings in `errors` AND emits named
`CHK-* PASS/FAIL` evidence via `expect_equal/expect_true/
expect_not_timed_out/expect_timeout`, finalized once with `finalize()`
(zero checks, failures, and missing required IDs all fail).

Item-level rules (clean-room from the public AMBA AXI4 spec, IHI 0022):
`AXI-RESP-LEGAL`, `AXI-LITE-SINGLE`, `AXI-LITE-RESP` (no EXOKAY on Lite),
`AXI-BEATS`, `AXI-BURST-LEGAL` (reserved 0b11), `AXI-WRAP-ALIGN`,
`AXI-FIXED-LEN`, `AXI-ALIGN` (opt-in), `AXI-4KB` (INCR only),
`AXI-STRB-LEGAL` (lane-window check when `bus_bytes` is configured).

## Reference Model And Scoreboard

`OcahAxiRefModel` is a stateful, cocotb-free shadow: a sparse byte memory
with strobe-masked commits, plus the expected-response policy —
address-region expectations (`add_region(OcahAxiRegionExpectation(...))`)
and one-shot armed errors (`expect_error(addr, resp, read=, write=)`, beat
aligned exactly like `OcahFaultMixin.inject_error` pops them). Predictions
resolve the response first and commit memory only on expected-OKAY writes.
`write_bytes()` mirrors backdoor preloads; `reset()` restores deterministic
state.

`OcahAxiScoreboard` pairs monitor items with model predictions and emits the
named evidence IDs:

| Check ID | Meaning |
|---|---|
| `CHK-AXI-RESP` | per-beat observed responses == model expectation (position-exact) |
| `CHK-AXI-RESP-EXPECTED` | an armed non-OKAY credit was consumed exactly |
| `CHK-AXI-RDATA` | read data == predicted readback (expected-OKAY reads) |
| `CHK-AXI-WMEM` | DUT memory bytes == expectation (`check_memory()`; pass `expected=` with stimulus-intent bytes for the non-circular form, else the model shadow proves RAM-vs-bus only) |
| `CHK-AXI-STRB` | observed write strobes == armed stimulus intent (`arm_expected_strobes()`) |
| `CHK-AXI-NOACT` | activity counters unchanged / blocked window empty |
| `CHK-AXI-BLOCKED` | violation detector: a transaction whose beats OVERLAP a `blocked=True` region fails, regardless of response — byte-span overlap, so regions smaller than a bus word and regions entered mid-burst are both caught |
| `CHK-AXI-DRAIN` | emitted per attached monitor at finalize: every accepted request completed (no in-flight AW/AR) and no orphan B/R response arrived without a request phase |
| `CHK-AXI-COMPLETION` / `CHK-AXI-TIMEOUT` | a timed-out transaction fails unless the test armed it via `arm_expected_timeout()`; nothing on the observed item can authorize its own pass |
| `CHK-AXI-CREDITS` | zero unconsumed armed credits (response, strobe, and timeout) at finalize |
| `CHK-AXI-STREAM-MIN` | per-stream minimum compared-transaction count |
| `CHK-AXI-PROTOCOL` | protocol-watcher findings == 0 |
| `CHK-AXI-NONVAC` | adopter's domain non-vacuity (`expect_nonvacuous()`) |

Expected-vs-unexpected non-OKAY: `arm_expected_resp(resp, count=1,
address=None, direction=None, stream=None)` declares expected errors (the
generalization of SEP's `arm_expected_decerr`); any other non-OKAY fails the
per-beat `CHK-AXI-RESP` comparison, and unconsumed credits fail
`CHK-AXI-CREDITS`. When a model is attached, the per-beat comparison is emitted in addition to
`CHK-AXI-RESP-EXPECTED` on every credited transaction, so an error response
in the wrong burst position — or a credit that conflicts with the model's
expectation — fails even on the expected path. A `blocked=True` region flags
a burst if ANY of its beats touches the region, not just the start address.
Scoreboard credits and the model are the ONLY classification sources — the
monitor's `arm_expected_resp` credits are a monitor-local tally
(`expected_resp_seen`/`unexpected_error_count`) and cannot override the
scoreboard. Write-strobe intent: `arm_expected_strobes(strobes, count=1,
address=None, stream=None)` declares the stimulus wstrb the observed bus
strobes must match. Blocked windows (`begin/end_blocked_window`) fail any
transaction observed while a stream must be silent;
`expect_no_activity(before=, after=)` compares counter snapshots from either
the monitors or DUT-side pulse counters. Multi-stream use: one scoreboard,
`attach_monitor(monitor, stream=..., model=...)` per port, and
`min_checks_per_stream` to reject silently-dead streams. Finalize exactly
once after drain.

A simulator-free self-test (positive flow + the A-R fail-closed negative suite)
lives at `cocotb/examples/example_axi_scoreboard_selftest.py`:

```bash
PYTHONPATH="$PWD/hw/common/dv/vip" .venv/bin/python \
  hw/common/dv/vip/ocah_axi_vip/cocotb/examples/example_axi_scoreboard_selftest.py
```

## Protocol Watchers (cycle-level)

`OcahAxiProtocolWatcher` / `OcahAxiLiteProtocolWatcher` sample per cycle
(RisingEdge + ReadOnly, pure Python, Verilator-friendly) and retain findings
for: `AXI-{AW,W,AR,R,B}-STABLE` (payload stable while VALID && !READY),
`AXI-{AW,W,AR,R,B}-HOLD` (VALID held until READY), `AXI-RESET-VALID`, and
(AXI4) `AXI-W-LAST` / `AXI-R-LAST` last-beat position. Report once before
finalization: `watcher.report(evidence)` emits `CHK-AXI-PROTOCOL` requiring
zero findings.

## SystemVerilog Layer (interface / sva / sv / uvm)

The SV side of this package (compiled via `[frameworks.uvm.build].sources`-style
explicit source lists in the consuming DUT's sim config, never Bender or
Verilator filelists):

- `interface/ocah_axi_if.sv` — flat AXI4/AXI4-Lite monitor interface
  (default = maximum widths so `virtual ocah_axi_if` is one type; geometry
  lives in `ocah_axi_config`; Lite adapters tie the AXI4-only fields).
- `sva/ocah_axi_sva.sv` — clean-room SVA protocol rules
  (`OCAH_AXI_*` asserts + `OCAH_AXI_C_*` covers): reset-VALID, per-channel
  stability/hold/X-hygiene, burst legality (reserved encoding, size,
  FIXED<=16, WRAP length+alignment, 4KB), WLAST/RLAST position, strobe
  lane-window, B/R ordering and ID matching, EXOKAY-exclusive, and the Lite
  response-legality rules. `IS_LITE` selects the subset; `en_i` is the
  runtime suppress knob. Rules are implemented from IHI 0022 rule
  descriptions only — no third-party checker source was consulted.
- `sv/ocah_axil_ram_responder.sv`, `sv/ocah_axi_ram_responder.sv` —
  behavioral error-injectable RAM responders (SV analogue of the cocotb
  fault RAMs) with port-driven arm/addr/resp/direction error controls.
- `uvm/ocah_axi_uvm_pkg.sv` — the UVM layer. Side-neutral passive stack:
  `ocah_axi_item`, `ocah_axi_config` (owns the `arm_expected_resp` table),
  `ocah_axi_checker` (SV port of the CHK-*/CHECKER_SUMMARY evidence grammar;
  FAIL lines raise `uvm_error`), `ocah_axi_monitor` (per-ID reconstruction
  over `ocah_axi_if.mon_cb`), `ocah_axi_ref_model` (shadow memory + expected
  items), `ocah_axi_scoreboard` (in-order pairing; `CHK-AXI-RESP/RDATA/
  BEATS/ADDR-ALIGN/ERR-INJ`; finalizes in `check_phase`), `ocah_axi_cov`
  (optional `ocah_axi_cov_if` sampler), and `ocah_axi_env` (cfg-gated
  passive bundle). Slave side: `ocah_axi_slave_config` (memory geometry +
  one-shot error injection tables), `ocah_axi_slave_driver` (reactive
  memory-backed responder — the class analogue of the RAM responder
  modules; samples via `mon_cb`, drives the responder-side vif signals
  procedurally), `ocah_axi_slave_sequence` (test-facing backdoor/inject
  API), and `ocah_axi_slave_agent` (reactive bundle: no sequencer, by
  design). The master side (active SV-UVM initiator) is not shipped yet.

The DTP SV-UVM flow (`--dut dtp --framework uvm`) is the first consumer:
tb_top wires the slave agent onto the SMC OTP AXI-Lite port (a dedicated
`ocah_axi_if` carries the connection) and keeps the behavioral RAM responder
module on the `m_axi` fabric port, instantiates the SVA checkers on both, and
`dtp_jtag2axi_single_op_seq` drives JTAG2AXI traffic through the wide-scan
JTAG VIP path, programming responder error injection via the slave agent's
`ocah_axi_slave_sequence`.

## Functional Coverage Hook

`ocah_axi_cov.sv` is commercial-simulator-only collateral. It provides:

- `ocah_axi_cov_if` with `sample_write()` and `sample_read()` tasks.
- `ocah_axi_cov` module wrapper with scalar sample ports for bind-friendly flows.

Do not add this file to Verilator default filelists.

## DTP Usage

DTP JTAG2AXI responders construct the shared agents directly —
`OcahAxiSlaveAgent.from_prefix(...).sequence` for the debug AXI4 port and
`OcahAxiLiteSlaveAgent.from_prefix(...).sequence` for the SMC/SEP OTP
AXI-Lite ports — and program faults and backpressure through the
`OcahAxi[Lite]SlaveSequence` API. There is no DTP-local adapter layer.

## SEP Compatibility Reference

Do not modify SEP code as part of this release. Existing SEP cocotbext usage is
the compatibility checklist for the wrapper:

| SEP pattern | OCAH wrapper support |
|---|---|
| `init_read` / `init_write` | Provided by `OcahAxiMasterAgent` and `OcahAxiLiteMasterAgent` |
| Explicit timeout around event wait | `timeout_ns` and event helpers |
| `allow_timeout` negative checks | `read_result` / `write_result` support `allow_timeout=True` |
| Exact response-code assertions | `resp`, `resp_list`, and `ok` fields |
| Error-expected probes | Use `raise_on_error=False`, `check_response=False` |

Future SEP migration can be planned separately after wrapper parity is proven by
DTP and import/smoke validation.

## Migration Notes

| Legacy/backend pattern | OCAH wrapper pattern |
|---|---|
| `AxiLiteMaster(...).read(...)` | `OcahAxiLiteMasterAgent(...).read_result(...)` |
| `AxiMaster(...).init_read(...)` | `OcahAxiMasterAgent(...).init_read(...)` |
| Backend response enum imports | `RESP_OKAY`, `RESP_SLVERR`, `RESP_DECERR` |
| DTP-local fault RAM subclasses | `OcahAxiSlaveAgent` / `OcahAxiLiteSlaveAgent` fault APIs |

If a test needs an AXI sideband or non-contiguous strobe pattern that the wrapper
does not expose, extend this package first so the public API stays stable.
