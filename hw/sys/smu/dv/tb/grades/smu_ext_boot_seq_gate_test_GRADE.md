---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smu_ext_boot_seq_gate_test
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
- path: hw/sys/smu/dv/build/kept_logs/smu_ext_boot_seq_gate_test.seed1.log
  sha256: 5e0db913bb8dd9b482c97ae4f603ed034958c505ea61c0242cb410b518b22f02
test_author:
  human_id: unknown
  run_id: unknown
  model:
    provider: unknown
    family: unknown
    version: unknown
auditor:
  human_id: minshaoho
  run_id: dv_test_audit-smu_ext_boot_seq_gate-L1-20260806-0273cc10673e
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

# Grade Report — smu_ext_boot_seq_gate_test (NO-PLAN-ENTRY Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason NO-PLAN-ENTRY)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | none | ⛔ NOT-READY |

> SMU_ALL has an approved plan/cards surface, but this leaf has **no plan record and no
> approved checkbox card** (header DV-CARD SMU_006 cites a missing `SMU_VPLAN_DETAIL.md`;
> not used as a contract). Layer 1 findings are the entire scope. `NOT-READY` records the
> **absence of a closure claim** (and the plan gap), not a Layer-1 structural defect.

## DELTA (re-audit vs prior grade)

| Item | Prior (`b04`, no kept log) | This audit (`0273cc10673e`, log `5e0db913…`) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| `no_contract_reason` | STANDALONE-REQUEST | NO-PLAN-ENTRY (SMU_ALL plan exists; leaf absent) |
| Findings | 🔴 2 Blocking | none |
| FIND-001 `[NO-FABRICATED-VERDICT]` | open — `expect_eq(True, True)` NONVAC | closed — `pairs_ok` vs `len(order)-1` measured from `_step_ts` |
| FIND-002 `[NO-ALWAYS-PASS-CHECKER]` | open — post-filtered scoreboard expects | closed — soft `_wait_eq` + live `expect_eq(sample, 1)` (expiry can fail) |
| Kept log | absent | `5e0db913bb8dd9b482c97ae4f603ed034958c505ea61c0242cb410b518b22f02` seed=1 |
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
| F1 fabricated verdict / backdoor write | ✅ clean — DUT pin samples; NONVAC uses measured `pairs_ok` |
| F2 can't-fail checker | ✅ clean — soft `_wait_eq` + `expect_eq` on primary/fuse samples; gated loop can raise |
| E1 skip-to-pass | ✅ clean — custom `bring_up` holds gate=0; no skip-to-pass branch |
| E2 empty phase | ✅ clean — S2 gated samples, S3 primary negative control, S4 ungate, timeout-path count |
| S1 silent fail | ✅ clean — gated-loop / `expect_eq` / timeout-path shape raise `AssertionError` |
| O1 checker disabled | ✅ clean |
| Phase-S obligations — L1 | ✅ clean — X-aware `_sample`; bounded waits fail via `expect_eq`; negative control present; enrolled in `smc.toml` / `all.toml` |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Code + kept log (Layer 1 only; no card checkers)</summary>

- Test: `hw/sys/smu/dv/cocotb/tests/smu_ext_boot_seq_gate_test.py` (overrides `bring_up` to hold
  `ext_boot_seq_done_i=0`)
- Sequence: `hw/sys/smu/dv/cocotb/seq_lib/smu_ext_boot_seq_gate_test_seq.py`
- Scoreboard: `hw/sys/smu/dv/cocotb/env/smu_scoreboard.py` (`expect_eq` + mapped
  `prove_mapped_features`)
- Stimulus: cold release with `ext_boot_seq_done_i=0`; 64 gated samples on
  `fuse_reset_n_delayed_o`; negative control `rst_primary_smc_clk_no→1`; ungate→fuse release
- Checks: `CHK-PRIMARY-NOT-GATED`, `CHK-BOOT-SEQ-GATE`, `CHK-TIMEOUT-PATHS`, `CHK-NONVAC`
  via soft wait + live compare / ordered fence
- Kept log: `hw/sys/smu/dv/build/kept_logs/smu_ext_boot_seq_gate_test.seed1.log`
  sha256 `5e0db913bb8dd9b482c97ae4f603ed034958c505ea61c0242cb410b518b22f02`
- Seed: 1 · simulator: verilator 5.050 · model_fingerprint: `48f5d6b1d3f2`
  (run `20260806_070521__verilator__smu_ext_boot_seq_gate_test`)
- Log cites: L26–29 PRIMARY + EVIDENCE; L31–34 BOOT-SEQ-GATE + EVIDENCE; L36–41 TIMEOUT-PATHS;
  L43–46 NONVAC; L47–54 FEATURE PROVEN ×4 + summary; L56–62 cocotb PASS / `TESTS=1 PASS=1`
- Final gate: `prove_mapped_features` + scoreboard `check_phase` (4 checks, zero errors);
  no unexplained ERROR/FATAL/Traceback
- Enrollment: `hw/sys/smu/dv/testlists/smc.toml`, `all.toml`; listed in `SMU_ALL_PIN.yaml`
  anchors but absent from `SMU_ALL_TESTCASE_PLAN.md` / `SMU_ALL_VPLAN_DETAIL.md`
- Bring-up trailer `+skip_fuse_sense` / ROM backdoor present; not on the boot-gate pin proof path

</details>

## Not concluded

- Whether fuse_reset boot-gate is the milestone-required property (O2) — Skill 3.
- Completeness against SMU_ALL feature_list — this leaf is not in the plan denominator.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers from code or logs.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
