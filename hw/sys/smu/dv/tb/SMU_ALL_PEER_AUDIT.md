---
schema: dv-quality/v1
artifact: ip-peer-audit
ip: SMU_ALL
milestone: P2
mode: CHECKBOX-MAPPING
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
pin_revision: 1
feature_list_sha256: 4b37c7ba88aa0234689282eec80604a4181b7fec42e255479eaa83bf8f58455c
feature_list_revision: 3
testcase_plan_sha256: be84741e8818c2d5073ba998d056548fce72d9d9a3669304cf897591b35fc97a
testcase_plan_revision: 18
cards_sha256: 9accd399ccdf41e510626510be75a968aef983e09044bac1f3aca071abde8dca
derivation_provenance:
  sealed_derivation: true
  anchor_seal_mechanism: ordered-single-context
  fresh_context_route: fresh-subagent
  feature_list_frozen_at: '2026-08-05T07:42:58+08:00'
  amendment_of:
    supersedes_artifact_revision: 2
    reason: 'Skill 3 reverse_diff CONFIRMED-OMISSION: add SMC-BOOT, SEP-BOOT, SMC-AXI-LITE-SHIMS, DTP-IJTAG-SCAN, INT-FUSE-SENSE-BOOT, INT-XBAR-APERTURE-INTEROP'
evidence_policy_sha256: 936b77700909a93bb122f9fb124a3ffb6f5dac5f508c623c5950285a5cefb79a
quality_policy_sha256: 936b77700909a93bb122f9fb124a3ffb6f5dac5f508c623c5950285a5cefb79a
grade_report_sha256:
- c55aedc2b80aa53242a4b37d65aabe092c8700c29ae821d0df1ce761c1e09a06
- 9e9015174f1a89e71cfddbfe147c9c8b03ffe3f741f678746a0fcad155b79ab1
- 2ce8cf592be3261c156b08ac16b15a1809bebf07b873bb116fdbef1c8a93662e
- 2d48e90dc54a0aa6e7c4f5a49ff4d086a0475c823d5d10f0122ebd72a01a2339
- 9cdcd799eb97d0fa09af9db36593df06c3e47a5d6ddb68b62eb1660dde88c009
- cf47c542a3c923b9b0499b3626fd1d925507387c3e7b22ba966f60f1b7c76b86
- 6adf161def8140f3efe8c9c9c7384e7b3b9b3b50174a462b78b572ac31f289c3
- ce6fa84090103bf23e60ac999e49a0c89275722c6bbcdcbdd67ac432bd9ca34b
reviewer:
  human_id: dv-peer-fresh-r18-regrade
  run_id: dv_peer_audit-SMU_ALL-P2-20260805T181600+0800-fresh-r18-regrade
  model:
    provider: cursor
    family: grok
    version: '4.5'
prior_participants:
- role: skill3-auditor
  human_id: dv-peer-fresh-optionB
  run_id: dv_peer_audit-SMU_ALL-P2-20260805T180900+0800-fresh-optionB
  model:
    provider: cursor
    family: grok
    version: '4.5'
- role: skill3-auditor
  human_id: dv-peer-flamend-rereview
  run_id: dv_peer_audit-SMU_ALL-P2-20260805T074600+0800-flamend-rereview
  model:
    provider: cursor
    family: grok
    version: '4.5'
- role: feature-list-generator
  human_id: minshaoho
  run_id: dv_vplan_gen-SMU_ALL-P2-20260805T074000+0800-amend-reverse-omission
  model:
    provider: cursor
    family: grok
    version: '4.5'
- role: feature-list-generator
  human_id: minshaoho
  run_id: dv_vplan_gen-SMU_ALL-P2-optionB-008-pwrgood-only-20260805
  model:
    provider: cursor
    family: grok
    version: '4.5'
- role: reverse-inventory-generator
  human_id: minshaoho
  run_id: revinv-25b762f8bc46
  model:
    provider: cursor
    family: grok
    version: '4.5'
- role: implementer
  human_id: minshaoho
  run_id: dv_test_impl-SMU_ALL_008-optionB-20260805
  model:
    provider: cursor
    family: grok
    version: '4.5'
- role: skill2-auditor
  human_id: minshaoho
  run_id: dv_test_audit-SMU_ALL-001-007-r18-regrade-20260805T181408
  model:
    provider: cursor
    family: grok
    version: '4.5'
- role: skill2-auditor
  human_id: minshaoho
  run_id: dv_test_audit-SMU_ALL_008-r18-84c27e9f-ea0a-6619-459c-f96ebefc27ed
  model:
    provider: cursor
    family: grok
    version: '4.5'
denominator:
  inventory_keys: 121
  excluded_keys: 95
  milestone_required_keys: 26
  covered_keys: 26
coverage:
- key: DTP-BOOT-STALL.S1
  required_proof_class: LIVE
  status: COVERED
  allocated_to: SMU_ALL_006
  closed_by_allocated: true
  proven_by:
  - checker_ref: smu_clock_stop_coordination_test/CHK-DTP-BOOT-STALL-S1/2d48e90dc54a
    independent_evidence:
      required: false
      method: NOT-REQUIRED
      source_run_id: dv_test_audit-SMU_ALL_006-r18-c727ddb6cf5d
      source_log_sha256: 727e97ce3ea6a97592887e2c5f7a222dba3fa221384e456b4b327ff9956fba60
      run_id: null
      build_fingerprint: 48f5d6b1d3f2
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model:
          provider: null
          family: null
          version: null
      gate_satisfied: true
  required_cells:
  - ovrd=1
  - stall=1
  - boot=held
  achieved_cells:
  - ovrd=1
  - stall=1
  - boot=held
- key: DTP-BOOT-STALL.S2
  required_proof_class: LIVE
  status: COVERED
  allocated_to: SMU_ALL_006
  closed_by_allocated: true
  proven_by:
  - checker_ref: smu_clock_stop_coordination_test/CHK-DTP-BOOT-STALL-S2/2d48e90dc54a
    independent_evidence:
      required: false
      method: NOT-REQUIRED
      source_run_id: dv_test_audit-SMU_ALL_006-r18-c727ddb6cf5d
      source_log_sha256: 727e97ce3ea6a97592887e2c5f7a222dba3fa221384e456b4b327ff9956fba60
      run_id: null
      build_fingerprint: 48f5d6b1d3f2
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model:
          provider: null
          family: null
          version: null
      gate_satisfied: true
  required_cells:
  - stall=0
  - boot=progresses
  achieved_cells:
  - stall=0
  - boot=progresses
- key: DTP-CLKSTOP-AGG.S1
  required_proof_class: LIVE
  status: COVERED
  allocated_to: SMU_ALL_006
  closed_by_allocated: true
  proven_by:
  - checker_ref: smu_clock_stop_coordination_test/CHK-DTP-CLKSTOP-AGG-S1/2d48e90dc54a
    independent_evidence:
      required: false
      method: NOT-REQUIRED
      source_run_id: dv_test_audit-SMU_ALL_006-r18-c727ddb6cf5d
      source_log_sha256: 727e97ce3ea6a97592887e2c5f7a222dba3fa221384e456b4b327ff9956fba60
      run_id: null
      build_fingerprint: 48f5d6b1d3f2
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model:
          provider: null
          family: null
          version: null
      gate_satisfied: true
  required_cells:
  - src=jtag
  - stop_clks=1
  achieved_cells:
  - src=jtag
  - stop_clks=1
- key: DTP-CLKSTOP-AGG.S2
  required_proof_class: LIVE
  status: COVERED
  allocated_to: SMU_ALL_006
  closed_by_allocated: true
  proven_by:
  - checker_ref: smu_clock_stop_coordination_test/CHK-DTP-CLKSTOP-AGG-S2/2d48e90dc54a
    independent_evidence:
      required: false
      method: NOT-REQUIRED
      source_run_id: dv_test_audit-SMU_ALL_006-r18-c727ddb6cf5d
      source_log_sha256: 727e97ce3ea6a97592887e2c5f7a222dba3fa221384e456b4b327ff9956fba60
      run_id: null
      build_fingerprint: 48f5d6b1d3f2
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model:
          provider: null
          family: null
          version: null
      gate_satisfied: true
  required_cells:
  - src=cla
  - stop_clks=1
  - cla_status=1
  achieved_cells:
  - src=cla
  - stop_clks=1
  - cla_status=1
