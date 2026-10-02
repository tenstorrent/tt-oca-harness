<!-- SPDX-License-Identifier: Apache-2.0 -->
# How to add a SEP DV testcase

A new testcase is **three edits**, in this order:

| # | File | Purpose |
|---|---|---|
| 1 | `cocotb/tests/<area>/<name>.py` | the stimulus and the checkers |
| 2 | `testlists/<area>.toml` | declare the scenario and its build axes |
| 3 | `testlists/all.toml` | add the name to the regression group(s) |

Nothing scans the filesystem for tests. A `.py` file that no testlist names is
dead code, and a testlist `name` that no group lists never runs in a regression.

---

## Step 0 — choose the three axes first

The axes decide the build, not the test body. Get them wrong and the test
compiles a model it cannot use.

| Axis | Key | Values | Choose |
|---|---|---|---|
| Run mode | `run_modes` | `no_cpu` / `cpu` | `no_cpu` if a cocotb AXI master can reach the DUT registers. `cpu` if firmware must execute. |
| RTL target | `target` | *(omit)* / `lsu_stub_all_live` / `rom_boot` | `lsu_stub_all_live` **with** `no_cpu`. Omit for `cpu` (full VeeR model). `rom_boot` only for production Boot ROM tests. |
| Firmware | `firmware` | *(omit)* / `"<name>"` / `{ name, mode }` | Omit unless the CPU runs an image. |

`run_modes` and `target` must agree. `no_cpu` + the default target builds the
full CPU and then holds it off — slow, and the LSU splice is absent.

Definitions: `[run_modes.*]` and `[targets.*]` in `sep_sim_cfg.toml`.

---

## Step 1 — write the test

Path is `cocotb/tests/<area>/<name>.py`. The subdirectory must hold an
`__init__.py` (all current ones do). Filename should equal the testlist `name`.

```python
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""One line: what this test proves."""

from __future__ import annotations

import pyuvm

from sep_base_test import sep_base_test
from seq_lib.sep_my_feature_seq import sep_my_feature_seq


@pyuvm.test()
class sep_my_feature_test(sep_base_test):
    """What the DUT must do, and what would make this test fail."""

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        await self.start_seq(sep_my_feature_seq("my_feature_seq"))
```

Rules that are enforced, not stylistic:

* **Override `run_scenario()`, not `run_phase()`.** The base class raises and
  drops the UVM objection around it.
* **One `@pyuvm.test()` class per module.** The launcher sets no test filter, so
  cocotb runs *every* registered test in the module. `@pyuvm.test()` registers
  into the module that defines the class, so importing a shared base from a
  sibling module (see `rom_fw/sep_backup_manifest_fail_base.py`) does not
  re-register the parent.
* **Import path.** `sys.path` gets, in order: `cocotb/tests`, `cocotb`,
  `hw/common/dv/vip`, `cocotb/env`. So `from seq_lib.x import y`,
  `from env.x import y`, and `from sep_base_test import sep_base_test` all work;
  a relative import does not.

### What `sep_base_test` already gives you

Do not re-implement these in a test.

| Call | Use |
|---|---|
| `await self.bring_up_no_cpu()` | clocks, reset, wait `sep_fuse_sense_done_o` |
| `await self.bring_up_cpu_boot(rst_vec, ...)` | same, CPU owns its buses |
| `await self.boot_firmware(sb, itcm_hex, dtcm_hex, rst_vec=…, max_run_cycles=…)` | stage TCM images, boot, poll to completion |
| `await self.poll_boot(sb, …)` | poll only — use when stimulus must run concurrently |
| `await self.resense()` | re-pulse reset for a second fuse sense |
| `await self.start_seq(seq)` / `start_ext_seq(seq)` | CPU-LSU AXI (`s_axi`) / external SMN AXI (`m_axi`) |
| `await self.jtag_axil_op(write=…, addr=…)` | JTAG AXI-Lite (`j_axi`), returns `(resp, rdata)` |
| `self.select_efuse_image(...)` / `self.write_efuse_image(img)` | OTP content |
| `await self.bring_up_entropy(...)` | ESRC→DRBG→CSRNG→EDN stack + CHK1..CHK5 scoreboard |
| `self.rd(sig)` | read a signal, X/Z → 0 |
| `self.random_seed()` | the runner seed; use it for any randomization |

Two traps:

* A test that does **not** pass `+skip_fuse_sense` runs the real 256-word sense,
  and the base class then auto-compares the sensed shadow against the golden.
  It **raises** if you never called `write_efuse_image()`.
* Set `build_env = False` on the class only if the test must not build `SepEnv`.

### Where stimulus goes

Multi-step register traffic belongs in `cocotb/seq_lib/sep_<name>_seq.py` as a
`uvm_sequence`, not inline in the test. Use `sym("…")` from `sep_reg_meta` for
addresses so the RDL stays the single source:

