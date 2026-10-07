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
| `cocotb/ocah_axi_item.py` | Generic AXI/AXI-Lite transaction items and result dataclasses (side-neutral) |
| `cocotb/ocah_axi_monitor.py` | Passive item-producing bus monitors (side-neutral) |
| `cocotb/ocah_axi_checker.py` | Item-level protocol checker (side-neutral) |
| `cocotb/ocah_axi_config.py` | Bus geometry and interface-scope binding (side-neutral; twin of `uvm/ocah_axi_config.svh`) |
| `cocotb/ocah_axi_types.py` | Response/protection code constants and value-conversion helpers (side-neutral) |
| `cov/ocah_axi_cov.sv` | Optional-backend functional coverage hook |

Tests always drive a side through its `*Sequence` class — usually
`agent.sequence` — never through the raw driver; missing operations get
added to the sequence layer first.

The cocotb package contains only canonical component files, matching the
SV-UVM flow's basenames (`uvm/ocah_axi_*.svh`) one-to-one; flow-only
components follow the same naming pattern. Shared dataclasses live in
`_item`, shared constants and value conversions in `_types`, and behavior
lives in the component that owns it (e.g. `AxiTimingProfile` is a
`_master_config` knob applied by the `_master_driver`) — support modules
outside the taxonomy are not added.

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

Response codes are plain integers (`RESP_OKAY`, `RESP_EXOKAY`, `RESP_SLVERR`,
`RESP_DECERR`, `RESP_TIMEOUT`); `resp_name(resp)` renders them for log and
failure messages. AxPROT values are built by OR-ing the plain
`PROT_PRIVILEGED`, `PROT_NONSECURE`, and `PROT_INSTRUCTION` bits and passed
via the `prot=` argument.

Do not import `cocotbext.axi.AxiMaster`, `AxiLiteMaster`, `AxiRam`, or backend
response enums in new OCAH tests. Add missing behavior to this wrapper instead.

## Bus Geometry

`interface/ocah_axi_if.sv` instantiates at its default (maximum) member
widths wherever the SV-UVM layer needs one `virtual ocah_axi_if` type; the
real bus geometry lives in the configuration on both sides. In SV the
`ocah_axi_config` widths mask what the monitor samples. In cocotb the
engines size byte lanes from the signals they are handed, so `OcahAxiConfig`
carries the same widths and `bus()` returns an `OcahAxiBus`, the package's
bus handle, over a view of the scope: every geometry-bearing member (`awaddr`, `araddr`, `wdata`,
`rdata`, `wstrb`, and for AXI4 the ID and user sidebands when their width is
non-zero) reports the configured width, reads return its low bits, and
writes drive the low bits with the bits above held at zero. A member already
at the configured width passes through unchanged, so one call binds a flat
port bundle (`prefix=`) or an interface handle alike; a configured width
wider than the member raises at binding.

```python
from ocah_axi_vip import OcahAxiConfig, OcahAxiLiteSlaveAgent, OcahAxiProtocol

otp = OcahAxiConfig(protocol=OcahAxiProtocol.AXI4_LITE, addr_width=32, data_width=32)
ram = OcahAxiLiteSlaveAgent(otp.bus(dut.u_smc_otp_axil_if), dut.clk_i, dut.rst_ni).sequence
```

The `dv/` harness binds the 32-bit stacks onto default-geometry instances
and judges every sub-word offset of the 8-byte member lane, the backdoor
view, and the idle upper lanes (`ocah_axi_lite_geometry_test`,
`ocah_axi_geometry_test`).

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

Plain-value helpers:

| Method | Return | Use |
|---|---|---|
| `await write(addr, data, ...)` | `int` response code | Tests that only need BRESP |
| `await read(addr, ...)` | `int` data | Tests that expect OKAY reads |

Result helpers:

| Method | Return | Use |
|---|---|---|
| `await write_result(addr, data, ...)` | `OcahAxiWriteResult` | Negative writes, exact response checks |
| `await read_result(addr, ...)` | `OcahAxiReadResult` | Negative reads, data plus RRESP checks |

`write_result`/`write` accept a contiguous partial `strb`: the selected
bytes of `data` are written as a sub-word access (the backend derives WSTRB
from address and length), so `strb=0x2` writes byte lane 1 only.
Non-contiguous patterns (`0x5`, `0x9`, ...) are rejected with `ValueError`.

Protocol-control operations (SV-UVM parity; see
`ocah_axi_master_sequence.svh` for the same knobs on the SV side):

