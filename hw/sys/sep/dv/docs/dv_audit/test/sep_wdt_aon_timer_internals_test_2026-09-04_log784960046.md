<!-- SPDX-License-Identifier: Apache-2.0 -->
# DV audit — `sep_wdt_aon_timer_internals_test`

**Verdict: NO-EVIDENCE.** No MUST-FIX and no GOOD-TO-HAVE in the source; the log this
audit was pointed at records a run that never simulated, and no log of this test records
the commit it was built from.

- Scope: test height, one test · Date: 2026-09-04
- Findings: **0 MUST-FIX · 0 GOOD-TO-HAVE · 2 OBSERVATION**
- Policy: `~/.claude-ai/skills/dv_audit/references/dv_policy.md` (not under git; SHA-256 `37cf7610c45aa272d2b6275e229ebadc38294e03f00ff3199389fbbca4b90210`)
- Nothing here blocks sign-off on the test's own merit. The package cannot sign off on
  the named log, because that log is not evidence of anything.

## Needs a decision

| Test | Verdict | Mechanism, in one line |
|---|---|---|
| `sep_wdt_aon_timer_internals_test` | `NO-EVIDENCE` | The log given (`20260904_032049__verilator__all`, seed 784960046) died before the simulator started — the verilated binary `build/cocotb/verilator/0f9489eff530/sep_uvm_top` was absent — so zero checkers ran. The runner called it `ERROR`, correctly; it is not a fake pass, it is an absent one. A later run does show all nine checkers passing with real values, but no log of this test records a commit or source identity, so freshness (policy 1.7) cannot be settled either way. |

Who to talk to: whoever owns the run flow. Two separate asks — re-run this test against a
present build, and make the run record the commit it was built from.

## Findings

Both are OBSERVATION under policy §3. Neither blocks, neither is counted against the package.

### OBS-1 — logs carry no source identity (policy 1.7 method, §3)
`build/runs/*/sep_wdt_aon_timer_internals_test/*/attempt_0/logs/*.log` and the sibling
`result.json` record a build *fingerprint* (`target_build.fingerprint`, e.g. `bbd37ee828f1`)
and a seed, but no git revision. The freshness judgment is therefore `NO-EVIDENCE` rather
than a finding — missing provenance is not a demonstrated lie. It is also the one gap that
cannot be retrofitted: no later effort recovers a commit id a log never wrote.
*Fix:* have the runner stamp the harness revision into `result.json` and the log header.

### OBS-2 — the `clk_wdt` ratio is a documented shortcut absent from the plan entry
`cocotb/tests/system/sep_wdt_aon_timer_internals_test.py:64` sets `WDT_CLK_RATIO = 8`,
against a silicon ratio the source itself gives as ~1000x, and every count window, poll
budget and CDC-settling tolerance in the test is sized from it. The shortcut is declared in
the module docstring and at the constant, and it is used within that stated scope, which
puts it in §3 rather than 2.9. It is not in the VPLAN entry (`docs/SEP_VPLAN.adoc:3283`),
whose *Run mode* line lists only `no_cpu`, `+skip_fuse_sense` and the seed count.
*Fix:* one clause in the plan entry's run-mode line.

## Why zero blocking findings — the two checkers most likely to be lying

A zero-finding report has to earn it. These two are the ones that would normally fail this
policy, and here is what cleared them.

**CHK-REGWEN-LOCK — a deny leg (policy 2.1).** "The locked register rejects the write" also
passes on a dead bus. Three things make it live in this test, all in the same run:
`_chk_regwen_lock_and_nonvac` first writes and reads back a distinct seeded value while
REGWEN is still 1 (`:376-381`, CHK-NONVAC); the shared driver raises on any non-OKAY
response (`cocotb/seq_lib/sep_axi_reg_driver.py:50,62`), so every one of the surrounding
accesses is a live-bus assertion; and the post-lock attempt value is `bark_prelock ^ 0xFFFF`
(`cocotb/seq_lib/sep_wdt_aon_seq.py:89`), so the unchanged readback cannot be the value the
write would have produced. `write_tolerant` swallows the response code by design, and the
proof does not rest on it — the readback is the proof, and the resp is logged, not checked.
Positive control present in-test; 2.1 does not fire.

**CHK-WKUP-PRESCALE — a bound that could be satisfied by a frozen counter (policy 1.2/1.4).**
The upper bound alone ("the divided run counted less") passes if the counter never moved.
It is guarded three ways: `adv_fast >= 20` against an independent literal (`:222`), so the
undivided run is known to have made progress; `adv_slow >= 1` (`:229`), which a frozen
counter fails; and both bounds derived from the programmed divisor rather than from the
undivided measurement (`:226-228`). The seeded divisor range is 24..63
(`sep_wdt_aon_seq.py:94`), so `window = 4*(presc+1)` is always ≥ 100 ticks and the
`adv_fast >= 20` floor is reachable — no seed makes the nonvacuity check itself vacuous.

## What I did not check

- **Freshness of any log against its sources.** No log records a revision; see OBS-1. Not
  resolvable by timestamps, and not attempted.
- **Whether the checked mechanisms still hold at the silicon `clk_wdt` ratio.** The register
  CDC busy-stall and the counter-rate bounds are exercised at 8x, not ~1000x. Settling this
  needs a run, which this audit does not perform.