- key: DTP-CLKSTOP-AGG.S3
  required_proof_class: CONNECTIVITY
  status: COVERED
  allocated_to: SMU_ALL_006
  closed_by_allocated: true
  proven_by:
  - checker_ref: smu_clock_stop_coordination_test/CHK-DTP-CLKSTOP-AGG-S3/2d48e90dc54a
    independent_evidence:
      required: false
      method: NOT-REQUIRED
      source_run_id: dv_test_audit-SMU_ALL_006-r18-c727ddb6cf5d
      source_log_sha256: 727e97ce3ea6a97592887e2c5f7a222dba3fa221384e456b4b327ff9956fba60
      run_id: null
      build_fingerprint: 48f5d6b1d3f2
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model:
          provider: null
          family: null
          version: null
      gate_satisfied: true
  required_cells:
  - port0=smc_reserved
  - smc_cla=handshake
  achieved_cells:
  - port0=smc_reserved
  - smc_cla=handshake
- key: DTP-FEAT-GATE.S1
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - policy=debug_disabled
  - jtag2axi=blocked
  achieved_cells: []
- key: DTP-FEAT-GATE.S2
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - policy=debug_enabled
  - jtag2axi=allowed
  achieved_cells: []
- key: DTP-FEAT-GATE.S3
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - sigint_err=1
  - feat_ctrl=0
  - debug=blocked
  achieved_cells: []
- key: DTP-IC-RESET.S1
  required_proof_class: LIVE
  status: COVERED
  allocated_to: SMU_ALL_006
  closed_by_allocated: true
  proven_by:
  - checker_ref: smu_clock_stop_coordination_test/CHK-DTP-IC-RESET-S1/2d48e90dc54a
    independent_evidence:
      required: false
      method: NOT-REQUIRED
      source_run_id: dv_test_audit-SMU_ALL_006-r18-c727ddb6cf5d
      source_log_sha256: 727e97ce3ea6a97592887e2c5f7a222dba3fa221384e456b4b327ff9956fba60
      run_id: null
      build_fingerprint: 48f5d6b1d3f2
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model:
          provider: null
          family: null
          version: null
      gate_satisfied: true
  required_cells:
  - target=smc
  - ovrd=1
  achieved_cells:
  - target=smc
  - ovrd=1
- key: DTP-IC-RESET.S2
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - target=sep
  - ovrd=1
  - sep=1
  achieved_cells: []
- key: DTP-IC-RESET.S3
  required_proof_class: LIVE
  status: COVERED
  allocated_to: SMU_ALL_006
  closed_by_allocated: true
  proven_by:
  - checker_ref: smu_clock_stop_coordination_test/CHK-DTP-IC-RESET-S3/2d48e90dc54a
    independent_evidence:
      required: false
      method: NOT-REQUIRED
      source_run_id: dv_test_audit-SMU_ALL_006-r18-c727ddb6cf5d
      source_log_sha256: 727e97ce3ea6a97592887e2c5f7a222dba3fa221384e456b4b327ff9956fba60
      run_id: null
      build_fingerprint: 48f5d6b1d3f2
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model:
          provider: null
          family: null
          version: null
      gate_satisfied: true
  required_cells:
  - exit=trst_por
  - exit=clear_ovrd
  achieved_cells:
  - exit=clear_ovrd
  - exit=trst_por
- key: DTP-IJTAG-SCAN.S1
  required_proof_class: CONNECTIVITY
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - bsr-scan-port
  achieved_cells: []
- key: DTP-IJTAG-SCAN.S2
  required_proof_class: CONNECTIVITY
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - ijtag-dfd-dft-ports
  achieved_cells: []
- key: DTP-JTAG-PTAP.S1
  required_proof_class: LIVE
  status: COVERED
  allocated_to: SMU_ALL_005
  closed_by_allocated: true
  proven_by:
  - checker_ref: smu_dtp_jtag_smoke_test/CHK-DTP-JTAG-PTAP-S1/9cdcd799eb97
    independent_evidence:
      required: false
      method: NOT-REQUIRED
      source_run_id: dv_test_audit-SMU_ALL_005-r18-55a4af92444b
      source_log_sha256: 0a563d0cdce7af80d38a313fc7c935355e0506fa26c7048377bc879a6fa23e0f
      run_id: null
      build_fingerprint: 48f5d6b1d3f2
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model:
          provider: null
          family: null
          version: null
      gate_satisfied: true
  required_cells:
  - inst=IDCODE
  achieved_cells:
  - inst=IDCODE
- key: DTP-JTAG-PTAP.S2
  required_proof_class: LIVE
  status: COVERED
  allocated_to: SMU_ALL_005
  closed_by_allocated: true
  proven_by:
  - checker_ref: smu_dtp_jtag_smoke_test/CHK-DTP-JTAG-PTAP-S2/9cdcd799eb97
    independent_evidence:
      required: false
      method: NOT-REQUIRED
      source_run_id: dv_test_audit-SMU_ALL_005-r18-55a4af92444b
      source_log_sha256: 0a563d0cdce7af80d38a313fc7c935355e0506fa26c7048377bc879a6fa23e0f
      run_id: null
      build_fingerprint: 48f5d6b1d3f2
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model:
          provider: null
          family: null
          version: null
      gate_satisfied: true
  required_cells:
  - inst=BYPASS
  achieved_cells:
  - inst=BYPASS
- key: DTP-JTAG-PTAP.S3
  required_proof_class: LIVE
  status: COVERED
  allocated_to: SMU_ALL_005
  closed_by_allocated: true
  proven_by:
  - checker_ref: smu_dtp_jtag_smoke_test/CHK-DTP-JTAG-PTAP-S3/9cdcd799eb97
    independent_evidence:
      required: false
      method: NOT-REQUIRED
      source_run_id: dv_test_audit-SMU_ALL_005-r18-55a4af92444b
      source_log_sha256: 0a563d0cdce7af80d38a313fc7c935355e0506fa26c7048377bc879a6fa23e0f
      run_id: null
      build_fingerprint: 48f5d6b1d3f2
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model:
          provider: null
          family: null
          version: null
      gate_satisfied: true
  required_cells:
  - rst=TRST
  - rst=POR
  - state=Test-Logic-Reset
  achieved_cells:
  - rst=TRST
  - rst=POR
  - state=Test-Logic-Reset
- key: DTP-JTAG2AXI-SMC.S1
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - op=read
  - op=write
  - dest=smc_csr
  achieved_cells: []
- key: DTP-JTAG2AXI-SMC.S2
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - feat_ctrl=debug_blocked
  - axi_traffic=0
  achieved_cells: []
- key: DTP-OTP-AXIL.S1
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - target=smc_otp
  achieved_cells: []
- key: DTP-OTP-AXIL.S2
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - target=sep_otp
  - sep=1
  achieved_cells: []
- key: DTP-OTP-AXIL.S3
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - sep=0
  - resp=DECERR
  - rdata=0xBADCAB1E
  achieved_cells: []
- key: DTP-STAP-SMC-SEP.S1
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - stap=smc
  - selected=1
  achieved_cells: []
- key: DTP-STAP-SMC-SEP.S2
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - stap=sep
  - sep=1
  - selected=1
  achieved_cells: []
- key: DTP-STAP-SMC-SEP.S3
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - stap=blocked
  - policy=disabled
  achieved_cells: []
- key: DTP-XTRIG-CTM.S1
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - route=programmed
  - pulse_seen=1
  achieved_cells: []
- key: DTP-XTRIG-CTM.S2
  required_proof_class: CONNECTIVITY
  status: COVERED
  allocated_to: SMU_ALL_007
  closed_by_allocated: true
  proven_by:
  - checker_ref: smu_sep_smoke_test/CHK-DTP-XTRIG-CTM-S2/cf47c542a3c9
    independent_evidence:
      required: false
      method: NOT-REQUIRED
      source_run_id: dv_test_audit-SMU_ALL_007-r18-e949ad81f942
      source_log_sha256: 4d0c8bea74d7f87c6e65b8bcaff575c8ad8fceda15bf9cafa420d8e5afd401d3
      run_id: null
      build_fingerprint: 48f5d6b1d3f2
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model:
          provider: null
          family: null
          version: null
      gate_satisfied: true
  required_cells:
  - mode=pulse_sync
  - ack_unused=1
  achieved_cells:
  - mode=pulse_sync
  - ack_unused=1