| Method | Return | Use |
|---|---|---|
| `await write_skewed_result(addr, data, *, aw_valid_delay, w_valid_delay, b_ready_delay, strb, ...)` | `OcahAxiWriteResult` | Single-beat write with independent AW/W launch skew — AXI permits either arrival order — plus a deferred BREADY assert after the request phase |
| `await read_hold_result(addr, hold_cycles, ...)` | `OcahAxiReadResult` | Read holding RREADY low for `hold_cycles` after RVALID; the result's `hold_stable` reports that RVALID stayed asserted with RDATA/RRESP unchanged across the window |
| `await write_pair_skewed_result(addr_a, data_a, addr_b, data_b, *, aw_valid_delay, w_valid_delay, b_ready_delay, strb_a, strb_b, ...)` | `OcahAxiWritePairResult` | Two single-beat writes queued back to back: the second write's AW and W follow the first on their channels, so under a W delay the second AW meets the responder while the first W is pending; BREADY is deferred `b_ready_delay` cycles after the first write's request phase and both B responses are accepted in order; `aw_stall_cycles` counts AWVALID-without-AWREADY cycles across the pair and `aw_stable` reports AWVALID and AWADDR held through every such stall |
| `await read_pair_hold_result(addr_a, addr_b, hold_cycles, ...)` | `OcahAxiReadPairResult` | Two single-beat reads: AR(b) follows AR(a) while RREADY is held low for `hold_cycles` after the first RVALID, so a responder that admits one read at a time stalls AR(b); `first.hold_stable` reports the hold window, `ar_stall_cycles` / `ar_stable` the AR channel across the pair |
| `await pipeline_result(ops, *, b_hold_cycles, r_hold_cycles, ...)` | `OcahAxiPipelineResult` | Single-beat reads and writes in flight together: each `OcahAxiPipelineOp` launches its beats no earlier than its `aw_valid_delay` / `w_valid_delay` / `ar_valid_delay`, counted in cycles from the start, and no earlier than the cycle after the beat ahead of it on its channel was accepted; BREADY and RREADY stay low for `b_hold_cycles` / `r_hold_cycles` after the first BVALID / RVALID; `results` holds one write or read result per access in list order, and `aw_stall_cycles` / `w_stall_cycles` / `ar_stall_cycles` count each request channel's VALID-without-READY cycles; an invalid access fails the call before any access is issued |

All five operations require idle engines (the skew is applied by pausing
the backend's channel sources/sinks). The first four bound every phase with
`timeout_cycles`; `pipeline_result` fails after `timeout_cycles` cycles with
no handshake on any channel while no beat or READY hold is still waiting on
its delay. `allow_timeout=True` converts an expiry into a `timed_out`
result. The pair results expose the two per-transaction results as `first`
and `second` in issue order. A `pipeline_result` expiry marks only the
accesses without a response `timed_out`: an access whose response arrived
keeps its result, which `check_response` and the statistics cover, a
timed-out write reports the byte length its `strb` selects, and the stall
counters hold the cycles counted up to the expiry. The backend goes on
presenting the unaccepted beats and retires them once the responder takes
them. A `pipeline_result` write is one beat, so a partial `strb` and an
unaligned address must stay inside it; a read at an unaligned address
returns the bytes up to the end of its beat. Each access is checked against
the backend (direction, address range, `prot` value and the bus's
protection signal, strobe, delays) before the first one is issued, so a
`ValueError` leaves the bus untouched.

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
is a 4-byte beat and `size=3` is an 8-byte beat. The sequence API accepts
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

Every blocking operation is bounded by `timeout_ns`: the call's value, else
the instance's, else the package default (`DEFAULT_TIMEOUT_NS`, 500 µs, or the
`+OCAH_AXI_TIMEOUT_NS` plusarg). Use `timeout_ns=<n>` and `allow_timeout=True`
only when a scenario explicitly accepts a non-completing access. The returned
result has `timed_out=True`, `ok=False`, and `resp=-1`.

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
| `inject_error(addr, resp, read=True, write=True, rdata=0)` | Program one-shot non-OKAY response; the errored read beat answers `rdata` as its RDATA word |
| `inject_id_corruption(mask=0x1, read=True, write=True)` | Arm one-shot response-ID corruption: the next selected transaction answers with `request_id ^ mask` (ID-width truncated); data path and response code stay untouched (AXI4 responder only) |
| `clear_errors()` | Clear all programmed errors and armed ID corruption |
| `enable_backpressure(channels, stall_cycles)` | Repeating bounded READY stalls |
| `disable_backpressure()` | Clear READY stalls |
| `set_response_delay(delays, read=True, write=True)` | Delay each B or R response by `delays` cycles (an integer), or by the next value of an iterable drawn once per response in request order (AXI4 responder only) |
| `clear_response_delay()` | Send every response as soon as it is ready |
| `max_outstanding` | The configured outstanding depth, or `None` |
| `outstanding_peak()` | Most writes and reads outstanding at once since construction; needs `max_outstanding` |
| `arm_w_before_aw()` | One-shot W-before-AW order for the next write; this responder accepts W beats independently of AW, so the call changes nothing on the wires |
| `randomize_resp_user(seed)` | Answer every later B and R beat with BUSER and RUSER drawn per beat, B from `random.Random(seed)` and R from `random.Random(seed + 1)`; zero until called (AXI4 responder only) |

