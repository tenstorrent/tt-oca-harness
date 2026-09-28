# Cover SEP-ROM-FUSE-010 with a fuse-sense hold test

**Status:** proposed
**Area:** SEP ROM DV (`hw/sys/sep/dv`), SEP ROM spec `[S08]`
**Raised:** 2026-09-10, during the SEP ROM specification review

## Summary

`[S08]` blocks the boot until the SMC reports fuse sensing complete, and
**[SEP-ROM-FUSE-010]** requires exactly that ordering. The stimulus needed to prove the ROM
really refuses to advance already exists — `+sep_smc_fuse_sense_hold` in `dv/tb/tb_top.sv` —
but **no test drives it**. So the requirement has positive coverage only, from boots that
proceed because the bit is already high, and nothing demonstrates the refusal.

This ticket asks for the negative test, plus an ordering assertion on the passing path.

## What is true today

### The requirement and what implements it

`[SEP-ROM-FUSE-010]`: *the ROM shall not consume any fuse shadow value before fuse sensing has
completed.* Completion is bit 0 (`smc_fuse_sense_done`) of
`SEP_CPU_CTRL_SMC_FUSE_SENSE_STATUS`, polled without timeout — the hang is the accepted BL0
failure mode under `[SEP-ROM-CPU-080]`, because the ROM never arms the watchdog.

The implementation is `smc_wait_fuse_sense()` in `bootrom/prod/include/sep_smc_interface.h`,
called unconditionally as `[S08]` in `rom_main.c` between `[S07]` (status init) and `[S09]`
(clock init). It emits `FUSE_SENSE_WAIT` before the poll and `FUSE_SENSE_DONE` after, and
reports `SEP_MSG_FUSE_SENSE_WAIT` (`0x9e`).

What it gates: `[S09]`'s `smu_pll_sysclk` read, `[S11]` lifecycle, `[S18]` `SBOOT_DIS`, and the
key-digest, revocation, security-version and identity reads inside `[S23]`.

Why the ordering is load-bearing: a shadow read taken before sensing completes returns zero,
and zero is a legal encoding for the fields that gate security — `LC_STATE` zero decodes as
`TEST_DEV`, where secure boot is optional. An early lifecycle read therefore **fails open**.
Until 2026-09-10 the wait lived inside `pll_init()` behind its `bl0_pll_clk` early return, so
on the refclk path no wait ran at all; that is the bug `[S08]` fixes.

### The stimulus that exists but is unused

`tb_top.sv` models `smc_fuse_sense_done_i`, which was previously tied to `1'b0`. The model
asserts the bit `SmcFuseSenseCycles = 64` cycles out of cold reset and holds it. It tracks
`rst_n_int` and deliberately not `wdt_rst_ni`, because a warm reset does not re-sense.

`+sep_smc_fuse_sense_hold` keeps the bit low for the whole run and prints
`[tb] smc_fuse_sense_done held low (+sep_smc_fuse_sense_hold)`. Nothing in
`dv/cocotb/tests/` or `dv/testlists/` references it.

### Why this test is shaped unlike the other negative tests

The closest existing pattern, `rom_fw/sep_spi_not_detected_terminal_test.py`, asserts a
*terminal* outcome: `fw_done` with `fw_pass == 0`, plus two specific status words. None of
that is available here.

- There is no terminal verdict. The ROM spins in a `while` loop, writes no status, and never
  reaches `rom_err_fail()`. `fw_done` never asserts.
- `SepBootScoreboard` cannot be used — it asserts `fw_done and fw_pass`. `expect_fw_pass` must
  be off, and the boot observables sampled directly.
- The pass condition is therefore the **absence** of progress within a bounded window, which is
  only meaningful next to positive evidence that the core is alive and spinning in the right
  place. Absence alone would also "pass" if the core had died on the way to `[S08]`.

One thing makes the test tractable: `sep_base_test.py`'s *"core retired no instructions in %d
cycles; aborting"* guard will **not** fire, because the poll retires instructions continuously.
A tight spin is observably different from a dead core, and that difference is the assertion.

## Requested work

### 1. The test module

`hw/sys/sep/dv/cocotb/tests/rom_fw/sep_fuse_sense_hold_test.py`

**Required** — positive evidence the ROM reached the wait and is still inside it:

- `FUSE_SENSE_WAIT` on the console exactly once.
- `SEP_MSG_FUSE_SENSE_WAIT` (`0x9e`) as the last report. Reuse the ring-invalid filtering from
  `sep_spi_not_detected_terminal_test.py`: the SEP DV environment leaves the ring descriptor's
  `num_entries` at 0, so every `report_status` is followed by an overwrite with
  `SEP_MSG_STATUS_REPORTING_INVALID`, and those have to be filtered before asking what the ROM
  last reported.
