# ocah_entropy_vip — OCAH Entropy Stream BFM

SPDX-License-Identifier: Apache-2.0

Configurable AXI-Stream entropy driver and passive monitor for the SEP TRNG
DV path.  Provides the testbench with `OcahEntropySource` (driver) and
`OcahEntropyMonitor` (passive observer) to exercise the SEP `ext_trng_axis_req_i`
/ `ext_trng_axis_rsp_o` AXI-Stream interface and the sideband `ext_trng_irq_i`
/ `ext_trng_alarm_i` signals.

---

## Purpose

The SEP TRNG vendor core (`trng_wrapper` + Synopsys TRNG) is not available in
the public-flow simulation.  The Task #12 RTL stub (`trng_core_stub`) replaces
the innermost vendor core, but tests that skip the full `trng_wrapper` pipeline
and drive entropy directly into SEP need a Python-level BFM.  This package
fills that role.

Key properties:

- **Deterministic by default** — emits one word (`0xDEAD_BEEF`) then stalls.
  Same word, same sequence, every run, without any configuration.
- **Random mode is opt-in** — `enable_random(seed)` requires an explicit fixed
  seed.  Time-of-day seeds are forbidden and enforced at construction time.
- **Backpressure support** — `set_backpressure(prob)` inserts stall cycles on
  TVALID using a reproducible internal PRNG.
- **IRQ and alarm injection** — `inject_irq()` / `inject_alarm()` assert the
  sideband signals for negative-test coverage.

---

## Package Layout

```
ocah_entropy_vip/
  __init__.py                    — public exports
  ocah_entropy_source.py         — OcahEntropySource driver
  ocah_entropy_monitor.py        — OcahEntropyMonitor passive observer
  examples/
    example_deterministic_entropy.py — annotated usage snippets
  README.md                      — this file
```

---

## Signal Mapping

The BFM is connected to the DUT via one of two mechanisms:

**Option A — `dut` handle (standard naming)**

```python
src = OcahEntropySource(dut.clk_i, dut=dut, stream_idx=0)
```

Resolves the following signal names from `dut`:

| BFM role | DUT signal |
|---|---|
| Drive TVALID | `ext_trng_axis_req_i_tvalid[stream_idx]` |
| Drive TDATA  | `ext_trng_axis_req_i_tdata[stream_idx]`  |
| Drive TSTRB  | `ext_trng_axis_req_i_tstrb[stream_idx]`  |
| Sample TREADY | `ext_trng_axis_rsp_o_tready[stream_idx]` |
| Assert IRQ   | `ext_trng_irq_i` |
| Assert ALARM | `ext_trng_alarm_i` |

**Option B — `signals` dict (non-standard naming)**

```python
src = OcahEntropySource(
    dut.clk_i,
    signals={
        "tvalid": dut.my_tvalid,
        "tdata":  dut.my_tdata,
        "tstrb":  dut.my_tstrb,
        "tready": dut.my_tready,
        "irq":    dut.my_irq,
        "alarm":  dut.my_alarm,
    },
)
```

---

## API Reference

### OcahEntropySource

```python
from ocah_entropy_vip import OcahEntropySource

src = OcahEntropySource(
    clock,               # cocotb clock handle
    dut=dut,             # or: signals=<dict>
    stream_idx=0,        # stream lane index (when using dut=)
    name="entropy_src",  # label for log messages
)
```

| Method | Returns | Notes |
|---|---|---|
| `src.init_signals()` | `None` | Drive all outputs to idle; call before first clock edge |
| `await src.start()` | `None` | Start the AXI-Stream driver coroutine |
| `await src.stop()` | `None` | Stop the coroutine; deassert TVALID |
| `src.set_pattern(words)` | `None` | Emit a list of 32-bit words in order, then stall |
| `src.set_constant_word(w)` | `None` | Drive the same word indefinitely |
| `src.enable_random(seed)` | `None` | Opt-in PRNG; explicit fixed `seed` required |
| `src.set_backpressure(prob)` | `None` | TVALID stall probability [0.0, 1.0] |
| `await src.inject_irq(duration_cycles)` | `None` | Assert `ext_trng_irq_i` for N cycles |
| `await src.inject_alarm(duration_cycles)` | `None` | Assert `ext_trng_alarm_i` for N cycles |
| `src.get_statistics()` | `dict` | `handshakes`, `backpressure_cycles` |
| `src.reset_statistics()` | `None` | Zero counters |

### Deterministic-by-Default Contract

After `init_signals()` and `start()`, the BFM emits **exactly one word** from
`+sep_entropy_word` (default `0xDEAD_BEEF`), then deasserts TVALID and stalls.
This mirrors the Task #12 `trng_core_stub` one-shot behavior.

To emit more words, call `set_pattern()`, `set_constant_word()`, or
`enable_random()` before or after `start()`.

### OcahEntropyMonitor

```python
from ocah_entropy_vip import OcahEntropyMonitor

mon = OcahEntropyMonitor(
    clock,
    dut=dut,
    stream_idx=0,
    name="entropy_mon",
    max_history=4096,
)
```