```python
from sep_reg_meta import sym
SEP_SRAM_BASE = sym("SEP_SRAM_MEM_BASE_ADDR")
```

---

## Step 2 — declare it in a testlist

Add a `[[tests]]` entry to the leaf file for the area (`system.toml`,
`cpu.toml`, `memory.toml`, `crypto.toml`, `efuse_lcc.toml`, `km.toml`,
`spi.toml`, `rom_fw.toml`). `all.toml` includes them all.

```toml
[[tests]]
# Prose goes in a comment: what it proves, why the axes are what they are,
# and what a pass does NOT cover. There is no `description` key.
name = "sep_my_feature_test"
module = "system.sep_my_feature_test"
seed = 1
timeout_sec = 1800
tags = ["my_feature", "subsystem"]
run_modes = ["no_cpu"]
target = "lsu_stub_all_live"
args = ["+skip_fuse_sense"]
```

**The 11 allowed keys — anything else is a hard config error:**

| Key | Req | Notes |
|---|---|---|
| `name` | yes | the `--items` token; must be unique across all included files |
| `module` | no | dotted path under `cocotb/tests`; **defaults to `name`**, which is wrong for every test in a subdirectory — always write it |
| `target` | no | `[targets.<name>]`; defaults to `[defaults].target` |
| `seed` | no | default 1; `--seed` wins; ignored under `--regress` |
| `reseed` | no | seeds per test under `--regress` |
| `timeout_sec` | no | `--timeout` > this > run-mode > 1800 |
| `tags` | no | for `--tag`. **Not validated** — a typo silently matches nothing |
| `run_modes` | no | `[0]` is the default mode. **Not validated** — an unknown name silently applies no args and no timeout |
| `firmware` | no | see below; omit it and `c_compile` is skipped |
| `args` | no | run args/plusargs; only `{seed}` and `{repo_root}` are substituted |
| `overrides` | no | `[tests.overrides.cocotb]`, inner keys `seed`/`timeout_sec`/`args` only; `args` append |

**`firmware`, two forms:**

```toml
firmware = "hello_world"                                # [c_build.default],   {fw_target}=hello_world
firmware = { name = "boot_rom", mode = "boot_rom" }     # [c_build.boot_rom]
```

An undeclared `mode` fails `c_compile` with `missing [c_build.<mode>] template`.
Declared outputs are re-checked at sim time, so a bare `--stage sim` fails with
`firmware outputs missing` rather than simulating a stale image.

**Arg layering**, lowest to highest:

```
[sim].args  <  [run_modes.<mode>].args  <  [[tests]].args  <  --sim-arg  <  --plusarg
```

Put plusargs in `args`. The `plusargs` key inside `[run_modes.*]` is accepted by
the schema but read by nothing.

---

## Step 3 — add it to a group

Groups live **only** in `all.toml`, as `[[groups]]` with an explicit `tests`
list. Nothing is derived from tags or run modes.

Add the name to `all`, plus the class group matching `run_modes[0]`
(`no_cpu`, `cpu`, or `rom_fw`). Add to `smoke` only for a fast test with no
firmware dependency — CI runs `--items smoke`.

---

## Step 4 — validate, then run

```bash
PY=tools/dv/run_dv.py

# Config only. Catches every schema error. Never imports your Python.
# Expect: `sep  OK` and `N DUT(s) ... 0 FAILED`.
python3 $PY --validate-configs

# Imports every testlist `module` in a child interpreter with the real
# PYTHONPATH. This is what catches a wrong `module` string or an import error.
# Expect: `test modules  OK  <N> modules import with the run PYTHONPATH`.
python3 $PY --doctor --dut sep

# Confirm the launcher resolved the binding you intended. Note `--items` does
# NOT filter `--list`; the JSON view is the one with per-test bindings and tags.
python3 $PY --dut sep --list --json

# Run it. Include hdl_compile: `--stage sim` alone reuses the model on disk,
# and a stale model can report a pass the current RTL would not give.
python3 $PY --dut sep --items sep_my_feature_test \
  --stage flist --stage hdl_compile --stage sim
```

Firmware tests also need `--stage c_compile`. It is auto-inserted when no
`--stage` is given at all and the selection declares `firmware`.

`--items` is `nargs='+'` — pass several names to **one** flag
(`--items a b c`). Repeating the flag keeps only the last group, and the run
still reports success for the reduced set.

Logs land in `build/runs/<run-id>/` (gitignored).

---

## What counts as a passing test

**PASS requires positive evidence in `results.xml`. A clean simulator exit is
not evidence.** State the check in the failure message so a red run is readable
without a waveform:

```python
assert actual == expected, (
    f"CHK-FOO FAIL: SRAM word0 = 0x{actual:08x}, expected 0x{expected:08x}"
)
```

Give each checker a stable tag (`CHK-…`) and log it on pass too. The
verification plans cite those tags; a checker with no runnable proof does not
get a row.

When a new test goes red, classify before editing:

