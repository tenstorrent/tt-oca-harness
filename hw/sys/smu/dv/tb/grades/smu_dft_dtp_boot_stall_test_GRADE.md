---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smu_dft_dtp_boot_stall_test
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
- path: hw/sys/smu/dv/build/kept_logs/smu_dft_dtp_boot_stall_test.seed1.log
  sha256: 75b29bef8f9a625ebb62823de96cbeed9dac115087b7d15a9c15d63fa6aa7a31
test_author:
  human_id: unknown
  run_id: unknown
  model:
    provider: unknown
    family: unknown
    version: unknown
auditor:
  human_id: minshaoho
  run_id: dv_test_audit-smu_dft_dtp_boot_stall-L1-20260806-d23
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

# Grade Report — smu_dft_dtp_boot_stall_test (NO-PLAN-ENTRY Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason NO-PLAN-ENTRY)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | none | ⛔ NOT-READY |

> SMU_ALL has an approved plan/cards surface, but this leaf has **no plan record and no
> approved checkbox card**. Layer 1 findings are the entire scope. `NOT-READY` records the
> **absence of a closure claim** (and the plan gap), not a Layer-1 structural defect.

## DELTA (re-audit vs prior grade)

| Item | Prior (`c13`, log `55bfbf37…`) | This audit (`d23`, log `75b29bef…`) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🟠 1 Major FIND-001 | none |
| FIND-001 `[EVIDENCE-TOKEN-CONDITIONAL]` | open — fuzzy STALL/ASSERT attached FEATURE tokens on idle / pre-cold | closed — idle/asserted emit name-derived tokens only; STALL_COLD_STICKY after post-cold gate (L118–122); STALL_REASSERT_STICKY after sticky re-assert (L138–142) |
| Kept log | `55bfbf37d695408d87c7d8a6b83484727920e891ef8cd99c3f3347e122353b52` | `75b29bef8f9a625ebb62823de96cbeed9dac115087b7d15a9c15d63fa6aa7a31` seed=1 |
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
| F1 fabricated verdict / backdoor write | ✅ clean — JTAG DEBUG_CONTROL frontdoor; DUT pin samples; cold via `rst_cold_ni` |
| F2 can't-fail checker | ✅ clean — `sb.expect_eq` compares DUT observations; mismatch raises |
| E1 skip-to-pass | ✅ clean — no missing-handle skip-to-pass |
| E2 empty phase | ✅ clean — Phase A combo matrix and Phase B cold-reset sticky path both stimulate and compare |
| S1 silent fail | ✅ clean — scoreboard mismatch and `wait_signal_high` timeout raise |
| O1 checker disabled | ✅ clean |
| Phase-S obligations — L1 | ✅ clean — FEATURE tokens after mapped compares; timeouts fail; enrolled in `dtp.toml` / `all.toml` |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Code + kept log (Layer 1 only; no card checkers)</summary>

- Test: `hw/sys/smu/dv/cocotb/tests/smu_dft_dtp_boot_stall_test.py`
- Evidence map: `STALL_COLD_STICKY`, `STALL_REASSERT_STICKY` (no TRST token for this leaf)
- Scoreboard: `env/smu_scoreboard.py` (`_resolve_token` — expect-keyword fuzzy removed)
- Kept log: `hw/sys/smu/dv/build/kept_logs/smu_dft_dtp_boot_stall_test.seed1.log`
  sha256 `75b29bef8f9a625ebb62823de96cbeed9dac115087b7d15a9c15d63fa6aa7a31`
- Seed: 1 · simulator: verilator 5.050 · run
  `20260806_082230__verilator__smu_dft_dtp_boot_stall_test`
- Evidence timing: idle/combo/asserted name-derived; STALL_COLD_STICKY on post-cold gate
  (L118–122); STALL_REASSERT_STICKY on sticky re-assert (L138–142); FEATURE PROVEN ×2
  (L144–145)
- Final: `TESTS=1 PASS=1 FAIL=0`; no unexplained ERROR/FATAL/Traceback
- Enrollment: `hw/sys/smu/dv/testlists/dtp.toml`, `all.toml`; absent from
  `SMU_ALL_TESTCASE_PLAN.md` / `SMU_ALL_VPLAN_DETAIL.md`

</details>

## Not concluded

- Whether DTP boot-stall sticky gating is the milestone-required property (O2) — Skill 3.
- Completeness against SMU_ALL feature_list — this leaf is not in the plan denominator.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers from code or logs.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
