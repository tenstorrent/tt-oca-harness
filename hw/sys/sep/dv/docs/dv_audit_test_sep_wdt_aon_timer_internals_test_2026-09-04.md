# DV Audit — `sep_wdt_aon_timer_internals_test`

**Can sign off.** No MUST-FIX. 1 test: 1 clean, 0 blocked, 0 weak, 0 accepted, 0 no-evidence.
Enumerated 1 · audited 1 · skipped 0. Three observations, none blocking.

Policy: `~/.claude-ai/skills/dv_audit/references/dv_policy.md`, sha256 `37cf7610c45aa…` (not under git).
Date: 2026-09-04.

## Needs a decision

Nothing. No test here is blocked, weak, or resting on an approved exception.

## Findings

### F1 — The plan's Test Procedure describes one of the six things the test does — OBSERVATION, routed to the plan owner

**Where:** `docs/SEP_VPLAN.adoc:3295-3299` against
`cocotb/tests/system/sep_wdt_aon_timer_internals_test.py:151-156`
**What disagrees:** the procedure is a single numbered step, "Expire the wakeup threshold and
W1C-clear the interrupt", while the test runs six checker groups — counter advance, prescaler
division, threshold expiry with the wakeup-cause clear, the interrupt-test force, the watchdog
pet, and the register lock with its scope probe. The nine checker contracts below it are
complete and accurate; it is only the procedure that understates the test.
**Why it is not a testcase finding:** nothing about it makes a pass false, and the claims the
checkers are measured against are all present. Policy §4 keeps plan-completeness out of the
testcase grade. It matters because a reader of the plan alone cannot tell what this test runs,
and the next person to edit either side has no procedure to keep in step.
**What would fix it:** five more numbered steps, matching the calls at lines 151-156.

### F2 — The watchdog clock runs 125x faster than silicon, and the CDC tolerances are sized for that — OBSERVATION

**Where:** `cocotb/tests/system/sep_wdt_aon_timer_internals_test.py:64` (`WDT_CLK_RATIO = 8`),
consumed at `:140-141`; the tolerances it sizes are at `:356` and `:362`
**What it does:** the test sets `clk_wdt` to 8x the core period, where silicon is roughly 1000x.
The reason is stated in the source: the ratio stays a valid clock-domain-crossing ratio (still
slower than the core) so the register CDC and the counters resolve inside the AXI timeout. The
pet check's `0x100` tolerance and its `count1 >= 0x400` floor are numbers chosen against this
ratio.
**Why it does not block:** this is a clock period, not a compiled-out datapath, so policy 1.7
does not reach it, and it is declared in the test docstring, the testlist comment and the plan.
The functional contracts under test — a counter that advances, a threshold that expires, a
prescaler that divides, a write that lands or is blocked — do not depend on the ratio.
**What to be aware of:** no leg of this test observes the aon_timer at the silicon clock ratio,
so a CDC defect that only appears at a wide ratio would not be caught here. That is a plan
question, not a defect in this test.

### F3 — `+skip_fuse_sense` leaves the shadow-register array at all-zero for the whole run — OBSERVATION

**Where:** run log lines 185-187; the plusarg comes from `testlists/system.toml:84` and is
declared in the plan's Run mode line
**What the log says:** "Skipping fuse sense", then "+skip_fuse_sense provided, but the required
shadow register preload plusarg was NOT found", then the shadow array is initialized to
`32'h00000000`.
**Why it does not block:** nothing in this test's proof path reads fuse- or lifecycle-derived
state — every checker works on the aon_timer CSR block over the CPU-LSU master, and that path
is demonstrably alive, because every access in the run returned OKAY and the register values
moved as the checkers required. So the skip does not supply any state a checked mechanism was
meant to produce, which is what policy 1.6 is about.
**Worth recording because:** the message reads like a missing input rather than an intended
configuration, and a reader of this log has to go to the testlist to find out which it is.

## What I did not check

- Whether the all-zero shadow-register array can gate the WDT CSR aperture in some
  configuration. Judged instead from the run's own behavior: the accesses completed and the
  registers responded, so the path was not gated in *this* run. The general question was not
  chased.
- Whether the aon_timer register offsets in `seq_lib/sep_wdt_aon_seq.py:38-50` match the vendor
  RDL. They are all imported by symbol through `WDT_TIMER.addr()` / `field_mask()`, not written
  as literals, so the policy 1.5 sub-case of a literal resolving to the wrong register cannot
  apply and I did not verify the generated map itself.
- Whether `WKUP_CAUSE` really clears on a write of zero rather than write-one-to-clear. The test
  header records this as an RTL finding contradicting the RDL's `onwrite=woclr` label. The test
  is consistent with its own claim either way, and settling which is right is design review, not
  this audit.
- Two leads from the log scan, both resolved as artifacts of the scanner rather than the run: the
  "claims PASS but an assertion failure is logged" hit is line 9, cocotb reporting that pytest is
  not installed for better `AssertionError` messages; the "no simulation time" hit is wrong, the
  log carries simulation timestamps throughout and ends at 151527 ns.
- No waveform was opened and nothing was rerun.

Budget spent: 4 source files read (the test whole, three helpers narrowly), 1 plan entry, 1 log
via the summarizer plus four targeted greps, 6 shell searches.

## Why zero MUST-FIX is not a shrug

The two checkers most likely to be vacuous here, and what cleared each:

**CHK-WKUP-COUNT's "stays 0" leg** (`:178`) is a claim that nothing happened, which passes on a
status bit stuck at zero, on a dead bus, and on a counter that never ran. Three separate things
rule that out. The same window asserts the counter advanced (`:174`, and the log shows 0 → 57).
The bus is proven live by every access raising `AssertionError` on a non-OKAY response
(`seq_lib/sep_axi_reg_driver.py:50-51`, `:61-62`). And the same test later drives that exact bit
to 1 under a low threshold and observes it (`:266`, log line 469) — a positive control for the
bit itself, in the same run, which is what policy 2.1 asks for.

**CHK-REGWEN-SCOPE's `WDOG_COUNT` write** (`:438-457`) is the subtlest check in the file, and it
is built the hard way on purpose. Proving a write landed by watching a free-running counter reach
a higher value would pass with the write blocked, since the counter climbs there unaided. The
test instead requires the counter to *fall*: it polls until the value passes a fixed floor of 40
ticks that no seeded value can move (`:69`), then writes zero and requires a readback strictly
below the value held just before the write. A blocked write leaves the counter at or above that
value, still climbing, and fails. The log shows the intended shape — 0x2b before, 0x00 after.

## Appendix A — inputs

| Input | Status |
|---|---|
| Test source | `cocotb/tests/system/sep_wdt_aon_timer_internals_test.py` (466 lines, read whole) |
| Proof-path helpers | `seq_lib/sep_wdt_aon_seq.py` (132 lines, whole), `seq_lib/sep_axi_reg_driver.py:41-63`, `tests/sep_base_test.py` (`bring_up_no_cpu`) |
| Verification plan | `docs/SEP_VPLAN.adoc:3283-3320` — nine checker contracts; claim ladder rung 1 |
| Testlists | `testlists/system.toml:74`; enrolled in `testlists/all.toml` at lines 98 and 201, and this run selected it |
| Simulation log | `build/runs/20260904_035853__verilator__all/sep_wdt_aon_timer_internals_test/seed_388281713/attempt_0/` — 705 lines, `TESTS=1 PASS=1 FAIL=0`, `results.xml` carries one passing testcase, `result.json` reports `status=PASS` from structured evidence |
| Approval records | none exist anywhere in `hw/sys/sep/dv/` — so any shortcut needing one would have been filed red |

**Freshness (policy 1.7):** the log carries no build identity or revision of its own, so by the
policy's stated method the freshness judgment is NO-EVIDENCE rather than a finding. What is
positive: `result.json` names build fingerprint `0f9489eff530`, the run started 2026-09-04
04:06 UTC, and the newest commit touching any proof-path source is older than that. Enrollment
is not in question — the test is in a scheduled group and this run executed it.

## Appendix B — the clean verdict, itemized

**Deciding lines:** nine, one per checker. The last to run, and the one the whole file builds
toward, is `cocotb/tests/system/sep_wdt_aon_timer_internals_test.py:453` — the assertion that
`WDOG_COUNT` fell below the value it held before the write.

**Claim (VPLAN, rung 1):** "Wakeup and watchdog tick, threshold expiry, wakeup cause and its
RW1C, the watchdog pet, and the REGWEN lock on the AON timer. Bark and bite are not claimed
here." The plan says explicitly that no checker in the entry observes bark or bite, and none does
— the test parks both thresholds high (`:346-347`) precisely so they cannot fire.

| Policy class | Result |
|---|---|
| 1.1 fabricated verdict | Excluded. Every PASS line in the log is emitted after its own assertion, never before it, and no expected value is assigned from the value it is compared against. |
| 1.2 a check that cannot fail | Excluded. Each threshold check carries a non-vacuity leg with real numbers in the log: the prescaler check requires the undivided run to advance at least 20 ticks before its divided bound means anything (`:222`; log 121 vs 3, bounds 1..6); the lock check requires a pre-lock write to land first (`:379`; log `0x91dd`); the pet check requires the pre-pet count above `0x400` (`:356`; log 1197). The seeded prescaler is drawn from 24..64 (`sep_wdt_aon_seq.py:94`), which is what keeps the divided and undivided rates distinguishable in one window — a small draw would make that comparison meaningless, and the range rules it out. |
| 1.3 a mismatch that does not fail | Excluded. Every poll helper returns a boolean the caller asserts on (`:263-266`, `:289-294`, `:327-330`, `:438-448`, `:450-457`); no expiry is swallowed. Both AXI accessors raise on a non-OKAY response. There is no `try`/`except` on the proof path. |
| 1.4 nothing was observed | Excluded. Nine PASS records in the log, each carrying the values it compared. |
| 1.5 the wrong thing proven | Excluded on the addressing sub-case: every register and field comes from the generated map by symbol (`sep_wdt_aon_seq.py:38-57`), so no literal can resolve to the wrong register. On the substantive side, the six checker groups map onto the plan's nine contracts with none left over on either side, and the plan's exclusion of bark and bite is honored. |
| 1.6 the testbench supplied the answer | Excluded. No force, deposit, or hierarchical write anywhere on the proof path — every value the checkers read comes back over the AXI frontdoor. The two shortcuts in the run are the boot-ROM image load at time zero, which policy 1.6 names as acceptable, and `+skip_fuse_sense`, covered in F3. `INTR_TEST` is a DUT register the plan claims a contract for, not a testbench backdoor. |
| 1.7 evidence not from this test at this commit | Partly excluded. Enrollment is confirmed and the run executed this test. Log-to-source identity is NO-EVIDENCE by the policy's method — the log names no revision. See Appendix A. |
