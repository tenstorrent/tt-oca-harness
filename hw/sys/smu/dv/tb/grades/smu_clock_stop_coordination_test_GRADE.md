---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smu_clock_stop_coordination_test
ip: SMU_ALL
anchor: smu_clock_stop_coordination_test
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
card_sha256: fef93d5f1ce5e0a024cbb8287d383a57720f1c07b91e8d6c99d3e95b33320a67
card_revision: 18
card_path: hw/sys/smu/dv/tb/SMU_ALL_VPLAN_DETAIL.md
testcase_plan:
  path: hw/sys/smu/dv/tb/SMU_ALL_TESTCASE_PLAN.md
  plan_revision: 18
  testcase_revision: 2
  testcase_record_sha256: 5e9e020a1de9b5206dd53b9568433a482086201ebdae23bb4d82ab6d4c97d110
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
- path: hw/sys/smu/dv/build/kept_logs/smu_clock_stop_coordination_test.seed1.log
  sha256: 727e97ce3ea6a97592887e2c5f7a222dba3fa221384e456b4b327ff9956fba60
test_author:
  human_id: minshaoho
  run_id: dv_test_impl-SMU_ALL_006-20260804T090752
  model:
    provider: cursor
    family: grok
    version: '4.5'
auditor:
  human_id: minshaoho
  run_id: dv_test_audit-SMU_ALL_006-r18-c727ddb6cf5d
  model:
    provider: cursor
    family: grok
    version: '4.5'
