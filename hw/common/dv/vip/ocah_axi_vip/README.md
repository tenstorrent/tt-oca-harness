# ocah_axi_vip — OCAH AXI Wrapper

SPDX-License-Identifier: Apache-2.0

Stable, OCAH-flavored Python wrappers for driving, responding to, and monitoring
AXI4 and AXI4-Lite buses in cocotb testbenches.  Tests import from this package
and never bind directly to the underlying VIP internals.

---

## Purpose

OCAH cocotb tests need a single, versioned API for bus-master transactions so
that:

1. Tests do not break when the underlying VIP is updated.
2. New test authors have one place to look for bus-access primitives.
3. Upstream API changes (`cocotbext-axi` or project VIPs) are absorbed at the
   wrapper boundary, not scattered across test files.

This package is the base bus BFM that the protocol-specific VIPs build on.

---

## Backend

The released AXI master and responder BFMs are backed by `cocotbext-axi`
(`cocotbext-axi>=0.1.24,<0.2` in `pyproject.toml`):

| Wrapper | Backend |
|---|---|
| `OcahAxiMasterAgent` | `cocotbext.axi.AxiMaster` |
| `OcahAxiLiteMasterAgent` | `cocotbext.axi.AxiLiteMaster` |
| `OcahAxiSlaveAgent` | OCAH fault-capable wrapper over `cocotbext-axi` RAM channels |
| `OcahAxiLiteSlaveAgent` | OCAH fault-capable wrapper over `cocotbext-axi` AXI-Lite RAM channels |
| `OcahAxiMonitor` / `OcahAxiLiteMonitor` | OCAH passive samplers that emit item dataclasses |
| `OcahAxiChecker` | OCAH item-level protocol checker |

Every driver zeroes its source-channel payload signals at construction
(`init_signals()`, also callable explicitly), overriding the backend's all-X
payload init so a bus idles clean from time 0 on 4-state simulators. No
process-global cocotb or `cocotbext-axi` state is touched.

---

## Which class to use

| Scenario | Recommended class |
|---|---|
| Writing a new OCAH cocotb test | `OcahAxiMasterAgent` / `OcahAxiLiteMasterAgent` |
| Burst AXI4 traffic (memory fills, DMA) | `OcahAxiMasterAgent` |
| Memory-backed AXI subordinate/responder | `OcahAxiSlaveAgent` |
| Control/status register access over AXI4-Lite | `OcahAxiLiteMasterAgent` |
| Memory-backed AXI4-Lite responder | `OcahAxiLiteSlaveAgent` |
| Passive observation without driving the bus | `OcahAxiMonitor` / `OcahAxiLiteMonitor` |
| Item-level protocol sanity checks | `OcahAxiChecker` |
| AXI-Stream (e.g. entropy data path) | **Out of scope** for this package — stream sources stay DUT-local |

Do not use `cocotbext-axi` types (`AxiMaster`, `AxiLiteMaster`, etc.)
directly in new test files; always go through this package.

---

## Package Layout

