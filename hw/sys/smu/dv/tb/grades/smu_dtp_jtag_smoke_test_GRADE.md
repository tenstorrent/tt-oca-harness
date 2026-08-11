---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smu_dtp_jtag_smoke_test
ip: SMU_ALL
anchor: smu_dtp_jtag_smoke_test
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
card_sha256: 31eb2a2142dc00ea1d40443b557748e6a5842f0bad643796a761f45bedf4f3ea
card_revision: 18
card_path: hw/sys/smu/dv/tb/SMU_ALL_VPLAN_DETAIL.md
testcase_plan:
  path: hw/sys/smu/dv/tb/SMU_ALL_TESTCASE_PLAN.md
  plan_revision: 18
  testcase_revision: 2
  testcase_record_sha256: 98d20efe3a8ebf7aff148b85ed901c7cc1f4056b280fa624fde0ed072ad46392
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
- path: hw/sys/smu/dv/build/kept_logs/smu_dtp_jtag_smoke_test.seed1.log
  sha256: 0a563d0cdce7af80d38a313fc7c935355e0506fa26c7048377bc879a6fa23e0f
test_author:
  human_id: minshaoho
  run_id: dv_test_impl-SMU_ALL_005-20260804T071244
  model:
    provider: cursor
    family: grok
    version: '4.5'
auditor:
  human_id: minshaoho
  run_id: dv_test_audit-SMU_ALL_005-r18-55a4af92444b
  model:
    provider: cursor
    family: grok
    version: '4.5'
exceptions: []
checkers:
- id: CHK-DTP-JTAG-PTAP-S1
  checks_steps:
  - S2
  proves:
  - DTP-JTAG-PTAP
  covers:
  - DTP-JTAG-PTAP.S1
  proof_class: LIVE
  expect_source: pinned SPEC citations on DTP-JTAG-PTAP.S1 in SMU_ALL_SPEC_FEATURE_LIST.md
  grade: PROVEN
  evidence:
  - token: 'CHK-DTP-JTAG-PTAP-S1: PASS (idcode=0x00000001 expect=0x00000001 marker=1 mfr=0x0 part=0x0 ver=0x0 inst_decoded=0x2 cell=inst=IDCODE)'
    log_sha256: 0a563d0cdce7af80d38a313fc7c935355e0506fa26c7048377bc879a6fa23e0f
    line: 32
    seed: 1
    implementation_path: hw/sys/smu/dv/cocotb/seq_lib/smu_dtp_jtag_smoke_test_seq.py:232
  lifecycle_results: null
  coverage_results:
  - key: DTP-JTAG-PTAP.S1
    method: DIRECTED
    required_cells:
    - inst=IDCODE
    achieved_cells:
    - inst=IDCODE
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds:
    - 1
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smu/dv/build/kept_logs/smu_dtp_jtag_smoke_test.seed1.log#0a563d0cdce7af80d38a313fc7c935355e0506fa26c7048377bc879a6fa23e0f
    satisfied: true
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-DTP-JTAG-PTAP-S2
  checks_steps:
  - S3
  proves:
  - DTP-JTAG-PTAP
  covers:
  - DTP-JTAG-PTAP.S2
  proof_class: LIVE
  expect_source: pinned SPEC citations on DTP-JTAG-PTAP.S2 in SMU_ALL_SPEC_FEATURE_LIST.md
  grade: PROVEN
  evidence:
  - token: 'CHK-DTP-JTAG-PTAP-S2: PASS (tdi=0xa5a5a5a5 tdo=0x4b4b4b4a expect=0x4b4b4b4a cap=0x8 sh=0x10 upd=0x100 cell=inst=BYPASS)'
    log_sha256: 0a563d0cdce7af80d38a313fc7c935355e0506fa26c7048377bc879a6fa23e0f
    line: 37
    seed: 1
    implementation_path: hw/sys/smu/dv/cocotb/seq_lib/smu_dtp_jtag_smoke_test_seq.py:305
  lifecycle_results: null
  coverage_results:
  - key: DTP-JTAG-PTAP.S2
    method: DIRECTED
    required_cells:
    - inst=BYPASS
    achieved_cells:
    - inst=BYPASS
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds:
    - 1
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smu/dv/build/kept_logs/smu_dtp_jtag_smoke_test.seed1.log#0a563d0cdce7af80d38a313fc7c935355e0506fa26c7048377bc879a6fa23e0f
    satisfied: true
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-DTP-JTAG-PTAP-S3
  checks_steps:
  - S4
  proves:
  - DTP-JTAG-PTAP
  covers:
  - DTP-JTAG-PTAP.S3
  proof_class: LIVE
  expect_source: pinned SPEC citations on DTP-JTAG-PTAP.S3 in SMU_ALL_SPEC_FEATURE_LIST.md
  grade: PROVEN
  evidence:
  - token: 'CHK-DTP-JTAG-PTAP-S3: PASS (pre_trst=0x10 tlr_trst=0x1 pre_por=0x10 tlr_por=0x1 cells=rst=TRST,rst=POR,state=Test-Logic-Reset)'
    log_sha256: 0a563d0cdce7af80d38a313fc7c935355e0506fa26c7048377bc879a6fa23e0f
    line: 42
    seed: 1
    implementation_path: hw/sys/smu/dv/cocotb/seq_lib/smu_dtp_jtag_smoke_test_seq.py:379
  lifecycle_results: null
  coverage_results:
  - key: DTP-JTAG-PTAP.S3
    method: DIRECTED
    required_cells:
    - rst=TRST
    - rst=POR
    - state=Test-Logic-Reset
    achieved_cells:
    - rst=TRST
    - rst=POR
    - state=Test-Logic-Reset
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds:
    - 1
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smu/dv/build/kept_logs/smu_dtp_jtag_smoke_test.seed1.log#0a563d0cdce7af80d38a313fc7c935355e0506fa26c7048377bc879a6fa23e0f
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
  proves: []
  covers: []
  proof_class: INTEGRITY
  expect_source: approved card ordering contract
  grade: PROVEN
  evidence:
  - token: 'CHK-NONVAC: Ordered fence S1<S2<S3<S4<S5<PASS all hold'
    log_sha256: 0a563d0cdce7af80d38a313fc7c935355e0506fa26c7048377bc879a6fa23e0f
    line: 61
    seed: 1
    implementation_path: hw/sys/smu/dv/cocotb/seq_lib/smu_dtp_jtag_smoke_test_seq.py:449
  lifecycle_results: null
  coverage_results: []
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-TIMEOUT-PATHS
  checks_steps:
  - S5
  proves: []
  covers: []
  proof_class: INTEGRITY
  expect_source: approved card timeout contract
  grade: PROVEN
  evidence:
  - token: 'CHK-TIMEOUT-PATHS: Finite bound on S5; expiry fails with last-state diagnostics (paths=9 expect=9 bound_tck=2000 bound_ref=2000)'
    log_sha256: 0a563d0cdce7af80d38a313fc7c935355e0506fa26c7048377bc879a6fa23e0f
    line: 56
    seed: 1
    implementation_path: hw/sys/smu/dv/cocotb/seq_lib/smu_dtp_jtag_smoke_test_seq.py:415
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
content_sha256: 9cdcd799eb97d0fa09af9db36593df06c3e47a5d6ddb68b62eb1660dde88c009
---