exceptions: []
checkers:
- id: CHK-DTP-BOOT-STALL-S1
  checks_steps:
  - S2
  proves:
  - DTP-BOOT-STALL
  covers:
  - DTP-BOOT-STALL.S1
  proof_class: LIVE
  expect_source: pinned SPEC citations on DTP-BOOT-STALL.S1 in SMU_ALL_SPEC_FEATURE_LIST.md
  grade: PROVEN
  evidence:
  - token: 'CHK-DTP-BOOT-STALL-S1: PASS (ovrd=1 stall=1 boot=held fuse_reset=0 cells=ovrd=1,stall=1,boot=held)'
    log_sha256: 727e97ce3ea6a97592887e2c5f7a222dba3fa221384e456b4b327ff9956fba60
    line: 31
    seed: 1
    implementation_path: hw/sys/smu/dv/cocotb/seq_lib/smu_clock_stop_coordination_test_seq.py:278
  lifecycle_results:
    set:
      token: 'LIFECYCLE CHK-DTP-BOOT-STALL-S1 set: assert observation DEBUG_CONTROL=0x3 ovrd=1 stall=1'
      line: 27
    observed:
      token: 'LIFECYCLE CHK-DTP-BOOT-STALL-S1 observed: consumer samples boot=held fuse_reset=0 ovrd=1 stall=1'
      line: 28
    cleared:
      token: 'LIFECYCLE CHK-DTP-BOOT-STALL-S1 cleared: clear/ack cold-reset exit rst_cold_ni=1 while stall holds'
      line: 29
    checked_cleared:
      token: 'LIFECYCLE CHK-DTP-BOOT-STALL-S1 checked_cleared: readback held fuse_reset=0 after cold-reset clear'
      line: 30
    complete: true
  coverage_results:
  - key: DTP-BOOT-STALL.S1
    method: DIRECTED
    required_cells:
    - ovrd=1
    - stall=1
    - boot=held
    achieved_cells:
    - ovrd=1
    - stall=1
    - boot=held
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds:
    - 1
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smu/dv/build/kept_logs/smu_clock_stop_coordination_test.seed1.log#727e97ce3ea6a97592887e2c5f7a222dba3fa221384e456b4b327ff9956fba60
    satisfied: true
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-DTP-BOOT-STALL-S2
  checks_steps:
  - S3
  proves:
  - DTP-BOOT-STALL
  covers:
  - DTP-BOOT-STALL.S2
  proof_class: LIVE
  expect_source: pinned SPEC citations on DTP-BOOT-STALL.S2 in SMU_ALL_SPEC_FEATURE_LIST.md
  grade: PROVEN
  evidence:
  - token: 'CHK-DTP-BOOT-STALL-S2: PASS (stall=0 boot=progresses fuse_reset=1 cells=stall=0,boot=progresses)'
    log_sha256: 727e97ce3ea6a97592887e2c5f7a222dba3fa221384e456b4b327ff9956fba60
    line: 41
    seed: 1
    implementation_path: hw/sys/smu/dv/cocotb/seq_lib/smu_clock_stop_coordination_test_seq.py:348
  lifecycle_results:
    set:
      token: 'LIFECYCLE CHK-DTP-BOOT-STALL-S2 set: assert observation DEBUG_CONTROL=0 (clear stall/ovrd)'
      line: 37
    observed:
      token: 'LIFECYCLE CHK-DTP-BOOT-STALL-S2 observed: consumer samples boot=progresses fuse_reset=1'
      line: 38
    cleared:
      token: 'LIFECYCLE CHK-DTP-BOOT-STALL-S2 cleared: clear/ack stall outputs ovrd=0 stall=0'
      line: 39
    checked_cleared:
      token: 'LIFECYCLE CHK-DTP-BOOT-STALL-S2 checked_cleared: readback cleared stall; fuse_reset=1'
      line: 40
    complete: true
  coverage_results:
  - key: DTP-BOOT-STALL.S2
    method: DIRECTED
    required_cells:
    - stall=0
    - boot=progresses
    achieved_cells:
    - stall=0
    - boot=progresses
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds:
    - 1
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smu/dv/build/kept_logs/smu_clock_stop_coordination_test.seed1.log#727e97ce3ea6a97592887e2c5f7a222dba3fa221384e456b4b327ff9956fba60
    satisfied: true
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-DTP-IC-RESET-S1
  checks_steps:
  - S4
  proves:
  - DTP-IC-RESET
  covers:
  - DTP-IC-RESET.S1
  proof_class: LIVE
  expect_source: pinned SPEC citations on DTP-IC-RESET.S1 in SMU_ALL_SPEC_FEATURE_LIST.md
  grade: PROVEN
  evidence:
  - token: 'CHK-DTP-IC-RESET-S1: PASS (target=smc ovrd=1 ctrl_n=0 cells=target=smc,ovrd=1)'
    log_sha256: 727e97ce3ea6a97592887e2c5f7a222dba3fa221384e456b4b327ff9956fba60
    line: 47
    seed: 1
    implementation_path: hw/sys/smu/dv/cocotb/seq_lib/smu_clock_stop_coordination_test_seq.py:386
  lifecycle_results: null
  coverage_results:
  - key: DTP-IC-RESET.S1
    method: DIRECTED
    required_cells:
    - target=smc
    - ovrd=1
    achieved_cells:
    - target=smc
    - ovrd=1
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds:
    - 1
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smu/dv/build/kept_logs/smu_clock_stop_coordination_test.seed1.log#727e97ce3ea6a97592887e2c5f7a222dba3fa221384e456b4b327ff9956fba60
    satisfied: true
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-DTP-IC-RESET-S3
  checks_steps:
  - S5
  proves:
  - DTP-IC-RESET
  covers:
  - DTP-IC-RESET.S3
  proof_class: LIVE
  expect_source: pinned SPEC citations on DTP-IC-RESET.S3 in SMU_ALL_SPEC_FEATURE_LIST.md
  grade: PROVEN
  evidence:
  - token: 'CHK-DTP-IC-RESET-S3: PASS (exit=clear_ovrd clr=0 exit=trst_por trst=0 cells=exit=clear_ovrd,exit=trst_por)'
    log_sha256: 727e97ce3ea6a97592887e2c5f7a222dba3fa221384e456b4b327ff9956fba60
    line: 55
    seed: 1
    implementation_path: hw/sys/smu/dv/cocotb/seq_lib/smu_clock_stop_coordination_test_seq.py:448
  lifecycle_results: null
  coverage_results:
  - key: DTP-IC-RESET.S3
    method: DIRECTED
    required_cells:
    - exit=trst_por
    - exit=clear_ovrd
    achieved_cells:
    - exit=clear_ovrd
    - exit=trst_por
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds:
    - 1
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smu/dv/build/kept_logs/smu_clock_stop_coordination_test.seed1.log#727e97ce3ea6a97592887e2c5f7a222dba3fa221384e456b4b327ff9956fba60
    satisfied: true
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-DTP-CLKSTOP-AGG-S1
  checks_steps:
  - S6
  proves:
  - DTP-CLKSTOP-AGG
  covers:
  - DTP-CLKSTOP-AGG.S1
  proof_class: LIVE
  expect_source: pinned SPEC citations on DTP-CLKSTOP-AGG.S1 in SMU_ALL_SPEC_FEATURE_LIST.md
  grade: PROVEN
  evidence:
  - token: 'CHK-DTP-CLKSTOP-AGG-S1: PASS (src=jtag stop_clks=1 then cleared cells=src=jtag,stop_clks=1)'
    log_sha256: 727e97ce3ea6a97592887e2c5f7a222dba3fa221384e456b4b327ff9956fba60
    line: 65
    seed: 1
    implementation_path: hw/sys/smu/dv/cocotb/seq_lib/smu_clock_stop_coordination_test_seq.py:518
  lifecycle_results:
    set:
      token: 'LIFECYCLE CHK-DTP-CLKSTOP-AGG-S1 set: assert observation DEBUG_CONTROL jtag_clock_stop val=0x8 xtrig=0'
      line: 61
    observed:
      token: 'LIFECYCLE CHK-DTP-CLKSTOP-AGG-S1 observed: consumer samples stop_clks=1 src=jtag xtrig=0'
      line: 62
    cleared:
      token: 'LIFECYCLE CHK-DTP-CLKSTOP-AGG-S1 cleared: clear/ack jtag_clock_stop; stop_clks=0'
      line: 63
    checked_cleared:
      token: 'LIFECYCLE CHK-DTP-CLKSTOP-AGG-S1 checked_cleared: readback cleared stop_clks=0'
      line: 64
    complete: true
  coverage_results:
  - key: DTP-CLKSTOP-AGG.S1
    method: DIRECTED
    required_cells:
    - src=jtag
    - stop_clks=1
    achieved_cells:
    - src=jtag
    - stop_clks=1
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds:
    - 1
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smu/dv/build/kept_logs/smu_clock_stop_coordination_test.seed1.log#727e97ce3ea6a97592887e2c5f7a222dba3fa221384e456b4b327ff9956fba60
    satisfied: true
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-DTP-CLKSTOP-AGG-S2
  checks_steps:
  - S7
  proves:
  - DTP-CLKSTOP-AGG
  covers:
  - DTP-CLKSTOP-AGG.S2
  proof_class: LIVE
  expect_source: pinned SPEC citations on DTP-CLKSTOP-AGG.S2 in SMU_ALL_SPEC_FEATURE_LIST.md
  grade: PROVEN
  evidence:
  - token: 'CHK-DTP-CLKSTOP-AGG-S2: PASS (src=cla stop_clks=1 cla_status=1 cells=src=cla,stop_clks=1,cla_status=1)'
    log_sha256: 727e97ce3ea6a97592887e2c5f7a222dba3fa221384e456b4b327ff9956fba60
    line: 75
    seed: 1
    implementation_path: hw/sys/smu/dv/cocotb/seq_lib/smu_clock_stop_coordination_test_seq.py:604
  lifecycle_results:
    set:
      token: 'LIFECYCLE CHK-DTP-CLKSTOP-AGG-S2 set: assert observation TB xtrig_clk_stop_req[0]=1 jtag_clock_stop=0'
      line: 71
    observed:
      token: 'LIFECYCLE CHK-DTP-CLKSTOP-AGG-S2 observed: consumer samples stop_clks=1 cla_status=1 jtag_stop=0'
      line: 72
    cleared:
      token: 'LIFECYCLE CHK-DTP-CLKSTOP-AGG-S2 cleared: clear/ack xtrig; stop_clks=0'
      line: 73
    checked_cleared:
      token: 'LIFECYCLE CHK-DTP-CLKSTOP-AGG-S2 checked_cleared: readback cleared stop=0 cla_status=0'
      line: 74
    complete: true
  coverage_results:
  - key: DTP-CLKSTOP-AGG.S2
    method: DIRECTED
    required_cells:
    - src=cla
    - stop_clks=1
    - cla_status=1
    achieved_cells:
    - src=cla
    - stop_clks=1
    - cla_status=1
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds:
    - 1
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smu/dv/build/kept_logs/smu_clock_stop_coordination_test.seed1.log#727e97ce3ea6a97592887e2c5f7a222dba3fa221384e456b4b327ff9956fba60
    satisfied: true
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-DTP-CLKSTOP-AGG-S3
  checks_steps:
  - S8
  proves:
  - DTP-CLKSTOP-AGG
  covers:
  - DTP-CLKSTOP-AGG.S3
  proof_class: CONNECTIVITY
  expect_source: pinned SPEC citations on DTP-CLKSTOP-AGG.S3 in SMU_ALL_SPEC_FEATURE_LIST.md
  grade: PROVEN
  evidence:
  - token: 'CHK-DTP-CLKSTOP-AGG-S3: PASS (port0=smc_reserved smc_cla=handshake dtp0=0 smc_fb=0 DTP[8:1]=0x1 cells=port0=smc_reserved,smc_cla=handshake)'
    log_sha256: 727e97ce3ea6a97592887e2c5f7a222dba3fa221384e456b4b327ff9956fba60
    line: 85
    seed: 1
    implementation_path: hw/sys/smu/dv/cocotb/seq_lib/smu_clock_stop_coordination_test_seq.py:714
  lifecycle_results:
    set:
      token: 'LIFECYCLE CHK-DTP-CLKSTOP-AGG-S3 set: assert observation cla_clock_stop_en=1 val=0x4'
      line: 81
    observed:
      token: 'LIFECYCLE CHK-DTP-CLKSTOP-AGG-S3 observed: consumer samples port0=smc_reserved dtp0=0 smc_fb=0 DTP[8:1]=0x1 en=1 smc_cla=handshake'
      line: 82
    cleared:
      token: 'LIFECYCLE CHK-DTP-CLKSTOP-AGG-S3 cleared: clear/ack cla_en and xtrig; en=0'
      line: 83
    checked_cleared:
      token: 'LIFECYCLE CHK-DTP-CLKSTOP-AGG-S3 checked_cleared: readback idle dtp=0x0 en=0'
      line: 84
    complete: true
  coverage_results:
  - key: DTP-CLKSTOP-AGG.S3
    method: DIRECTED
    required_cells:
    - port0=smc_reserved
    - smc_cla=handshake
    achieved_cells:
    - port0=smc_reserved
    - smc_cla=handshake
    random_knobs: []
    resolved_knobs: []
    min_seeds: 1
    actual_seeds:
    - 1
    required_artifact: null
    coverage_artifacts:
    - hw/sys/smu/dv/build/kept_logs/smu_clock_stop_coordination_test.seed1.log#727e97ce3ea6a97592887e2c5f7a222dba3fa221384e456b4b327ff9956fba60
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
  - S7
  - S8
  - S9
  proves: []
  covers: []
  proof_class: INTEGRITY
  expect_source: approved card ordering contract
  grade: PROVEN
  evidence:
  - token: 'CHK-NONVAC: Ordered fence S1<S2<S3<S4<S5<S6<S7<S8<S9<PASS all hold'
    log_sha256: 727e97ce3ea6a97592887e2c5f7a222dba3fa221384e456b4b327ff9956fba60
    line: 104
    seed: 1
    implementation_path: hw/sys/smu/dv/cocotb/seq_lib/smu_clock_stop_coordination_test_seq.py:793
  lifecycle_results: null
  coverage_results: []
  linked_issue: null
  finding_ids: []
  remediation: null