```
ocah_axi_vip/
  __init__.py                  — exports all public symbols
  cocotb/                      — cocotb flow (per-side files, x2 protocol stems
                                 ocah_axi / ocah_axi_lite)
    ocah_axi[_lite]_master_agent.py     — OcahAxi[Lite]MasterAgent (bundle)
    ocah_axi[_lite]_master_config.py    — OcahAxi[Lite]MasterConfig
    ocah_axi[_lite]_master_driver.py    — OcahAxi[Lite]MasterDriver (cocotbext engine)
    ocah_axi[_lite]_master_sequence.py  — OcahAxi[Lite]MasterSequence (test-facing API)
    ocah_axi[_lite]_slave_agent.py      — OcahAxi[Lite]SlaveAgent (bundle)
    ocah_axi[_lite]_slave_config.py     — OcahAxi[Lite]SlaveConfig
    ocah_axi[_lite]_slave_driver.py     — OcahAxi[Lite]SlaveDriver (fault-capable RAM engine)
    ocah_axi[_lite]_slave_sequence.py   — OcahAxi[Lite]SlaveSequence (backdoor/inject API)
    ocah_axi_item.py                    — transaction item dataclasses (side-neutral)
    ocah_axi_monitor.py                 — OcahAxiMonitor, OcahAxiLiteMonitor (side-neutral)
    ocah_axi_checker.py                 — OcahAxiChecker (item rules + CHK-* evidence)
    ocah_axi_ref_model.py               — OcahAxiRefModel (shadow memory + response policy)
    ocah_axi_scoreboard.py              — OcahAxiScoreboard (evidence-emitting comparator)
    ocah_axi_protocol_watcher.py        — cycle-level protocol-rule watchers
    ocah_axi_types.py                   — response/protection codes + value-conversion helpers
  interface/ocah_axi_if.sv       — flat AXI4/AXI4-Lite monitor interface (SV)
  sva/ocah_axi_sva.sv            — clean-room AXI protocol SVA (OCAH_AXI_* rules)
  sv/ocah_axil_ram_responder.sv  — behavioral AXI-Lite RAM responder (error-injectable)
  sv/ocah_axi_ram_responder.sv   — behavioral AXI4 RAM responder (error-injectable)
  uvm/ocah_axi_uvm_pkg.sv        — SV-UVM layer: side-neutral passive stack
                                   (monitor/ref-model/scoreboard/env) + slave
                                   agent (reactive memory-backed responder)
                                   + master agent/env (active initiator driven
                                   through ocah_axi_master_sequence)
  cov/ocah_axi_cov.sv            — commercial-simulator functional coverage
  examples/
    example_register_access.py            — annotated usage snippets
    example_axi_scoreboard_selftest.py    — simulator-free checker/model/scoreboard proof
  dv/                            — simulated VIP selftests on a passive wire
                                   harness (master <-> fault slave; response-ID
                                   observation and corruption proofs), one
                                   scenario set for both frameworks:
                                   python3 tools/dv/run_dv.py --dut ocah_axi_vip --items smoke
                                   python3 tools/dv/run_dv.py --dut ocah_axi_vip \
                                       --framework uvm --tool vcs --items smoke
```

### Side-token naming

The VIP is implemented per side (master = initiator, slave = responder), and
side-specific components — agent, config, driver, sequence — carry the side
token in their basenames. Tests consume each side ONLY through its
`*Sequence` class (usually `agent.sequence`); missing operations get added to
the sequence layer, never inlined in tests. The bus monitors and the passive
UVM environment are side-NEUTRAL and carry no side token: they reconstruct
traffic from the shared wires regardless of who generated it (a VIP master, a
VIP responder, or the DUT itself — DTP observes purely DUT-generated traffic
with no VIP master present).

The package contains only canonical component files, matching the SV-UVM
flow's basenames one-to-one (flow-only components follow the same pattern):
shared dataclasses live in `ocah_axi_item.py`, shared constants and value
conversions in `ocah_axi_types.py`, and behavior lives in the component that
owns it — support modules outside the taxonomy are not added.

The checker, reference model, and scoreboard follow the shared contract in
`hw/common/dv/docs/vip-checker-model.adoc`: named
`CHK-* PASS/FAIL` evidence with a `CHECKER_SUMMARY`, expected-vs-unexpected
non-OKAY classification via armed credits, blocked-window/no-activity checks,
and fail-closed finalization. Protocol rules are re-implemented clean-room
from the public AMBA AXI4 specification (ARM IHI 0022) rule descriptions;
no third-party protocol-checker source was consulted or copied. See
`MANUAL.md` for the full rule and check-ID tables, the SV-UVM layer, and the
DTP adoption pattern.

---

## Public API Reference

### OcahAxiMasterAgent — AXI4 full bus

