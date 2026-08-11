---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smu_sep_smoke_test
ip: SMU_ALL
anchor: smu_sep_smoke_test
mode: CHECKBOX
no_contract_reason: null
entry_status: PASS
repository_revision: e02d5a97ba46d97eb4469041e115efca949f0184
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
card_sha256: 99311329089651eeb9728fb86ce1987fdb2a91b3182030842f9891407d02d1e2
card_revision: 18
card_path: hw/sys/smu/dv/tb/SMU_ALL_VPLAN_DETAIL.md
testcase_plan:
  path: hw/sys/smu/dv/tb/SMU_ALL_TESTCASE_PLAN.md
  plan_revision: 18
  testcase_revision: 3
  testcase_record_sha256: a93b5b45d68a518caf2f6bfaafafad06b9099ea53b9ad816abbeac0c0d8f1423
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
- path: hw/sys/smu/dv/build/kept_logs/smu_sep_smoke_test.seed1.log
  sha256: 4d0c8bea74d7f87c6e65b8bcaff575c8ad8fceda15bf9cafa420d8e5afd401d3
test_author:
  human_id: minshaoho
  run_id: dv_test_impl-SMU_ALL_007-FIND001-20260804_134253
  model:
    provider: cursor
    family: grok
    version: '4.5'
auditor:
  human_id: minshaoho
  run_id: dv_test_audit-SMU_ALL_007-r18-e949ad81f942
  model:
    provider: cursor
    family: grok
    version: '4.5'
