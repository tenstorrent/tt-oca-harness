---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_powergood_glitch_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094523__verilator__smc_powergood_glitch_test/smc_powergood_glitch_test/logs/smc_powergood_glitch_test.log
  sha256: 435dd165657e5e4f3c7283c44b38e7280980bc348ad5ada299a246cb626c2d51
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
    Mid-glitch / recovery-window RAW_SAMPLE items only update FUNC_COV bins and return
    without asserting that powergood_stable or primary resets actually deasserted. The only
    failing compares are SAMPLE post-stable all-1s (baseline + recovered). A DUT that ignores
    powergood_i (stays released through the glitch) still yields two SAMPLE items with
    powergood_stable==1 and all primary resets released, so the scoreboard and cocotb PASS
    without proving the stretcher / glitch path ran. Kept log shows mid-window
    reset_state=(0,0,0,0) and transition bins, but those values are never FAIL-ON compared.
  closure_condition: >
    On at least one RAW_SAMPLE (or equivalent SAMPLE with a glitch-phase expect) after
    POWERGOOD_LO and before recovery completes, assert the glitch effect
    (e.g. powergood_stable==0 and/or primary resets asserted) so a no-effect DUT fails;
    keep the post-recovery SAMPLE all-1s compare.
  waived_by: null
- id: FIND-002
  tag: '[NO-BLIND-DELAY-SYNC]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_powergood_glitch_test_seq.py:60-64
  observed: >
    After POWERGOOD_HI, recovery completion is `ClockCycles(dut.clk_ref_i, tail)` with
    RECOVER_WAIT_REF_CYCLES=500 (already_waited=120 → tail=380), then a SAMPLE that expects
    stable released state. There is no bounded event/handshake wait on powergood_stable_o /
    primary-reset release that fails on timeout with last-state diagnostics; the fixed delay
    stands in for recovery completion.
  closure_condition: >
    Replace the fixed recover-tail ClockCycles with a bounded wait on the recovery signals
    (e.g. wait until powergood_stable_o and primary resets are released, raising on expiry
    with last-state diagnostics), then SAMPLE / scoreboard-compare.
  waived_by: null
- id: FIND-003
  tag: '[NO-DUMMY-DEAD-CODE]'
  severity: Minor
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_powergood_glitch_test_seq.py:27-28,39,64
  observed: >
    Sequence stores `self.baseline_sample` and `self.recovered_sample` after the two SAMPLE
    dispatches, but nothing reads those attributes or compares baseline vs recovered. The
    live fail path is only scoreboard `_check_reset` post-stable all-1s asserts. The stored
    items therefore look like an unfinished cross-sample / glitch-delta compare that never
    runs.
  closure_condition: >
    Either assert a real baseline-vs-recovered (or mid-window) compare on the stored items,
    or drop the unused attributes and keep only the scoreboard path.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_powergood_glitch_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🔴 1 Blocking · 🟠 1 Major · 🟡 1 Minor | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase. Layer 1 findings are
> the entire scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect** in the test by itself.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `f066a221…`)