- key: DTP-XTRIG-CTM.S3
  required_proof_class: CONNECTIVITY
  status: COVERED
  allocated_to: SMU_ALL_007
  closed_by_allocated: true
  proven_by:
  - checker_ref: smu_sep_smoke_test/CHK-DTP-XTRIG-CTM-S3/cf47c542a3c9
    independent_evidence:
      required: false
      method: NOT-REQUIRED
      source_run_id: dv_test_audit-SMU_ALL_007-r18-e949ad81f942
      source_log_sha256: 4d0c8bea74d7f87c6e65b8bcaff575c8ad8fceda15bf9cafa420d8e5afd401d3
      run_id: null
      build_fingerprint: 48f5d6b1d3f2
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model:
          provider: null
          family: null
          version: null
      gate_satisfied: true
  required_cells:
  - bits=1:0
  - owner=smc
  achieved_cells:
  - bits=1:0
  - owner=smc
- key: DTP-XTRIG-CTP.S1
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - mode=wire_or
  - mode=p2p
  - phase=req_out
  achieved_cells: []
- key: DTP-XTRIG-CTP.S2
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - mode=p2p
  - phase=ack
  achieved_cells: []
- key: INT-ALIAS-VS-XBAR-SMC
  required_proof_class: CONNECTIVITY
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - path=alias_bypass
  - path=xbar_aperture
  achieved_cells: []
- key: INT-BOOT-STALL-INTEROP
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - stall=hold_sep
  - stall=release
  - mbx=complete
  achieved_cells: []
- key: INT-CLKSTOP-SMC-CLA
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - src=smc_cla,stop=1
  - src=jtag,cla_status=0
  achieved_cells: []
- key: INT-FEAT-CTRL-DTP-GATE
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - policy=disabled,jtag2axi=0
  - policy=enabled,jtag2axi=1
  achieved_cells: []
- key: INT-FUSE-SENSE-BOOT
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - fuse-sense-then-boot
  achieved_cells: []
- key: INT-MBX-CHALLENGE-IRQ
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - exchange=complete
  - irq=sep_mbx_seen
  achieved_cells: []
- key: INT-PWRGOOD-DTP-POR
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - powergood=0,tap=reset
  - powergood=1,tap=runnable
  achieved_cells: []
- key: INT-SEP0-OTP-ERR
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - sep=0
  - resp=DECERR
  - rdata=0xBADCAB1E
  achieved_cells: []
- key: INT-XBAR-APERTURE-INTEROP
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - aperture-plus-mailbox-routing
  achieved_cells: []
- key: SEP-BOOT.S1
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - sep-tcm-boot-progress
  achieved_cells: []
- key: SEP-BOOT.S2
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - sep-reset-exports
  achieved_cells: []
- key: SEP-FUSE-SENSE-HS.S1
  required_proof_class: CONNECTIVITY
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - smc_done=1
  - sep_sees=1
  achieved_cells: []
- key: SEP-FUSE-SENSE-HS.S2
  required_proof_class: CONNECTIVITY
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - sep_done=1
  achieved_cells: []
- key: SEP-FUSE-SENSE-HS.S3
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - sec_dis=0
  - latch=fuse_sense_done
  - sec_dis=1
  - latch=cold_reset_release
  achieved_cells: []
- key: SEP-LC-FEAT-EXPORT.S1
  required_proof_class: CONNECTIVITY
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - width=8
  - src=sep
  achieved_cells: []
- key: SEP-LC-FEAT-EXPORT.S2
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - bit=SEP_DBG
  - effect=dtp_gate
  achieved_cells: []
- key: SEP-LC-FEAT-EXPORT.S3
  required_proof_class: CONNECTIVITY
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - demote=1
  - demote=2
  achieved_cells: []
- key: SEP-MBX-IRQ-SMC.S1
  required_proof_class: CONNECTIVITY
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - n=0
  - n=3
  - n=7
  - cfg=4core
  achieved_cells: []
- key: SEP-MBX-IRQ-SMC.S2
  required_proof_class: CONNECTIVITY
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - n=0
  - n=7
  - cfg=1core
  achieved_cells: []
- key: SEP-MEM-BOUND-PASSTHROUGH.S1
  required_proof_class: CONNECTIVITY
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - mem=tcm
  - op=read
  - op=write
  achieved_cells: []
- key: SEP-MEM-BOUND-PASSTHROUGH.S2
  required_proof_class: CONNECTIVITY
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - mem=boot_rom
  - mem=scratch_sram
  achieved_cells: []
- key: SEP-MEM-BOUND-PASSTHROUGH.S3
  required_proof_class: CONNECTIVITY
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - mem=otbn_imem
  - mem=km_sram
  achieved_cells: []
- key: SEP-SEC-DIS.S1
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - token=match
  - sec_dis=1
  - feat_ctrl=open
  achieved_cells: []
- key: SEP-SEC-DIS.S2
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - token=mismatch
  - sec_dis=0
  achieved_cells: []
- key: SEP-SEC-DIS.S3
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - reset=por_functional
  - token_reg=retained
  achieved_cells: []
- key: SEP-SYSIF-SMU-XBAR.S1
  required_proof_class: CONNECTIVITY
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - dest=smc_global
  achieved_cells: []
- key: SEP-SYSIF-SMU-XBAR.S2
  required_proof_class: CONNECTIVITY
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - dest=smn
  - path=ext_out
  achieved_cells: []
- key: SEP-SYSIF-SMU-XBAR.S3
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - dir=inbound
  - filter=default_block
  - filter=allow
  achieved_cells: []
- key: SEP-WDT-RST-SMC.S1
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - wdt=timeout
  - smc_obs=1
  achieved_cells: []
- key: SEP-WDT-RST-SMC.S2
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - wdt=cleared
  achieved_cells: []
- key: SMC-AXI-LITE-SHIMS.S1
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - axil-shim-handshake
  achieved_cells: []
- key: SMC-AXI-LITE-SHIMS.S2
  required_proof_class: CONNECTIVITY
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - smc-external-decerr-tieoff
  achieved_cells: []
- key: SMC-BOOT.S1
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - smc-rom-fetch-progress
  achieved_cells: []
- key: SMC-BOOT.S2
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - boot-seq-gate
  achieved_cells: []
- key: SMC-BOOT.S3
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - smc-boot-sep0
  achieved_cells: []
- key: SMC-DECODE-APERTURE.S1
  required_proof_class: DECODE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - base=local
  - base=global
  - offset=mailbox
  achieved_cells: []
- key: SMC-DECODE-APERTURE.S2
  required_proof_class: DECODE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - region_size_reset=16MiB
  - addr=inside
  - addr=outside
  achieved_cells: []
- key: SMC-DECODE-APERTURE.S3
  required_proof_class: DECODE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - dest=mailbox
  - dest=dtp_ctrl
  achieved_cells: []
- key: SMC-DTP-CSR.S1
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - op=write
  - op=read
  - dest=dtp_csr
  achieved_cells: []
- key: SMC-DTP-CSR.S2
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - cfg=ctm_route
  - effect=observed
  achieved_cells: []
- key: SMC-FAB-DUAL-NET.S1
  required_proof_class: CONNECTIVITY
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - dest=SRAM
  - dest=PLIC
  - dest=CLINT
  - dest=WDT
  - dest=external_axi
  achieved_cells: []
- key: SMC-FAB-DUAL-NET.S2
  required_proof_class: CONNECTIVITY
  status: COVERED
  allocated_to: SMU_ALL_003
  closed_by_allocated: true
  proven_by:
  - checker_ref: smu_smc_smoke_test/CHK-SMC-FAB-DUAL-NET-S2/6adf161def81
    independent_evidence:
      required: false
      method: NOT-REQUIRED
      source_run_id: dv_test_audit-SMU_ALL_003-r18-250948484e4b
      source_log_sha256: b575348c09fe1b2170415ff48e83f6f69f1992bbb288be1ecac86fb4316318d5
      run_id: null
      build_fingerprint: 48f5d6b1d3f2
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model:
          provider: null
          family: null
          version: null
      gate_satisfied: true
  required_cells:
  - dest=local_peripheral
  - dest=config_register
  achieved_cells:
  - dest=local_peripheral
  - dest=config_register
- key: SMC-FAB-DUAL-NET.S3
  required_proof_class: CONNECTIVITY
  status: COVERED
  allocated_to: SMU_ALL_003
  closed_by_allocated: true
  proven_by:
  - checker_ref: smu_smc_smoke_test/CHK-SMC-FAB-DUAL-NET-S3/6adf161def81
    independent_evidence:
      required: false
      method: NOT-REQUIRED
      source_run_id: dv_test_audit-SMU_ALL_003-r18-250948484e4b
      source_log_sha256: b575348c09fe1b2170415ff48e83f6f69f1992bbb288be1ecac86fb4316318d5
      run_id: null
      build_fingerprint: 48f5d6b1d3f2
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model:
          provider: null
          family: null
          version: null
      gate_satisfied: true
  required_cells:
  - net=AXI4,data=64
  - net=AXI4-Lite,data=64
  achieved_cells:
  - net=AXI4,data=64
  - net=AXI4-Lite,data=64