# Grade Report — smu_dtp_jtag_smoke_test (SMU_ALL_005)

**VERDICT: 5/5 PROVEN — READY** (mode CHECKBOX, entry PASS)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `CHECKBOX` | ✅ PASS | 5/5 PROVEN | none | ✅ EVIDENCE-CLOSED-AWAITING-SIGNOFF |

> Card r9 PTAP-only (`d1b60225…`) matches parent plan r2 (`98d20efe…`) at `plan_revision: 9`. Entry PASS on kept log `0a563d0c…` (byte-identical to run `20260804_073057`). All five checkers PROVEN with FL cells satisfied; prior FIND-001 closed by integer TAP-state pair scoreboard.

## DELTA (re-audit vs prior grade)

| Item | Prior (`dv_test_audit-SMU_ALL_005-r9-a91f3c6e-2b84-4d17-9e50-6c1a8f4d2e70`, card r9) | This audit (`dv_test_audit-SMU_ALL_005-r18-55a4af92444b`, card r18) |
|---|---|---|
| Verdict | 5/5 PROVEN — READY | 5/5 PROVEN — READY |
| Card hash | `d1b60225e167bf1eae0232095647a37e7077704f340f2a4b37ad864fbc56f57d` (STALE vs plan r18) | `31eb2a2142dc00ea1d40443b557748e6a5842f0bad643796a761f45bedf4f3ea` (current) |
| Plan revision | 9 | 18 |
| Checkers / OWNS | unchanged | unchanged — all 5 tokens re-verified on same kept log |
| Kept log | `0a563d0cdce7af80d38a313fc7c935355e0506fa26c7048377bc879a6fa23e0f` | `0a563d0cdce7af80d38a313fc7c935355e0506fa26c7048377bc879a6fa23e0f` (unchanged) |
| Findings | none open | none open |
| Waivers carried | none signed | none |
| Signoff | prior `2026-08-05T17:16:48+08:00` | renewed `2026-08-05T18:14:08+08:00` (standing order) |


## Your to-do — none

**SIGNOFF RECORDED** — see ## Human signoff below.

**Then:** `/dv_peer_audit` on SMU_ALL when all seven r18 grades are filed.

## All checkers

| Checker | Grade | Proof class | Covers |
|---|---|---|---|
| CHK-DTP-JTAG-PTAP-S1 | ✅ PROVEN | LIVE | DTP-JTAG-PTAP.S1 |
| CHK-DTP-JTAG-PTAP-S2 | ✅ PROVEN | LIVE | DTP-JTAG-PTAP.S2 |
| CHK-DTP-JTAG-PTAP-S3 | ✅ PROVEN | LIVE | DTP-JTAG-PTAP.S3 |
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