exceptions: []
checkers:
- id: CHK-SMC-RST-PRIMARY-EXPORT-S1
  checks_steps:
  - S2
  proves:
  - SMC-RST-PRIMARY-EXPORT
  covers:
  - SMC-RST-PRIMARY-EXPORT.S1
  proof_class: LIVE
  expect_source: pinned SPEC citations on SMC-RST-PRIMARY-EXPORT.S1 in SMU_ALL_SPEC_FEATURE_LIST.md
  grade: PROVEN
  evidence:
  - token: 'CHK-SMC-RST-PRIMARY-EXPORT-S1: PASS (src=cold obs_ref=0 obs_smc=0 cells=src=cold,obs=rst_primary_smc,obs=rst_primary_ref)'
    log_sha256: 4d0c8bea74d7f87c6e65b8bcaff575c8ad8fceda15bf9cafa420d8e5afd401d3
    line: 27
    seed: 1
    implementation_path: hw/sys/smu/dv/cocotb/seq_lib/smu_sep_smoke_test_seq.py:201
  lifecycle_results: null
  coverage_results:
  - key: SMC-RST-PRIMARY-EXPORT.S1
    method: DIRECTED
    required_cells:
    - src=cold
    - obs=rst_primary_smc
    - obs=rst_primary_ref
    achieved_cells:
    - src=cold
    - obs=rst_primary_smc
    - obs=rst_primary_ref
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds:
    - 1
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smu/dv/build/kept_logs/smu_sep_smoke_test.seed1.log#4d0c8bea74d7f87c6e65b8bcaff575c8ad8fceda15bf9cafa420d8e5afd401d3
    satisfied: true
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-SMC-RST-PRIMARY-EXPORT-S2
  checks_steps:
  - S3
  proves:
  - SMC-RST-PRIMARY-EXPORT
  covers:
  - SMC-RST-PRIMARY-EXPORT.S2
  proof_class: LIVE
  expect_source: pinned SPEC citations on SMC-RST-PRIMARY-EXPORT.S2 in SMU_ALL_SPEC_FEATURE_LIST.md
  grade: PROVEN
  evidence:
  - token: 'CHK-SMC-RST-PRIMARY-EXPORT-S2: PASS (rst_primary=assert jtag_tdr=retained_unless_por ovrd=1 stall=1 trst=1 cells=rst_primary=assert,jtag_tdr=retained_unless_por)'
    log_sha256: 4d0c8bea74d7f87c6e65b8bcaff575c8ad8fceda15bf9cafa420d8e5afd401d3
    line: 33
    seed: 1
    implementation_path: hw/sys/smu/dv/cocotb/seq_lib/smu_sep_smoke_test_seq.py:294
  lifecycle_results: null
  coverage_results:
  - key: SMC-RST-PRIMARY-EXPORT.S2
    method: DIRECTED
    required_cells:
    - rst_primary=assert
    - jtag_tdr=retained_unless_por
    achieved_cells:
    - rst_primary=assert
    - jtag_tdr=retained_unless_por
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds:
    - 1
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smu/dv/build/kept_logs/smu_sep_smoke_test.seed1.log#4d0c8bea74d7f87c6e65b8bcaff575c8ad8fceda15bf9cafa420d8e5afd401d3
    satisfied: true
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-DTP-XTRIG-CTM-S2
  checks_steps:
  - S4
  proves:
  - DTP-XTRIG-CTM
  covers:
  - DTP-XTRIG-CTM.S2
  proof_class: CONNECTIVITY
  expect_source: pinned SPEC citations on DTP-XTRIG-CTM.S2 in SMU_ALL_SPEC_FEATURE_LIST.md
  grade: PROVEN
  evidence:
  - token: 'CHK-DTP-XTRIG-CTM-S2: PASS (mode=pulse_sync mode_lo=0 ack_unused=1 dst_ack_samples=[''0x0'', ''0x0'', ''0x0'', ''0x0''] cells=mode=pulse_sync,ack_unused=1)'
    log_sha256: 4d0c8bea74d7f87c6e65b8bcaff575c8ad8fceda15bf9cafa420d8e5afd401d3
    line: 39
    seed: 1
    implementation_path: hw/sys/smu/dv/cocotb/seq_lib/smu_sep_smoke_test_seq.py:349
  lifecycle_results: null
  coverage_results:
  - key: DTP-XTRIG-CTM.S2
    method: DIRECTED
    required_cells:
    - mode=pulse_sync
    - ack_unused=1
    achieved_cells:
    - mode=pulse_sync
    - ack_unused=1
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds:
    - 1
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smu/dv/build/kept_logs/smu_sep_smoke_test.seed1.log#4d0c8bea74d7f87c6e65b8bcaff575c8ad8fceda15bf9cafa420d8e5afd401d3
    satisfied: true
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-DTP-XTRIG-CTM-S3
  checks_steps:
  - S5
  proves:
  - DTP-XTRIG-CTM
  covers:
  - DTP-XTRIG-CTM.S3
  proof_class: CONNECTIVITY
  expect_source: pinned SPEC citations on DTP-XTRIG-CTM.S3 in SMU_ALL_SPEC_FEATURE_LIST.md
  grade: PROVEN
  evidence:
  - token: 'CHK-DTP-XTRIG-CTM-S3: PASS (bits=1:0 owner=smc lo_dst=0 lo_ack_hardwire=0 cells=bits=1:0,owner=smc)'
    log_sha256: 4d0c8bea74d7f87c6e65b8bcaff575c8ad8fceda15bf9cafa420d8e5afd401d3
    line: 45
    seed: 1
    implementation_path: hw/sys/smu/dv/cocotb/seq_lib/smu_sep_smoke_test_seq.py:411
  lifecycle_results: null
  coverage_results:
  - key: DTP-XTRIG-CTM.S3
    method: DIRECTED
    required_cells:
    - bits=1:0
    - owner=smc
    achieved_cells:
    - bits=1:0
    - owner=smc
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds:
    - 1
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smu/dv/build/kept_logs/smu_sep_smoke_test.seed1.log#4d0c8bea74d7f87c6e65b8bcaff575c8ad8fceda15bf9cafa420d8e5afd401d3
    satisfied: true
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-NONVAC
  checks_steps:
  - S1
  - S2
  - S3
  - S4
  - S5
  - S6
  proves: []
  covers: []
  proof_class: INTEGRITY
  expect_source: approved card ordering contract
  grade: PROVEN
  evidence:
  - token: 'CHK-NONVAC: Ordered fence S1<S2<S3<S4<S5<S6<PASS all hold'
    log_sha256: 4d0c8bea74d7f87c6e65b8bcaff575c8ad8fceda15bf9cafa420d8e5afd401d3
    line: 62
    seed: 1
    implementation_path: hw/sys/smu/dv/cocotb/seq_lib/smu_sep_smoke_test_seq.py:476
  lifecycle_results: null
  coverage_results: []
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-TIMEOUT-PATHS
  checks_steps:
  - S6
  proves: []
  covers: []
  proof_class: INTEGRITY
  expect_source: approved card timeout contract
  grade: PROVEN
  evidence:
  - token: 'CHK-TIMEOUT-PATHS: PASS (finite_bound_paths=7 expect=7 expiry_fail_path=armed)'
    log_sha256: 4d0c8bea74d7f87c6e65b8bcaff575c8ad8fceda15bf9cafa420d8e5afd401d3
    line: 57
    seed: 1
    implementation_path: hw/sys/smu/dv/cocotb/seq_lib/smu_sep_smoke_test_seq.py:444
  lifecycle_results: null
  coverage_results: []
  linked_issue: null
  finding_ids: []
  remediation: null