* **(A) test issue** — wrong harness wiring, wrong expected value, timeout,
  seed. Fix it, and say what changed and why.
* **(B) DUT/design issue** — RTL or ROM does not match the spec. **Stop and
  report** with spec reference, log excerpt, and repro. Do not relax the
  assertion, skip the path, or comment out the case.

A test that fails because it found a real bug has done its job.

---

## Where the DUT ends — and what that means for your claim

**This testbench verifies SEP. Everything outside SEP is a model, on purpose.**
That is the intended scope, not a gap to apologise for. But it draws a hard line
around what a green run is allowed to mean, and that line is easy to cross by
accident.

The SMC is an `axi_sim_mem` — a flat behavioural memory instantiated as
`u_smc_mem` in `../tb/tb_top.sv`. It has no register semantics at all. So when a
plusarg "sets a register", what it really does is write bytes into that memory at
the address the ROM will read:

```systemverilog
// tb_top.sv — +sep_dft_status
u_smc_mem.mem[56'h4000_F800] = dft_status_ovr[7:0];
u_smc_mem.mem[56'h4000_F801] = dft_status_ovr[15:8];
// ... etc
```

`+sep_dft_status`, `+sep_straps_hi`, `+sep_boot_from_spi` and `+sep_smc_mem_hex`
all work this way. That is legitimate stimulus — SEP still performs the real AXI
read, and its decision logic is genuinely under test. It is not a backdoor into
SEP.

### The four things a memory model cannot reproduce

Take `DFX_CTRL_STATUS_SMU` as the worked example. In real hardware its fields are
declared `sw = r; hw = w; stickybit`
(`hw/sys/smc/regs/blocks/dfx_ctrl_status/dfx_ctrl_status.rdl`), driven by wires
from chip-level DFT through `smu_wrapper.sv` → `smc.sv` → `smc_base.sv`. Against
that, a flat memory loses:

| Property | Real hardware | `axi_sim_mem` |
|---|---|---|
| **Address** | fixed by the SMC register map | wherever the ROM reads — the TB was written to match |
| **Sticky** | sticky-1 until reset | an ordinary memory location |
| **Access** | software cannot write it | software can write it freely |
| **Timing** | published by DFT at some point relative to reset release | present from t=0 |

### The rule this gives you

**Assert what SEP does with a value. Never assert that the value was correct to
begin with.**

The address row is the one that bites hardest, and it is worth understanding why
rather than memorising it. The TB writes at `0x4000_F800` for exactly one reason:
that is where the ROM reads. Instrument and DUT share the assumption under test,
so no run in this environment can ever falsify it — a wrong offset in
`bootrom/prod/include/sep_smc_interface.h` would look identical to a right one.
The same applies to every SMC-side offset the ROM uses: SRAM, straps, scratch,
fuse map, chip ID.

So a testcase like `sep_firmware_mbist_pass_test` legitimately covers *the ROM
continues when it reads a success bit, halts when it does not, and honours the
bypass fuse*. It does not cover *the memory-repair reporting path*, and a
verification plan must not book it as such. If the feature you are booked against
lives partly on the far side of the boundary, say so in the status report's
`failure_or_blocker_summary` — not only in a comment — so a green row cannot be
merged as coverage that does not exist.

### When you actually need the real thing

Closing any of the four rows needs an integration testbench where SEP sees the
real SMC RTL with its hardware inputs driven. That is not a change to this
testbench; there is no real SMC here to drive. Raise it as a separate scope
question rather than trying to approximate it with a better model, because a
better model still shares the DUT's assumptions.

---

## Error messages and what they mean

| Message | Cause |
|---|---|
| `<file> [[tests]]: unsupported key(s): …` | key not in the 11 above (e.g. `description`) |
| `<file>: duplicate test \`x\`` / `… after include expansion` | the name exists in another leaf testlist |
| `unknown test/group \`x\`` | `--items` name is in no testlist and no group |
| `selected target \`x\` is not defined in [targets.x]` | typo in `target` |
| `missing [c_build.<mode>] template` | `firmware.mode` has no profile in `sep_sim_cfg.toml` |
| `firmware outputs missing for \`x\`; run c_compile first` | `--stage sim` without a built image |
| `ModuleNotFoundError` at sim start | `module` path wrong, or the subdirectory has no `__init__.py` |
| test runs but does nothing | `run_scenario()` not overridden, or `@pyuvm.test()` missing |

---

## Reference

* Env, run modes, layout — [`../README.md`](../README.md)
* eFuse selection, memory models, ROM builds — [`dv_env_reference.adoc`](dv_env_reference.adoc)
* eFuse OTP images from TOML — [`../tb/efuse_preloads/efuse_configurations/README.md`](../tb/efuse_preloads/efuse_configurations/README.md)
* Schema source of truth — `tools/dv/runlib/config.py` (`TEST_KEYS`, `GROUP_KEYS`, `TARGET_KEYS`, `RUN_MODE_KEYS`)