- **The `+skip_fuse_sense` bring-up path (policy 1.6).** Judged off the proof path by
  reading the WDT closure — no checker in this test reads state that fuse sense produces —
  not by inspecting the bring-up sequence in full.
- **RTL behaviour of `WKUP_CAUSE` versus its RDL label.** The test comment
  (`sep_wdt_aon_timer_internals_test.py:53-57`) notes that the cause clears on a write of 0
  despite an `onwrite=woclr` label in the vendored RDL. The expected semantics trace to
  upstream OpenTitan and firmware behaviour (cited at `:285`), i.e. outside this design, so
  policy 2.2 does not fire. Whether the RDL label or the RTL is wrong is a register-map
  question for its owner and is not a testcase finding.
- **Other seeds.** One PASS log read (seed 1414860525). The seeded ranges were checked by
  reading `SepWdtCfg`, not by running the sweep.

<details>
<summary>Appendix — inputs, enumeration, evidence</summary>

**Inputs**

| Input | Path |
|---|---|
| Test | `hw/sys/sep/dv/cocotb/tests/system/sep_wdt_aon_timer_internals_test.py` (466 lines) |
| Closure | `cocotb/seq_lib/sep_wdt_aon_seq.py`, `cocotb/seq_lib/sep_axi_reg_driver.py`, `cocotb/seq_lib/sep_axi_access_seq.py`, `cocotb/tests/sep_base_test.py` (`run_phase`, `bring_up_no_cpu`, `random_seed`) |
| Claim | `docs/SEP_VPLAN.adoc:3283` entry, summary row `:437` — ladder rung 1 (VPLAN) |
| Enrollment | `testlists/system.toml:74`; group member in `testlists/all.toml:107,210` |
| Log audited | `build/runs/20260904_032049__verilator__all/.../seed_784960046/attempt_0/logs/sep_wdt_aon_timer_internals_test.log` (20 lines, `status=ERROR`, `exit_code=2`) |
| Corroborating log | `build/runs/20260903_232230__vcs__all/.../seed_1414860525/attempt_0/...log` (757 lines, PASS, 9 checker lines) |

**Enumerated 1 · audited 1 · skipped 0.**

**Claim, quoted (VPLAN rung):** "Wakeup and watchdog tick, threshold expiry, wakeup cause
and its RW1C, the watchdog pet, and the REGWEN lock on the AON timer. Bark and bite are not
claimed here." The test performs exactly those legs and observes none of bark or bite, so
policy 1.5 does not fire.

**The line that decides pass/fail:** there is no single one — nine `assert` statements in
`sep_wdt_aon_timer_internals_test.py`, at `:174`, `:178`, `:222`, `:229`, `:233`, `:237`,
`:266`, `:275`, `:281`, `:292`, `:303`, `:322`, `:330`, `:333`, `:356`, `:362`, `:365`,
`:379`, `:387`, `:393`, `:400`, `:422`, `:444`, `:453`. `sep_base_test.run_phase`
(`tests/sep_base_test.py:1029-1031`) awaits `run_scenario` with no `try`/`except` around
it, so any of those propagates and fails the run.

**Seven-class ledger**

| Class | Outcome |
|---|---|
| 1.1 fabricated verdict | excluded — every logged `PASS` string is emitted after its compare, on the path the compare guards |
| 1.2 a check that cannot fail | excluded — each bound is guarded by an independent nonvacuity assert (`:222`, `:356`, `:379`, `:444`) or by a distinct written value |
| 1.3 a mismatch that does not fail | excluded — all four poll helpers return a boolean the caller asserts (`:266`, `:292`, `:330`, `:444`, `:453`); no bare timeout, no `except` on the proof path; the driver raises on non-OKAY |
| 1.4 nothing observed | excluded — the log carries measured values, not just verdicts (`WKUP_COUNT 0 -> 57`, `advanced 141 vs 3`, `WDOG_COUNT 1197 -> 0`, `fell from 0x2b to 0x0`) |
| 1.5 the wrong thing proven | excluded — all addresses and field masks come from the generated map by symbol (`sep_wdt_aon_seq.py:37-57`, `sep_reg_meta.WDT_TIMER`); no numeric register literal on the proof path |
| 1.6 the TB supplied the answer | excluded — no `force`/`deposit` on the proof path; the log's backdoor mentions are boot-ROM image load and the fuse-sense skip, both in bring-up. `INTR_TEST` is the DUT's own register-driven force and is the claimed mechanism, not a TB shortcut |
| 1.7 evidence not from this test at this commit | **not evaluated** — no log records a revision; see OBS-1. This is what holds the verdict at `NO-EVIDENCE` |

**Yellow triggers evaluated:** 2.1 (deny with no live control) — cleared, see above. 2.2
(golden from RTL) — cleared, expected values are seeded stimulus or upstream-documented
semantics. 2.3 (hand-copied addressing) — cleared, symbols only. 2.5 (seed) — cleared, seed
logged at `:137`. 2.8 (looser than the claim) — cleared, the plan says "reject writes" and
the test checks the readback is unchanged.
**Left unevaluated:** 2.4 as it applies at the silicon clock ratio, and 2.6 (X/Z) in the
AON-domain read windows — both need a run or a waveform.
