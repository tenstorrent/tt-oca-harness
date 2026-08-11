---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smu_ic_reset_dual_domain_illegal_test
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
- path: hw/sys/smu/dv/build/kept_logs/smu_ic_reset_dual_domain_illegal_test.seed1.log
  sha256: b483484b88568a3db4154d17c3e640771f3b1701886f66d1b03f35663f6acd0a
test_author:
  human_id: unknown
  run_id: unknown
  model:
    provider: unknown
    family: unknown
    version: unknown
auditor:
  human_id: minshaoho
  run_id: dv_test_audit-smu_ic_reset_dual_domain_illegal-L1-20260806-0f4c4442
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

# Grade Report — smu_ic_reset_dual_domain_illegal_test (NO-PLAN-ENTRY Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason NO-PLAN-ENTRY)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | none | ⛔ NOT-READY |

> SMU_ALL has an approved plan/cards surface, but this leaf has **no plan record and no
> approved checkbox card**. Layer 1 findings are the entire scope. `NOT-READY` records the
> **absence of a closure claim** (and the plan gap), not a Layer-1 structural defect.

## DELTA (re-audit vs prior grade)

| Item | Prior (`…-f11a7c2e`, log `d2dde9db…`) | This audit (`…-0f4c4442`, log `b483484b…`) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🟠 1 Major (FIND-001) | none |
| FIND-001 `[EVIDENCE-TOKEN-CONDITIONAL]` | open — idle fuzzy-map emitted `IC_RESET_DUAL_PACK` (L22–26) | closed — idle emits name-derived `IDLE_*` (L22–41); first `IC_RESET_DUAL_PACK` at L72–76 after fuse+warm assert/no-bleed + DEFAULT clear; scoreboard `_resolve_token` no longer fuzzy-matches expect keywords |
| Kept log | `d2dde9db…` | `b483484b88568a3db4154d17c3e640771f3b1701886f66d1b03f35663f6acd0a` seed=1 · cocotb PASS |
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
| F2 can't-fail checker | ✅ clean — selected ovrd/val and non-selected idle compares can fail independently |
| E1 skip-to-pass | ✅ clean |
| E2 empty phase | ✅ clean — fuse+warm and cool+cold pairs each assert, check bleed, DEFAULT clear |
| S1 silent fail | ✅ clean — `expect_eq` raises on mismatch |
| O1 checker disabled | ✅ clean |
| Phase-S obligations — L1 | ✅ clean — X-aware helper; FEATURE token after dual-pack cycle; enrolled in `dtp.toml` / `all.toml` |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smu/dv/cocotb/tests/smu_ic_reset_dual_domain_illegal_test.py`
- Helpers: `pack_ic_reset_ports`, X-aware `read_smc_reset_ctrl_bit` in
  `seq_lib/smu_jtag_helpers.py`; scoreboard `_resolve_token` (expect-keyword fuzzy removed) +
  `smu_evidence_map.py` (`CHK-IC-DUAL` → `IC_RESET_DUAL_PACK`)
- Log: `hw/sys/smu/dv/build/kept_logs/smu_ic_reset_dual_domain_illegal_test.seed1.log` sha256
  `b483484b88568a3db4154d17c3e640771f3b1701886f66d1b03f35663f6acd0a` (matches claimed;
  run `20260806_082235__verilator__smu_ic_reset_dual_domain_illegal_test`)
- Seed: 1 · simulator: verilator 5.050 · cocotb summary: `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Stimulus: single DR enabling two SMC ports; DEFAULT clear between pairs
- Observations: fuse/warm/cool/cold ovrd+val under `u_dut.jtag_smc_reset_ctrl`
- Evidence: idle name-tokens L22–41; dual-pack asserts/no-bleed L42–71; first
  `IC_RESET_DUAL_PACK` L72–76 (explicit `evidence=` on DEFAULT clear); cool+cold cycle;
  FEATURE PROVEN CHK-IC-DUAL L123
- Enrollment: `hw/sys/smu/dv/testlists/dtp.toml`, `all.toml`; absent from
  `SMU_ALL_TESTCASE_PLAN.md` / `SMU_ALL_VPLAN_DETAIL.md`

</details>

## Not concluded

- Whether "dual pack" vs leaf name "illegal" is the SPEC-required property (O2) — Skill 3 /
  plan allocation.
- Completeness against a feature_list — no current inventory allocates this leaf.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
