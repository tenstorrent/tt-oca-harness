---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_reset_ctrl_test
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
  run_id: dv_test_audit-smc_reset_ctrl-L1-20260806-a01
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

# Grade Report — smc_reset_ctrl_test (NO-PLAN-ENTRY Layer 1)

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
| F1 fabricated verdict / backdoor write | ✅ clean — top-level reset port samples only; no Force/deposit |
| F2 can't-fail checker | ✅ clean — `sb.expect_eq` + mid-hold `AssertionError` on any domain dropping from 1 |
| E1 skip-to-pass | ✅ clean — no missing-handle skip |
| E2 empty phase | ✅ clean — post-bring-up domain release + HOLD_CYCLES stability window with compares |
| S1 silent fail | ✅ clean — mismatch raises via scoreboard / hold loop |
| O1 checker disabled | ✅ clean |
| Phase-S obligations — L1 | ✅ clean — X/Z-aware `_sample1`; scoreboard refuses zero checks; enrolled in `smc.toml` / `all.toml`; bring-up uses bounded `wait_signal_high` |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Code + proof-path notes (no kept log)</summary>

- Implementation: `hw/sys/smu/dv/cocotb/tests/smc_reset_ctrl_test.py`
- Helpers: `tests/smu_base_test.py` (bring-up), `env/smu_scoreboard.py` (`expect_eq`),
  `seq_lib/smu_axi_helpers.py` (`wait_signal_high` on bring-up path)
- Stimulus: SMU cold/primary bring-up only (observe released resets)
- Observations: `rst_cold_stable_ref_clk_no`, `rst_primary_ref_clk_no`,
  `rst_primary_smc_clk_no`, `rst_primary_periph_clk_no` over HOLD_CYCLES=100
- Evidence map: `RST_PRIMARY_SMC_1`, `RST_COLD_STABLE_1` (`smu_evidence_map.py`)
- Enrollment: `hw/sys/smu/dv/testlists/smc.toml`, `all.toml`
- Absent from `SMU_ALL_TESTCASE_PLAN.md` (NO-PLAN-ENTRY)
- No kept log supplied — Layer 2 / authoritative PASS not evaluated

</details>

## Not concluded

- Whether post-settle high samples prove the SPEC reset-control properties a future card would
  require (O2 / transition ownership) — Skill 3.
- Completeness against SMU_ALL feature_list — this leaf is not in the plan denominator.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers from code or logs.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