```python
from ocah_axi_vip import OcahAxiMasterAgent

master = OcahAxiMasterAgent(
    dut.axi_if,              # cocotb handle for the AXI4 interface instance
    name="axi4_host",        # used in log messages
    timeout_cycles=1000,     # clock cycles before TimeoutError
    addr_width=32,           # address bus width (informational)
    data_width=32,           # data bus width; derives full_strb
    raise_on_error=True,     # raise OcahAxiMasterError on non-OKAY response
).sequence                   # tests consume the sequence surface
```

| Method | Returns | Notes |
|---|---|---|
| `master.init_signals()` | `None` | Re-drive payload signals to 0 idle (already done at construction) |
| `await master.wait_for_reset()` | `None` | Block until `aresetn` deasserts |
| `await master.write(addr, data, *, strb, size, burst, id, prot)` | `int` (resp code) | Single-beat write |
| `await master.read(addr, *, size, burst, id, prot)` | `int` (data) | Single-beat read |
| `await master.write_result(addr, data, ...)` | `OcahAxiWriteResult` | Response, `ok`, timeout, issued/observed AWID-BID, raw debug object |
| `await master.read_result(addr, ...)` | `OcahAxiReadResult` | Data bytes/words, response inspection, issued/observed ARID-RID |
| `master.init_write(...)` / `master.init_read(...)` | cocotb event | Event-style access for explicit timeout flows |
| `await master.burst_write(addr, data_list, *, strb_list, size, burst, id, prot)` | `int` (resp code) | Multi-beat write; `len(data_list)` determines AWLEN |
| `await master.burst_read(addr, length, *, size, burst, id, prot)` | `list[int]` | Multi-beat read; `length` = number of beats |
| `master.configure(**kwargs)` | `None` | Pass knobs to underlying BFM (see below) |
| `master.get_statistics()` | `dict` | Cumulative counters |
| `master.reset_statistics()` | `None` | Zero the counters |

#### Configure knobs

| Key | Type | Default | Description |
|---|---|---|---|
| `timeout_cycles` | int | 1000 | Per-channel handshake timeout |
| `default_id` | int | 0 | Default AWID/ARID |
| `b_ready_before_valid` | bool | True | Assert BREADY before BVALID |
| `r_ready_before_valid` | bool | True | Assert RREADY before RVALID |
| `b_ready_delay_min/max` | int | 0 | Backpressure delay on B channel |
| `r_ready_delay_min/max` | int | 0 | Backpressure delay on R channel |

`enable_random_delays` is forwarded but logged as a warning because it breaks
deterministic replay.

---

### OcahAxiLiteMasterAgent — AXI4-Lite (register access)

```python
from ocah_axi_vip import OcahAxiLiteMasterAgent

master = OcahAxiLiteMasterAgent(
    dut.axil_if,
    name="axilite_host",
    timeout_cycles=500,
    data_width=32,
    raise_on_error=True,
).sequence
```

| Method | Returns | Notes |
|---|---|---|
| `master.init_signals()` | `None` | Re-drive payload signals to 0 idle (already done at construction) |
| `await master.wait_for_reset()` | `None` | |
| `await master.write(addr, data, *, strb, prot)` | `int` (resp) | Compatibility helper |
| `await master.read(addr, *, prot)` | `int` (data) | Compatibility helper |
| `await master.write_result(addr, data, ...)` | `OcahAxiWriteResult` | Use for non-OKAY inspection; contiguous partial `strb` supported |
| `await master.read_result(addr, ...)` | `OcahAxiReadResult` | Use for read response inspection |
| `await master.write_skewed_result(addr, data, *, aw_valid_delay, w_valid_delay, b_ready_delay, ...)` | `OcahAxiWriteResult` | Single-beat write with independent AW/W launch skew and deferred BREADY (SV-UVM parity op) |
| `await master.read_hold_result(addr, hold_cycles, ...)` | `OcahAxiReadResult` | Read holding RREADY low after RVALID; `hold_stable` reports RDATA/RRESP stability (SV-UVM parity op) |
| `master.init_write(...)` / `master.init_read(...)` | cocotb event | Event-style access for explicit timeout flows |
| `master.configure(**kwargs)` | `None` | Same keys as AXI4, minus ID/burst/size |
| `master.get_statistics()` | `dict` | |
| `master.reset_statistics()` | `None` | |