Both responders drive BVALID and RVALID low as their reset input asserts
(IHI 0022 A3.1.2), not at the next clock edge. `ocah_axi_responder_ops_test`
proves the errored-beat word, the W-before-AW order, the USER streams, and
the reset drop on the wires of `OcahAxiSlaveAgent`.

### Outstanding depth

By default the AXI4 responder serves one request at a time, in request
order: its request queues hold two more, and a request whose response
cannot be sent holds up every request behind it. Constructed with
`max_outstanding=N` (an agent keyword argument or the
`OcahAxiSlaveConfig.max_outstanding` field), it accepts up to N writes and N
reads, each counted from its address handshake to its B or RLAST handshake,
and holds AWREADY or ARREADY low while N are outstanding. Each response
then runs on its own: it waits its response delay, then for the previous
response of the same ID, so same-ID responses leave in request order while
responses of different IDs overtake one another. W beats are taken in AW
order, and the beats of one read burst are never interleaved with another's.
Error injection, ID corruption, backpressure and the response USER policy
apply in either mode. The W channel holds N beats, so up to N W beats are
accepted ahead of their AW. BUSER and RUSER are drawn as each response is
queued, so the USER streams follow the order of B and R beats on the wires,
which with a depth is the response order. A reset drops every response in
service and empties the window: after the release the responder accepts N
new requests and answers none taken before the reset.

In both modes a read claims the one-shot errors of all its beats, with
their errored-beat words, when the responder takes it into service, before
its first R beat, so an `inject_error(..., read=True)` armed while a burst
is in progress applies to a later read of the address, not to the remaining
beats of that burst. A write claims its one-shot errors as each W beat
arrives.

```python
ram = OcahAxiSlaveAgent(bus, dut.clk_i, dut.rst_ni, reset_active_level=False,
                        max_outstanding=8).sequence
rng = random.Random(seed)
ram.set_response_delay(iter(lambda: rng.randint(8, 32), None))
...
assert ram.outstanding_peak()["read"] > 3
```

`OcahAxiLiteSlaveAgent` provides the same fault-control API for AXI4-Lite
responder ports, apart from the AXI4-only operations.

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

## Struct-Port Boundaries

Every DUT-mastered AXI boundary is answered by the slave agent above. A port
the bench flattens to pins attaches through `from_prefix` (cocotb) or the
agent's `vif` (SV-UVM). A port that stays a pulp-style request/response
struct inside `tb_top` (SMU, SMC, and SEP hand their outbound AXI to the
bench this way) is placed on an `ocah_axi_if` instance by
`interface/ocah_axi_struct_bridge.sv`, and the agent attaches to that
instance:

```systemverilog
ocah_axi_if u_output_axi_if (.aclk(clk), .aresetn(rst_n));

ocah_axi_struct_bridge #(
  .axi_req_t  (smc_sys_out_axi_req_t),
  .axi_resp_t (smc_sys_out_axi_resp_t)
) u_output_bridge (
  .axi_req_i  (output_axi_req),
  .axi_resp_o (output_axi_resp),
  .axi_if     (u_output_axi_if)
);
```

```python
output_mem = OcahAxiSlaveAgent(
    OcahAxiConfig(protocol=OcahAxiProtocol.AXI4, addr_width=56, data_width=64,
                  id_width=8, user_width=12).bus(dut.u_output_axi_if),
    dut.clk, dut.rst_n, reset_active_level=False, size=2**20,
).sequence
output_mem.write(0x0200_0000, image_bytes)          # preload
output_mem.inject_error(0x0200_0040, RESP_SLVERR)    # one-shot fault
```