- The retire count strictly increasing to the end of the window — the core is live, not parked.
- `len(mon.pcs)` constant across the final samples and `mon.last_pc` confined to a two- or
  three-instruction window: the signature of the poll loop. Locate the window from the
  build's `boot_rom.sym`/`.dis` rather than hardcoding an address, which moves with every build.
- `[tb] smc_fuse_sense_done held low` in the sim log, so the stimulus is shown to have applied
  rather than assumed.

**Forbidden** — proof no fuse was consumed:

- `FUSE_SENSE_DONE`.
- Every `[S09]` marker: `CLK_REFCLK`, `CLK_PLL freq=`, `SYS_CLK_MHZ=`, `PLL_FUSES_BLANK`.
- Every fuse-derived marker: `LC_STATE=`, `LC=`, `FEAT_CTRL_LO=`, `FUSE_VER=`, `PUBK_SEL=`,
  `PUBK_REVOKE=`.
- `MANIFEST_OK`, `PAYLOAD_OK`, `GO!`.
- The FAIL verdict in `cold_scratch[0]`. A hang here is the specified behaviour, not a failure,
  and a FAIL verdict would mean the ROM took some other path.

### 2. The testlist entry

In `dv/testlists/rom_fw.toml`, following the house shape:

```toml
name = "sep_fuse_sense_hold_test"
module = "rom_fw.sep_fuse_sense_hold_test"
target = "rom_boot"
firmware = { name = "boot_rom", mode = "boot_rom" }
seed = 1
tags = ["boot", "rom", "fuse", "cpu", "subsystem"]
run_modes = ["cpu"]
args = [
  "+sep_boot_rom_hex={repo_root}/hw/sys/sep/bootrom/prod/build/boot_rom.vmem",
  "+sep_smc_fuse_sense_hold",
]
```

On the timeout: the test only has to reach `[S08]`, which a passing
`sep_rom_non_secure_boot_test` hit at **~9.0 ms sim time** out of a ~28 ms full boot (1886 s
wall on this box, 2026-09-10). The test should close its own observation window and end
rather than run to the timeout, so set `timeout_sec` as a backstop well under the boot tests'
7200 and let the module decide when it has seen enough.

### 3. Guard the positive direction as well

The hold test proves the ROM waits. It does not prove the ordering holds on the path that
matters, which is what the requirement actually states. Add an assertion — to a normal boot
test or to the shared base — that `FUSE_SENSE_DONE` precedes every fuse-derived marker.

`sep_rom_non_secure_boot_test` already emits the full chain in the right order
(`FUSE_SENSE_WAIT` → `FUSE_SENSE_DONE` → `CLK_REFCLK` → `SYS_CLK_MHZ=` → `BL0_STATE_OK` →
`LC_STATE=` → `LC=TEST_DEV` → `CHIP_ID=` → `CRYPTO_SELFTEST_OK`, verified 2026-09-10), so the
assertion is cheap to add where the chain is already being read.

## Consequences elsewhere

- **The warm-reset family must not set this plusarg.** `[S08]` runs only in `rom_main()`, and a
  warm reset jumps from `vector.S` straight to BL1 without entering it. The TB model tracks
  cold reset only, matching hardware. A warm-reset test that set the plusarg expecting a hang
  would be asserting something the design does not do.
- **The ordering assertion in 3 can go vacuous.** If a future TB — or a real-SMC environment —
  asserts `smc_fuse_sense_done` before SEP's reset releases, the wait completes on its first
  read and the two markers land adjacently with nothing in between. The assertion still holds
  but stops discriminating. Worth a comment at the assertion site saying so.
- **64 cycles is a modelling choice, not a measurement.** No SEP-visible number for real SMC
  fuse-sense latency was available when the model was written. If one appears, the constant
  should move to it, and a long-latency variant becomes a cheap extra case.

## Open questions

- **Should the hold be releasable mid-run?** A `+sep_smc_fuse_sense_hold_cycles=<n>` that holds
  the bit low for a set time and then asserts it would prove the ROM *resumes* — that `[S08]`
  is a wait and not a dead end. That is arguably the stronger test, and it produces a normal
  PASS instead of a hang, so it fits the regression better. It needs the TB model to take a
  release time, which is a small change to the block already added.
- **Given that, is the pure-hang variant worth carrying at all?** The release variant covers
  "the ROM waits" and "the ROM resumes" in one passing run. The hang variant's unique value is
  proving the wait is genuinely unbounded, which is what `[SEP-ROM-CPU-080]` promises — but it
  costs a test that can only ever end by timeout.