- id: CHK-TIMEOUT-PATHS
  checks_steps:
  - S9
  proves: []
  covers: []
  proof_class: INTEGRITY
  expect_source: approved card timeout contract
  grade: PROVEN
  evidence:
  - token: 'CHK-TIMEOUT-PATHS: Finite bound on S9; expiry fails with last-state diagnostics (paths=9 expect=9 bound_cycles=2000)'
    log_sha256: 727e97ce3ea6a97592887e2c5f7a222dba3fa221384e456b4b327ff9956fba60
    line: 99
    seed: 1
    implementation_path: hw/sys/smu/dv/cocotb/seq_lib/smu_clock_stop_coordination_test_seq.py:747
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
content_sha256: 2d48e90dc54a0aa6e7c4f5a49ff4d086a0475c823d5d10f0122ebd72a01a2339
---

# Grade Report — smu_clock_stop_coordination_test (SMU_ALL_006)

**VERDICT: 9/9 PROVEN — READY** (mode CHECKBOX, entry PASS)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `CHECKBOX` | ✅ PASS | 9/9 PROVEN | none | ✅ EVIDENCE-CLOSED-AWAITING-SIGNOFF |

> Card r10 narrowed Option B (`d4e8d527…`) matches parent plan r2 (`5e9e020a…`) at `plan_revision: 10`. Entry PASS on kept log `727e97ce…` (byte-identical to invoker sha; run `20260804_090752`). All nine checkers PROVEN with FL cells satisfied; lifecycle legs complete where the card declares them.

