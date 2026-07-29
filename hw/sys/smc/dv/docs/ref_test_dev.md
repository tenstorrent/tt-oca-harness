<!-- SPDX-License-Identifier: Apache-2.0 -->
# Reference: SMC OSS DV — Test Development

How tests, sequences, and checkers are structured in the SMC OSS cocotb/PyUVM
environment (`hw/sys/smc/dv/`). The sibling SEP env
(`hw/sys/sep/dv/`) shares the same runner and cocotb/PyUVM idioms; where
SMC and SEP differ, this doc describes **SMC** and notes the SEP contrast.

## What kind of environment this is

- **cocotb + PyUVM**, not classic SystemVerilog UVM. Env, sequences, scoreboards,
  and models are Python.
- **Verilator** is the functional backend; VCS/Xcelium run the same cocotb tests
  for coverage. Driven by `tools/dv/run_dv.py`.
- **Two DUTs / two configs** (independent catalogs sharing this DV root):
  - `--dut smc` → `smc_sim_cfg.toml`, top `smc_uvm_top` (`tb/tb_top.sv`), env
    `cocotb/`. The primary DV surface (~130 tests). Memory / eFuse are backed by
    TB behavioral models (`models/mem/*.sv`, `models/analog/*.sv`).
  - `--dut smc` → `smc_sim_cfg.toml`, top `smc_uvm_top` (`tb/tb_top.sv`)
    instantiating `smc_wrapper`. eFuse
    / GPIO pads fold into wrapper RTL (SEP `sep_wrapper` direction); CPU mem
    ports remain external until absorbed.

The two envs have separate `smc_base_test` and `SmcEnvCfg` with different
bring-up and cfg fields — do not merge them.

## Directory layout

```
hw/sys/smc/dv/
├── cocotb/                 # bare-SMC PyUVM env
│   ├── env/                #   agents, monitors, scoreboard, memory model, env cfg
│   ├── seq_lib/            #   sequences + protocol VIP/BFM helpers
│   ├── tests/              #   @pyuvm.test() entries + smc_base_test.py
│   └── wrapper/            # smc_wrapper flavor (own base_test + env_cfg + seq_lib)
├── models/{mem,analog,wrapper,regs}/  # behavioral / sim stand-ins
├── tb/                     # tb_top.sv, verilator_stubs/
├── testlists/              # per-feature TOML leaves + all.toml (groups)
├── assets/                 # ROM/eFuse/shadow preload images
├── smc_sim_cfg.toml        # sole launch config (tb_top → smc_wrapper)
└── docs/                   # SMC_VPLAN.adoc + notes
```

## The three-layer test structure

Mirrors UVM test / sequence / item, in Python.

### 1. Test — `cocotb/tests/<name>.py`

Inherit `smc_base_test`, override `run_scenario()`:

```python
# SPDX-License-Identifier: Apache-2.0
import pyuvm
from smc_base_test import smc_base_test
from seq_lib.smc_register_sanity_test_seq import smc_register_sanity_test_seq

@pyuvm.test()
class smc_register_sanity_test(smc_base_test):
    # Optional: auto-record a protocol-VIP evidence item after the scenario.
    protocol_vip_kind = None  # or e.g. SmcProtocolVipKind.I2C

    async def run_scenario(self) -> None:
        seq = smc_register_sanity_test_seq("reg_sanity_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
```

`smc_base_test.run_phase()` does `raise_objection()` → `_bring_up()` →
`run_scenario()` → optional protocol-VIP auto-record → `drop_objection()`. Put
stimulus in `run_scenario()`; do not re-implement `run_phase`.

### 2. Base test — `cocotb/tests/smc_base_test.py`

- `build_phase()` builds `SmcEnvCfg`, randomizes timing from the seed, publishes
  cfg to `ConfigDB`, builds `SmcEnv`.
- `_bring_up()` — the **power-good + cold-reset** sequence: drives all idle-safe
  pad defaults (i2c/i3c/jtag/spi/telemetry/avsbus/octs), starts the three clocks
  (`clk_ref_i / clk_smc_i / clk_periph_i`), asserts power-good, releases
  `rst_cold_ni`, settles, then sets `cfg.reset_done`. (SEP contrast: SEP gates on
  `sep_fuse_sense_done_o` and has no-cpu / cpu-boot / firmware-boot variants.)