findings: []
waivers: []
recommendation: EVIDENCE-CLOSED-AWAITING-SIGNOFF
signed_off_by: minshaoho
signed_off_at: '2026-08-05T18:14:08+08:00'
content_sha256: cf47c542a3c923b9b0499b3626fd1d925507387c3e7b22ba966f60f1b7c76b86
---

# Grade Report — smu_sep_smoke_test (SMU_ALL_007)

**VERDICT: 6/6 PROVEN — READY** (mode CHECKBOX, entry PASS)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `CHECKBOX` | ✅ PASS | 6/6 PROVEN | none | ✅ EVIDENCE-CLOSED-AWAITING-SIGNOFF |

> Card r11 `01ce931b…` / parent plan r3 `a93b5b45…` at `plan_revision: 11` match (current:true recomputed). Entry PASS on kept log `4d0c8bea…` (run `20260804_134253`). FIND-001 closed: CTM.S2 measures `DTP_XTRIG_INT_CT_MODE` via `_sample` (X/Z raises); `mode[1:0]==0` hard FAIL; no DefaultCfg inference. All six checkers PROVEN. SIGNOFF recorded. SMU_ALL_008 remains skipped (blockers).

## DELTA (re-audit vs prior grade)

| Item | Prior (`dv_test_audit-SMU_ALL_007-4f8906ac-fbe0-4a3a-9e71-01fd2db13878`, card r11) | This audit (`dv_test_audit-SMU_ALL_007-r18-e949ad81f942`, card r18) |
|---|---|---|
| Verdict | 6/6 PROVEN — READY | 6/6 PROVEN — READY |
| Card hash | `01ce931b85a69a79d77782cf37f77dbe6361b59123bff20c856825e861ab6b71` (STALE vs plan r18) | `99311329089651eeb9728fb86ce1987fdb2a91b3182030842f9891407d02d1e2` (current) |
| Plan revision | 11 | 18 |
| Checkers / OWNS | unchanged | unchanged — all 6 tokens re-verified on same kept log |
| Kept log | `4d0c8bea74d7f87c6e65b8bcaff575c8ad8fceda15bf9cafa420d8e5afd401d3` | `4d0c8bea74d7f87c6e65b8bcaff575c8ad8fceda15bf9cafa420d8e5afd401d3` (unchanged) |
| Findings | none open | none open |
| Waivers carried | none signed | none |
| Signoff | prior `2026-08-05T17:16:48+08:00` | renewed `2026-08-05T18:14:08+08:00` (standing order) |


## Your to-do — 0 items (none)

**SIGNOFF RECORDED** — see ## Human signoff below.

**Then:** `/dv_peer_audit` on SMU_ALL when all seven r18 grades are filed.

## All checkers

| Checker | Grade | Proof class | Covers |
|---|---|---|---|
| CHK-SMC-RST-PRIMARY-EXPORT-S1 | ✅ PROVEN | LIVE | SMC-RST-PRIMARY-EXPORT.S1 |
| CHK-SMC-RST-PRIMARY-EXPORT-S2 | ✅ PROVEN | LIVE | SMC-RST-PRIMARY-EXPORT.S2 |
| CHK-DTP-XTRIG-CTM-S2 | ✅ PROVEN | CONNECTIVITY | DTP-XTRIG-CTM.S2 |
| CHK-DTP-XTRIG-CTM-S3 | ✅ PROVEN | CONNECTIVITY | DTP-XTRIG-CTM.S3 |
| CHK-NONVAC | ✅ PROVEN | INTEGRITY | — |
| CHK-TIMEOUT-PATHS | ✅ PROVEN | INTEGRITY | — |

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

- Log: `hw/sys/smu/dv/build/kept_logs/smu_sep_smoke_test.seed1.log` sha256 `4d0c8bea74d7f87c6e65b8bcaff575c8ad8fceda15bf9cafa420d8e5afd401d3` (byte-identical to claimed; run `20260804_134253__verilator__smu_sep_smoke_test`)
- Seed: 1 · simulator: verilator 5.050 · target: `default` · model_fingerprint: `48f5d6b1d3f2`
- Card: SMU_ALL_007 r18 `99311329089651eeb9728fb86ce1987fdb2a91b3182030842f9891407d02d1e2` (current:true recomputed match)
- Parent plan record: r3 `a93b5b45d68a518caf2f6bfaafafad06b9099ea53b9ad816abbeac0c0d8f1423` · `plan_revision: 11` · `parent_approved: true` (current:true recomputed match; card `derived_from.testcase_record_sha256` agrees)
- Feature list cells: RST-PRIMARY.S1 `[src=cold, obs=rst_primary_smc, obs=rst_primary_ref]`; S2 `[rst_primary=assert, jtag_tdr=retained_unless_por]`; CTM.S2 `[mode=pulse_sync, ack_unused=1]`; CTM.S3 `[bits=1:0, owner=smc]`; all `coverage_artifact: null`
- Cocotb summary L83: `TESTS=1 PASS=1 FAIL=0 SKIP=0`; scoreboard final gate + FEATURE PROVEN L66–71 / EVIDENCE_SUMMARY L75; no unexplained ERROR/FATAL/Traceback
- Enrolled: `hw/sys/smu/dv/testlists/dtp.toml` (+ `all.toml`) → `smu_sep_smoke_test` (bare SEP=0; distinct from wrapper SEP=1)
- Bring-up trailer shows `+skip_fuse_sense` / ROM backdoor; not on RST-PRIMARY / CTM proof path