- key: SMC-FAB-IN-PORTS.S1
  required_proof_class: CONNECTIVITY
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - port=sys_axi_in
  - id_w=6
  - user_w=12
  achieved_cells: []
- key: SMC-FAB-IN-PORTS.S2
  required_proof_class: CONNECTIVITY
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - port=jtag_axi_in
  - id_w=2
  achieved_cells: []
- key: SMC-FAB-IN-PORTS.S3
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - port=sep_axi_in
  - filter=default_block
  - filter=allow_programmed
  achieved_cells: []
- key: SMC-FAB-OUT-SMN.S1
  required_proof_class: CONNECTIVITY
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - path=direct
  - sid=SMC_ID
  achieved_cells: []
- key: SMC-FAB-OUT-SMN.S2
  required_proof_class: CONNECTIVITY
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - path=xvisor
  - sid=OTHER_ID
  - path=mmode
  - sid=MMODE_ID
  achieved_cells: []
- key: SMC-FAB-OUT-SMN.S3
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - filter=deny
  - resp=error
  achieved_cells: []
- key: SMC-MBX-CHANNELS.S1
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - ch=outbound0
  - peer=sep
  achieved_cells: []
- key: SMC-MBX-CHANNELS.S2
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - ch=inbound0
  - irq=mailbox_bit
  achieved_cells: []
- key: SMC-MBX-CHANNELS.S3
  required_proof_class: DECODE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - ch=0
  - ch=15
  - ch=16
  - ch=31
  achieved_cells: []
- key: SMC-MBX-IRQ-EXT.S1
  required_proof_class: CONNECTIVITY
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - bit=0
  - bit=31
  achieved_cells: []
- key: SMC-MBX-IRQ-EXT.S2
  required_proof_class: DECODE
  status: COVERED
  allocated_to: SMU_ALL_004
  closed_by_allocated: true
  proven_by:
  - checker_ref: smc_mailbox_int_test/CHK-SMC-MBX-IRQ-EXT-S2/c55aedc2b80a
    independent_evidence:
      required: false
      method: NOT-REQUIRED
      source_run_id: dv_test_audit-SMU_ALL_004-r18-58c8569adafc
      source_log_sha256: a0f50c9c906171c082a3810006942306ae34b618f910524552a2b1844624efbd
      run_id: null
      build_fingerprint: 48f5d6b1d3f2
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model:
          provider: null
          family: null
          version: null
      gate_satisfied: true
  required_cells:
  - width=32
  achieved_cells:
  - width=32
- key: SMC-PWRGOOD-DTP-POR.S1
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - powergood=0
  - trst=1
  - tap=reset
  achieved_cells: []
- key: SMC-PWRGOOD-DTP-POR.S2
  required_proof_class: LIVE
  status: COVERED
  allocated_to: SMU_ALL_008
  closed_by_allocated: true
  proven_by:
  - checker_ref: smu_axi_crossbar_error_handling_test/CHK-SMC-PWRGOOD-DTP-POR-S2/9e9015174f1a
    independent_evidence:
      required: false
      method: NOT-REQUIRED
      source_run_id: dv_test_audit-SMU_ALL_008-r18-84c27e9f-ea0a-6619-459c-f96ebefc27ed
      source_log_sha256: 04c129e6eb1d47cd507efcdc937e7ae29433c0c858325b423511ed1ad9e24f1a
      run_id: null
      build_fingerprint: 48f5d6b1d3f2
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model:
          provider: null
          family: null
          version: null
      gate_satisfied: true
  required_cells:
  - powergood=1
  - trst=1
  - tap=exit_tlr
  achieved_cells:
  - powergood=1
  - trst=1
  - tap=exit_tlr
- key: SMC-RST-PRIMARY-EXPORT.S1
  required_proof_class: LIVE
  status: COVERED
  allocated_to: SMU_ALL_007
  closed_by_allocated: true
  proven_by:
  - checker_ref: smu_sep_smoke_test/CHK-SMC-RST-PRIMARY-EXPORT-S1/cf47c542a3c9
    independent_evidence:
      required: false
      method: NOT-REQUIRED
      source_run_id: dv_test_audit-SMU_ALL_007-r18-e949ad81f942
      source_log_sha256: 4d0c8bea74d7f87c6e65b8bcaff575c8ad8fceda15bf9cafa420d8e5afd401d3
      run_id: null
      build_fingerprint: 48f5d6b1d3f2
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model:
          provider: null
          family: null
          version: null
      gate_satisfied: true
  required_cells:
  - src=cold
  - obs=rst_primary_smc
  - obs=rst_primary_ref
  achieved_cells:
  - src=cold
  - obs=rst_primary_smc
  - obs=rst_primary_ref
- key: SMC-RST-PRIMARY-EXPORT.S2
  required_proof_class: LIVE
  status: COVERED
  allocated_to: SMU_ALL_007
  closed_by_allocated: true
  proven_by:
  - checker_ref: smu_sep_smoke_test/CHK-SMC-RST-PRIMARY-EXPORT-S2/cf47c542a3c9
    independent_evidence:
      required: false
      method: NOT-REQUIRED
      source_run_id: dv_test_audit-SMU_ALL_007-r18-e949ad81f942
      source_log_sha256: 4d0c8bea74d7f87c6e65b8bcaff575c8ad8fceda15bf9cafa420d8e5afd401d3
      run_id: null
      build_fingerprint: 48f5d6b1d3f2
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model:
          provider: null
          family: null
          version: null
      gate_satisfied: true
  required_cells:
  - rst_primary=assert
  - jtag_tdr=retained_unless_por
  achieved_cells:
  - rst_primary=assert
  - jtag_tdr=retained_unless_por
- key: SMU-COMPOSE-BLOCKS.S1
  required_proof_class: CONNECTIVITY
  status: COVERED
  allocated_to: SMU_ALL_001
  closed_by_allocated: true
  proven_by:
  - checker_ref: smu_wrapper_elaboration_sep_rtl_test/CHK-SMU-COMPOSE-BLOCKS-S1/ce6fa8409010
    independent_evidence:
      required: false
      method: NOT-REQUIRED
      source_run_id: dv_test_audit-SMU_ALL_001-r18-77499f4e3b45
      source_log_sha256: ce58253444b88a16cc5e5940f1f6afb5bf658749b431f0d220a43231e185a9c2
      run_id: null
      build_fingerprint: f31560a93189
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model:
          provider: null
          family: null
          version: null
      gate_satisfied: true
  required_cells:
  - sep=1
  - blocks=smc+sep+dtp+xbar
  achieved_cells:
  - sep=1
  - blocks=smc+sep+dtp+xbar
- key: SMU-COMPOSE-BLOCKS.S2
  required_proof_class: CONNECTIVITY
  status: COVERED
  allocated_to: SMU_ALL_001
  closed_by_allocated: true
  proven_by:
  - checker_ref: smu_wrapper_elaboration_sep_rtl_test/CHK-SMU-COMPOSE-BLOCKS-S2/ce6fa8409010
    independent_evidence:
      required: false
      method: NOT-REQUIRED
      source_run_id: dv_test_audit-SMU_ALL_001-r18-77499f4e3b45
      source_log_sha256: ce58253444b88a16cc5e5940f1f6afb5bf658749b431f0d220a43231e185a9c2
      run_id: null
      build_fingerprint: f31560a93189
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model:
          provider: null
          family: null
          version: null
      gate_satisfied: true
  required_cells:
  - domain=clk_smu
  - rst=rst_primary_smc_clk_no
  achieved_cells:
  - domain=clk_smu
  - rst=rst_primary_smc_clk_no
- key: SMU-COMPOSE-BLOCKS.S3
  required_proof_class: CONNECTIVITY
  status: COVERED
  allocated_to: SMU_ALL_001
  closed_by_allocated: true
  proven_by:
  - checker_ref: smu_wrapper_elaboration_sep_rtl_test/CHK-SMU-COMPOSE-BLOCKS-S3/ce6fa8409010
    independent_evidence:
      required: false
      method: NOT-REQUIRED
      source_run_id: dv_test_audit-SMU_ALL_001-r18-77499f4e3b45
      source_log_sha256: ce58253444b88a16cc5e5940f1f6afb5bf658749b431f0d220a43231e185a9c2
      run_id: null
      build_fingerprint: f31560a93189
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model:
          provider: null
          family: null
          version: null
      gate_satisfied: true
  required_cells:
  - port_group=jtag
  - port_group=smu_axi
  - port_group=xtrig
  - port_group=lifecycle
  achieved_cells:
  - port_group=jtag
  - port_group=smu_axi
  - port_group=xtrig
  - port_group=lifecycle
