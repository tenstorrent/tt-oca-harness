---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_reset_recovery_matrix_test
ip: SMC_ACTIVE_REGRESSION
anchor: null
mode: NO-CHECKBOX
no_contract_reason: STANDALONE-REQUEST
entry_status: NOT-EVALUATED
repository_revision: c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7
spec: []
card_sha256: null
card_revision: null
card_path: null
testcase_plan:
  path: null
  plan_revision: null
  testcase_revision: null
  testcase_record_sha256: null
  parent_approved: null
evidence_class: null
closure_tier: null
quality_policy:
  path: /home/minshaoho/.claude/skills/dv_common/DV_QUALITY_POLICY.md
  revision: 51a3357d9c31a018d69451b055bc956c089af26e1051368e25ce396c84ac2a75
build_config: default
simulator: verilator
simulator_version: 5.050 2026-07-01
compile_target: default
model_fingerprint: 2c815fa08277
compile_inputs_sha256: null
seeds:
- 1
logs:
- path: hw/sys/smc/dv/build/runs/20260806_094523__verilator__smc_reset_recovery_matrix_test/smc_reset_recovery_matrix_test/logs/smc_reset_recovery_matrix_test.log
  sha256: 36d8f8db894d422902549c484fc135064c5def5880ae9968b37f31785100090f
test_author:
  human_id: unknown
  run_id: unknown
  model:
    provider: unknown
    family: unknown
    version: unknown
auditor:
  human_id: minshaoho
  run_id: cursor/grok/4.5-reaudit-20260806
  model:
    provider: cursor
    family: grok
    version: '4.5'
exceptions: []
checkers: []
findings:
- id: FIND-001
  tag: '[CHECKER-NONVACUITY]'
  severity: Blocking
  artifact_ref: hw/sys/smc/dv/cocotb/env/smc_scoreboard.py:86-103
  observed: >
    Matrix mid-window RAW_SAMPLE items only update FUNC_COV bins and return without
    asserting that powergood / cold / cool stimulus actually cleared powergood_stable or
    asserted primary resets. The only FAIL-ON compares are SAMPLE post-stable all-1s
    (baseline + three recoveries) plus sequence length/resolvable gates
    (`smc_reset_recovery_matrix_test_seq.py:80-84`). A DUT that ignores powergood_i /
    rst_cold_ni / rst_cool_ni (stays released through the matrix) still yields four SAMPLE
    items with all-1s after the fixed recover delay, so cocotb PASS does not prove any
    transition leg ran. Kept log (sha256 36d8f8db…): mid-window reset_state includes
    (0,0,0,0) after POWERGOOD_LO and (1,0,0,0) after cold release, but those values are
    never FAIL-ON compared; cool-window RAW samples stay (1,1,1,1) @ 17680/18384 ns while
    the test still passes.
  closure_condition: >
    On each matrix leg (powergood glitch, cold reassert, cool pulse), assert at least one
    mid-window sample that fails unless the expected effect is observed (e.g. powergood_stable
    cleared and/or primary resets asserted), then keep the post-recovery SAMPLE all-1s
    compare; do not treat FUNC_COV alone as proof.
  waived_by: null
- id: FIND-002
  tag: '[NO-BLIND-DELAY-SYNC]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_reset_recovery_matrix_test_seq.py:47-49
  observed: >
    `_recover_and_sample` always waits a fixed `RECOVER_REF_CYCLES=700` on `clk_ref_i` then
    issues SAMPLE. Kept log: last powergood-window RAW @ 5776 ns → SAMPLE #2 @ 11376 ns
    (=700×8 ns); post-cold RAW @ 12016 ns → SAMPLE #3 @ 17616 ns; post-cool RAW @ 18384 ns
    → SAMPLE #4 @ 23984 ns — each recover gap is exactly 700 ref cycles. There is no bounded
    predicate wait on powergood_stable_o / primary-reset release that fails on expiry with
    last-state diagnostics; the magic cycle count stands in for recovery completion on every
    matrix leg.
  closure_condition: >
    Replace `_recover_and_sample` with a bounded wait on the recovery outputs (released /
    stable levels) that raises on timeout with last-state diagnostics, then SAMPLE /
    scoreboard-compare.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_reset_recovery_matrix_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🔴 1 Blocking · 🟠 1 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase. Layer 1 findings
> are the entire scope of this report. `NOT-READY` records the **absence of a closure
> claim, not a defect**. Kept log is a sim PASS (seed 1); Layer 2 was not entered.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `6ce4ea0e…`)

| Item | Prior (log `6ce4ea0e…`) | This audit (log `36d8f8db…`) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🔴 1 Blocking FIND-001 · 🟠 1 Major FIND-002 | same two findings, open |
| FIND-001 | open — RAW_SAMPLE cov-only / no mid-leg FAIL-ON | still open — same scoreboard path; cool RAW still `(1,1,1,1)` |
| FIND-002 | open — fixed 700-cycle `_recover_and_sample` | still open — HI/RAW→SAMPLE gaps still exactly 700×8 ns |
| Kept log | `6ce4ea0ec519db9e1cae847f11ec99c66bcb0fa87176fc815c189cd8fef5208c` PASS seed=1 | `36d8f8db894d422902549c484fc135064c5def5880ae9968b37f31785100090f` PASS seed=1 |
| Waivers carried | none signed (`waivers: []`; nothing to drop) | none |