| Method | Returns | Notes |
|---|---|---|
| `mon.add_data_callback(fn)` | `None` | fn(word: int) on each accepted transfer |
| `mon.add_irq_callback(fn)` | `None` | fn(level: int) on IRQ edge |
| `mon.add_alarm_callback(fn)` | `None` | fn(level: int) on alarm edge |
| `await mon.start()` | `None` | Start passive monitoring |
| `await mon.stop()` | `None` | Stop monitoring |
| `mon.get_words()` | `list[int]` | Every accepted entropy word in transfer order |
| `mon.get_irq_events()` | `list[dict]` | `{"sim_time": float, "level": int}` per edge |
| `mon.get_alarm_events()` | `list[dict]` | Same format |
| `mon.get_statistics()` | `dict` | See below |
| `mon.clear_history()` | `None` | Discard word/event lists |
| `mon.reset_statistics()` | `None` | Zero counters + clear history |

Statistics dict keys: `handshakes`, `irq_assertions`, `alarm_assertions`,
`words_recorded`, `irq_events_recorded`, `alarm_events_recorded`.

---

## Plusargs

All plusargs are optional.  When absent, the BFM applies the documented defaults.

| Plusarg | Default | Description |
|---|---|---|
| `+sep_entropy_word=<hex>` | `0xDEAD_BEEF` | Default 32-bit word for single-word mode. Sampled at `OcahEntropySource` construction time. |
| `+sep_entropy_seed=<N>` | — | If present, `enable_random()` is called automatically during `start()` with this decimal seed. Takes precedence over single-word mode. |
| `+sep_entropy_pattern=<file>` | — | Path to a text file with one hex word per line. If present, `set_pattern()` is called automatically during `start()` with the file contents. |

Cocotb surfaces plusargs as `COCOTB_PLUSARG_<KEY>=<VALUE>` in the process
environment (cocotb >= 1.8 with a forwarding runner).  When the runner does
not forward plusargs, pass values programmatically through the Python API.

Example runner invocation (Verilator):

```makefile
SIM_ARGS += +sep_entropy_word=cafebabe
SIM_ARGS += +sep_entropy_seed=12345
```

---

## AXI-Stream Driver Implementation

The BFM implements the AXI-Stream producer protocol locally without an
external dependency on `cocotbext-axi`.  Reasons:

1. The project does not guarantee `cocotbext-axi` is installed in the
   simulation environment.
2. The entropy stream is 32-bit, 1-lane, with no ID/LAST/USER fields — a
   full AXI-Stream VIP adds unnecessary complexity.

Protocol rules implemented:

- TVALID is asserted when a word is available from the generator.
- Once asserted, TVALID stays high until TREADY is sampled high (transfer
  completes on the rising clock edge when both are high).
- TSTRB is always `0xF` (all bytes valid).
- After the generator is exhausted, TVALID is deasserted.

**Migration note:** if `cocotbext-axi` is later added to the project
environment, the `_run_stream_loop` method in `ocah_entropy_source.py` can
be replaced with a `cocotbext_axi.AxiStreamSource` instance.  The public
`OcahEntropySource` API does not change at that migration point.

---

## Modes and Default Behavior

| Mode | How to activate | Terminates? |
|---|---|---|
| Single-word deterministic | `init_signals()` (automatic default) | Yes — stalls after one word |
| Fixed-pattern | `set_pattern(words)` | Yes — stalls after last word |
| Constant word | `set_constant_word(w)` | No |
| PRNG (opt-in) | `enable_random(seed)` | No |

Switching mode while the driver is running: call `set_pattern()`,
`set_constant_word()`, or `enable_random()` at any time.  The change takes
effect at the next generator poll (next clock edge where the BFM is ready for
a new word).

---

## Backpressure

```python
src.set_backpressure(prob=0.5)   # 50% stall probability
```

When backpressure probability is non-zero, the BFM randomly deasserts TVALID
for one cycle before presenting each word.  The backpressure PRNG uses a fixed
internal seed (0) so the stall pattern is reproducible across runs.

To change the backpressure seed, access `src._bp_rng.seed(new_seed)` directly
(not part of the stable API; use with care).

---

## Scope Exclusions

The following are intentionally out of scope for this BFM:

- **Health-test logic** — TRNG health counters and diagnostic registers.
  Use the `trng_wrapper` CSR path (AXI-Lite) for health-test tests.
- **CSR access** — AXI-Lite CSR programming of `trng_wrapper` registers.
  Use `OcahAxiLiteMaster` from `ocah_axi_vip` for that path.
- **Multi-stream simultaneous drive** — instantiate one `OcahEntropySource`
  per stream lane and assign `stream_idx` accordingly.

---

## Examples

See `examples/example_deterministic_entropy.py` for annotated snippets covering:

1. Default deterministic mode
2. Fixed-pattern mode
3. Backpressure test
4. PRNG mode (opt-in)
5. IRQ / alarm injection
6. Non-standard signal names via `signals` dict

---

## Determinism Guarantee

> **Time-of-day seeds are forbidden.**

`enable_random()` raises `OcahEntropySourceError` if `seed` is not a `int`.
This guards against `float(time.time())` or similar patterns that break
deterministic replay.

All BFM randomness (entropy words and backpressure decisions) uses Python's
`random.Random` with an explicit, caller-supplied seed.  The same seed always
produces the same sequence on any machine, simulator, and OS.
