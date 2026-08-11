---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smu_jtag_reset_override_test
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
- path: hw/sys/smu/dv/build/kept_logs/smu_jtag_reset_override_test.seed1.log
  sha256: a10da41266cceb7c3944e756eb98b5ff296320a658e59167159d723074d25159
test_author:
  human_id: unknown
  run_id: unknown
  model:
    provider: unknown
    family: unknown
    version: unknown
auditor:
  human_id: minshaoho
  run_id: dv_test_audit-smu_jtag_reset_override-L1-20260806-f14d2b90
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

# Grade Report — smu_jtag_reset_override_test (NO-PLAN-ENTRY Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason NO-PLAN-ENTRY)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | none | ⛔ NOT-READY |

> SMU_ALL has an approved plan/cards surface, but this leaf has **no plan record and no
> approved checkbox card**. Layer 1 findings are the entire scope. `NOT-READY` records the
> **absence of a closure claim** (and the plan gap), not a Layer-1 structural defect by itself.

## DELTA (re-audit vs prior grade)

| Item | Prior (`…-c02`, no kept log) | This audit (`…-f14d2b90`, log `a10da412…`) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| `no_contract_reason` | STANDALONE-REQUEST | NO-PLAN-ENTRY (SMU_ALL plan exists; leaf absent) |
| FIND-001 `[EVIDENCE-TOKEN-CONDITIONAL]` | open — IC_RESET_DOMAIN_EXCL on idle ext-ovrd | closed — idle uses no exclusivity token; first IC_RESET_DOMAIN_EXCL after EXT assert + SMC idle (log L47–51) |
| FIND-002 `[X-AWARE-CHECK]` | open — bare `int(signal.value)` on pins | closed — local `_sample` asserts `is_resolvable` (`:34–38`) before every ovrd/ctrl_n compare |
| Kept log | none supplied | `a10da412…` seed=1 · cocotb PASS · FEATURE PROVEN CHK-IC-DEFAULT / CHK-IC-DOMAIN |
| Waivers carried | none signed | none |

## Your to-do — 0 items (none)

| # | Sev | Item |
|---|---|---|
| — | — | none open |

**Then:** residual Layer 1 is clean; route to `/dv_vplan_gen` if SMU_ALL should allocate this
leaf (`augment`) or the owner retires it; re-invoke `/dv_test_audit` after a card exists if
Layer 2 grading is required.

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — JTAG IC_RESET frontdoor; top-level ovrd/ctrl_n observes |
| F2 can't-fail checker | ✅ clean — default readback, EXT/SMC assert/clear, and cross-domain release compares can fail |
| E1 skip-to-pass | ✅ clean |
| E2 empty phase | ✅ clean — default → EXT assert → SMC assert → DEFAULT clear |
| S1 silent fail | ✅ clean — `sb.expect_eq` / `_sample` raise |
| O1 checker disabled | ✅ clean |
| Phase-S obligations — L1 | ✅ clean — X-aware `_sample`; tokens gated after exclusivity compares; enrolled in `dtp.toml` / `all.toml` |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smu/dv/cocotb/tests/smu_jtag_reset_override_test.py`
- Helpers: `pack_ic_reset_ports`, `SMU_IC_RESET_*` in `seq_lib/smu_jtag_helpers.py`; local
  `_sample` X-aware gate
- Log: `hw/sys/smu/dv/build/kept_logs/smu_jtag_reset_override_test.seed1.log` sha256
  `a10da41266cceb7c3944e756eb98b5ff296320a658e59167159d723074d25159` (matches claimed)
- Seed: 1 · simulator: verilator 5.050 · cocotb summary: `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Stimulus: EXT port then SMC cold_reset port via 139-bit IC_RESET TDR
- Observations: `jtag_ic_reset_ext_ovrd/ctrl_n`, `jtag_ic_reset_smc_ovrd/ctrl_n`, TDR readback
- Evidence: `IC_RESET_DEFAULT` on default readback; `IC_RESET_DOMAIN_EXCL` first after EXT
  assert with SMC idle (L47–51), again after SMC assert with EXT released (L67–71)
- Enrollment: `hw/sys/smu/dv/testlists/dtp.toml`, `all.toml`

</details>

## Not concluded

- Whether EXT/SMC override alone proves the full IC_RESET domain matrix a future card would
  require (O2) — Skill 3 / plan allocation.
- Completeness against a feature_list — no current inventory allocates this leaf.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
