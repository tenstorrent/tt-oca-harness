---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_security_demote_pm_test
ip: SMU_ENROLLED_RESIDUAL
anchor: null
mode: NO-CHECKBOX
no_contract_reason: NO-PLAN-ENTRY
entry_status: NOT-EVALUATED
repository_revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
spec: []
card_sha256: null
card_revision: null
card_path: null
testcase_plan:
  path: hw/sys/smu/dv/tb/SMU_ALL_TESTCASE_PLAN.md
  plan_revision: null
  testcase_revision: null
  testcase_record_sha256: null
  parent_approved: null
evidence_class: null
closure_tier: null
quality_policy:
  path: /home/minshaoho/.claude/skills/dv_common/DV_QUALITY_POLICY.md
  revision: 51a3357d9c31a018d69451b055bc956c089af26e1051368e25ce396c84ac2a75
build_config: null
simulator: null
simulator_version: null
compile_target: null
model_fingerprint: null
compile_inputs_sha256: null
seeds: []
logs: []
test_author:
  human_id: unknown
  run_id: unknown
  model:
    provider: unknown
    family: unknown
    version: unknown
auditor:
  human_id: minshaoho
  run_id: dv_test_audit-smc_security_demote_pm-L1-20260806-a02
  model:
    provider: cursor
    family: grok
    version: '4.5'
exceptions: []
checkers: []
findings: []
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_security_demote_pm_test (NO-PLAN-ENTRY Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason NO-PLAN-ENTRY)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | none | ⛔ NOT-READY |

> SMU_ALL has an approved plan/cards surface, but this leaf has **no plan record and no
> approved checkbox card**. Layer 1 findings are the entire scope. `NOT-READY` records the
> **absence of a closure claim** (and the plan gap), not a Layer-1 structural defect.

## Your to-do — 0 items (none)

| # | Sev | Item |
|---|---|---|
| — | — | none open |

**Then:** route to `/dv_vplan_gen` so SMU_ALL either allocates this leaf (`augment`) or the owner
retires it; re-invoke `/dv_test_audit` after a card exists if Layer 2 grading is required.

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — top-level port observe; docstring records Force/sigint inject removed |
| F2 can't-fail checker | ✅ clean — demote!=0 / lc_state!=0xf0 raise in hold loop and via `sb.expect_eq` |
| E1 skip-to-pass | ✅ clean — no missing-handle skip; deferred sigint claim is omitted, not skipped-to-pass |
| E2 empty phase | ✅ clean — HOLD_CYCLES observe window with exact compares |
| S1 silent fail | ✅ clean — mismatch raises |
| O1 checker disabled | ✅ clean |
| Phase-S obligations — L1 | ✅ clean — X/Z-aware `_sample`; scoreboard non-vacuity; enrolled in `smc.toml` / `all.toml` |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Code + proof-path notes (no kept log)</summary>

- Implementation: `hw/sys/smu/dv/cocotb/tests/smc_security_demote_pm_test.py`
- Helpers: `tests/smu_base_test.py`, `env/smu_scoreboard.py`
- Stimulus: none beyond bring-up (SEP=0 hardwire observe)
- Observations: `lcc_demote_state_1/2_o`, `lc_state_o` over HOLD_CYCLES=16; expect demote==0,
  `lc_state==0xf0`
- Evidence map: `DEMOTE_TIEOFF_OBS` (`smu_evidence_map.py`)
- Enrollment: `hw/sys/smu/dv/testlists/smc.toml`, `all.toml`
- Absent from `SMU_ALL_TESTCASE_PLAN.md` (NO-PLAN-ENTRY)
- No kept log supplied — Layer 2 / authoritative PASS not evaluated
- Note (not a finding): demote non-zero / sigint inject contrast is explicitly deferred; this
  audit does not invent a deny-path contract for that deferred claim

</details>

## Not concluded

- Whether SEP=0 hardwire observe proves the SPEC demote/LC properties a future card would
  require (O2) — Skill 3.
- Completeness against SMU_ALL feature_list — this leaf is not in the plan denominator.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers from code or logs.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