## DELTA (re-audit vs prior grade)

| Item | Prior (`dv_test_audit-SMU_ALL_006-r10-c7e2a194-5b8d-4f31-9a6e-1d0f3b8c4e72`, card r10) | This audit (`dv_test_audit-SMU_ALL_006-r18-c727ddb6cf5d`, card r18) |
|---|---|---|
| Verdict | 9/9 PROVEN — READY | 9/9 PROVEN — READY |
| Card hash | `d4e8d5273983c0aa6cead03bdea268dedea1dae02876d88e207b74fcdc090c51` (STALE vs plan r18) | `fef93d5f1ce5e0a024cbb8287d383a57720f1c07b91e8d6c99d3e95b33320a67` (current) |
| Plan revision | 10 | 18 |
| Checkers / OWNS | unchanged | unchanged — all 9 tokens re-verified on same kept log |
| Kept log | `727e97ce3ea6a97592887e2c5f7a222dba3fa221384e456b4b327ff9956fba60` | `727e97ce3ea6a97592887e2c5f7a222dba3fa221384e456b4b327ff9956fba60` (unchanged) |
| Findings | none open | none open |
| Waivers carried | none signed | none |
| Signoff | prior `2026-08-05T17:16:48+08:00` | renewed `2026-08-05T18:14:08+08:00` (standing order) |