## Your to-do — 2 items (🔴 1 Blocking · 🟠 1 Major)

| # | Sev | Item |
|---|---|---|
| 1 | 🔴 Blocking | FIND-001 `[CHECKER-NONVACUITY]` — matrix mid-state never FAIL-ON |
| 2 | 🟠 Major | FIND-002 `[NO-BLIND-DELAY-SYNC]` — `_recover_and_sample` fixed 700-cycle settle |

<details>
<summary>1. 🔴 Blocking — FIND-001 `[CHECKER-NONVACUITY]` at scoreboard RAW_SAMPLE path</summary>

`_check_reset` returns on `RAW_SAMPLE` after coverage only (`smc_scoreboard.py:88-92`).
Sequence end-gates only require four SAMPLE items, non-empty RAW list, and resolvable.
Kept-log mid-window `reset_state` tuples are never compared for FAIL-ON; a no-effect DUT
still passes the post-recover all-1s SAMPLE path. Cool-window RAW stays `(1,1,1,1)`.

**Close when:** each matrix leg has at least one checked mid-window sample that fails unless
the glitch/cold/cool effect is observed, then keep post-recovery SAMPLE all-1s.

</details>

<details>
<summary>2. 🟠 Major — FIND-002 `[NO-BLIND-DELAY-SYNC]` at `_recover_and_sample`</summary>

All three recovery SAMPLE legs synchronize with a fixed 700-cycle `ClockCycles` then SAMPLE
(log gaps match 700×8 ns after intervening RAW offsets). No bounded handshake wait with
fail-on-expiry.

**Close when:** recovery proof uses predicate waits with fail-on-expiry and last-state
diagnostics, not a blind cycle count.

</details>

**Then:** owner remediates FIND-001/002 in the scoreboard and/or sequence, re-keeps a PASS
log, and re-invokes `/dv_test_audit`. Do not invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — pin drive via `SmcResetDriver` on top-level `powergood_i` / `rst_cold_ni` / `rst_cool_ni`; samples top-level status outputs; no force/deposit on proof path |
| F2 can't-fail checker | ✅ clean — post-stable `SAMPLE` asserts (`powergood_stable==1`, primary resets==1) can fail on stuck recovery |
| E1 skip-to-pass | ✅ clean — missing ops raise; no HDL-path skip-to-pass |
| E2 empty phase | ✅ clean — powergood / cold / cool drive + SAMPLE/RAW_SAMPLE path present |
| S1 silent fail | ✅ clean — scoreboard uses `assert`; sequence length/resolvable gates raise; `check_phase` requires nonzero SAMPLE activity |
| O1 checker disabled | ✅ clean — scoreboard reset checks remain enabled; RAW_SAMPLE intentionally skips post-stable invariants (vacuity filed under Phase-S, not O1) |
| Phase-S obligations — L1 | 🔴 Blocking — FIND-001 · 🟠 Major — FIND-002; X-aware `is_resolvable`; enrolled in `reset.toml` / `all.toml` / `vplan_triplets.toml` |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Log: `hw/sys/smc/dv/build/runs/20260806_094523__verilator__smc_reset_recovery_matrix_test/smc_reset_recovery_matrix_test/logs/smc_reset_recovery_matrix_test.log`
  sha256 `36d8f8db894d422902549c484fc135064c5def5880ae9968b37f31785100090f`
  (verified via `sha256sum`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `exit_code: 0`, cocotb summary: `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Test: `hw/sys/smc/dv/cocotb/tests/smc_reset_recovery_matrix_test.py` starts
  `smc_reset_recovery_matrix_test_seq` on `reset_agent.sequencer` after `smc_base_test` bring-up
- Seq proof path: `smc_reset_recovery_matrix_test_seq.py` → `SmcResetAgent` /
  `SmcScoreboard._check_reset`
- Stimulus cites: POWERGOOD_LO @ 4152 ns; POWERGOOD_HI @ 4216 ns; COLD_RST_LO @ 11376 ns;
  COLD_RST_HI @ 11696 ns; COOL_RST_LO @ 17616 ns; COOL_RST_HI @ 18256 ns
- SAMPLE cites: #1 @ 4152 ns; #2 @ 11376 ns; #3 @ 17616 ns; #4 @ 23984 ns (all all-1s)
- Mid-window cov cites (never FAIL-ON): POWERGOOD RAW `(0,0,0,0)` @ 4168/4216 ns;
  cold post-release RAW `(1,0,0,0)` @ 11760/12016 ns; cool RAW stays `(1,1,1,1)` @
  17680/18384 ns
- Blind recover cite: powergood last RAW 5776→SAMPLE 11376; cold 12016→17616; cool
  18384→23984 (=700 ref cycles × 8 ns each)
- Enrollment: `hw/sys/smc/dv/testlists/reset.toml`, `all.toml`, `vplan_triplets.toml`
- Bring-up trailer: efuse hex + ROM `$readmemh` — time-0 image load; not used as golden
  for these pin-level checks (policy §6 standing preload exception; off this proof path)
- No unexplained `ERROR`/`FATAL`/`Traceback`; only cocotb deprecation warnings
- Provenance: legacy (`test_author.run_id: unknown`); auditor
  `run_id: cursor/grok/4.5-reaudit-20260806`

</details>

## Not concluded

- Whether the matrix checks the SPEC reset/powergood recovery properties a future card would
  require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers from
  the passing log.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
