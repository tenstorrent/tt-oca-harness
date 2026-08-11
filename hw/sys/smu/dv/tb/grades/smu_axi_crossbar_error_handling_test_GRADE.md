---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smu_axi_crossbar_error_handling_test
ip: SMU_ALL
anchor: smu_axi_crossbar_error_handling_test
mode: CHECKBOX
no_contract_reason: null
entry_status: PASS
repository_revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
spec:
- path: hw/sys/smu/doc/SMU_SPEC.md
  revision: 88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
- path: hw/sys/smu/doc/port_table.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/smc/doc/index.adoc
  revision: 1e98bd45a59ae32ca1bb4715a963b721e26aaf3b
- path: hw/sys/smc/doc/overview.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/smc/doc/fabric.adoc
  revision: ffc8cdcc349e1e01a2b970442a01070b1c62c0d7
- path: hw/sys/smc/doc/port_table.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/smc/doc/cpu.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/smc/doc/clk_rst.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/smc/doc/interrupts.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/smc/doc/memmap.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/smc/doc/periphs.adoc
  revision: ffc8cdcc349e1e01a2b970442a01070b1c62c0d7
- path: hw/sys/smc/doc/dma.adoc
  revision: e2aae39953bb8001c7c20e3afd3956e68c22440c
- path: hw/sys/smc/doc/rom.adoc
  revision: df9e3efe4c8a68f95acb339d0aaf9c9f3f90ab4d
- path: hw/sys/sep/doc/index.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/introduction.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/overview.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/fabric.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/cpu.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/crypto.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/periphs.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/memory_map.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/port_table.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/lifecycle_controller.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/security_disable.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/test_mode.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/token_processing.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/dtp/doc/index.adoc
  revision: ffc8cdcc349e1e01a2b970442a01070b1c62c0d7
- path: hw/sys/dtp/doc/overview.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/dtp/doc/jtag.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/dtp/doc/clock_stop.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/dtp/doc/port_table.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
card_sha256: 3be11166c37e13bc35de8dddbea105adf69f1f819525f7bb5bdcd292ffdf521d
card_revision: 18
card_path: hw/sys/smu/dv/tb/SMU_ALL_VPLAN_DETAIL.md
testcase_plan:
  path: hw/sys/smu/dv/tb/SMU_ALL_TESTCASE_PLAN.md
  plan_revision: 18
  testcase_revision: 17
  testcase_record_sha256: f79c50aeaa5d0c5aa0afb34c305d2e5763cc2a5af8ba95d7df377cc53c2f8859
  parent_approved: true
evidence_class: frontdoor-func
closure_tier: B
quality_policy:
  path: hw/sys/smu/dv/tb/SMU_ALL_QUALITY_POLICY.md
  revision: 936b77700909a93bb122f9fb124a3ffb6f5dac5f508c623c5950285a5cefb79a
build_config: default
simulator: verilator
simulator_version: 5.050 2026-07-01 rev v5.050 (mod)
compile_target: default
model_fingerprint: 48f5d6b1d3f2
compile_inputs_sha256: null
seeds:
- 1
logs:
- path: hw/sys/smu/dv/build/kept_logs/smu_axi_crossbar_error_handling_test.seed1.log
  sha256: 04c129e6eb1d47cd507efcdc937e7ae29433c0c858325b423511ed1ad9e24f1a
test_author:
  human_id: minshaoho
  run_id: dv_test_impl-SMU_ALL_008-r18-pwrgood-20260805
  model:
    provider: cursor
    family: grok
    version: '4.5'
auditor:
  human_id: minshaoho
  run_id: dv_test_audit-SMU_ALL_008-r18-84c27e9f-ea0a-6619-459c-f96ebefc27ed
  model:
    provider: cursor
    family: grok
    version: '4.5'