---

### OcahAxiSlaveAgent — AXI4 memory-backed responder

```python
from ocah_axi_vip import OcahAxiSlaveAgent

ram = OcahAxiSlaveAgent.from_prefix(
    dut,
    "m_axi",
    dut.clk_i,
    dut.rst_n_i,
    reset_active_level=False,
    size=2**16,
).sequence

ram.write64(0x40, 0x0123_4567_89AB_CDEF)
observed = ram.read64(0x40)
```

| Method | Returns | Notes |
|---|---|---|
| `OcahAxiSlaveAgent.from_prefix(dut, prefix, clock, reset, ...).sequence` | `OcahAxiSlaveSequence` | Build from flattened AXI prefix |
| `read(addr, length)` | `bytes` | Backdoor byte read |
| `write(addr, data)` | `None` | Backdoor byte write |
| `read32(addr)` / `read64(addr)` | `int` | Little-endian integer reads |
| `write32(addr, value)` / `write64(addr, value)` | `None` | Little-endian integer writes |
| `hexdump(addr, length)` | `str` | Backend-generated memory dump |
| `inject_error(addr, resp, read=True, write=True)` | `None` | One-shot non-OKAY response injection |
| `clear_errors()` | `None` | Clear programmed errors |
| `enable_backpressure(channels, stall_cycles)` | `None` | Bounded READY stalls on `aw`, `w`, and/or `ar` |
| `disable_backpressure()` | `None` | Clear READY stalls |
| `backend` | cocotbext-backed RAM | Advanced debug-only access |

### OcahAxiLiteSlaveAgent — AXI4-Lite memory-backed responder

```python
from ocah_axi_vip import OcahAxiLiteSlaveAgent, RESP_DECERR

ram = OcahAxiLiteSlaveAgent.from_prefix(
    dut,
    "cfg_axil",
    dut.clk_i,
    dut.rst_ni,
    reset_active_level=False,
    size=2**16,
).sequence

ram.write32(0x10, 0xA5A5_5A5A)
ram.inject_error(0x20, RESP_DECERR, read=True, write=False)
```

It has the same backdoor and fault-control helpers as `OcahAxiSlaveAgent`.

---

### OcahAxiMonitor — passive AXI4 observation

```python
from ocah_axi_vip import OcahAxiMonitor

mon = OcahAxiMonitor(dut.axi_if, dut.aclk, name="passive_mon")

# Register callbacks (called with OcahAxiItem objects).
mon.add_write_callback(lambda item: ...)
mon.add_read_callback(lambda item: ...)

await mon.start()
# ... run traffic ...
await mon.stop()

writes = mon.get_write_transactions()   # list[OcahAxiItem]
stats  = mon.get_statistics()
```

Callback signature: `fn(item: OcahAxiItem) -> None`.

`OcahAxiLiteMonitor` has the same API for AXI4-Lite interfaces.

Attach `OcahAxiChecker` to a monitor for protocol sanity checks:

```python
checker = OcahAxiChecker()
checker.attach_monitor(mon)
...
checker.assert_clean()
```

---

## Plusargs

The following cocotb plusargs are recognised by the wrapper layer.  All are
optional and default to deterministic / non-verbose behaviour.

| Plusarg | Type | Default | Description |
|---|---|---|---|
| `+OCAH_AXI_TIMEOUT` | int | 1000 | Default `timeout_cycles` for all master instances constructed without an explicit value |
| `+OCAH_AXI_VERBOSE` | 0 or 1 | 0 | Set logging level to DEBUG for all ocah_axi_vip loggers |

