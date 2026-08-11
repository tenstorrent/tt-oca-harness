---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_cold_reset_repeated_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094523__verilator__smc_cold_reset_repeated_test/smc_cold_reset_repeated_test/logs/smc_cold_reset_repeated_test.log
  sha256: 83e49cbf0afd47504c027c37b49b214d57c9cde4ea7e833a68851c38fcd0c02f
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
  tag: '[NO-ALWAYS-PASS-CHECKER]'
  severity: Blocking
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_cold_reset_repeated_test_seq.py:26-40
  observed: >
    The sequence comment states mid-assertion RAW_SAMPLE should see cold active
    with primary outputs low, but neither the sequence nor the scoreboard asserts
    RAW_SAMPLE levels. SmcScoreboard._check_reset returns after coverage-only
    logging for RAW_SAMPLE (smc_scoreboard.py:88-92). Kept log
    sha256 83e49cbf…: COLD_RST_LO @ 4152 ns → mid RAW_SAMPLE @ 4184 ns records
    reset_state=(1, 1, 1, 1) (primaries still released) and the test still PASSes.
    Post-release stretcher RAW_SAMPLEs log (1, 0, 0, 0) at 4488–4792 ns (and
    analogous loops) without any level compare. A DUT that ignores rst_cold_ni
    through all three re-assert loops would still satisfy the only level asserts
    (post-recover SAMPLE all-released).
  closure_condition: >
    After each COLD_RST_LO (and across the stretcher window after COLD_RST_HI),
    assert exact expected primary/cold-stable levels on RAW_SAMPLE or via a
    bounded predicate wait with FAIL-ON mismatch; emit evidence only after those
    checks pass. Mid-assert primary-still-released must fail the test.
  waived_by: null
- id: FIND-002
  tag: '[NO-ALWAYS-PASS-CHECKER]'
  severity: Blocking
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_cold_reset_repeated_test_seq.py:43-48
  observed: >
    Cool pulse (COOL_RST_LO → fixed REASSERT_REF_CYCLES → COOL_RST_HI → fixed
    RECOVER_REF_CYCLES → SAMPLE) has no mid-assert sample and no check that cool
    ever asserted primary. Comment admits the goal is scoreboard reset_op
    coverage range. Final SAMPLE only requires released levels, which also hold
    if rst_cool_ni is ignored. Kept log: COOL_RST_LO @ 15512 ns, COOL_RST_HI @
    15832 ns, SAMPLE #3 all-released @ 21432 ns with no cool-assert evidence
    token or level compare.
  closure_condition: >
    Sample or wait for cool-asserted primary levels with a real FAIL-ON path
    before release/recover, then prove cleared; do not treat reset_op coverage
    alone as cool behavioral proof.
  waived_by: null
- id: FIND-003
  tag: '[NO-BLIND-DELAY-SYNC]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_cold_reset_repeated_test_seq.py:15-48
  observed: >
    All timing on the proof path is fixed ClockCycles: mid-assert 4,
    REASSERT_REF_CYCLES=40, BETWEEN_REF_CYCLES=200, RECOVER_REF_CYCLES=700
    (twice). Post-cold and post-cool recovery synchronize by magic cycle count
    then SAMPLE, not by a predicate wait with fail-on-expiry. Kept log:
    last cold COLD_RST_HI @ 8312 ns → SAMPLE #2 @ 15512 ns (= 700×8 ns +
    between-loop residue geometry); COOL_RST_HI @ 15832 ns → SAMPLE #3 @
    21432 ns (= exactly 700×8 ns).
  closure_condition: >
    Replace recovery (and any mid-window completion sync used as proof) with
    bounded predicate waits that fail on timeout with last-state diagnostics;
    keep fixed delays only when the delay itself is the SPEC quantity under test.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_cold_reset_repeated_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🔴 2 Blocking · 🟠 1 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase. Layer 1 findings
> are the entire scope of this report. `NOT-READY` records the **absence of a closure
> claim, not a defect**. Kept log is a sim PASS (seed 1); Layer 2 was not entered.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `1fa18ecd…`)

| Field | Prior | This audit |
|---|---|---|
| Kept log | `…20260806_081631…` sha256 `1fa18ecd…` | `…20260806_094523…` sha256 `83e49cbf…` |
| Repo rev | `2ecc7b22…` | `c10b6d63…` |
| Auditor `run_id` | `dv_test_audit-smc_cold_reset_repeated-L1-20260806-0e47d7811402` | `cursor/grok/4.5-reaudit-20260806` |
| Findings | FIND-001/002/003 open | **unchanged** — same tags/severities; new log reproduces the same vacuity geometry |
| Waivers carried | none (`waivers: []`) | none (no signed `approved_by` entries to carry; unsigned nulls dropped) |
| Recommendation | ⛔ NOT-READY | ⛔ NOT-READY |

Sequence and scoreboard proof path were not remediated; re-audit confirms the prior Layer 1 holes on the new kept log.

## Your to-do — 3 items (🔴 2 Blocking · 🟠 1 Major)