The bridge drives the interface's initiator-side members from the request
struct and forms the response struct from the responder-side members the
agent drives; the interface keeps its default geometry and the agent's config
states the real one. A memory preload is a backdoor write on the slave
sequence (`write` / `write32` / `write64` in cocotb, `write_bytes` / `write32`
/ `write64` in SV-UVM), and fault programming goes through `inject_error` in
both realizations. The passive `ocah_axi_env` attaches to the same interface
instance and scores the boundary like any other bus; a preload written into
the agent behind its back is mirrored into that env's reference model
(`OcahAxiRefModel.write_bytes` / `ocah_axi_ref_model.backdoor_write`) so the
readback prediction starts from the preloaded contents.

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

Item-level rules derived from the public AMBA AXI4 specification, IHI 0022:
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

A simulator-free self-test (positive flow + the fail-closed negative suite)
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

The SV side of this package compiles through the VIP-owned ordered manifest
`uvm/sources.toml` (incdirs + sources): a consuming DUT lists that manifest in
its `[frameworks.uvm.build].source_lists` and the runner expands it ahead of
the DUT's own sources — never hand-copy these paths into a DUT sim config, and
never add them to Bender filelists. The one entry a cocotb/Verilator build
lists directly in its `[build].sources` is `sva/ocah_axi_sva.sv`, whose
two-state rules run there. The manifest is the complete VIP layer; unused
modules simply do not elaborate. Its contents:

- `interface/ocah_axi_if.sv` — flat AXI4/AXI4-Lite monitor interface
  (default = maximum widths so `virtual ocah_axi_if` is one type; geometry
  lives in `ocah_axi_config` on the SV side and `OcahAxiConfig` on the cocotb
  side; Lite adapters tie the AXI4-only fields).
- `sva/ocah_axi_sva.sv` — SVA protocol rules derived from IHI 0022
  (`OCAH_AXI_*` asserts + `OCAH_AXI_C_*` covers): reset-VALID, per-channel
  stability/hold/X-hygiene, burst legality (reserved encoding, size,
  FIXED<=16, WRAP length+alignment, 4KB), WLAST/RLAST position, strobe
  lane-window, B/R ordering and ID matching, EXOKAY-exclusive, and the Lite
  response-legality rules. `IS_LITE` selects the subset; `en_i` is the
  runtime suppress knob. The `dv/` harness binds it to every VIP-driven
  bundle; the response-ID corruption bundles stay unbound because the
  ID-ordering rules fire there by design. Rules implement the IHI 0022 rule
  descriptions. Simulator capability selects between two trees. The two-state
  rules use `OCAH_SVA_RULE` (`hw/common/assert/ocah_sva_macros.svh`) and run
  on every simulator, Verilator included under `--assert`, and on licensed
  formal backends under `FORMAL`; the X-hygiene rules and the covers use
  `OCAH_RULE` / `OCAH_COVER` and run on four-state simulators and licensed
  backends only. Each rule belongs to the side that drives its signals, and
  `ASSUME_MASTER_RULES` / `ASSUME_SLAVE_RULES` emit that side's rules as
  assumptions, so a formal environment asserts the design's side and assumes
  its own; both default to assertions.
- `sva/ocah_axi_fv.sv` — the same protocol's handshake, reset,
  burst-legality and response-ordering rules written in the boolean subset
  the open-source formal frontend reads (`OCAH_FV_RULE`,
  `hw/common/assert/ocah_fv_macros.svh`), with the flat port list of
  `ocah_axi_sva` and the same two side parameters; the formal environments
  of the DTP bind it (`hw/common/dv/docs/formal-property-style.adoc`,
  Shared protocol checkers). Rules that need per-ID or per-beat history stay
  in `sva/ocah_axi_sva.sv`.
- `interface/ocah_axi_struct_bridge.sv` — places a DUT-mastered port that
  stays a pulp request/response struct inside `tb_top` on an `ocah_axi_if`
  instance for the slave agent (see "Struct-Port Boundaries").