exceptions: []
checkers:
- id: CHK-SMC-PWRGOOD-DTP-POR-S2
  checks_steps:
  - S1
  proves:
  - SMC-PWRGOOD-DTP-POR
  covers:
  - SMC-PWRGOOD-DTP-POR.S2
  proof_class: LIVE
  expect_source: pinned SPEC citations on SMC-PWRGOOD-DTP-POR.S2 in SMU_ALL_SPEC_FEATURE_LIST.md
  grade: PROVEN
  evidence:
  - token: 'CHK-SMC-PWRGOOD-DTP-POR-S2: PASS (powergood=1 trst=1 pre_tlr=0x1 post_state=0x2 expect_rti=0x2
      cell=tap=exit_tlr)'
    log_sha256: 04c129e6eb1d47cd507efcdc937e7ae29433c0c858325b423511ed1ad9e24f1a
    line: 25
    seed: 1
    implementation_path: hw/sys/smu/dv/cocotb/seq_lib/smu_axi_crossbar_error_handling_test_seq.py:140
  lifecycle_results: null
  coverage_results:
  - key: SMC-PWRGOOD-DTP-POR.S2
    method: DIRECTED
    required_cells:
    - powergood=1
    - trst=1
    - tap=exit_tlr
    achieved_cells:
    - powergood=1
    - trst=1
    - tap=exit_tlr
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds:
    - 1
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smu/dv/build/kept_logs/smu_axi_crossbar_error_handling_test.seed1.log#04c129e6eb1d47cd507efcdc937e7ae29433c0c858325b423511ed1ad9e24f1a
    satisfied: true
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-NONVAC
  checks_steps:
  - S1
  proves: []
  covers: []
  proof_class: INTEGRITY
  expect_source: approved card ordering contract
  grade: PROVEN
  evidence:
  - token: 'CHK-NONVAC: PASS (Ordered fence S1<PASS; reset_released=1 clocks_advanced=1 s1_pass=1
      positive_deltas=1 delta_ns=37840938)'
    log_sha256: 04c129e6eb1d47cd507efcdc937e7ae29433c0c858325b423511ed1ad9e24f1a
    line: 33
    seed: 1
    implementation_path: hw/sys/smu/dv/cocotb/seq_lib/smu_axi_crossbar_error_handling_test_seq.py:204
  lifecycle_results: null
  coverage_results: []
  linked_issue: null
  finding_ids: []
  remediation: null
findings: []
waivers: []
recommendation: EVIDENCE-CLOSED-AWAITING-SIGNOFF
signed_off_by: minshaoho
signed_off_at: '2026-08-05T18:05:53+08:00'
content_sha256: 9e9015174f1a89e71cfddbfe147c9c8b03ffe3f741f678746a0fcad155b79ab1
---

# Grade Report — smu_axi_crossbar_error_handling_test (SMU_ALL_008)

**VERDICT: 2/2 PROVEN — READY** (mode CHECKBOX, entry PASS)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `CHECKBOX` | ✅ PASS | 2/2 PROVEN | none | ✅ EVIDENCE-CLOSED-AWAITING-SIGNOFF |

> Card r18 PWRGOOD-only (`3be11166…`) matches parent plan r17 (`f79c50ae…`) at `plan_revision: 18`. Entry PASS on new kept log `04c129e6…` (byte-identical to run `20260805_100351`). Both checkers PROVEN; prior FIND-001 closed by integer `expect_eq(positive_deltas, 1)`. Standing-order signoff applied.

## DELTA (re-audit vs prior grade)

| Item | Prior (card r18 `3be11166…`, log `f9649f92…`) | This audit (card r18 `3be11166…`, log `04c129e6…`) |
|---|---|---|
| Verdict | 2/2 PROVEN — NOT READY | 2/2 PROVEN — READY |
| CHK-SMC-PWRGOOD-DTP-POR-S2 | ✅ PROVEN | ✅ PROVEN — leave-TLR under powergood+TRST; cells satisfied |
| CHK-NONVAC | ✅ PROVEN + FIND-001 Minor | ✅ PROVEN — `expect_eq(positive_deltas, 1)` logs integer `1` |
| FIND-001 `[NO-DUMMY-DEAD-CODE]` | open Minor — `expect_eq(bool, True)` | closed — scoreboard L34 `positive step-delta count: 1` |
| Kept log | `f9649f92…` (run `095817`) | `04c129e6…` (run `100351`) |
| Waivers carried | none signed | none |

## Your to-do — none

**SIGNOFF RECORDED** — see ## Human signoff below.

**Then:** continue remaining SMU_ALL Skill 1.5/2 work, or `/dv_peer_audit` when the milestone set is ready for Skill 3.

## All checkers

| Checker | Grade | Proof class | Covers |
|---|---|---|---|
| CHK-SMC-PWRGOOD-DTP-POR-S2 | ✅ PROVEN | LIVE | SMC-PWRGOOD-DTP-POR.S2 |
| CHK-NONVAC | ✅ PROVEN | INTEGRITY | — |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean |
| F2 can't-fail checker | ✅ clean |
| E1 skip-to-pass | ✅ clean |
| E2 empty phase | ✅ clean |
| S1 silent fail | ✅ clean |
| O1 checker disabled | ✅ clean |
| Phase-S obligations — L1 | ✅ clean |
| Phase-S obligations — L2 (needs the card) | ✅ clean |

## Evidence appendix

<details>
<summary>Kept log + build identity</summary>

