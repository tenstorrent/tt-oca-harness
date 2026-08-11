---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smu_ic_reset_ss_domain_matrix_test
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
model_fingerprint: null
compile_inputs_sha256: null
seeds:
- 1
logs:
- path: hw/sys/smu/dv/build/kept_logs/smu_ic_reset_ss_domain_matrix_test.seed1.log
  sha256: 4b3d12d038c128fd477e115f30a4e02cd2a74bfb1189e7540cde362586e8bcec
test_author:
  human_id: unknown
  run_id: unknown
  model:
    provider: unknown
    family: unknown
    version: unknown
auditor:
  human_id: minshaoho
  run_id: dv_test_audit-smu_ic_reset_ss_domain_matrix-L1-20260806-69400aa5
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

# Grade Report — smu_ic_reset_ss_domain_matrix_test (NO-PLAN-ENTRY Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason NO-PLAN-ENTRY)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | none | ⛔ NOT-READY |

> SMU_ALL has an approved plan/cards surface, but this leaf has **no plan record and no
> approved checkbox card**. Layer 1 findings are the entire scope. `NOT-READY` records the
> **absence of a closure claim** (and the plan gap), not a Layer-1 structural defect.

## DELTA (re-audit vs prior grade)

| Item | Prior (`…-f13c4e8a`, log `06e8b8d9…`) | This audit (`…-69400aa5`, log `4b3d12d0…`) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🟠 1 Major (FIND-001) | none |
| FIND-001 `[EVIDENCE-TOKEN-CONDITIONAL]` | open — idle fuzzy-map emitted `IC_RESET_SS_COLD_OVRD` (L22–26) | closed — idle emits name-derived `IDLE_SS_*` (L22–31); first `IC_RESET_SS_COLD_OVRD` at L32–36 on SS assert with explicit `evidence=`; scoreboard expect-keyword fuzzy removed |
| Kept log | `06e8b8d9…` | `4b3d12d038c128fd477e115f30a4e02cd2a74bfb1189e7540cde362586e8bcec` seed=1 · cocotb PASS |
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
| F1 fabricated verdict / backdoor write | ✅ clean — JTAG IC_RESET frontdoor; hierarchical observe via `read_smc_reset_ctrl_bit` |
| F2 can't-fail checker | ✅ clean — SS cold0/warm0 ovrd/val asserts and mutual-exclusion idles use independent expects |
| E1 skip-to-pass | ✅ clean — no missing-handle skip-to-pass |
| E2 empty phase | ✅ clean — each SS domain assert → excl checks → DEFAULT clear → release compare |
| S1 silent fail | ✅ clean — `sb.expect_eq` raises on mismatch |
| O1 checker disabled | ✅ clean |
| Phase-S obligations — L1 | ✅ clean — X-aware helper; FEATURE token after SS assert; enrolled in `dtp.toml` / `all.toml`; docstring scopes out `ss_reset_complete` handshake |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smu/dv/cocotb/tests/smu_ic_reset_ss_domain_matrix_test.py`
- Helpers: `pack_ic_reset_ports`, X-aware `read_smc_reset_ctrl_bit` in
  `seq_lib/smu_jtag_helpers.py`; scoreboard `_resolve_token` (no expect-keyword fuzzy) +
  `smu_evidence_map.py` (`CHK-IC-SS` → `IC_RESET_SS_COLD_OVRD`)
- Log: `hw/sys/smu/dv/build/kept_logs/smu_ic_reset_ss_domain_matrix_test.seed1.log` sha256
  `4b3d12d038c128fd477e115f30a4e02cd2a74bfb1189e7540cde362586e8bcec` (matches claimed;
  run `20260806_082248__verilator__smu_ic_reset_ss_domain_matrix_test`)
- Seed: 1 · simulator: verilator 5.050 · cocotb summary: `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Stimulus: one-at-a-time IC_RESET enable on SS_COLD0 (port 5) and SS_WARM0 (port 37)
- Observations: `ss_*_reset_n_ovrd/val[0]` plus scalar fuse/warm/cool/cold ovrd idle
- Evidence: idle name-tokens L22–31; first `IC_RESET_SS_COLD_OVRD` L32–36; excl tokens;
  SS warm assert L72–76; FEATURE PROVEN CHK-IC-SS L113
- Enrollment: `hw/sys/smu/dv/testlists/dtp.toml`, `all.toml`; absent from
  `SMU_ALL_TESTCASE_PLAN.md` / `SMU_ALL_VPLAN_DETAIL.md`

</details>

## Not concluded

- Whether SS domain matrix without `ss_reset_complete` handshake proves the SPEC property a
  future card would require (O2) — Skill 3 / plan allocation.
- Completeness against a feature_list — no current inventory allocates this leaf.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