- `uvm/ocah_axi_uvm_pkg.sv` — the UVM layer. Side-neutral passive stack:
  `ocah_axi_item`, `ocah_axi_config` (owns the `arm_expected_resp` table),
  `ocah_axi_checker` (SV port of the CHK-*/CHECKER_SUMMARY evidence grammar;
  FAIL lines raise `uvm_error`), `ocah_axi_monitor` (per-ID reconstruction
  over `ocah_axi_if.mon_cb`), `ocah_axi_ref_model` (shadow memory + expected
  items), `ocah_axi_scoreboard` (in-order pairing; `CHK-AXI-RESP/RDATA/
  BEATS/ADDR-ALIGN/ERR-INJ`; finalizes in `check_phase`), `ocah_axi_cov`
  (optional `ocah_axi_cov_if` sampler), and `ocah_axi_env` (cfg-gated
  passive bundle; frozen surface `cfg`, `item_ap`, `m_checker`). Slave
  side: `ocah_axi_slave_config` (memory geometry +
  one-shot error injection tables), `ocah_axi_slave_driver` (reactive
  memory-backed responder; samples via `mon_cb`, drives the responder-side vif signals
  procedurally), `ocah_axi_slave_sequence` (test-facing backdoor/inject
  API), and `ocah_axi_slave_agent` (reactive bundle without a
  sequencer). Master side: `ocah_axi_master_config` (vif, geometry, handshake
  watchdog), `ocah_axi_master_driver` (active initiator: sequential AW/W/B
  and AR/R engines, one transaction outstanding except for the pair
  operations, whose second single-beat transaction launches before the
  first completes, and the pipelined operation, whose single-beat reads and
  writes run together; samples via `mon_cb`, drives the initiator-side vif
  signals procedurally), the standard
  `ocah_axi_master_sequencer`, `ocah_axi_master_sequence` (the test-facing
  `ocah_axi_master_sequencer`, `ocah_axi_master_sequence` (the test-facing
  stimulus API — see below), `ocah_axi_master_agent` (driver + sequencer;
  no agent monitor — observation stays with the side-neutral
  `cfg`; the optional-backend override unit, with the same template contract as
  `ocah_jtag_master_env`).

Optional-backend integration follows the Template Contract in the
ocah_jtag_vip README: the open tree carries only the hooks (the opaque
`vendor_cfg` extension, the `en_monitor` knob, the guarded
`OCAH_AXI_VENDOR_IF` nest inside `ocah_axi_if`, and the factory-overridable
env/agent classes above). Adopter overlays supply backend implementations
without adding a dependency from the open tree.

### SV-UVM master sequence API

`ocah_axi_master_sequence` is the SV twin of the cocotb
`OcahAxiMasterSequence` surface: tests and DUT sequence libraries extend it
and drive the master only through its blocking operations — `write` /
`read` / `write_result` / `read_result` / `burst_write[_result]` /
`burst_read[_result]` — never through raw `ocah_axi_item` handshakes.
Missing operations get added there first. Every `*_result` operation
returns the completed `ocah_axi_item` as the result object, the SV analogue
of `OcahAxiWriteResult`/`OcahAxiReadResult`:

| Item field | Result meaning |
|---|---|
| `transaction_id` | The issued AWID/ARID (as passed to the operation) |
| `observed_id` / `observed_id_valid` | BID/RID sampled live from the response handshake on the completing beat (RLAST for reads); invalid on ID-less buses and timeouts |
| `id_match()` | Both IDs known and equal (gate on `observed_id_valid` to separate mismatch from capture miss) |
| `resp_list` / `worst_resp()` / `is_ok()` | Per-beat response evidence; `is_ok()` is 0 on a timed-out result |
| `data_words` | Read data, one raw bus word per beat |
| `timed_out` | A handshake wait exceeded `ocah_axi_master_config.timeout_cycles` before the final response handshake (RLAST for reads); the beats received stay in `data_words` / `resp_list` |

Every operation first clears the result fields of the items it is given
(`ocah_axi_item::clear_results()`), so an item reused across operations
carries no result from an earlier one.

`pipeline_result(ops, result, b_hold_cycles, r_hold_cycles)` is the SV
side of the cocotb pipelined operation: `pipeline_write` and
`pipeline_read` build the single-beat ops with their channel delays, the
driver keeps them in flight together under the same launch and hold rules,
each op comes back filled like a plain result, and `result` carries
`aw_stall_cycles` / `w_stall_cycles` / `ar_stall_cycles`. Each handshake
wait is bounded by `timeout_cycles`; when one expires, `result` and every
op whose final response handshake has not completed report `timed_out` (a
read keeps the beats it received in `data_words` and `resp_list`), the
other ops keep their results, and the stall counts cover the cycles before
the expiry. The driver checks every op before it drives anything: a write
that does not carry exactly one data word and at most one strobe entry, or
an address with bits set above `addr_width`, fails the operation with a
`uvm_error` under the message ID `OCAH_AXI_PIPELINE_INVALID` and leaves the
bus idle. On an AXI4 bus every op uses one ID, because the driver collects
the responses in list order per direction.

The response-ID contract is cross-flow parity with "Response-ID
observation" above: `observed_id` is wire truth, never an issued-ID echo.
On the responder side, `ocah_axi_slave_sequence.inject_id_corruption(mask,
for_read, for_write)` mirrors the cocotb fault slave: the next selected
transaction answers `request_id ^ mask` (ID-width truncated; data path and
response code untouched), one-shot per direction, disarmed by
`clear_errors()`. `inject_missing_rlast(addr)` arms a one-shot at a
beat-aligned address like `inject_error`: the next read whose AR address
aligns there answers its final beat with RLAST low and sends no further
beat, so the master's read times out holding that beat; `clear_errors()`
disarms it and `pending_errors()` counts it (SV-UVM responder only).
`inject_error(addr, resp, for_read, for_write, rdata)` returns `rdata`
(default zero) as the errored read beat's RDATA word, as the cocotb
responder does. `arm_w_before_aw()` arms a one-shot write order: the next
write raises WREADY with its first AWREADY window, so its first W beat is
accepted while its AW waits (IHI 0022 A3.3.1); later writes take AW first.
The cocotb responder accepts W independently of AW, which gives the same
order on every write. `randomize_resp_user(seed)` answers every later B and
R beat with BUSER and RUSER drawn per beat, the write pump's process RNG
seeded from `seed` and the read pump's from `seed + 1` (AXI4 only; zero
until called). The responder drives BVALID, RVALID and its READYs low as
`aresetn` asserts and abandons the transfer in flight, including after a
reset that ends between two clock edges. The SV-UVM
`ocah_axi_responder_ops_test` proves the errored-beat word, the W-before-AW
order and the USER streams on the harness bus; the SV-UVM master holds
`aresetn` high across an item, so only the cocotb realization drops a reset.
The SV-UVM responder serves one write and one read at a time, so it has no
outstanding depth and no response delay (see "Outstanding depth" above).
`check_response=1` (default) escalates a non-OKAY response to `uvm_error`;
`allow_timeout=1` downgrades a watchdog expiry to a returned result with
`timed_out` set.