- key: SMU-MBX-CHALLENGE.S1
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - phase=challenge
  - phase=response
  - payload=complement
  achieved_cells: []
- key: SMU-MBX-CHALLENGE.S2
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - irq=sep_mbx0
  - irq=sep_mbx7
  achieved_cells: []
- key: SMU-MBX-CHALLENGE.S3
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - sep=stalled_then_release
  - exchange=completes
  achieved_cells: []
- key: SMU-PORT-CLK-RST.S1
  required_proof_class: LIVE
  status: COVERED
  allocated_to: SMU_ALL_001
  closed_by_allocated: true
  proven_by:
  - checker_ref: smu_wrapper_elaboration_sep_rtl_test/CHK-SMU-PORT-CLK-RST-S1/ce6fa8409010
    independent_evidence:
      required: false
      method: NOT-REQUIRED
      source_run_id: dv_test_audit-SMU_ALL_001-r18-77499f4e3b45
      source_log_sha256: ce58253444b88a16cc5e5940f1f6afb5bf658749b431f0d220a43231e185a9c2
      run_id: null
      build_fingerprint: f31560a93189
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model:
          provider: null
          family: null
          version: null
      gate_satisfied: true
  required_cells:
  - rst=cold_assert
  - rst=cold_deassert
  - obs=rst_primary_smc
  achieved_cells:
  - rst=cold_assert
  - rst=cold_deassert
  - obs=rst_primary_smc
- key: SMU-PORT-CLK-RST.S2
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - powergood=0
  - powergood=1
  achieved_cells: []
- key: SMU-PORT-CLK-RST.S3
  required_proof_class: CONNECTIVITY
  status: COVERED
  allocated_to: SMU_ALL_001
  closed_by_allocated: true
  proven_by:
  - checker_ref: smu_wrapper_elaboration_sep_rtl_test/CHK-SMU-PORT-CLK-RST-S3/ce6fa8409010
    independent_evidence:
      required: false
      method: NOT-REQUIRED
      source_run_id: dv_test_audit-SMU_ALL_001-r18-77499f4e3b45
      source_log_sha256: ce58253444b88a16cc5e5940f1f6afb5bf658749b431f0d220a43231e185a9c2
      run_id: null
      build_fingerprint: f31560a93189
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model:
          provider: null
          family: null
          version: null
      gate_satisfied: true
  required_cells:
  - clk=telemetry
  - clk=sep_wdt
  achieved_cells:
  - clk=telemetry
  - clk=sep_wdt
- key: SMU-PORT-SMN-AXI.S1
  required_proof_class: CONNECTIVITY
  status: COVERED
  allocated_to: SMU_ALL_002
  closed_by_allocated: true
  proven_by:
  - checker_ref: smu_axi_external_port_connectivity_test/CHK-SMU-PORT-SMN-AXI-S1/2ce8cf592be3
    independent_evidence:
      required: false
      method: NOT-REQUIRED
      source_run_id: dv_test_audit-SMU_ALL_002-r18-75c1aff41eb5
      source_log_sha256: df05f91ec71e702daea2a045fba9e06b4f5c5d659a09890589ca586c9947fb8b
      run_id: null
      build_fingerprint: 74386ebf48af
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model:
          provider: null
          family: null
          version: null
      gate_satisfied: true
  required_cells:
  - dir=in
  - dest=smc_aperture
  achieved_cells:
  - dir=in
  - dest=smc_aperture
- key: SMU-PORT-SMN-AXI.S2
  required_proof_class: CONNECTIVITY
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - dir=out
  - src=smc_out
  - src=sep_out
  achieved_cells: []
- key: SMU-PORT-SMN-AXI.S3
  required_proof_class: DECODE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - id_width_in=8
  achieved_cells: []
- key: SMU-PORT-SMN-AXI.S4
  required_proof_class: CONNECTIVITY
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - dir=in
  - dest=sep_aperture
  achieved_cells: []
- key: SMU-SEP-PARAM.S1
  required_proof_class: CONNECTIVITY
  status: COVERED
  allocated_to: SMU_ALL_001
  closed_by_allocated: true
  proven_by:
  - checker_ref: smu_wrapper_elaboration_sep_rtl_test/CHK-SMU-SEP-PARAM-S1/ce6fa8409010
    independent_evidence:
      required: false
      method: NOT-REQUIRED
      source_run_id: dv_test_audit-SMU_ALL_001-r18-77499f4e3b45
      source_log_sha256: ce58253444b88a16cc5e5940f1f6afb5bf658749b431f0d220a43231e185a9c2
      run_id: null
      build_fingerprint: f31560a93189
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model:
          provider: null
          family: null
          version: null
      gate_satisfied: true
  required_cells:
  - sep=1
  - xbar=present
  - lc_state=from_sep
  achieved_cells:
  - sep=1
  - xbar=present
  - lc_state=from_sep
- key: SMU-SEP-PARAM.S2
  required_proof_class: CONNECTIVITY
  status: COVERED
  allocated_to: SMU_ALL_002
  closed_by_allocated: true
  proven_by:
  - checker_ref: smu_axi_external_port_connectivity_test/CHK-SMU-SEP-PARAM-S2/2ce8cf592be3
    independent_evidence:
      required: false
      method: NOT-REQUIRED
      source_run_id: dv_test_audit-SMU_ALL_002-r18-75c1aff41eb5
      source_log_sha256: df05f91ec71e702daea2a045fba9e06b4f5c5d659a09890589ca586c9947fb8b
      run_id: null
      build_fingerprint: 74386ebf48af
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model:
          provider: null
          family: null
          version: null
      gate_satisfied: true
  required_cells:
  - sep=0
  - path=direct_smc_ext
  achieved_cells:
  - sep=0
  - path=direct_smc_ext
- key: SMU-SEP-PARAM.S3
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - sep=0
  - otp_resp=DECERR
  - otp_rdata=0xBADCAB1E
  - lc_state=0xf0
  achieved_cells: []
- key: SMU-SEP-SMC-ALIAS.S1
  required_proof_class: DECODE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - addr=0x40000000
  - alias=0x0
  - bypass_xbar=1
  achieved_cells: []
- key: SMU-SEP-SMC-ALIAS.S2
  required_proof_class: CONNECTIVITY
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - addr=near_top
  - alias_top=1
  achieved_cells: []
- key: SMU-SEP-SMC-ALIAS.S3
  required_proof_class: CONNECTIVITY
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - path=alias_remap
  - xbar_required=0
  achieved_cells: []
- key: SMU-XBAR-APERTURE.S1
  required_proof_class: DECODE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - aperture=smc
  - addr=inside
  - dest=smc_in
  achieved_cells: []
- key: SMU-XBAR-APERTURE.S2
  required_proof_class: DECODE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - aperture=sep
  - addr=inside
  - dest=sep_in
  achieved_cells: []
- key: SMU-XBAR-APERTURE.S3
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - overlap=reprogram_during_inflight
  - outcome=complete_or_error
  achieved_cells: []
- key: SMU-XBAR-ATOP-REJECT.S1
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - src=ext_in
  - atop=asserted
  - result=rejected
  achieved_cells: []
- key: SMU-XBAR-ATOP-REJECT.S2
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - src=smc_out
  - src=sep_out
  - result=rejected
  achieved_cells: []
- key: SMU-XBAR-BACKPRESSURE.S1
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - pair=smc+sep
  - bp=ext_out
  - outcome=bounded
  achieved_cells: []
- key: SMU-XBAR-BACKPRESSURE.S2
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - src=ext_in
  - bp=local
  - outcome=bounded
  achieved_cells: []
- key: SMU-XBAR-BACKPRESSURE.S3
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - state=saturated
  - outcome=bounded
  achieved_cells: []
- key: SMU-XBAR-CONNECT.S1
  required_proof_class: CONNECTIVITY
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - src=sep_out,dst=smc_in
  - src=sep_out,dst=ext_out
  achieved_cells: []
- key: SMU-XBAR-CONNECT.S2
  required_proof_class: CONNECTIVITY
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - src=smc_out,dst=sep_in
  - src=smc_out,dst=ext_out
  achieved_cells: []
- key: SMU-XBAR-CONNECT.S3
  required_proof_class: CONNECTIVITY
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - src=ext_in,dst=sep_in
  - src=ext_in,dst=smc_in
  achieved_cells: []