- `start_seq(seq, sequencer=None)` — runs a sequence, injecting `seq.cfg`/
  `seq.env`; defaults to the `i2c_agent` sequencer, so **pass the sequencer you
  want** (usually `self.env.sys_axi_agent.sequencer` for CSR traffic).
- `record_protocol_vip(kind, scenario, ...)` — emit an evidence item (below).
- Auto-record: set the test class attribute `protocol_vip_kind`
  (`SmcProtocolVipKind`) to auto-emit one at end of `run_phase`. A legacy
  name→kind map (`_PROTOCOL_VIP_TESTS`) still works for older tests; the class
  attribute is preferred for new tests.

### 3. Sequence — `cocotb/seq_lib/<name>_seq.py`

CSR sequences inherit `SmcCsrSeq` (`seq_lib/smc_csr_seq_utils.py`), which wraps
`SmcSysAxiItem` in compact helpers:

```python
from seq_lib.smc_csr_seq_utils import SmcCsrSeq

class smc_register_sanity_test_seq(SmcCsrSeq):
    async def body(self) -> None:
        await self.csr_read("VERSION_LO", 0xC000_0000, expected=0x000100A0)
        await self.csr_write_readback("SCRATCH", 0xC001_0040, 0xDEAD_BEEF)
        # Negative path: window must return an error response (not OKAY/wedge).
        await self.csr_read_err_signature("I3C_STUB", 0xC000_A000)  # asserts 0xBADCAB1E
```

Key `SmcCsrSeq` helpers: `csr_read(expected=)`, `csr_write`,
`csr_write_readback`, `csr_read_many`, `csr_read_err_signature` /
`csr_read_expect_error` (strict negative), `csr_read_allow_error` (tolerant),
`csr_read_bounded` (tolerates DECERR **and** timeout), `assert_all_reachable` /
`assert_reachable_or_gated` (non-vacuous reachability gates).

`smc_base_test_seq` is the minimal, agent-agnostic base for non-CSR sequences
(gpio/clk/reset/irq item types), dispatched via `_OneShot` (below).

## Env and agents (`cocotb/env/smc_env.py`)

Agents are split by **honesty class** — this is the defining SMC structure:

- **SAMPLE-only** (observability sampling, NOT protocol BFMs): `i2c_agent`,
  `reset_agent`, `clk_agent`, `irq_agent`, `gpio_agent`, `axil_agent`.
- **Protocol / traffic**: `sys_axi_agent` (SEP_IN, prefix `s_axi`),
  `sys_in_axi_agent` (`sys_axi`), `jtag_axi_agent` (`jtag_axi`) — all
  `SmcSysAxiDriver` subclasses over `ocah_axi_vip.OcahAxiMaster`, differing only
  by `bus_prefix`; plus `protocol_vip_agent` (records scenario evidence items).
- **Passive monitors**: `axi_monitor` (SEP_IN), `output_axi_monitor` (SYS_OUT).

Every agent's analysis port connects to the single `SmcScoreboard`.

`SmcSysAxiItem` fields: `op`, `addr`, `length`, `wdata`, `expected` (value check),
`expected_resp` (exact response code), `allow_error` (tolerate non-OKAY),
`expect_error` (structural negative-path guard — see below), `allow_timeout`,
`timeout_ns`, and `update_golden`/`check_golden`/`memory_region` for the memory
model.

## Scoreboard — `cocotb/env/smc_scoreboard.py`

A **multi-item-type dispatcher** (`write()` branches on item class), unlike SEP's
single-item value scoreboard. Per type:

- **SAMPLE items** (i2c/reset/clk/irq/gpio/axil): assert `resolvable` (no X/Z) and
  the type's idle invariants; emit `FUNC_COV_VALUE` coverage bins. (GPIO
  aggregates are checked for resolvability only — their level is a bus-aggregate
  artifact, not GPIO-diagnostic; isolated per-pad drive is proven by
  `smc_gpio_output_driveback_test`.)
