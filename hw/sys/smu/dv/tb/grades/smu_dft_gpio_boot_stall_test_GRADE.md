---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smu_dft_gpio_boot_stall_test
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
- path: hw/sys/smu/dv/build/kept_logs/smu_dft_gpio_boot_stall_test.seed1.log
  sha256: ab3008c54855cd7efe3c6f049244d4420118cb14795bf08696725c660b7da155
test_author:
  human_id: unknown
  run_id: unknown
  model:
    provider: unknown
    family: unknown
    version: unknown
auditor:
  human_id: minshaoho
  run_id: dv_test_audit-smu_dft_gpio_boot_stall-L1-20260806-c14
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

# Grade Report — smu_dft_gpio_boot_stall_test (NO-PLAN-ENTRY Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason NO-PLAN-ENTRY)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | none | ⛔ NOT-READY |

> SMU_ALL has an approved plan/cards surface, but this leaf has **no plan record and no
> approved checkbox card**. Layer 1 findings are the entire scope. `NOT-READY` records the
> **absence of a closure claim** (and the plan gap), not a Layer-1 structural defect.

## DELTA (re-audit vs prior grade)

| Item | Prior (`b02`, STANDALONE-REQUEST) | This audit (`c14`, log `ab3008c5…`) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| `no_contract_reason` | STANDALONE-REQUEST | NO-PLAN-ENTRY |
| Findings | 🟠 2 Major (FIND-001, FIND-002) | none |
| FIND-001 `[EVIDENCE-TOKEN-CONDITIONAL]` | open — tokens on bring-up / first-gate | closed — STALL_COLD_STICKY on gated compare (L28-32); STALL_REASSERT_STICKY on sticky re-assert (L38-42); no premature fuzzy hit |
| FIND-002 `[NO-BLIND-DELAY-SYNC]` | open — `ClockCycles(128)` release wait | closed — `wait_signal_high(fuse_reset_n_delayed_o, …, timeout_cycles=2000)` (test.py:72-78) |
| Kept log | absent in prior report | `ab3008c54855cd7efe3c6f049244d4420118cb14795bf08696725c660b7da155` seed=1 |
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
| F1 fabricated verdict / backdoor write | ✅ clean — TB `gpio_boot_stall_drive_i` pin stimulus (OR into pad2core bit[57]; not Force); DUT `fuse_reset_n_delayed_o` sampled |
| F2 can't-fail checker | ✅ clean — gated==0 / released==1 / sticky stays-1 are real DUT compares |
| E1 skip-to-pass | ✅ clean |
| E2 empty phase | ✅ clean — assert→cold→gate→clear→re-assert path present |
| S1 silent fail | ✅ clean — scoreboard + `wait_signal_high` raise on timeout/mismatch |
| O1 checker disabled | ✅ clean |
| Phase-S obligations — L1 | ✅ clean — bounded fuse release wait; evidence tokens after mapped compares; enrolled in `dtp.toml` / `all.toml` |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Code + kept log (Layer 1 only; no card checkers)</summary>

- Test: `hw/sys/smu/dv/cocotb/tests/smu_dft_gpio_boot_stall_test.py`
- TB: `hw/sys/smu/dv/tb/tb_top.sv:602-607` — `pad2core |= gpio_boot_stall_drive_i << 57`
- Stimulus: `gpio_boot_stall_drive_i`, cold `rst_cold_ni` pulse
- Observation: `fuse_reset_n_delayed_o`, `rst_primary_smc_clk_no`
- Kept log: `hw/sys/smu/dv/build/kept_logs/smu_dft_gpio_boot_stall_test.seed1.log`
  sha256 `ab3008c54855cd7efe3c6f049244d4420118cb14795bf08696725c660b7da155`
- Seed: 1 · simulator: verilator 5.050 · run
  `20260806_081605__verilator__smu_dft_gpio_boot_stall_test`
- Evidence: L22–26 bring-up (name-derived); L28–32 STALL_COLD_STICKY; L33–37 release;
  L38–42 STALL_REASSERT_STICKY; L44–45 FEATURE PROVEN ×2; L55–57 cocotb PASS
- Final gate: `prove_mapped_features` + scoreboard `check_phase` (4 checks, zero errors);
  no unexplained ERROR/FATAL/Traceback
- Enrollment: `hw/sys/smu/dv/testlists/dtp.toml`, `all.toml`; absent from
  `SMU_ALL_TESTCASE_PLAN.md` / `SMU_ALL_VPLAN_DETAIL.md`

</details>

## Not concluded

- Whether GPIO pad boot-stall sticky gating is the milestone-required property (O2) — Skill 3.
- Completeness against SMU_ALL feature_list — this leaf is not in the plan denominator.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers from code or logs.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