- key: SMU-XBAR-ID-CONV.S1
  required_proof_class: CONNECTIVITY
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - dest=smc
  - ids>=2
  - resp_match=1
  achieved_cells: []
- key: SMU-XBAR-ID-CONV.S2
  required_proof_class: CONNECTIVITY
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - dest=sep
  - ids>=2
  - resp_match=1
  achieved_cells: []
- key: SMU-XBAR-UNMAPPED.S1
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - src=ext_in
  - addr=unmapped
  - resp=DECERR
  achieved_cells: []
- key: SMU-XBAR-UNMAPPED.S2
  required_proof_class: CONNECTIVITY
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells:
  - src=sep_out
  - src=smc_out
  - dest=ext_out_default
  achieved_cells: []
residuals:
- key: DTP-FEAT-GATE.S1
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: DTP-FEAT-GATE.S2
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: DTP-FEAT-GATE.S3
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: DTP-IC-RESET.S2
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-03T14:22:00+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: DTP-IJTAG-SCAN.S1
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: DTP-IJTAG-SCAN.S2
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: DTP-JTAG2AXI-SMC.S1
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: DTP-JTAG2AXI-SMC.S2
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: DTP-OTP-AXIL.S1
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: DTP-OTP-AXIL.S2
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: DTP-OTP-AXIL.S3
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:16:48+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: DTP-STAP-SMC-SEP.S1
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: DTP-STAP-SMC-SEP.S2
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: DTP-STAP-SMC-SEP.S3
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: DTP-XTRIG-CTM.S1
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: DTP-XTRIG-CTP.S1
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: DTP-XTRIG-CTP.S2
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-03T14:22:00+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: INT-ALIAS-VS-XBAR-SMC
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: INT-BOOT-STALL-INTEROP
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-03T14:22:00+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: INT-CLKSTOP-SMC-CLA
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: INT-FEAT-CTRL-DTP-GATE
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: INT-FUSE-SENSE-BOOT
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: INT-MBX-CHALLENGE-IRQ
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:16:48+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: INT-PWRGOOD-DTP-POR
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T08:32:03+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: INT-SEP0-OTP-ERR
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:16:48+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: INT-XBAR-APERTURE-INTEROP
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SEP-BOOT.S1
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SEP-BOOT.S2
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SEP-FUSE-SENSE-HS.S1
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SEP-FUSE-SENSE-HS.S2
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SEP-FUSE-SENSE-HS.S3
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-03T14:22:00+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SEP-LC-FEAT-EXPORT.S1
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SEP-LC-FEAT-EXPORT.S2
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SEP-LC-FEAT-EXPORT.S3
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SEP-MBX-IRQ-SMC.S1
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:16:48+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SEP-MBX-IRQ-SMC.S2
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SEP-MEM-BOUND-PASSTHROUGH.S1
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SEP-MEM-BOUND-PASSTHROUGH.S2
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SEP-MEM-BOUND-PASSTHROUGH.S3
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-03T14:22:00+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SEP-SEC-DIS.S1
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SEP-SEC-DIS.S2
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SEP-SEC-DIS.S3
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-03T14:22:00+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SEP-SYSIF-SMU-XBAR.S1
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T08:32:03+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SEP-SYSIF-SMU-XBAR.S2
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SEP-SYSIF-SMU-XBAR.S3
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SEP-WDT-RST-SMC.S1
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SEP-WDT-RST-SMC.S2
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SMC-AXI-LITE-SHIMS.S1
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SMC-AXI-LITE-SHIMS.S2
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SMC-BOOT.S1
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SMC-BOOT.S2
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SMC-BOOT.S3
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SMC-DECODE-APERTURE.S1
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:36:57+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SMC-DECODE-APERTURE.S2
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T08:32:03+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SMC-DECODE-APERTURE.S3
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:36:57+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SMC-DTP-CSR.S1
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SMC-DTP-CSR.S2
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SMC-FAB-DUAL-NET.S1
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T08:32:03+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SMC-FAB-IN-PORTS.S1
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:37:56+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SMC-FAB-IN-PORTS.S2
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SMC-FAB-IN-PORTS.S3
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SMC-FAB-OUT-SMN.S1
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SMC-FAB-OUT-SMN.S2
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-03T14:22:00+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SMC-FAB-OUT-SMN.S3
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-03T14:22:00+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SMC-MBX-CHANNELS.S1
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SMC-MBX-CHANNELS.S2
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SMC-MBX-CHANNELS.S3
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SMC-MBX-IRQ-EXT.S1
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SMC-PWRGOOD-DTP-POR.S1
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T08:32:03+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SMU-MBX-CHALLENGE.S1
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:16:48+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SMU-MBX-CHALLENGE.S2
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SMU-MBX-CHALLENGE.S3
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-03T14:22:00+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SMU-PORT-CLK-RST.S2
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T08:32:03+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SMU-PORT-SMN-AXI.S2
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SMU-PORT-SMN-AXI.S3
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T08:32:03+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SMU-PORT-SMN-AXI.S4
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SMU-SEP-PARAM.S3
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:16:48+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SMU-SEP-SMC-ALIAS.S1
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SMU-SEP-SMC-ALIAS.S2
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-03T14:22:00+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SMU-SEP-SMC-ALIAS.S3
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SMU-XBAR-APERTURE.S1
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:16:48+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SMU-XBAR-APERTURE.S2
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:16:48+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SMU-XBAR-APERTURE.S3
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-03T14:22:00+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SMU-XBAR-ATOP-REJECT.S1
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:16:48+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SMU-XBAR-ATOP-REJECT.S2
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:16:48+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SMU-XBAR-BACKPRESSURE.S1
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-03T14:22:00+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SMU-XBAR-BACKPRESSURE.S2
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-03T14:22:00+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SMU-XBAR-BACKPRESSURE.S3
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-03T14:22:00+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SMU-XBAR-CONNECT.S1
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SMU-XBAR-CONNECT.S2
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SMU-XBAR-CONNECT.S3
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SMU-XBAR-ID-CONV.S1
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T08:32:03+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SMU-XBAR-ID-CONV.S2
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SMU-XBAR-UNMAPPED.S1
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
- key: SMU-XBAR-UNMAPPED.S2
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: plan unallocated OUT-OF-MILESTONE accepted_by minshaoho at 2026-08-05T17:24:29+08:00
  closes_at_milestone: P3
  review_or_expiry: pin rev 1 / plan rev 18
findings: []
inventory_delta:
  status: CLEAN
  keys: []
  notes: |-
    Reverse-vs-approved inventory compared on prior independent candidate revinv-25b762f8bc46 vs FL r3; residual key-string deltas classified as rename/split, not new omissions. FL content_sha256 unchanged this re-review.
reverse_diff:
  spec_sha256: 88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  generated_inventory_sha256: fd4100e0607d4a4d11e2091041eadb06a16199ffbcf3e0cc0e839fe416fc584b
  run_id: revinv-25b762f8bc46
  actor:
    human_id: minshaoho
    model:
      provider: cursor
      family: grok
      version: '4.5'
  compared_generator:
    run_id: dv_vplan_gen-SMU_ALL-P2-20260805T074000+0800-amend-reverse-omission
    model:
      provider: cursor
      family: grok
      version: '4.5'
  separation_gate_satisfied: true
  reviewed_by: dv-peer-fresh-r18-regrade
  disposition: CLEAN
result: PASS
---

# IP Peer Audit — SMU_ALL, P2 gate (MODE=CHECKBOX-MAPPING)

## EXECUTIVE RESULT

Result: **PASS** — 100% feature-mapped evidence closure for the frozen P2 non-residual required scenario set (26 of 121 inventory keys required at this milestone); MILESTONE-DEFERRED/WAIVED/UNREACHABLE exclusions reported separately.

Required at P2: **26 of 121** inventory keys (95 MILESTONE-DEFERRED excluded from denominator) · Covered: **26 of 26** · REAL-GAP: **0** · BLOCKED: **0** · deferred (excluded): **95** · waived: **0** · findings: 0 Blocking / 0 Major / 0 Minor · reverse_diff disposition: **CLEAN**.

## DELTA (re-review 2026-08-05 post Skill-2 regrade of 001–008 @ cards r18)

Prior advisory was **FAIL** solely because grades SMU_ALL_001–007 carried stale `card_sha256` after plan/cards r18 (judged covered_keys=1). Fresh recomputation:

- All eight grades now match current approved card `record_sha256` (cards r18 / plan r18) and cite pinned `SMU_ALL_QUALITY_POLICY.md@936b7770…`.
- closure.py FACTS: **26/26** PROVEN merge; peer judgment agrees (no freshness override).
- `[ALLOCATION-INTENT-DIFF]`: unmet/accidental/fully_unmet empty.
- reverse_diff remains **CLEAN** on candidate `revinv-25b762f8bc46` vs FL r3 (content unchanged).

## BLOCKING ITEMS

None.

## COVERAGE MAP

| Feature | Tally | Scenario statuses |
|---|---|---|
| SMU-COMPOSE-BLOCKS | 3/3 required · 3 in inventory | SMU-COMPOSE-BLOCKS.S1:COVERED; SMU-COMPOSE-BLOCKS.S2:COVERED; SMU-COMPOSE-BLOCKS.S3:COVERED |
| SMU-PORT-CLK-RST | 2/2 required · 3 in inventory | SMU-PORT-CLK-RST.S1:COVERED; SMU-PORT-CLK-RST.S2:MILESTONE-DEFERRED; SMU-PORT-CLK-RST.S3:COVERED |
| SMU-PORT-SMN-AXI | 1/1 required · 4 in inventory | SMU-PORT-SMN-AXI.S1:COVERED; SMU-PORT-SMN-AXI.S2:MILESTONE-DEFERRED; SMU-PORT-SMN-AXI.S3:MILESTONE-DEFERRED; SMU-PORT-SMN-AXI.S4:MILESTONE-DEFERRED |
| SMU-SEP-PARAM | 2/2 required · 3 in inventory | SMU-SEP-PARAM.S1:COVERED; SMU-SEP-PARAM.S2:COVERED; SMU-SEP-PARAM.S3:MILESTONE-DEFERRED |
| SMU-XBAR-CONNECT | 0/0 required · 3 in inventory (all deferred) | SMU-XBAR-CONNECT.S1:MILESTONE-DEFERRED; SMU-XBAR-CONNECT.S2:MILESTONE-DEFERRED; SMU-XBAR-CONNECT.S3:MILESTONE-DEFERRED |
| SMU-XBAR-APERTURE | 0/0 required · 3 in inventory (all deferred) | SMU-XBAR-APERTURE.S1:MILESTONE-DEFERRED; SMU-XBAR-APERTURE.S2:MILESTONE-DEFERRED; SMU-XBAR-APERTURE.S3:MILESTONE-DEFERRED |
| SMU-XBAR-ATOP-REJECT | 0/0 required · 2 in inventory (all deferred) | SMU-XBAR-ATOP-REJECT.S1:MILESTONE-DEFERRED; SMU-XBAR-ATOP-REJECT.S2:MILESTONE-DEFERRED |
| SMU-XBAR-ID-CONV | 0/0 required · 2 in inventory (all deferred) | SMU-XBAR-ID-CONV.S1:MILESTONE-DEFERRED; SMU-XBAR-ID-CONV.S2:MILESTONE-DEFERRED |
| SMU-XBAR-UNMAPPED | 0/0 required · 2 in inventory (all deferred) | SMU-XBAR-UNMAPPED.S1:MILESTONE-DEFERRED; SMU-XBAR-UNMAPPED.S2:MILESTONE-DEFERRED |
| SMU-XBAR-BACKPRESSURE | 0/0 required · 3 in inventory (all deferred) | SMU-XBAR-BACKPRESSURE.S1:MILESTONE-DEFERRED; SMU-XBAR-BACKPRESSURE.S2:MILESTONE-DEFERRED; SMU-XBAR-BACKPRESSURE.S3:MILESTONE-DEFERRED |
| SMU-SEP-SMC-ALIAS | 0/0 required · 3 in inventory (all deferred) | SMU-SEP-SMC-ALIAS.S1:MILESTONE-DEFERRED; SMU-SEP-SMC-ALIAS.S2:MILESTONE-DEFERRED; SMU-SEP-SMC-ALIAS.S3:MILESTONE-DEFERRED |
| SMC-FAB-DUAL-NET | 2/2 required · 3 in inventory | SMC-FAB-DUAL-NET.S1:MILESTONE-DEFERRED; SMC-FAB-DUAL-NET.S2:COVERED; SMC-FAB-DUAL-NET.S3:COVERED |
| SMC-FAB-IN-PORTS | 0/0 required · 3 in inventory (all deferred) | SMC-FAB-IN-PORTS.S1:MILESTONE-DEFERRED; SMC-FAB-IN-PORTS.S2:MILESTONE-DEFERRED; SMC-FAB-IN-PORTS.S3:MILESTONE-DEFERRED |
| SMC-FAB-OUT-SMN | 0/0 required · 3 in inventory (all deferred) | SMC-FAB-OUT-SMN.S1:MILESTONE-DEFERRED; SMC-FAB-OUT-SMN.S2:MILESTONE-DEFERRED; SMC-FAB-OUT-SMN.S3:MILESTONE-DEFERRED |
| SMC-DECODE-APERTURE | 0/0 required · 3 in inventory (all deferred) | SMC-DECODE-APERTURE.S1:MILESTONE-DEFERRED; SMC-DECODE-APERTURE.S2:MILESTONE-DEFERRED; SMC-DECODE-APERTURE.S3:MILESTONE-DEFERRED |
| SMC-MBX-CHANNELS | 0/0 required · 3 in inventory (all deferred) | SMC-MBX-CHANNELS.S1:MILESTONE-DEFERRED; SMC-MBX-CHANNELS.S2:MILESTONE-DEFERRED; SMC-MBX-CHANNELS.S3:MILESTONE-DEFERRED |
| SMU-MBX-CHALLENGE | 0/0 required · 3 in inventory (all deferred) | SMU-MBX-CHALLENGE.S1:MILESTONE-DEFERRED; SMU-MBX-CHALLENGE.S2:MILESTONE-DEFERRED; SMU-MBX-CHALLENGE.S3:MILESTONE-DEFERRED |
| SEP-MBX-IRQ-SMC | 0/0 required · 2 in inventory (all deferred) | SEP-MBX-IRQ-SMC.S1:MILESTONE-DEFERRED; SEP-MBX-IRQ-SMC.S2:MILESTONE-DEFERRED |
| SMC-MBX-IRQ-EXT | 1/1 required · 2 in inventory | SMC-MBX-IRQ-EXT.S1:MILESTONE-DEFERRED; SMC-MBX-IRQ-EXT.S2:COVERED |
| SMC-PWRGOOD-DTP-POR | 1/1 required · 2 in inventory | SMC-PWRGOOD-DTP-POR.S1:MILESTONE-DEFERRED; SMC-PWRGOOD-DTP-POR.S2:COVERED |
| SMC-RST-PRIMARY-EXPORT | 2/2 required · 2 in inventory | SMC-RST-PRIMARY-EXPORT.S1:COVERED; SMC-RST-PRIMARY-EXPORT.S2:COVERED |
| SMC-DTP-CSR | 0/0 required · 2 in inventory (all deferred) | SMC-DTP-CSR.S1:MILESTONE-DEFERRED; SMC-DTP-CSR.S2:MILESTONE-DEFERRED |
| DTP-JTAG-PTAP | 3/3 required · 3 in inventory | DTP-JTAG-PTAP.S1:COVERED; DTP-JTAG-PTAP.S2:COVERED; DTP-JTAG-PTAP.S3:COVERED |
| DTP-JTAG2AXI-SMC | 0/0 required · 2 in inventory (all deferred) | DTP-JTAG2AXI-SMC.S1:MILESTONE-DEFERRED; DTP-JTAG2AXI-SMC.S2:MILESTONE-DEFERRED |
| DTP-OTP-AXIL | 0/0 required · 3 in inventory (all deferred) | DTP-OTP-AXIL.S1:MILESTONE-DEFERRED; DTP-OTP-AXIL.S2:MILESTONE-DEFERRED; DTP-OTP-AXIL.S3:MILESTONE-DEFERRED |
| DTP-BOOT-STALL | 2/2 required · 2 in inventory | DTP-BOOT-STALL.S1:COVERED; DTP-BOOT-STALL.S2:COVERED |
| DTP-IC-RESET | 2/2 required · 3 in inventory | DTP-IC-RESET.S1:COVERED; DTP-IC-RESET.S2:MILESTONE-DEFERRED; DTP-IC-RESET.S3:COVERED |
| DTP-FEAT-GATE | 0/0 required · 3 in inventory (all deferred) | DTP-FEAT-GATE.S1:MILESTONE-DEFERRED; DTP-FEAT-GATE.S2:MILESTONE-DEFERRED; DTP-FEAT-GATE.S3:MILESTONE-DEFERRED |
| DTP-CLKSTOP-AGG | 3/3 required · 3 in inventory | DTP-CLKSTOP-AGG.S1:COVERED; DTP-CLKSTOP-AGG.S2:COVERED; DTP-CLKSTOP-AGG.S3:COVERED |
| DTP-XTRIG-CTM | 2/2 required · 3 in inventory | DTP-XTRIG-CTM.S1:MILESTONE-DEFERRED; DTP-XTRIG-CTM.S2:COVERED; DTP-XTRIG-CTM.S3:COVERED |
| DTP-XTRIG-CTP | 0/0 required · 2 in inventory (all deferred) | DTP-XTRIG-CTP.S1:MILESTONE-DEFERRED; DTP-XTRIG-CTP.S2:MILESTONE-DEFERRED |
| DTP-STAP-SMC-SEP | 0/0 required · 3 in inventory (all deferred) | DTP-STAP-SMC-SEP.S1:MILESTONE-DEFERRED; DTP-STAP-SMC-SEP.S2:MILESTONE-DEFERRED; DTP-STAP-SMC-SEP.S3:MILESTONE-DEFERRED |
| SEP-SYSIF-SMU-XBAR | 0/0 required · 3 in inventory (all deferred) | SEP-SYSIF-SMU-XBAR.S1:MILESTONE-DEFERRED; SEP-SYSIF-SMU-XBAR.S2:MILESTONE-DEFERRED; SEP-SYSIF-SMU-XBAR.S3:MILESTONE-DEFERRED |
| SEP-LC-FEAT-EXPORT | 0/0 required · 3 in inventory (all deferred) | SEP-LC-FEAT-EXPORT.S1:MILESTONE-DEFERRED; SEP-LC-FEAT-EXPORT.S2:MILESTONE-DEFERRED; SEP-LC-FEAT-EXPORT.S3:MILESTONE-DEFERRED |
| SEP-SEC-DIS | 0/0 required · 3 in inventory (all deferred) | SEP-SEC-DIS.S1:MILESTONE-DEFERRED; SEP-SEC-DIS.S2:MILESTONE-DEFERRED; SEP-SEC-DIS.S3:MILESTONE-DEFERRED |
| SEP-WDT-RST-SMC | 0/0 required · 2 in inventory (all deferred) | SEP-WDT-RST-SMC.S1:MILESTONE-DEFERRED; SEP-WDT-RST-SMC.S2:MILESTONE-DEFERRED |
| SEP-FUSE-SENSE-HS | 0/0 required · 3 in inventory (all deferred) | SEP-FUSE-SENSE-HS.S1:MILESTONE-DEFERRED; SEP-FUSE-SENSE-HS.S2:MILESTONE-DEFERRED; SEP-FUSE-SENSE-HS.S3:MILESTONE-DEFERRED |
| SEP-MEM-BOUND-PASSTHROUGH | 0/0 required · 3 in inventory (all deferred) | SEP-MEM-BOUND-PASSTHROUGH.S1:MILESTONE-DEFERRED; SEP-MEM-BOUND-PASSTHROUGH.S2:MILESTONE-DEFERRED; SEP-MEM-BOUND-PASSTHROUGH.S3:MILESTONE-DEFERRED |
| SMC-BOOT | 0/0 required · 3 in inventory (all deferred) | SMC-BOOT.S1:MILESTONE-DEFERRED; SMC-BOOT.S2:MILESTONE-DEFERRED; SMC-BOOT.S3:MILESTONE-DEFERRED |
| SEP-BOOT | 0/0 required · 2 in inventory (all deferred) | SEP-BOOT.S1:MILESTONE-DEFERRED; SEP-BOOT.S2:MILESTONE-DEFERRED |
| SMC-AXI-LITE-SHIMS | 0/0 required · 2 in inventory (all deferred) | SMC-AXI-LITE-SHIMS.S1:MILESTONE-DEFERRED; SMC-AXI-LITE-SHIMS.S2:MILESTONE-DEFERRED |
| DTP-IJTAG-SCAN | 0/0 required · 2 in inventory (all deferred) | DTP-IJTAG-SCAN.S1:MILESTONE-DEFERRED; DTP-IJTAG-SCAN.S2:MILESTONE-DEFERRED |
| INT-MBX-CHALLENGE-IRQ | 0/0 required · 1 in inventory (all deferred) | INT-MBX-CHALLENGE-IRQ:MILESTONE-DEFERRED |
| INT-FEAT-CTRL-DTP-GATE | 0/0 required · 1 in inventory (all deferred) | INT-FEAT-CTRL-DTP-GATE:MILESTONE-DEFERRED |
| INT-PWRGOOD-DTP-POR | 0/0 required · 1 in inventory (all deferred) | INT-PWRGOOD-DTP-POR:MILESTONE-DEFERRED |
| INT-CLKSTOP-SMC-CLA | 0/0 required · 1 in inventory (all deferred) | INT-CLKSTOP-SMC-CLA:MILESTONE-DEFERRED |
| INT-SEP0-OTP-ERR | 0/0 required · 1 in inventory (all deferred) | INT-SEP0-OTP-ERR:MILESTONE-DEFERRED |
| INT-ALIAS-VS-XBAR-SMC | 0/0 required · 1 in inventory (all deferred) | INT-ALIAS-VS-XBAR-SMC:MILESTONE-DEFERRED |
| INT-BOOT-STALL-INTEROP | 0/0 required · 1 in inventory (all deferred) | INT-BOOT-STALL-INTEROP:MILESTONE-DEFERRED |
| INT-FUSE-SENSE-BOOT | 0/0 required · 1 in inventory (all deferred) | INT-FUSE-SENSE-BOOT:MILESTONE-DEFERRED |
| INT-XBAR-APERTURE-INTEROP | 0/0 required · 1 in inventory (all deferred) | INT-XBAR-APERTURE-INTEROP:MILESTONE-DEFERRED |