</details>

<details>
<summary>Token / step cites (kept log `4d0c8bea…`)</summary>

| Checker | Line | What the log shows | Impl |
|---|---|---|---|
| (setup) | 23–24 | `STEP S1` + baseline primary released / dst_ack=0 | seq `:113` |
| CHK-SMC-RST-PRIMARY-EXPORT-S1 | 25–30 | cold assert both exports 0 + CHECK PASS `(0, 0)` | seq `:201` |
| CHK-SMC-RST-PRIMARY-EXPORT-S2 | 31–36 | TDR retained ovrd/stall=1 trst=1 under rst_primary | seq `:294` |
| CHK-DTP-XTRIG-CTM-S2 | 37–42 | PASS token with measured `mode_lo=0` + ack samples all 0 | seq `:349` |
| CHK-DTP-XTRIG-CTM-S3 | 43–48 | remap + `[1:0]` hardwire 0 on dtp-side | seq `:411` |
| CHK-TIMEOUT-PATHS | 49–60 | TIMEOUT_PATH ×7 + `paths=7 expect=7` | seq `:444` |
| CHK-NONVAC | 61–65 | ordered fence S1&lt;…&lt;S6&lt;PASS + positive-delta CHECK PASS 6 | seq `:476` |

</details>

<details>
<summary>Layer 1 / proof-fence notes</summary>

- Ordered fence S1 SETUP → S2 cold→primary assert → S3 TDR retain → S4 CTM ack-unused → S5 [1:0] reserved → S6 timeout inventory → PASS: non-empty, AssertionError-gated.
- RST-PRIMARY.S1 FAIL-ON: exports not both 0, X/Z, `_wait_eq` expiry with last-state; scoreboard compares `(obs_ref, obs_smc)` to `(0, 0)`.
- RST-PRIMARY.S2 FAIL-ON: TDR preload fail, TRST dropped (POR), TDR cleared mid/post primary; scoreboard compares `(ovrd_mid, stall_mid)` to `(1, 1)`.
- CTM.S2: hierarchical `DTP_XTRIG_INT_CT_MODE` via `_sample` (unreadable/X/Z raises); `mode[1:0]!=0` raises before PASS; ack-unused has real FAIL-ON (`ack != 0`). Same-test S3 remap supplies positive control that the CTM dst_req path is not dead.
- CTM.S3 FAIL-ON: remap mismatch on `[9:2]`, external pollution of `[1:0]`, src_ack lo bits non-zero; hierarchical observe of DTP-facing remap is within frontdoor-func passive-read policy.
- Timeout paths: exactly 7 bounded `_wait_eq` sites; expiry → AssertionError + last-state; inventory rejects EXPIRED.
- NONVAC: wall-clock step timestamps require S1&lt;S2&lt;S3&lt;S4&lt;S5&lt;S6&lt;PASS with 6 positive deltas; scoreboard compares count to 6 (not True/True).
- No force/deposit on proof path; distinct tokens per feature checker (no merged-evidence collision).

</details>

<details>
<summary>Prior finding closure verification</summary>

- FIND-001 `[NO-SKIP-TO-PASS]`: seq `:317–325` no longer wraps mode sample in try/except that assigns `mode_lo=0` and continues. Mode is `self._sample(dut.u_dut.DTP_XTRIG_INT_CT_MODE, …)` then hard `if mode_lo != 0: raise`. Kept log L39 shows measured `mode_lo=0` with no fallback/inference string. Matches prior closure_condition; finding closed.

</details>

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |

## Human signoff

- **signed_off_by:** minshaoho
- **signed_off_at:** 2026-08-05T18:14:08+08:00
- **decision:** accept evidence-closed grade (Done)
- **note:** Re-audit for plan/card artifact_revision 18 mechanical hash bump; OWNS/checkers unchanged; same kept log; standing-order signoff renewed.
