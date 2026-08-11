---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smu_boot_stall_vs_ic_reset_priority_test
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
  path: hw/sys/smu/dv/tb/SMU_ALL_QUALITY_POLICY.md
  revision: 936b77700909a93bb122f9fb124a3ffb6f5dac5f508c623c5950285a5cefb79a
build_config: default
simulator: verilator
simulator_version: 5.050 2026-07-01
compile_target: default
model_fingerprint: 48f5d6b1d3f2
compile_inputs_sha256: null
seeds:
- 1
logs:
- path: hw/sys/smu/dv/build/kept_logs/smu_boot_stall_vs_ic_reset_priority_test.seed1.log
  sha256: 46f229886fd30892e815dc216310ae2e2063d937a4c215c7ca7c9a298decefc8
test_author:
  human_id: unknown
  run_id: unknown
  model:
    provider: unknown
    family: unknown
    version: unknown
auditor:
  human_id: minshaoho
  run_id: dv_test_audit-smu_boot_stall_vs_ic_reset_priority-L1-20260806-d22
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

# Grade Report — smu_boot_stall_vs_ic_reset_priority_test (NO-PLAN-ENTRY Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason NO-PLAN-ENTRY)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | none | ⛔ NOT-READY |

> SMU_ALL has an approved plan/cards surface, but this leaf has **no plan record and no
> approved checkbox card**. Layer 1 findings are the entire scope. `NOT-READY` records the
> **absence of a closure claim** (and the plan gap), not a Layer-1 structural defect.

## DELTA (re-audit vs prior grade)

| Item | Prior (`c12`, log `55fd32da…`) | This audit (`d22`, log `46f22988…`) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🟠 1 Major FIND-001 | none |
| FIND-001 `[EVIDENCE-TOKEN-CONDITIONAL]` | open — fuzzy `RESET` ⊂ bring-up name emitted STALL_VS_IC_RESET early | closed — bring-up emits name-derived `FUSE_RESET_AFTER_BRING_UP` only (L22–26); STALL_VS_IC_RESET sole emit after `stall survives IC_RESET warm` (L63–67) |
| Kept log | `55fd32da4840d137aa4123f33a21a4eeaea4a9cf6289b9e0e8bf98817201f5d0` | `46f229886fd30892e815dc216310ae2e2063d937a4c215c7ca7c9a298decefc8` seed=1 |
| Waivers carried | none signed | none |

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
| F1 fabricated verdict / backdoor write | ✅ clean — JTAG DEBUG_CONTROL / IC_RESET frontdoor; cold via `rst_cold_ni`; hierarchical `jtag_smc_reset_ctrl` observe-only |
| F2 can't-fail checker | ✅ clean — stall / IC_RESET ovrd / fuse compares are real DUT observations |
| E1 skip-to-pass | ✅ clean — no missing-handle skip |
| E2 empty phase | ✅ clean — sticky stall + warm/cold IC_RESET + DEFAULT + TRST sequence present |
| S1 silent fail | ✅ clean — scoreboard mismatch and `wait_signal_high` timeout raise |
| O1 checker disabled | ✅ clean |
| Phase-S obligations — L1 | ✅ clean — FEATURE token after IC_RESET isolation compare; bounded waits; enrolled in `dtp.toml` / `all.toml` |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Code + kept log (Layer 1 only; no card checkers)</summary>

- Test: `hw/sys/smu/dv/cocotb/tests/smu_boot_stall_vs_ic_reset_priority_test.py`
- Helpers: `seq_lib/smu_jtag_helpers.py` (`pack_ic_reset_ports`, `read_smc_reset_ctrl_bit`),
  `env/smu_scoreboard.py` (`_resolve_token` — expect-keyword fuzzy removed),
  `env/smu_evidence_map.py` (`STALL_VS_IC_RESET`)
- Stimulus: stall sticky across cold; IC_RESET warm then cold; DEFAULT; TRST clear
- Kept log: `hw/sys/smu/dv/build/kept_logs/smu_boot_stall_vs_ic_reset_priority_test.seed1.log`
  sha256 `46f229886fd30892e815dc216310ae2e2063d937a4c215c7ca7c9a298decefc8`
- Seed: 1 · simulator: verilator 5.050 · run
  `20260806_082225__verilator__smu_boot_stall_vs_ic_reset_priority_test`
- Evidence timing: bring-up `FUSE_RESET_AFTER_BRING_UP` (L22–26); STALL_VS_IC_RESET once
  after IC_RESET warm isolation (L63–67); FEATURE PROVEN CHK-STALL-VS-IC (L134)
- Final: `SmuScoreboard: 22 check(s) passed`; `TESTS=1 PASS=1 FAIL=0`; no unexplained
  ERROR/FATAL/Traceback
- Enrollment: `hw/sys/smu/dv/testlists/dtp.toml`, `all.toml`; absent from
  `SMU_ALL_TESTCASE_PLAN.md` / `SMU_ALL_VPLAN_DETAIL.md`

</details>

## Not concluded

- Whether stall|IC_RESET isolation is the milestone-required property (O2) — Skill 3.
- Completeness against SMU_ALL feature_list — this leaf is not in the plan denominator.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers from code or logs.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
