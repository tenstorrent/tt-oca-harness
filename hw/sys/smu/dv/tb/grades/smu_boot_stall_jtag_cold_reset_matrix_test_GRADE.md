---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smu_boot_stall_jtag_cold_reset_matrix_test
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
- path: hw/sys/smu/dv/build/kept_logs/smu_boot_stall_jtag_cold_reset_matrix_test.seed1.log
  sha256: f58544c07dc67f653859d8d8afc930db7ccca1f2673119b14f5857718e80aa7c
test_author:
  human_id: unknown
  run_id: unknown
  model:
    provider: unknown
    family: unknown
    version: unknown
auditor:
  human_id: minshaoho
  run_id: dv_test_audit-smu_boot_stall_jtag_cold_reset_matrix-L1-20260806-d21
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

# Grade Report — smu_boot_stall_jtag_cold_reset_matrix_test (NO-PLAN-ENTRY Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason NO-PLAN-ENTRY)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | none | ⛔ NOT-READY |

> SMU_ALL has an approved plan/cards surface, but this leaf has **no plan record and no
> approved checkbox card**. Layer 1 findings are the entire scope. `NOT-READY` records the
> **absence of a closure claim** (and the plan gap), not a Layer-1 structural defect.

## DELTA (re-audit vs prior grade)

| Item | Prior (`c11`, log `a4de9c17…`) | This audit (`d21`, log `f58544c0…`) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🟠 1 Major FIND-001 | none |
| FIND-001 `[EVIDENCE-TOKEN-CONDITIONAL]` | open — scoreboard expect-keyword fuzzy attached STALL_* on idle/pre-stimulus | closed — `_resolve_token` no longer fuzzy-matches expect keywords; FEATURE tokens only via explicit `evidence=` after mapped compares (L48–52 / L63–67 / L78–82) |
| Kept log | `a4de9c177b74f4e34dc3f19cfd101d4ec9595747b9e4e639dbd8615b2e12e546` | `f58544c07dc67f653859d8d8afc930db7ccca1f2673119b14f5857718e80aa7c` seed=1 |
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
| F1 fabricated verdict / backdoor write | ✅ clean — JTAG DEBUG_CONTROL frontdoor; cold via `rst_cold_ni`; DUT port samples |
| F2 can't-fail checker | ✅ clean — sticky / TRST / fuse compares are real DUT observations via `sb.expect_eq` |
| E1 skip-to-pass | ✅ clean — no missing-handle skip |
| E2 empty phase | ✅ clean — stall→cold sticky→TRST clear→re-assert matrix stimulates and compares |
| S1 silent fail | ✅ clean — scoreboard mismatch and `wait_signal_high` timeout raise |
| O1 checker disabled | ✅ clean |
| Phase-S obligations — L1 | ✅ clean — FEATURE tokens after mapped compares; bounded waits; enrolled in `dtp.toml` / `all.toml` |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Code + kept log (Layer 1 only; no card checkers)</summary>

- Test: `hw/sys/smu/dv/cocotb/tests/smu_boot_stall_jtag_cold_reset_matrix_test.py`
- Helpers: `seq_lib/smu_jtag_helpers.py`, `seq_lib/smu_axi_helpers.py` (`wait_signal_high`),
  `env/smu_scoreboard.py` (`_resolve_token` — expect-keyword fuzzy removed),
  `env/smu_evidence_map.py`
- Stimulus: JTAG DEBUG_CONTROL stall; cold with TRST high; TRST clear; sticky re-assert
- Observations: `jtag_boot_stall_ovrd` / `jtag_boot_stall` / `fuse_reset_n_delayed_o` /
  `rst_primary_smc_clk_no`
- Kept log: `hw/sys/smu/dv/build/kept_logs/smu_boot_stall_jtag_cold_reset_matrix_test.seed1.log`
  sha256 `f58544c07dc67f653859d8d8afc930db7ccca1f2673119b14f5857718e80aa7c`
- Seed: 1 · simulator: verilator 5.050 · run
  `20260806_082220__verilator__smu_boot_stall_jtag_cold_reset_matrix_test`
- Evidence timing: pre-stimulus name-derived only (L22–36); STALL_COLD_STICKY after fuse gated
  (L48–52); STALL_TRST_CLEAR after TRST fuse high (L63–67); STALL_REASSERT_STICKY after
  sticky re-assert (L78–82); FEATURE PROVEN ×3 (L84–86)
- Final: `SmuScoreboard: 12 check(s) passed`; `TESTS=1 PASS=1 FAIL=0`; no unexplained
  ERROR/FATAL/Traceback
- Enrollment: `hw/sys/smu/dv/testlists/dtp.toml`, `all.toml`; absent from
  `SMU_ALL_TESTCASE_PLAN.md` / `SMU_ALL_VPLAN_DETAIL.md`

</details>

## Not concluded

- Whether the sticky/TRST matrix proves the SPEC properties a future card would require (O2)
  — Skill 3.
- Completeness against SMU_ALL feature_list — this leaf is not in the plan denominator.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers from code or logs.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