## Your to-do — 0 items (none)

**SIGNOFF RECORDED** — see ## Human signoff below.

**Then:** `/dv_peer_audit` on SMU_ALL when all seven r18 grades are filed.

## All checkers

| Checker | Grade | Proof class | Covers |
|---|---|---|---|
| CHK-DTP-BOOT-STALL-S1 | ✅ PROVEN | LIVE | DTP-BOOT-STALL.S1 |
| CHK-DTP-BOOT-STALL-S2 | ✅ PROVEN | LIVE | DTP-BOOT-STALL.S2 |
| CHK-DTP-IC-RESET-S1 | ✅ PROVEN | LIVE | DTP-IC-RESET.S1 |
| CHK-DTP-IC-RESET-S3 | ✅ PROVEN | LIVE | DTP-IC-RESET.S3 |
| CHK-DTP-CLKSTOP-AGG-S1 | ✅ PROVEN | LIVE | DTP-CLKSTOP-AGG.S1 |
| CHK-DTP-CLKSTOP-AGG-S2 | ✅ PROVEN | LIVE | DTP-CLKSTOP-AGG.S2 |
| CHK-DTP-CLKSTOP-AGG-S3 | ✅ PROVEN | CONNECTIVITY | DTP-CLKSTOP-AGG.S3 |
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