| # | Sev | Item |
|---|---|---|
| 1 | 🔴 Blocking | FIND-001 `[NO-ALWAYS-PASS-CHECKER]` — mid-assert RAW_SAMPLE never fails on primary levels |
| 2 | 🔴 Blocking | FIND-002 `[NO-ALWAYS-PASS-CHECKER]` — cool pulse has no cool-assert FAIL-ON |
| 3 | 🟠 Major | FIND-003 `[NO-BLIND-DELAY-SYNC]` — fixed 40/200/700-cycle settle instead of predicate wait |

<details>
<summary>1. 🔴 Blocking — FIND-001 `[NO-ALWAYS-PASS-CHECKER]` at cold re-assert RAW_SAMPLE loop</summary>

Sequence comment claims mid-assert primary low; scoreboard RAW_SAMPLE path only logs
`FUNC_COV_VALUE` and returns. Kept log mid RAW_SAMPLE @ 4184 ns is `(1,1,1,1)` and
PASS still holds — cold re-assert behavior is not on any FAIL-ON path.

**Close when:** each cold assert / stretcher window checks exact expected levels (or
bounded wait FAIL-ON), so primary-still-released mid-assert fails the test.

</details>

<details>
<summary>2. 🔴 Blocking — FIND-002 `[NO-ALWAYS-PASS-CHECKER]` at cool pulse trail</summary>

COOL_RST_LO/HI only expand `reset_op` coverage; final SAMPLE requires released levels
that also hold if cool is ignored. No cool-asserted observation.

**Close when:** prove cool-asserted primary (FAIL-ON) then cleared, not coverage-only.

</details>

<details>
<summary>3. 🟠 Major — FIND-003 `[NO-BLIND-DELAY-SYNC]` at fixed recover/reassert delays</summary>

REASSERT/BETWEEN/RECOVER are magic cycle counts; recovery is delay-then-SAMPLE, not
a TIMEOUT-failing predicate wait (log: 700×8 ns geometry to SAMPLE #2/#3).

**Close when:** recovery/completion sync uses bounded predicate waits with last-state
TIMEOUT failure.

</details>

**Then:** owner remediates FIND-001/002/003 in the sequence (and RAW_SAMPLE scoreboard
policy if needed), re-keeps a PASS log, and re-invokes `/dv_test_audit`. Do not invent
a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — pin drive via `SmcResetDriver` on top-level `rst_cold_ni` / `rst_cool_ni`; samples top-level status outputs; no force/deposit on proof path |
| F2 can't-fail checker | 🔴 Blocking — FIND-001, FIND-002 |
| E1 skip-to-pass | ✅ clean — unsupported ops raise; no HDL-path skip-to-pass |
| E2 empty phase | ✅ clean — body drives/samples cold×3 + cool; vacuity is F2 (missing FAIL-ON), not a no-op stub |
| S1 silent fail | ✅ clean — SAMPLE path asserts raise on mismatch; RAW_SAMPLE intentionally skips invariants (captured as F2, not silent log-only mismatch handling of a compared value) |
| O1 checker disabled | ✅ clean — scoreboard reset SAMPLE checks remain enabled; RAW_SAMPLE skip is by design of that op |
| Phase-S obligations — L1 | 🟠 Major — FIND-003 `[NO-BLIND-DELAY-SYNC]`; enrolled in `reset.toml` / `all.toml`; SAMPLE asserts non-vacuous for released state only; no unexplained skip |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Log: `hw/sys/smc/dv/build/runs/20260806_094523__verilator__smc_cold_reset_repeated_test/smc_cold_reset_repeated_test/logs/smc_cold_reset_repeated_test.log`
  sha256 `83e49cbf0afd47504c027c37b49b214d57c9cde4ea7e833a68851c38fcd0c02f`
  (verified via `sha256sum`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `return_code: 0`, cocotb summary:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Test: `hw/sys/smc/dv/cocotb/tests/smc_cold_reset_repeated_test.py` starts
  `smc_cold_reset_repeated_test_seq` on `reset_agent.sequencer` after `smc_base_test` bring-up
- Seq proof path: `smc_cold_reset_repeated_test_seq.py` → `SmcResetAgent` →
  `SmcScoreboard._check_reset` (SAMPLE level asserts only; RAW_SAMPLE coverage-only)
- Mid-assert vacuity cite: COLD_RST_LO @ 4152 ns; RAW_SAMPLE @ 4184 ns
  `reset_state=(1, 1, 1, 1)`; PASS @ L453/L455
- Stretcher cite (unchecked): post COLD_RST_HI RAW_SAMPLEs show `(1, 0, 0, 0)` at
  4488–4792 ns (and analogous loops) — logged, never compared
- Recover cite: SAMPLE #2 @ 15512 ns all-released; SAMPLE #3 @ 21432 ns after cool
- Enrollment: `hw/sys/smc/dv/testlists/reset.toml`, `all.toml`
- Bring-up trailer: efuse hex + ROM `$readmemh` — time-0 image load; not used as golden
  for these pin-level ops (policy §6 standing preload exception; off this proof path)
- No unexplained `ERROR`/`FATAL`/`Traceback`; only cocotb deprecation warnings / fuse-sense INFO

</details>

## Not concluded

- Whether repeated cold/cool pin behavior matches SPEC reset properties (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers from
  the passing log.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