- Log: `hw/sys/smu/dv/build/kept_logs/smu_dtp_jtag_smoke_test.seed1.log` sha256 `0a563d0cdce7af80d38a313fc7c935355e0506fa26c7048377bc879a6fa23e0f` (byte-identical to run `20260804_073057__verilator__smu_dtp_jtag_smoke_test` sim log)
- Seed: 1 · simulator: verilator 5.050 · target: `default` · model_fingerprint: `48f5d6b1d3f2`
- Card: SMU_ALL_005 r18 `31eb2a2142dc00ea1d40443b557748e6a5842f0bad643796a761f45bedf4f3ea` (recomputed match; current+approved)
- Parent plan record: r2 `98d20efe3a8ebf7aff148b85ed901c7cc1f4056b280fa624fde0ed072ad46392` · `plan_revision: 9` · `parent_approved: true` (recomputed match; current+approved)
- Feature list: `DTP-JTAG-PTAP.S1` cells `[inst=IDCODE]`; `.S2` `[inst=BYPASS]`; `.S3` `[rst=TRST, rst=POR, state=Test-Logic-Reset]`; `coverage_artifact: null`
- IDCODE expect `0x00000001` from `DTP_DEFAULT_IDCODE`, matching pinned SMU_SPEC defaults (`IDCODE_MFR_ID/PART_NUM/SI_REV/OCH_VER=0` → IEEE marker-only IDCODE)
- Cocotb summary L81: `TESTS=1 PASS=1 FAIL=0 SKIP=0`; scoreboard 5 checks / zero errors; `prove_mapped_features` executed; no unexplained ERROR/FATAL/Traceback
- Enrolled: `hw/sys/smu/dv/testlists/dtp.toml` + `all.toml` → `smu_dtp_jtag_smoke_test`
- Bring-up trailer `+skip_fuse_sense` / ROM backdoor present; not on the PTAP JTAG proof path

</details>

<details>
<summary>Token / step cites (kept log `0a563d0c…`)</summary>

| Checker | Line | What the log shows | Impl |
|---|---|---|---|
| (setup) | 29–30 | `STEP S1` + BASELINE RTI + idcode_expect | seq `:177` |
| CHK-DTP-JTAG-PTAP-S1 | 32 | IDCODE `0x00000001` fields + `cell=inst=IDCODE` | seq `:232` |
| CHK-DTP-JTAG-PTAP-S2 | 37 | BYPASS TDI→TDO one-bit shift + `cell=inst=BYPASS` | seq `:305` |
| CHK-DTP-JTAG-PTAP-S3 | 42 | pre≠TLR; TRST+POR → TLR; cells `rst=TRST,rst=POR,state=Test-Logic-Reset` | seq `:379` |
| CHK-TIMEOUT-PATHS | 47–56 | 9 TIMEOUT-PATH lines + `paths=9 expect=9 bound_tck=2000 bound_ref=2000` | seq `:415` |
| CHK-NONVAC | 61 | `Ordered fence S1<S2<S3<S4<S5<PASS all hold` + positive-delta count 5 | seq `:449` |

</details>

<details>
<summary>Layer 1 notes (F/E/S clean)</summary>

- Ordered fence S1 SETUP → S2 IDCODE frontdoor TDO → S3 BYPASS frontdoor TDO → S4 TRST then POR pin stimulus → S5 timeout inventory → PASS: non-empty, ordered, AssertionError-gated.
- IDCODE/BYPASS sample DUT TDO via `OcahJtagTap._cycle` (not VIP model gold); expect from SPEC defaults / IEEE BYPASS shift model.
- S3 FAIL-ON: pre-TRST/pre-POR already TLR; bounded wait expiry with last TAP state; TRST must be deasserted before POR path.
- TAP state samples use `_sample` (X/Z → AssertionError). Top pins `jtag_*` / `powergood_i`; passive `jtag_ptap_state` / `jtag_ptap_inst_decoded` observation only.
- No Force/deposit on proof path; VIP `_state` bookkeeping after async reset is TB mirror sync, not DUT write.
- Timeout paths inventory exact count 9 with `bound=` + `ok last=` / `EXPIRED last=`; expiry raises.
- NONVAC compares positive wall-clock step-delta count to 5 (not decorative True/True).
- No merged-evidence collision: each feature checker has an independent token; integrity checkers do not substitute for feature proof.

</details>

<details>
<summary>Prior finding closure verification</summary>

- FIND-001 `[NO-DUMMY-DEAD-CODE]`: S3 scoreboard no longer calls `expect_eq(bool_and, True)`. Seq `:380–387` compares integer pair `(tlr_trst, tlr_por)` to `(int(TEST_LOGIC_RESET), int(TEST_LOGIC_RESET))`. Kept log L43 records `CHECK PASS … TLR: (1, 1)` (not `True`). Matches prior closure_condition; finding closed.

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