| Item | Prior (log `f066a221…`, PASS) | This audit (log `435dd165…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🔴 1 Blocking · 🟠 1 Major | 🔴 1 Blocking · 🟠 1 Major · 🟡 1 Minor |
| FIND-001 `[CHECKER-NONVACUITY]` | open — RAW_SAMPLE coverage-only; no glitch FAIL-ON | still open — same scoreboard path; mid-window `(0,0,0,0)` logged but not asserted |
| FIND-002 `[NO-BLIND-DELAY-SYNC]` | open — fixed 500-cycle recover wait | still open — recover-tail `ClockCycles` before proof SAMPLE unchanged |
| FIND-003 `[NO-DUMMY-DEAD-CODE]` | not filed | **new** — unused `baseline_sample` / `recovered_sample` stores |
| Kept log | `f066a2218293f7f74b9043737aaf50ceee2e70009e5e9f608e1d87c91929de6c` | `435dd165657e5e4f3c7283c44b38e7280980bc348ad5ada299a246cb626c2d51` |
| Waivers carried | none signed (`waivers: []`) | none (nothing to drop; no signed entries) |

## Your to-do — 3 items (🔴 1 Blocking · 🟠 1 Major · 🟡 1 Minor)

| # | Sev | Item |
|---|---|---|
| 1 | 🔴 Blocking | FIND-001 `[CHECKER-NONVACUITY]` — glitch mid-state never FAIL-ON |
| 2 | 🟠 Major | FIND-002 `[NO-BLIND-DELAY-SYNC]` — fixed 500-cycle recover wait |
| 3 | 🟡 Minor | FIND-003 `[NO-DUMMY-DEAD-CODE]` — unused baseline/recovered stores |

<details>
<summary>1. 🔴 Blocking FIND-001 — assert glitch effect before recovery SAMPLE</summary>

After `POWERGOOD_LO`, require at least one checked sample that fails unless resets /
`powergood_stable` show the glitch (scoreboard today returns on `RAW_SAMPLE` with coverage
only — `smc_scoreboard.py:88-92`). Keep the post-recovery `SAMPLE` all-1s asserts.

</details>

<details>
<summary>2. 🟠 Major FIND-002 — handshake recovery instead of fixed ClockCycles</summary>

Replace `RECOVER_WAIT_REF_CYCLES` tail wait (`smc_powergood_glitch_test_seq.py:60-64`) with a
bounded wait on recovery outputs that raises on timeout with last-state diagnostics, then
`SAMPLE`.

</details>

<details>
<summary>3. 🟡 Minor FIND-003 — use or drop baseline_sample / recovered_sample</summary>

Assert a real compare on `self.baseline_sample` / `self.recovered_sample`, or remove the
unused stores so they do not read as an unfinished cross-sample check
(`smc_powergood_glitch_test_seq.py:27-28,39,64`).

</details>

**Then:** owner remediates FIND-001/002/003 and re-invokes `/dv_test_audit` on this leaf; Layer 2
needs an approved card (not invented here).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — top-level `powergood_i` drive; DUT pin samples; no Force/deposit on proof path |
| F2 can't-fail checker | ✅ clean — post-stable `SAMPLE` asserts (`powergood_stable==1`, primary resets==1) can fail on stuck recovery |
| E1 skip-to-pass | ✅ clean |
| E2 empty phase | ✅ clean — POWERGOOD_LO/HI + SAMPLE/RAW_SAMPLE path present |
| S1 silent fail | ✅ clean — scoreboard uses `assert`; UVM `check_phase` requires nonzero SAMPLE activity |
| O1 checker disabled | ✅ clean |
| Phase-S obligations — L1 | 🔴 Blocking — FIND-001 · 🟠 Major — FIND-002 · 🟡 Minor — FIND-003; X-aware `is_resolvable`; enrolled in `reset.toml` / `all.toml` |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_powergood_glitch_test.py`
  sha256 `a3aff54d85bbd7653efd3fbe1588db83e777ddd14fc0729b3764161065d25965`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_powergood_glitch_test_seq.py`
  sha256 `07e7197704d7d944b4720c10c2468b2d8318dddf2fcfa01c0040e87e62fbb3c8`
- Agent / scoreboard (proof path): `smc_reset_agent.py` → `SmcScoreboard._check_reset`
- Log: `hw/sys/smc/dv/build/runs/20260806_094523__verilator__smc_powergood_glitch_test/smc_powergood_glitch_test/logs/smc_powergood_glitch_test.log`
  sha256 `435dd165657e5e4f3c7283c44b38e7280980bc348ad5ada299a246cb626c2d51`
  (verified via `manifest.py hash-file`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- Cocotb summary: `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Stimulus: reset-agent `POWERGOOD_LO` / `POWERGOOD_HI` on `powergood_i` (pin frontdoor); mid-window `RAW_SAMPLE` cadence + recover-tail `ClockCycles`
- Observation: top-level `powergood_stable_o`, `rst_*_no` via `SmcResetDriver._sample` (X → `resolvable=False`)
- Checks: scoreboard `_check_reset` asserts only on `SAMPLE` (log sample #1 @4152ns, #2 @8216ns); `RAW_SAMPLE` coverage-only through glitch/recover window (e.g. `(0,0,0,0)` @4168ns, `(1,0,0,0)` @4576ns)
- Fail path (static): non-resolvable pins or post-stable all-1s mismatch → AssertionError; no mid-window FAIL-ON
- Enrollment: `hw/sys/smc/dv/testlists/reset.toml`, `all.toml`
- Bring-up trailer: efuse/ROM `$readmemh` lines after cocotb PASS; not used by pin-sample proof path
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`)

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>435dd165…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| bring-up | 266–267 | powergood + cold release | `smc_base_test` |
| SAMPLE #1 | 280–283 | all-1s, scoreboard #1 | seq baseline SAMPLE / `_check_reset` |
| POWERGOOD_LO | 284–285 | `powergood_i=0` | reset agent |
| RAW_SAMPLE mid-glitch | 317–322 | `reset_state=(0,0,0,0)` coverage only | seq + scoreboard return |
| POWERGOOD_HI | 323–324 | `powergood_i=1` | reset agent |
| RAW_SAMPLE recover | 325–357 | transition bins incl. `(1,0,0,0)` | coverage only |
| SAMPLE #2 | 379–382 | all-1s after recover-tail wait | seq recovered SAMPLE / `_check_reset` |
| cocotb result | 385–391 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | — |

</details>

## Not concluded

- Whether this leaf proves the SPEC powergood-stretcher properties a future card would require
  (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