- Log: `hw/sys/smu/dv/build/kept_logs/smu_axi_crossbar_error_handling_test.seed1.log` sha256 `04c129e6eb1d47cd507efcdc937e7ae29433c0c858325b423511ed1ad9e24f1a` (byte-identical to run `20260805_100351__verilator__smu_axi_crossbar_error_handling_test` sim log)
- Seed: 1 · simulator: verilator 5.050 · target: `default` · model_fingerprint: `48f5d6b1d3f2`
- Card: SMU_ALL_008 r18 `3be11166c37e13bc35de8dddbea105adf69f1f819525f7bb5bdcd292ffdf521d` (recomputed match; current+approved)
- Parent plan record: r17 `f79c50aeaa5d0c5aa0afb34c305d2e5763cc2a5af8ba95d7df377cc53c2f8859` · `plan_revision: 18` · `parent_approved: true` (recomputed match; current+approved)
- Feature list: `SMC-PWRGOOD-DTP-POR.S2` cells `[powergood=1, trst=1, tap=exit_tlr]`; `coverage_artifact: null`
- Cocotb summary L50: `TESTS=1 PASS=1 FAIL=0 SKIP=0`; scoreboard 2 checks / zero errors; `prove_mapped_features` executed; no unexplained ERROR/FATAL/Traceback
- Enrolled: `hw/sys/smu/dv/testlists/fabric.toml` + `all.toml` → `smu_axi_crossbar_error_handling_test`
- Bring-up trailer `+skip_fuse_sense` / ROM backdoor present; not on the PTAP leave-TLR proof path
- OWNS r18: only `SMC-PWRGOOD-DTP-POR.S2` + `CHK-NONVAC` (FAB-IN / DECODE intentionally OOM — not demanded)

</details>

<details>
<summary>Token / step cites (kept log `04c129e6…`)</summary>

| Checker | Line | What the log shows | Impl |
|---|---|---|---|
| (setup) | 22–23 | `DUT_TAG=BARE` + `STEP S1` leave-TLR under power-good | seq `:81` |
| coverage | 24 | `COVERAGE … cells: powergood=1 trst=1 tap=exit_tlr` | seq `:87` |
| CHK-SMC-PWRGOOD-DTP-POR-S2 | 25–28 | PASS with `pre_tlr=0x1 post_state=0x2 expect_rti=0x2`; scoreboard leave-TLR state `2` | seq `:140` |
| TIMEOUT-PATH | 29–31 | `s1_enter_tlr` / `s1_exit_tlr_rti` bound=2000 ok last-state | seq `:163` |
| CHK-NONVAC | 32–33 | Ordered fence `S1<PASS` + `reset_released=1` + `positive_deltas=1` + `delta_ns=37840938` | seq `:204` |
| (hygiene) | 34 | `CHECK PASS CHK-NONVAC positive step-delta count: 1` ← FIND-001 closed | seq `:210` |

</details>

<details>
<summary>Layer 1 notes (F/E/S + Phase-S clean)</summary>

- Ordered fence SETUP (powergood+TRST) → ACTION (leave TLR via TMS) → RESPONSE (`jtag_ptap_state` RTI) → EFFECT (not TLR) → NONVAC: non-empty, AssertionError-gated.
- S1 FAIL-ON: `powergood_i!=1`, `jtag_trst!=1`, still in Test-Logic-Reset, X/Z sample, bounded-wait expiry with last TAP state.
- Scoreboard compares integer TAP state to `RUN_TEST_IDLE` (not True/True) for the feature checker.
- NONVAC scoreboard compares integer `positive_deltas` to `1` (not boolean True/True); prior FIND-001 hygiene closed.
- No Force/deposit on proof path; TRST release is TB pin drive; passive `jtag_ptap_state` / `powergood_i` observation.
- Timeout paths inventory with `bound=` + `ok last=` / `EXPIRED last=`; expiry raises.
- No merged-evidence collision: feature token independent of NONVAC integrity token.
- FAB-IN / DECODE tokens absent by r18 contract — not demanded.

</details>

<details>
<summary>Prior finding closure verification</summary>

- FIND-001: sequence now builds `positive_deltas = 1 if delta_ns > 0 else 0`, fails via AssertionError when not 1, then `sb.expect_eq(..., positive_deltas, 1)` (seq `:198–215`). Kept log L33/L34 show `positive_deltas=1` and scoreboard observed `1` — matches prescribed closure (same class as SMU_ALL_002 NONVAC).

</details>

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |

## Human signoff

- **signed_off_by:** minshaoho
- **signed_off_at:** 2026-08-05T18:05:53+08:00
- **decision:** accept evidence-closed grade (Done)
- **note:** Standing order — all checkers PROVEN and evidence-closed; auto signoff for SMU_ALL_008.