- Log: `hw/sys/smu/dv/build/kept_logs/smu_clock_stop_coordination_test.seed1.log` sha256 `727e97ce3ea6a97592887e2c5f7a222dba3fa221384e456b4b327ff9956fba60` (byte-identical to run `20260804_090752__verilator__smu_clock_stop_coordination_test` sim log)
- Seed: 1 · simulator: verilator 5.050 · target: `default` · model_fingerprint: `48f5d6b1d3f2`
- Card: SMU_ALL_006 r18 `fef93d5f1ce5e0a024cbb8287d383a57720f1c07b91e8d6c99d3e95b33320a67` (recomputed match; current+approved)
- Parent plan record: r2 `5e9e020a1de9b5206dd53b9568433a482086201ebdae23bb4d82ab6d4c97d110` · `plan_revision: 10` · `parent_approved: true` (recomputed match; current+approved)
- Feature list cells (all `coverage_artifact: null`): BOOT-STALL.S1 `[ovrd=1,stall=1,boot=held]`; .S2 `[stall=0,boot=progresses]`; IC-RESET.S1 `[target=smc,ovrd=1]`; .S3 `[exit=trst_por,exit=clear_ovrd]`; CLKSTOP-AGG.S1 `[src=jtag,stop_clks=1]`; .S2 `[src=cla,stop_clks=1,cla_status=1]`; .S3 `[port0=smc_reserved,smc_cla=handshake]`
- Cocotb summary L128: `TESTS=1 PASS=1 FAIL=0 SKIP=0`; scoreboard 9 checks / zero errors; `prove_mapped_features` executed; no unexplained ERROR/FATAL/Traceback
- Enrolled: `hw/sys/smu/dv/testlists/dtp.toml` + `all.toml` → `smu_clock_stop_coordination_test`
- Bring-up trailer `+skip_fuse_sense` / ROM backdoor present; boot-stall proof samples `fuse_reset_n_delayed_o` under JTAG DEBUG_CONTROL (stall gate), not fuse-sense completion; ROM preload is standing §6 exception

</details>

<details>
<summary>Token / step cites (kept log `727e97ce…`)</summary>

| Checker | Line | What the log shows | Impl |
|---|---|---|---|
| (setup) | 23–24 | `STEP S1` + BASELINE stop=0 stall=0 fuse=1 SEP=0 bare | seq `:159` |
| CHK-DTP-BOOT-STALL-S1 | 25–31 | ovrd/stall=1 across cold; fuse held 0; lifecycle complete | seq `:278` |
| CHK-DTP-BOOT-STALL-S2 | 35–41 | clear stall; fuse progresses to 1; lifecycle complete | seq `:348` |
| CHK-DTP-IC-RESET-S1 | 45–47 | SMC cold port ovrd=1 ctrl_n=0 | seq `:386` |
| CHK-DTP-IC-RESET-S3 | 51–55 | clear_ovrd then TRST both clear ovrd | seq `:448` |
| CHK-DTP-CLKSTOP-AGG-S1 | 59–65 | jtag-only stop_clks=1 then clear; xtrig=0 | seq `:518` |
| CHK-DTP-CLKSTOP-AGG-S2 | 69–75 | CLA-only stop + cla_status=1; jtag_stop=0 | seq `:604` |
| CHK-DTP-CLKSTOP-AGG-S3 | 79–85 | port0==smc_fb; DTP[8:1]=0x1; en handshake | seq `:714` |
| CHK-TIMEOUT-PATHS | 89–99 | 9 TIMEOUT-PATH lines + `paths=9 expect=9 bound_cycles=2000` | seq `:747` |
| CHK-NONVAC | 103–104 | Ordered fence S1…S9\<PASS + positive-delta count 9 | seq `:793` |

</details>

<details>
<summary>Layer 1 notes (F/E/S clean)</summary>

- Ordered fence S1 SETUP → S2/S3 boot-stall → S4/S5 IC-RESET → S6–S8 clkstop agg → S9 timeout inventory → PASS: non-empty, ordered, AssertionError-gated.
- Expects independent of programmed golden echo: fuse_reset held/released, stop_clks polarity, IC_RESET ovrd/ctrl_n pair, CLA status bit, port0↔SMC-fb equality + remap.
- `_sample` is X/Z-aware; `_wait_eq` / `_wait_eq_hold` expiry raises with last-state; timeout inventory exact count 9.
- No Force/deposit on proof path; VIP `_state` bookkeeping after TRST is TB mirror sync, not DUT write.
- Hierarchical reads `u_dut.dtp_xtrig_clk_stop_req` / `tdr_dbg_ctrl_clocks_stopped_by_cla` are passive observation (policy §4 frontdoor-func).
- No merged-evidence collision: each feature checker has an independent token; integrity checkers do not substitute for feature proof.
- NONVAC compares positive wall-clock step-delta count to 9 (not decorative True/True).

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