Read them in your test with:

```python
import os
timeout = int(os.environ.get("COCOTB_PLUSARG_OCAH_AXI_TIMEOUT", "1000"))
master = OcahAxiLiteMasterAgent(dut.axil_if, timeout_cycles=timeout).sequence
```

Simulator plusarg forwarding varies by runner; see the cocotb documentation
for `PLUSARGS` / `SIM_ARGS` in Makefile or `sim_args` in `pyproject.toml`.

---

## Response codes

```python
from ocah_axi_vip import RESP_OKAY, RESP_SLVERR, RESP_DECERR, RESP_EXOKAY
```

| Constant | Value | Meaning |
|---|---|---|
| `RESP_OKAY` | 0 | Normal success |
| `RESP_EXOKAY` | 1 | Exclusive access success |
| `RESP_SLVERR` | 2 | Subordinate error |
| `RESP_DECERR` | 3 | Decode error |

---

## Error handling

By default (`raise_on_error=True`) all master methods raise a typed exception
on non-OKAY responses:

- `OcahAxiMasterError` — from `OcahAxiMasterAgent`
- `OcahAxiLiteMasterError` — from `OcahAxiLiteMasterAgent`

To inspect the response code manually:

```python
master = OcahAxiLiteMasterAgent(dut.axil_if, raise_on_error=False).sequence
result = await master.read_result(0x1000, check_response=False)
if not result.ok:
    cocotb.log.warning(f"read returned resp=0x{result.resp:X}")
```

Use `allow_timeout=True` with `timeout_ns=<n>` when a negative test
accepts a non-completing access. In that case the result has `timed_out=True`,
`ok=False`, and `resp=-1`.

---

## Determinism

Non-deterministic behaviour (random delays, random ID selection) is disabled
by default.  To enable random delays for stress/backpressure testing:

```python
master.configure(enable_random_delays=True, max_random_delay=5)
```

A warning is emitted each time `enable_random_delays` is forwarded so that
test logs make non-determinism visible.  Tests that use random delays should
also set a fixed cocotb seed via `COCOTB_RANDOM_SEED` to allow deterministic
replay of failures.

---

## Detailed Manual

See `MANUAL.md` in this folder for complete construction rules, result-object
semantics, DTP fault responder usage, SEP no-touch compatibility notes, and
migration guidance.

---

## Examples

See `examples/example_register_access.py` for annotated snippets covering the
AXI4 / AXI4-Lite master types and the passive monitor.

---

## Extending the wrapper

The wrapper API does not expose backend transaction types. If you need
fine-grained control (e.g. non-default QOS or LOCK bits) that the wrapper does
not expose, open an issue on the OCAH tracker so the API can be extended rather
than bypassed.

## Hierarchical VIP Layout

This package follows the OCAH hierarchical VIP convention (see
`hw/common/dv/README.md` and the 1_vip layout guide): all cocotb (Python)
code lives in `cocotb/`, and the root `__init__.py` is a thin shim
re-exporting the stable public API — always import
`from ocah_axi_vip import <Class>`, never from the subfolders.
`cov/` holds this package's framework-neutral commercial-simulator
functional-coverage model (`cov/ocah_axi_cov.sv` — plain covergroup/bind SV
with no UVM phasing, so the cocotb commercial-sim flow compiles it and the
UVM flow binds the same file). `interface/` holds the shared SV interfaces and
`uvm/` the SV-UVM agents and envs. The SV-UVM
template and the commercial-VIP plug-in contract (env-level factory
override, user-implemented API wrapper, monitor closing, nested vendor
interface) are documented in `../ocah_jtag_vip/README.md`
("Template Contract") — the reference implementation for all OCAH SV-UVM
VIPs.
