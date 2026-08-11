---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smu_wrapper_elaboration_no_sep_test
ip: SMU_ENROLLED_RESIDUAL
anchor: null
mode: NO-CHECKBOX
no_contract_reason: NO-APPROVED-CARD
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
build_config: compile_smu_chiplet_no_sep
simulator: verilator
simulator_version: 5.050 2026-07-01
compile_target: compile_smu_chiplet_no_sep
model_fingerprint: null
compile_inputs_sha256: null
seeds:
- 1
logs:
- path: hw/sys/smu/dv/build/kept_logs/smu_wrapper_elaboration_no_sep_test.seed1.log
  sha256: 20a5c6875edebc7ffeee36d427b40d5c7d9802236048c70dd18c9ecd93d94a86
test_author:
  human_id: unknown
  run_id: unknown
  model:
    provider: unknown
    family: unknown
    version: unknown
auditor:
  human_id: minshaoho
  run_id: dv_test_audit-smu_wrapper_elaboration_no_sep-L1-20260806-f15e6a33
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

# Grade Report — smu_wrapper_elaboration_no_sep_test (NO-APPROVED-CARD Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason NO-APPROVED-CARD)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | none | ⛔ NOT-READY |

> This leaf once had SMU_ALL_008 plan/card records for `smu_wrapper_elaboration_no_sep_test`,
> but those records are `current: false` (superseded). There is **no current approved card**
> (and SMU-SEP-PARAM.S2 ownership now lives on `smu_axi_external_port_connectivity_test`).
> Layer 1 findings are the entire scope. `NOT-READY` records the **absence of a closure
> claim** / VPLAN migration gap, not a Layer-1 structural defect by itself.

## DELTA (re-audit vs prior grade)

| Item | Prior (`…-c04`, no kept log) | This audit (`…-f15e6a33`, log `20a5c687…`) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| `no_contract_reason` | STANDALONE-REQUEST | NO-APPROVED-CARD (superseded SMU_ALL_008; no current card) |
| FIND-001 `[EVIDENCE-TOKEN-CONDITIONAL]` | open — CHK-NONVAC without ordered fence on no_sep path | closed — `_run_legacy_no_sep` builds fail-capable S1&lt;S2&lt;S3&lt;PASS fence then emits CHK-NONVAC (seq `:175–194`, log L57–59) |
| Kept log | none supplied | `20a5c687…` seed=1 · cocotb PASS · WRAP_ELAB_OK after fence |
| Waivers carried | none signed | none |

## Your to-do — 0 items (none)

| # | Sev | Item |
|---|---|---|
| — | — | none open |

**Then:** residual Layer 1 is clean. Route to `/dv_vplan_gen` if SMU_ALL should re-allocate
this leaf (or formally retire it now that SEP=0 compose intent sits on SMU_ALL_002); re-invoke
`/dv_test_audit` after a current approved card exists if Layer 2 grading is required.

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — DUT pin asserts / `wait_value`; no Force on proof path |
| F2 can't-fail checker | ✅ clean — profile cold-reset SEP sample, powergood/rst_cold waits, and NONVAC fence can fail |
| E1 skip-to-pass | ✅ clean — missing `+expected_sep` asserts; wait timeouts raise |
| E2 empty phase | ✅ clean — profile sample + powergood/rst release + two cold-reset pulses + fence |
| S1 silent fail | ✅ clean — assert / `wait_value` / fence raise |
| O1 checker disabled | ✅ clean |
| Phase-S obligations — L1 | ✅ clean — X-aware `read_int`; seed logged; CHK-NONVAC after fence; enrolled as `smu_wrapper_elaboration_no_sep_test` in `wrapper.toml` (`module=smu_wrapper_elaboration_test`, `run_modes=["no_sep"]`, `+expected_sep=0`) |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Grade leaf name: `smu_wrapper_elaboration_no_sep_test`
- Implementation module: `hw/sys/smu/dv/cocotb_wrapper/tests/smu_wrapper_elaboration_test.py`
- Sequence: `cocotb_wrapper/seq_lib/smu_wrapper_elaboration_seq.py` → `_run_legacy_no_sep`
- Log: `hw/sys/smu/dv/build/kept_logs/smu_wrapper_elaboration_no_sep_test.seed1.log` sha256
  `20a5c6875edebc7ffeee36d427b40d5c7d9802236048c70dd18c9ecd93d94a86` (matches claimed;
  run `20260806_081314__verilator__smu_wrapper_elaboration_no_sep_test`)
- Seed: 1 · simulator: verilator 5.050 · cocotb summary: `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Profile: `wrapper.toml` name `smu_wrapper_elaboration_no_sep_test`, target
  `compile_smu_chiplet_no_sep`, args `+expected_sep=0`
- Stimulus: bring-up cold-reset sample of `sep_reset_n_o` / fuse; powergood + rst_cold waits;
  two randomized-hold cold pulses with `wait_value` completion
- Evidence: STEP S1/S2/S3 then `CHK-NONVAC: ordered fence S1<S2<S3<PASS (pairs_ok=3)` (L57)
  before `EVIDENCE:CHK-NONVAC` (L58–59); test then logs WRAP_ELAB_OK
- Note: SEP=1 card path (`_run_smu_all_001`) is out of scope for this no_sep grade

</details>

## Not concluded

- Whether no_sep wrapper elab/reset smoke proves the SPEC composition properties now owned by
  other leaves (O2) — Skill 3 / VPLAN migration.
- Completeness against a feature_list — no current approved card for this anchor.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