All 26 milestone-required scenario keys are COVERED. Scenario-level hole rows: none.

## FINDINGS

None.

## RESIDUAL LEDGER

MILESTONE-DEFERRED (counts_against_closure=false; authority_kind=PLAN-ROW; closes_at_milestone=P3) — 95 keys (all signed OUT-OF-MILESTONE → P3; accepted_by minshaoho on plan r18). Full key list is in YAML `residuals[]`.

REAL-GAP / BLOCKED / WAIVED / OUT-OF-SCOPE / UNREACHABLE — none.

## MACHINERY APPENDIX

Normative YAML (denominator, coverage[], residuals[], reverse_diff, hashes) is in the front matter of this file.

Sampling / re-verification:
- Tier-A PROVENs: none (all eight current cards closure_tier B).
- Sample floor: 20% of 41 PROVEN checkers → 8; peer re-verified ≥8 scenario-covering PROVENs across all eight grades (mailbox S2, axi_xbar PWRGOOD S2, external_port SMN-AXI S1, clock_stop BOOT-STALL S1 + CLKSTOP-AGG S1, dtp_jtag PTAP S1, sep_smoke RST-PRIMARY S1, smc_smoke FAB-DUAL-NET S2, wrapper COMPOSE S1). Kept-log sha256 matched grade manifests; CHK-*: PASS / COVERAGE tokens present; no false-PROVEN in sample.
- Independent reproduce: not required for tier-B / non-security numerator under pinned policy; IE method NOT-REQUIRED with gate_satisfied derived true.
- Cross-testcase claim matrix: no polarity/value conflicts among the 26 COVERED keys (disjoint scenario ownership; shared cells consistent where overlapping features use distinct scenarios).
- O2: each grade's PROVEN coverage keys are a subset of its current card owns/PROOF targets — no wrong-target diffs.
- E3: all eight plan-approved allocated anchors enrolled in `hw/sys/smu/dv/testlists/`.
- Shared infra / common-mode: no force/deposit exception gaps on sampled paths; build fingerprints recorded per grade.
- Reverse inventory: candidate content_sha256 fd4100e0… / run_id revinv-25b762f8bc46 vs FL content_sha256 4b37c7ba…; actor run_id ≠ compared_generator run_id → separation_gate_satisfied true (derived). FL `anchor_seal_mechanism: ordered-single-context` noted (widen caution only; not a finding).
- Freeze: pin file sha 2f6d5079…; FL content 4b37c7ba…; plan content be84741e… (r18); cards content 9accd399… (r18); quality_policy 936b7770…; eight grade content_sha256 listed in front matter.
- Closure statement eligible: CHECKBOX-MAPPING with approved FL+plan+cards; 26/26 PROVEN at required proof class; holes only valid MILESTONE-DEFERRED.