The DTP SV-UVM flow (`--dut dtp --framework uvm`) consumes both sides: a
slave agent answers each JTAG2AXI port (SMC OTP and SEP OTP AXI-Lite, SMC
fabric AXI4; a dedicated `ocah_axi_if` per port carries the connection), the
master env drives the XTRIG CSR AXI-Lite port, tb_top instantiates the SVA
checkers on every port, and the scenario sequences program responder memory,
error injection, backpressure, and write order through each port's
`ocah_axi_slave_sequence`. The cocotb flow answers the same ports with
`OcahAxi[Lite]SlaveAgent` and drives the XTRIG CSR port with
`OcahAxiLiteMasterAgent`. The SV-UVM selftests (`--dut ocah_axi_vip
--framework uvm`) drive the master side through the same scenarios as the
cocotb selftests, full-stack through the master sequence API against the
fault slave, with the passive env scoring the same wires wherever a
scenario leaves them in a state it can judge.

## UVM Env Surface Convention

The OCAH VIPs with an SV-UVM layer (`ocah_jtag_vip`, `ocah_axi_vip`) follow
one surface convention, with the JTAG master env as the reference template:

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

## Functional Coverage Hook

`ocah_axi_cov.sv` is optional-backend collateral. It provides:

- `ocah_axi_cov_if` with `sample_write()` and `sample_read()` tasks.
- `ocah_axi_cov` module wrapper with scalar sample ports for bind-friendly flows.

Do not add this file to Verilator default filelists.

## DTP Usage

The DTP env's `DtpAxiAgent` builds the shared agents from `tb_if` bus
handles — `OcahAxiSlaveAgent(tb.axi_bus("smc_axi"), ...).sequence` for the
debug AXI4 port and `OcahAxiLiteSlaveAgent(tb.axi_bus(...), ...).sequence`
for the SMC/SEP OTP AXI-Lite ports — and programs faults and backpressure
through the `OcahAxi[Lite]SlaveSequence` API.

## Extending The Wrapper

If a test needs an AXI sideband or non-contiguous strobe pattern that the wrapper
does not expose, extend this package first so the public API stays stable.