- **`SmcSysAxiItem`** (`_check_sys_axi`):
  - `expect_error` items: must return a real error (SLVERR/DECERR) — **fails on
    OKAY and on timeout**. This structural guard means a wrongly-OKAY blocked
    access fails at the checker layer, not only in the sequence body. Set by
    `csr_read_err_signature` / `csr_read_expect_error`.
  - otherwise: assert OKAY (`resp_ok`); if `expected_resp` set, assert exact code;
    if `expected` set, assert exact read value.
  - **Memory-model golden**: `update_golden` writes to the TB-local
    `SmcMemoryModel` (never a DUT backdoor); `check_golden` compares a read
    against it. Both refuse non-OKAY traffic.
- **`SmcProtocolVipItem`** (`_check_protocol_vip`): validates evidence
  consistency (passed, non-empty scenario/details, `timeouts <= csr_accesses`)
  and an optional byte-level golden (`expected_bytes` vs `observed_bytes`).

`check_phase()` asserts total evidence `> 0` (non-vacuity house rule).

## Protocol-VIP "proxy" pattern (SMC-specific)

Many peripherals have no public BFM yet, so tests drive CSR via direct AXI and
the **real protocol assertions live in the sequence body**; the sequence then
records a `SmcProtocolVipItem` (kind, scenario, `csr_accesses`, `timeouts`,
`proxy=True`, optional `expected_bytes`/`observed_bytes`) as evidence. The base
test auto-records one when `protocol_vip_kind` (or the legacy map) resolves.
`proxy=False` marks a scenario driven by a real BFM. (SEP has no proxy concept —
it uses real BFMs such as `OcahSpiFlash` and golden-chain scoreboards.)

## Cross-sequencer dispatch — `_OneShot`

To drive several agents from one parent sequence, wrap each item in `_OneShot`
and start it on the target agent's sequencer:

```python
from seq_lib._one_shot import _OneShot
await _OneShot(reset_item, "os").start(self.env.reset_agent.sequencer)
await _OneShot(clk_item,   "os").start(self.env.clk_agent.sequencer)
```

`smc_canonical_smoke_test` uses this to run reset/i2c/clk/irq/gpio/axil
observability in one scenario.

## Testlists (TOML)

`testlists/all.toml` includes the per-feature leaves and defines `groups`
(`smoke`, `pyuvm`). Each test entry lives once in a leaf list:

```toml
[[tests]]
name = "smc_register_sanity_test"
module = "smc_register_sanity_test"   # module under cocotb/tests/
target = "default"
seed = 1
timeout_sec = 1800
tags = ["smoke", "csr"]
run_modes = ["smoke"]
```

The `smc_wrapper` catalog is `testlists/wrapper.toml` (independent of `all.toml`).

## How to run

```bash
PY=tools/dv/run_dv.py
python3 $PY --dut smc --items smc_canonical_smoke_test --stage flist --stage sim
python3 $PY --dut smc --items all --tag smoke --stage sim
python3 $PY --dut smc --items all --tag smoke --tool vcs --cov
python3 $PY --dut smc --items all --stage sim --regress
python3 $PY --dut smc --items all
```

Prereqs: Python 3.11+ with the OSS DV BFM installed
(`pip install -e hw/common/dv` → cocotb + pyuvm + cocotbext-axi),
Verilator on PATH, C++20 toolchain (g++ ≥10) for the model build.

## House rules

- **PASS/FAIL needs positive evidence from `results.xml`** (parser registry
  `hw/common/dv/configs/parsers.toml`) — a clean exit alone is not enough.
  The scoreboard also asserts non-vacuity (`total > 0`).
- **No DUT backdoor writes**: the only `.value=` writes in `seq_lib` target
  TB external-pad stimulus (`dut.tb_*`), never internal DUT registers. The
  memory-model golden is TB-local, not a DUT-hierarchy read.
- **OSS hygiene**: the public filelist must be vendor-clean — verify with
  `check_no_vendor_paths.py --filelist build/smc_bender.f --target smc`. Never
  commit simulator artifacts (waves/logs/xrun tmpdirs); the local `.gitignore`
  covers them.
- **Negative checks belong at the checker layer**: use `expect_error` (via the
  strict `csr_read_err_signature`/`csr_read_expect_error` helpers) so a
  wrongly-OKAY blocked access fails structurally, not just in a sequence assert.
- **Golden-value traceability**: prefer RDL-cited reset values over
  golden==observed regression-locks; where a value is not RDL-traceable, label it
  a regression-lock with its real source (see `smcoss_audit.md`, finding F1).
