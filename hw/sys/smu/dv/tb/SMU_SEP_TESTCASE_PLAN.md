---
schema: dv-quality/v1
artifact: testcase-plan
artifact_revision: 1
content_sha256: 62dbac82d1c065ca21815bcedd8f4cf3b3c66b695a976f21d4a9ded1df5ab1c2
ip: SMU_SEP
milestone: P2
status: candidate
pin_revision: 1
spec:
- path: hw/sys/smu/doc/SMU_SPEC.md
  revision: 88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
- path: hw/sys/smu/doc/port_table.adoc
  revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
- path: hw/sys/sep/doc/index.adoc
  revision: 06ed854b2f40c7a31468fdcd6e535d21378ede5e
- path: hw/sys/sep/doc/introduction.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/sep/doc/overview.adoc
  revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
- path: hw/sys/sep/doc/fabric.adoc
  revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
- path: hw/sys/sep/doc/cpu.adoc
  revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
- path: hw/sys/sep/doc/crypto.adoc
  revision: 06ed854b2f40c7a31468fdcd6e535d21378ede5e
- path: hw/sys/sep/doc/periphs.adoc
  revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
- path: hw/sys/sep/doc/memory_map.adoc
  revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
- path: hw/sys/sep/doc/port_table.adoc
  revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
- path: hw/sys/sep/doc/lifecycle_controller.adoc
  revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
- path: hw/sys/sep/doc/security_disable.adoc
  revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
- path: hw/sys/sep/doc/test_mode.adoc
  revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
- path: hw/sys/sep/doc/token_processing.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/smc/doc/index.adoc
  revision: 06ed854b2f40c7a31468fdcd6e535d21378ede5e
- path: hw/sys/smc/doc/overview.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/smc/doc/fabric.adoc
  revision: ffc8cdcc349e1e01a2b970442a01070b1c62c0d7
- path: hw/sys/smc/doc/memmap.adoc
  revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
- path: hw/sys/smc/doc/interrupts.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
source_revision: c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7
quality_policy:
  path: hw/sys/smu/dv/tb/SMU_ALL_QUALITY_POLICY.md
  revision: 936b77700909a93bb122f9fb124a3ffb6f5dac5f508c623c5950285a5cefb79a
generated_by:
  human_id: minshaoho
  run_id: smu-sep-skill1-20260807
  model:
    provider: cursor
    family: grok
    version: '4.5'
derivation_provenance:
  sealed_derivation: false
  anchor_seal_mechanism: ordered-single-context
  fresh_context_route: fresh-subagent
  feature_list_frozen_at: '2026-08-07T17:45:00+08:00'
approved_by: null
approved_at: null
plan_revision: 1
anchor_mode: augment
derived_from:
  feature_list_revision: 1
  feature_list_sha256: a78ab08448e2271e9a4c9f9b4e85538f40fb53a553b5046d66d42732f8a5dcd4
testcases:
- id: SEP_SMU_001
  anchor: smu_sep_smoke_test
  origin: given
  revision: 1
  supersedes_revision: null
  current: true
  status: candidate
  record_sha256: cc12d2c296a455e20de80c7a0e6de9688d8eb749fe753ae7b300cd7fe070a927
  approved_by: null
  approved_at: null
  intent: SEP is composed under SEP=1, held/released through SMC reset, fuse-authorized, and boots BL0
  category: SEP boot/reset/fuse foundation
  owns: Boot/reset/fuse/ROM foundation only (no xbar/mailbox/filter)
  evidence_class: strict-e2e
  closure_tier: A
  allocated:
    features:
    - SEP-COMPOSE-ENABLE
    - SEP-RESET-CONTROL
    - SEP-FUSE-SENSE-HANDSHAKE
    - SEP-ROM-BOOT-ENABLE
    scenarios:
    - SEP-COMPOSE-ENABLE.S1
    - SEP-RESET-CONTROL.S1
    - SEP-RESET-CONTROL.S2
    - SEP-RESET-CONTROL.S3
    - SEP-FUSE-SENSE-HANDSHAKE.S1
    - SEP-ROM-BOOT-ENABLE.S1
    - SEP-ROM-BOOT-ENABLE.S2
    - INT-FUSE-AUTH-TO-ROM
  rationale: 'One path: top-pin power/reset into real SMC reset unit into SEP reset/fuse/ROM boot'
  size_justification: null
  reuse: smu_sep_smoke_test (rewritten in place)
  blockers: []
- id: SEP_SMU_002
  anchor: smu_fuse_sense_handshake_test
  origin: given
  revision: 1
  supersedes_revision: null
  current: true
  status: candidate
  record_sha256: d3cc7c418555098616072741cdd339a79550bcf4731fb7d86ae1fe39351c874a
  approved_by: null
  approved_at: null
  intent: SEP fuse_sense_done is exported at the SMU boundary after SMC authorization
  category: SEP fuse-sense export
  owns: sep_fuse_sense_done_o export only
  evidence_class: frontdoor-func
  closure_tier: A
  allocated:
    features:
    - SEP-FUSE-SENSE-HANDSHAKE
    scenarios:
    - SEP-FUSE-SENSE-HANDSHAKE.S2
  rationale: 'One path: SEP fuse completion to SMU-exported sep_fuse_sense_done_o'
  size_justification: null
  reuse: smu_fuse_sense_handshake_test (rewritten in place)
  blockers: []
- id: SEP_SMU_003
  anchor: smu_sep_smc_alias_remap_consistency_test
  origin: given
  revision: 1
  supersedes_revision: null
  current: true
  status: candidate
  record_sha256: 8c9c8224a7a3f656f5d302c090f9985c9ebbca485f56982e3953d3f080decfcb
  approved_by: null
  approved_at: null
  intent: SEP→SMC fixed alias remap delivers correct SMC addresses on the dedicated path
  category: SEP→SMC alias remap
  owns: Alias remap path and SMC aperture bound only
  evidence_class: strict-e2e
  closure_tier: A
  allocated:
    features:
    - SEP-SMC-ALIAS-REMAP
    scenarios:
    - SEP-SMC-ALIAS-REMAP.S1
    - SEP-SMC-ALIAS-REMAP.S2
    - SEP-SMC-ALIAS-REMAP.S3
  rationale: 'One path: SEP access in 0x4000_0000 window through dedicated alias remap into SMC'
  size_justification: null
  reuse: smu_sep_smc_alias_remap_consistency_test (rewritten in place)
  blockers: []
- id: SEP_SMU_004
  anchor: smu_sep_alias_mailbox_interrupt_probe_test
  origin: given
  revision: 1
  supersedes_revision: null
  current: true
  status: candidate
  record_sha256: 3a594b390d6cf26f85bf731c93727dd00d34a41e3630055e2dac4845b2ac5b27
  approved_by: null
  approved_at: null
  intent: SEP↔SMC mailbox payload exchange and SEP mailbox IRQs into SMC
  category: SEP mailbox interop
  owns: Mailbox data + IRQ crossing only (alias used as transport)
  evidence_class: strict-e2e
  closure_tier: A
  allocated:
    features:
    - SEP-MAILBOX-IRQ-TO-SMC
    - SEP-MAILBOX-DATA-EXCHANGE
    - SEP-SMC-ALIAS-REMAP
    scenarios:
    - SEP-MAILBOX-IRQ-TO-SMC.S1
    - SEP-MAILBOX-IRQ-TO-SMC.S2
    - SEP-MAILBOX-IRQ-TO-SMC.S3
    - SEP-MAILBOX-DATA-EXCHANGE.S1
    - SEP-MAILBOX-DATA-EXCHANGE.S2
    - SEP-MAILBOX-DATA-EXCHANGE.S3
    - INT-ALIAS-MAILBOX
  rationale: 'One path: alias-reachable SMC mailbox region for payload + IRQ sideband into SMC aggregator'
  size_justification: 7 scenarios + interaction share one mailbox interop setup; still <=12 steps/checkers
  reuse: smu_sep_alias_mailbox_interrupt_probe_test (rewritten in place)
  blockers: []
- id: SEP_SMU_005
  anchor: smu_sep_smc_xbar_programmable_addr_test
  origin: given
  revision: 1
  supersedes_revision: null
  current: true
  status: candidate
  record_sha256: bb862432d04234c6fe5f32cd20c8f5a1d95019b1ddfeeb1a59fa8be8390e7f66
  approved_by: null
  approved_at: null
  intent: SEP participates in SMU xbar decode, connectivity matrix, and programmed apertures
  category: SEP SMU xbar sysif/aperture/connectivity
  owns: SMU xbar SEP ports only (not alias path)
  evidence_class: strict-e2e
  closure_tier: A
  allocated:
    features:
    - SEP-XBAR-SYSIF
    - SEP-XBAR-APERTURE
    - SEP-XBAR-CONNECTIVITY
    scenarios:
    - SEP-XBAR-SYSIF.S1
    - SEP-XBAR-SYSIF.S2
    - SEP-XBAR-SYSIF.S3
    - SEP-XBAR-APERTURE.S1
    - SEP-XBAR-APERTURE.S2
    - SEP-XBAR-CONNECTIVITY.S1
    - SEP-XBAR-CONNECTIVITY.S2
    - SEP-XBAR-CONNECTIVITY.S3
  rationale: 'One path: SMU axi_xbar SEP slave/master ports with CSR apertures and connectivity rules'
  size_justification: 8 xbar scenarios share one aperture-programmed fabric setup
  reuse: smu_sep_smc_xbar_programmable_addr_test (rewritten in place)
  blockers:
  - SF-006
- id: SEP_SMU_006
  anchor: smu_lifecycle_security_handoff_test
  origin: given
  revision: 1
  supersedes_revision: null
  current: true
  status: candidate
  record_sha256: 5521761a3b5df69c2fbeb0f2c6c82a584764c8c9c869f7ad36097a1caf58d41b
  approved_by: null
  approved_at: null
  intent: SEP lifecycle state, feat_ctrl, and security_disable export as the SMU security handoff
  category: SEP lifecycle/security handoff
  owns: LC state + feat_ctrl profile + security_disable export
  evidence_class: strict-e2e
  closure_tier: A
  allocated:
    features:
    - SEP-FEAT-CTRL-EXPORT
    - SEP-LC-STATE-EXPORT
    - SEP-SECURITY-DISABLE-EXPORT
    scenarios:
    - SEP-FEAT-CTRL-EXPORT.S1
    - SEP-LC-STATE-EXPORT.S1
    - SEP-LC-STATE-EXPORT.S3
    - SEP-SECURITY-DISABLE-EXPORT.S1
    - INT-FEAT-LC-HANDOFF
  rationale: 'One path: SEP LCC exports lc_state/feat_ctrl/security_disable at SMU boundary into SMC/DTP'
  size_justification: null
  reuse: smu_lifecycle_security_handoff_test (rewritten in place)
  blockers: []
- id: SEP_SMU_007
  anchor: smu_feat_ctrl_monitor_test
  origin: given
  revision: 1
  supersedes_revision: null
  current: true
  status: candidate
  record_sha256: 76bc4f3e7abdc38bd7977b42a9449dd2ef3d289c22712192752f6b03995d1b59
  approved_by: null
  approved_at: null
  intent: feat_ctrl fail-closed and demote-altered profiles are observed at the SMU export
  category: SEP feat_ctrl profile variants
  owns: feat_ctrl fail-closed and demote profiles only
  evidence_class: frontdoor-func
  closure_tier: B
  allocated:
    features:
    - SEP-FEAT-CTRL-EXPORT
    scenarios:
    - SEP-FEAT-CTRL-EXPORT.S2
    - SEP-FEAT-CTRL-EXPORT.S3
  rationale: 'One path: LCC integrity/demote inputs changing feat_ctrl_o at SMU'
  size_justification: null
  reuse: smu_feat_ctrl_monitor_test (rewritten in place)
  blockers: []
- id: SEP_SMU_008
  anchor: smu_sep_wdt_reset_to_smc_test
  origin: given
  revision: 1
  supersedes_revision: null
  current: true
  status: candidate
  record_sha256: a347f8f8c308fb394144aa494c1bae6e4a50794664b3bc46f1b5924ad697dd25
  approved_by: null
  approved_at: null
  intent: SEP WDT bark/bite crosses into the SMC SEP-watchdog interrupt/reset indication
  category: SEP WDT→SMC
  owns: WDT bark vs bite into SMC IRQ path only
  evidence_class: strict-e2e
  closure_tier: A
  allocated:
    features:
    - SEP-WDT-RESET-TO-SMC
    scenarios:
    - SEP-WDT-RESET-TO-SMC.S1
    - SEP-WDT-RESET-TO-SMC.S2
    - SEP-WDT-RESET-TO-SMC.S3
  rationale: 'One path: SEP aon_timer WDT timeouts into SMC peripheral interrupt aggregation'
  size_justification: null
  reuse: smu_sep_wdt_reset_to_smc_test (rewritten in place)
  blockers:
  - SF-007
- id: SEP_SMU_009
  anchor: smu_sep_outbound_demux_decode_test
  origin: given
  revision: 1
  supersedes_revision: null
  current: true
  status: candidate
  record_sha256: f2f1e21dd382c07e45594b6fe0e404728bd86680bd4f83d5f6d5305d9ebe392f
  approved_by: null
  approved_at: null
  intent: SEP outbound demux selects SMC vs SMN vs local for address classes
  category: SEP outbound demux
  owns: Outbound demux decode only
  evidence_class: strict-e2e
  closure_tier: A
  allocated:
    features:
    - SEP-OUTBOUND-DEMUX
    scenarios:
    - SEP-OUTBOUND-DEMUX.S1
    - SEP-OUTBOUND-DEMUX.S2
    - SEP-OUTBOUND-DEMUX.S3
  rationale: 'One path: SEP system-peripherals outbound address demux'
  size_justification: null
  reuse: smu_sep_outbound_demux_decode_test (rewritten in place)
  blockers: []
- id: SEP_SMU_010
  anchor: smu_sep_filter_rule_matrix_test
  origin: given
  revision: 1
  supersedes_revision: null
  current: true
  status: candidate
  record_sha256: f93595830c2f5846a1b6bfc3095e1ecab24c93b1d49c9a3d7517aa498a237067
  approved_by: null
  approved_at: null
  intent: SEP inbound default-deny/allow/STEE rules and outbound filter allow/deny
  category: SEP inbound/outbound filters
  owns: Inbound+outbound filter rule matrix only
  evidence_class: strict-e2e
  closure_tier: A
  allocated:
    features:
    - SEP-INBOUND-FILTER
    - SEP-OUTBOUND-FILTER
    scenarios:
    - SEP-INBOUND-FILTER.S1
    - SEP-INBOUND-FILTER.S2
    - SEP-INBOUND-FILTER.S3
    - SEP-OUTBOUND-FILTER.S1
    - SEP-OUTBOUND-FILTER.S2
  rationale: 'One path: SEP CPU programs filter CSRs; external/outbound traffic hits allow/deny'
  size_justification: null
  reuse: smu_sep_filter_rule_matrix_test (rewritten in place)
  blockers: []
- id: SEP_SMU_011
  anchor: smu_sep_ap_stee_output_remap_test
  origin: given
  revision: 1
  supersedes_revision: null
  current: true
  status: candidate
  record_sha256: a17d31d7b17ee107e9ffa0389633749a760fb4522aecf6350438ed0904544b6a
  approved_by: null
  approved_at: null
  intent: AP/STEE remap windows pass-through then translate per programmed region attributes
  category: SEP AP/STEE remap
  owns: AP/STEE remap regions only
  evidence_class: strict-e2e
  closure_tier: B
  allocated:
    features:
    - SEP-AP-STEE-REMAP
    scenarios:
    - SEP-AP-STEE-REMAP.S1
    - SEP-AP-STEE-REMAP.S2
    - SEP-AP-STEE-REMAP.S3
  rationale: 'One path: SEP writes into AP/STEE remap windows through remappers to outbound'
  size_justification: null
  reuse: smu_sep_ap_stee_output_remap_test (rewritten in place)
  blockers: []
- id: SEP_SMU_012
  anchor: smu_sep_memory_integrity_test
  origin: given
  revision: 1
  supersedes_revision: null
  current: true
  status: candidate
  record_sha256: 6ae7087e32d132c45495110974396a95f27293f84a3ea2a6ce01acb1754dd799
  approved_by: null
  approved_at: null
  intent: SEP TCM/SRAM/Boot-ROM ports at SMU show correct boundary activity
  category: SEP memory ports
  owns: TCM/SRAM/ROM port observability only
  evidence_class: strict-e2e
  closure_tier: A
  allocated:
    features:
    - SEP-MEMORY-PORT-OBS
    scenarios:
    - SEP-MEMORY-PORT-OBS.S1
    - SEP-MEMORY-PORT-OBS.S2
    - SEP-MEMORY-PORT-OBS.S3
  rationale: 'One path: SEP execution exercising SMU-passthrough memory macro ports'
  size_justification: null
  reuse: smu_sep_memory_integrity_test (rewritten in place)
  blockers: []
- id: SEP_SMU_013
  anchor: smu_sep_km_otbn_memory_test
  origin: given
  revision: 1
  supersedes_revision: null
  current: true
  status: candidate
  record_sha256: 1f673960a797b0de63b99a00ea399f2076d0c2edb3d443f7114119e0a27f2496
  approved_by: null
  approved_at: null
  intent: SEP AES/OTBN/KM boundary ports are exercisable at SMU without deep crypto proof
  category: SEP crypto ports
  owns: AES/OTBN/KM SMU-visible ports only
  evidence_class: frontdoor-func
  closure_tier: B
  allocated:
    features:
    - SEP-CRYPTO-PORT-OBS
    scenarios:
    - SEP-CRYPTO-PORT-OBS.S1
    - SEP-CRYPTO-PORT-OBS.S2
    - SEP-CRYPTO-PORT-OBS.S3
  rationale: 'One path: SEP programs crypto CSRs/memories observed on SMU passthrough ports'
  size_justification: null
  reuse: smu_sep_km_otbn_memory_test (rewritten in place)
  blockers: []
- id: SEP_SMU_014
  anchor: smu_sep_dma_test
  origin: given
  revision: 1
  supersedes_revision: null
  current: true
  status: candidate
  record_sha256: 50b88fd9439b417c2e6aa6ccafdd9ba0c4323d4d342b22bca7b220d7066219a4
  approved_by: null
  approved_at: null
  intent: SEP DMA CSR kickoff and TCM preload complete at the SMU-visible fabric/memory boundary
  category: SEP DMA ports
  owns: DMA CSR and TCM preload only
  evidence_class: strict-e2e
  closure_tier: B
  allocated:
    features:
    - SEP-DMA-PORT-OBS
    scenarios:
    - SEP-DMA-PORT-OBS.S1
    - SEP-DMA-PORT-OBS.S2
  rationale: 'One path: SEP DMA master moving data into TCM/SRAM observed at boundary'
  size_justification: null
  reuse: smu_sep_dma_test (rewritten in place)
  blockers: []
- id: SEP_SMU_015
  anchor: smu_sep_spi_bridge_test
  origin: given
  revision: 1
  supersedes_revision: null
  current: true
  status: candidate
  record_sha256: 2a73799a95e8aed199f2bf925c822fd5fe6bb8ac353546ee561b6c5bc250d097
  approved_by: null
  approved_at: null
  intent: SEP SPI host request and muxed SPI IRQ are visible at SMU
  category: SEP SPI ports
  owns: SPI req/IRQ mux only
  evidence_class: frontdoor-func
  closure_tier: B
  allocated:
    features:
    - SEP-SPI-PORT-OBS
    scenarios:
    - SEP-SPI-PORT-OBS.S1
    - SEP-SPI-PORT-OBS.S2
  rationale: 'One path: SEP SPI programming to SMU SPI pads/IRQ mux'
  size_justification: null
  reuse: smu_sep_spi_bridge_test (rewritten in place)
  blockers: []
- id: SEP_SMU_016
  anchor: smu_sep_efuse_test
  origin: given
  revision: 1
  supersedes_revision: null
  current: true
  status: candidate
  record_sha256: e56863a99bd290691364975070aa20348248088cf008450face0d03a6cd8fdf5
  approved_by: null
  approved_at: null
  intent: SEP eFuse bank/command and JTAG-OTP paths complete at SMU eFuse ports
  category: SEP eFuse ports
  owns: eFuse bank/command/JTAG-OTP only
  evidence_class: strict-e2e
  closure_tier: A
  allocated:
    features:
    - SEP-EFUSE-PORT-OBS
    scenarios:
    - SEP-EFUSE-PORT-OBS.S1
    - SEP-EFUSE-PORT-OBS.S2
    - SEP-EFUSE-PORT-OBS.S3
  rationale: 'One path: SEP/DTP eFuse transactions through SMU passthrough to eFuse shim'
  size_justification: null
  reuse: smu_sep_efuse_test (rewritten in place)
  blockers: []
unallocated:
- key: SEP-COMPOSE-ENABLE.S2
  reason: OUT-OF-MILESTONE
  detail: SEP=0 compile-time tie-off matrix deferred to P3
  downstream_class: out-of-scope
  accepted_by: null
  accepted_at: null
- key: SEP-RESET-CONTROL.S4
  reason: OUT-OF-MILESTONE
  detail: reset-mid-window contested stress deferred to P3
  downstream_class: out-of-scope
  accepted_by: null
  accepted_at: null
- key: SEP-XBAR-APERTURE.S3
  reason: OUT-OF-MILESTONE
  detail: live aperture reprogram-under-traffic deferred to P3
  downstream_class: out-of-scope
  accepted_by: null
  accepted_at: null
- key: SEP-LC-STATE-EXPORT.S2
  reason: OUT-OF-MILESTONE
  detail: SEP=0 lc_state_o=8'hf0 build matrix deferred to P3
  downstream_class: out-of-scope
  accepted_by: null
  accepted_at: null
- key: SEP-SECURITY-DISABLE-EXPORT.S2
  reason: BLOCKED-BY-SPEC-FINDING
  detail: blocked by open SF-005 (SEC_DIS token match exactness at SMU bind point)
  downstream_class: blocked
  accepted_by: null
  accepted_at: null
- key: SEP-SECURITY-DISABLE-EXPORT.S3
  reason: BLOCKED-BY-SPEC-FINDING
  detail: blocked by open SF-005 (SEC_DIS token mismatch exactness)
  downstream_class: blocked
  accepted_by: null
  accepted_at: null
- key: SEP-TEST-MODE-SECURE-TM.S1
  reason: OUT-OF-MILESTONE
  detail: SECURE_TM latch timing matrix deferred to P3
  downstream_class: out-of-scope
  accepted_by: null
  accepted_at: null
- key: SEP-TEST-MODE-SECURE-TM.S2
  reason: OUT-OF-MILESTONE
  detail: SECURE_TM clear-on-reset matrix deferred to P3
  downstream_class: out-of-scope
  accepted_by: null
  accepted_at: null
- key: SEP-OUTBOUND-FILTER.S3
  reason: BLOCKED-BY-SPEC-FINDING
  detail: blocked by open SF-001 (SMC-egress vs outbound filter relationship unspecified)
  downstream_class: blocked
  accepted_by: null
  accepted_at: null
- key: SEP-AXI-EXTENSION.S1
  reason: OUT-OF-MILESTONE
  detail: AXI extension port decode deferred to P3 (review-budget; pinned smu_sep_axi_extension_decode_test
    unused this rev)
  downstream_class: out-of-scope
  accepted_by: null
  accepted_at: null
- key: SEP-AXI-EXTENSION.S2
  reason: OUT-OF-MILESTONE
  detail: AXI extension DECERR tie-off deferred to P3
  downstream_class: out-of-scope
  accepted_by: null
  accepted_at: null
- key: SEP-DEBUG-BUS-EXPORT.S1
  reason: OUT-OF-MILESTONE
  detail: debug bus export observability deferred to P3 (pinned smu_sep_debug_bus_test unused this rev)
  downstream_class: out-of-scope
  accepted_by: null
  accepted_at: null
- key: SEP-EXTERNAL-IRQ.S1
  reason: OUT-OF-MILESTONE
  detail: SEP external IRQ pending deferred to P3 (pinned smu_sep_external_irq_test unused this rev)
  downstream_class: out-of-scope
  accepted_by: null
  accepted_at: null
- key: SEP-EXTERNAL-IRQ.S2
  reason: OUT-OF-MILESTONE
  detail: SEP external IRQ clear deferred to P3
  downstream_class: out-of-scope
  accepted_by: null
  accepted_at: null
- key: SEP-IC-RESET-EXT-SLICE.S1
  reason: OUT-OF-MILESTONE
  detail: IC_RESET SEP slice assert deferred to P3 (pinned smu_ic_reset_sep_ext_slice_test unused this
    rev)
  downstream_class: out-of-scope
  accepted_by: null
  accepted_at: null
- key: SEP-IC-RESET-EXT-SLICE.S2
  reason: OUT-OF-MILESTONE
  detail: IC_RESET SEP slice release deferred to P3
  downstream_class: out-of-scope
  accepted_by: null
  accepted_at: null
---

# SMU_SEP — Testcase Plan (candidate)

- anchor_mode: augment · plan_revision: 1 · parent FL sha `a78ab08448e2…`
- testcases: 16 (all origin:given / pinned reuse) · unallocated: 16
- Review budget: 16 cards = policy max_cards_per_packet; remaining pinned anchors listed on TESTCASE_REVIEW as unused-this-rev.

## Testcases

### SEP_SMU_001 — `smu_sep_smoke_test` (given)
- Intent: SEP is composed under SEP=1, held/released through SMC reset, fuse-authorized, and boots BL0
- OWNS: Boot/reset/fuse/ROM foundation only (no xbar/mailbox/filter)
- Evidence/Tier: strict-e2e / A
- Allocated scenarios: ['SEP-COMPOSE-ENABLE.S1', 'SEP-RESET-CONTROL.S1', 'SEP-RESET-CONTROL.S2', 'SEP-RESET-CONTROL.S3', 'SEP-FUSE-SENSE-HANDSHAKE.S1', 'SEP-ROM-BOOT-ENABLE.S1', 'SEP-ROM-BOOT-ENABLE.S2', 'INT-FUSE-AUTH-TO-ROM']
- Rationale: One path: top-pin power/reset into real SMC reset unit into SEP reset/fuse/ROM boot

### SEP_SMU_002 — `smu_fuse_sense_handshake_test` (given)
- Intent: SEP fuse_sense_done is exported at the SMU boundary after SMC authorization
- OWNS: sep_fuse_sense_done_o export only
- Evidence/Tier: frontdoor-func / A
- Allocated scenarios: ['SEP-FUSE-SENSE-HANDSHAKE.S2']
- Rationale: One path: SEP fuse completion to SMU-exported sep_fuse_sense_done_o

### SEP_SMU_003 — `smu_sep_smc_alias_remap_consistency_test` (given)
- Intent: SEP→SMC fixed alias remap delivers correct SMC addresses on the dedicated path
- OWNS: Alias remap path and SMC aperture bound only
- Evidence/Tier: strict-e2e / A
- Allocated scenarios: ['SEP-SMC-ALIAS-REMAP.S1', 'SEP-SMC-ALIAS-REMAP.S2', 'SEP-SMC-ALIAS-REMAP.S3']
- Rationale: One path: SEP access in 0x4000_0000 window through dedicated alias remap into SMC

### SEP_SMU_004 — `smu_sep_alias_mailbox_interrupt_probe_test` (given)
- Intent: SEP↔SMC mailbox payload exchange and SEP mailbox IRQs into SMC
- OWNS: Mailbox data + IRQ crossing only (alias used as transport)
- Evidence/Tier: strict-e2e / A
- Allocated scenarios: ['SEP-MAILBOX-IRQ-TO-SMC.S1', 'SEP-MAILBOX-IRQ-TO-SMC.S2', 'SEP-MAILBOX-IRQ-TO-SMC.S3', 'SEP-MAILBOX-DATA-EXCHANGE.S1', 'SEP-MAILBOX-DATA-EXCHANGE.S2', 'SEP-MAILBOX-DATA-EXCHANGE.S3', 'INT-ALIAS-MAILBOX']
- Rationale: One path: alias-reachable SMC mailbox region for payload + IRQ sideband into SMC aggregator

### SEP_SMU_005 — `smu_sep_smc_xbar_programmable_addr_test` (given)
- Intent: SEP participates in SMU xbar decode, connectivity matrix, and programmed apertures
- OWNS: SMU xbar SEP ports only (not alias path)
- Evidence/Tier: strict-e2e / A
- Allocated scenarios: ['SEP-XBAR-SYSIF.S1', 'SEP-XBAR-SYSIF.S2', 'SEP-XBAR-SYSIF.S3', 'SEP-XBAR-APERTURE.S1', 'SEP-XBAR-APERTURE.S2', 'SEP-XBAR-CONNECTIVITY.S1', 'SEP-XBAR-CONNECTIVITY.S2', 'SEP-XBAR-CONNECTIVITY.S3']
- Rationale: One path: SMU axi_xbar SEP slave/master ports with CSR apertures and connectivity rules

### SEP_SMU_006 — `smu_lifecycle_security_handoff_test` (given)
- Intent: SEP lifecycle state, feat_ctrl, and security_disable export as the SMU security handoff
- OWNS: LC state + feat_ctrl profile + security_disable export
- Evidence/Tier: strict-e2e / A
- Allocated scenarios: ['SEP-FEAT-CTRL-EXPORT.S1', 'SEP-LC-STATE-EXPORT.S1', 'SEP-LC-STATE-EXPORT.S3', 'SEP-SECURITY-DISABLE-EXPORT.S1', 'INT-FEAT-LC-HANDOFF']
- Rationale: One path: SEP LCC exports lc_state/feat_ctrl/security_disable at SMU boundary into SMC/DTP

### SEP_SMU_007 — `smu_feat_ctrl_monitor_test` (given)
- Intent: feat_ctrl fail-closed and demote-altered profiles are observed at the SMU export
- OWNS: feat_ctrl fail-closed and demote profiles only
- Evidence/Tier: frontdoor-func / B
- Allocated scenarios: ['SEP-FEAT-CTRL-EXPORT.S2', 'SEP-FEAT-CTRL-EXPORT.S3']
- Rationale: One path: LCC integrity/demote inputs changing feat_ctrl_o at SMU

### SEP_SMU_008 — `smu_sep_wdt_reset_to_smc_test` (given)
- Intent: SEP WDT bark/bite crosses into the SMC SEP-watchdog interrupt/reset indication
- OWNS: WDT bark vs bite into SMC IRQ path only
- Evidence/Tier: strict-e2e / A
- Allocated scenarios: ['SEP-WDT-RESET-TO-SMC.S1', 'SEP-WDT-RESET-TO-SMC.S2', 'SEP-WDT-RESET-TO-SMC.S3']
- Rationale: One path: SEP aon_timer WDT timeouts into SMC peripheral interrupt aggregation

### SEP_SMU_009 — `smu_sep_outbound_demux_decode_test` (given)
- Intent: SEP outbound demux selects SMC vs SMN vs local for address classes
- OWNS: Outbound demux decode only
- Evidence/Tier: strict-e2e / A
- Allocated scenarios: ['SEP-OUTBOUND-DEMUX.S1', 'SEP-OUTBOUND-DEMUX.S2', 'SEP-OUTBOUND-DEMUX.S3']
- Rationale: One path: SEP system-peripherals outbound address demux

### SEP_SMU_010 — `smu_sep_filter_rule_matrix_test` (given)
- Intent: SEP inbound default-deny/allow/STEE rules and outbound filter allow/deny
- OWNS: Inbound+outbound filter rule matrix only
- Evidence/Tier: strict-e2e / A
- Allocated scenarios: ['SEP-INBOUND-FILTER.S1', 'SEP-INBOUND-FILTER.S2', 'SEP-INBOUND-FILTER.S3', 'SEP-OUTBOUND-FILTER.S1', 'SEP-OUTBOUND-FILTER.S2']
- Rationale: One path: SEP CPU programs filter CSRs; external/outbound traffic hits allow/deny

### SEP_SMU_011 — `smu_sep_ap_stee_output_remap_test` (given)
- Intent: AP/STEE remap windows pass-through then translate per programmed region attributes
- OWNS: AP/STEE remap regions only
- Evidence/Tier: strict-e2e / B
- Allocated scenarios: ['SEP-AP-STEE-REMAP.S1', 'SEP-AP-STEE-REMAP.S2', 'SEP-AP-STEE-REMAP.S3']
- Rationale: One path: SEP writes into AP/STEE remap windows through remappers to outbound

### SEP_SMU_012 — `smu_sep_memory_integrity_test` (given)
- Intent: SEP TCM/SRAM/Boot-ROM ports at SMU show correct boundary activity
- OWNS: TCM/SRAM/ROM port observability only
- Evidence/Tier: strict-e2e / A
- Allocated scenarios: ['SEP-MEMORY-PORT-OBS.S1', 'SEP-MEMORY-PORT-OBS.S2', 'SEP-MEMORY-PORT-OBS.S3']
- Rationale: One path: SEP execution exercising SMU-passthrough memory macro ports

### SEP_SMU_013 — `smu_sep_km_otbn_memory_test` (given)
- Intent: SEP AES/OTBN/KM boundary ports are exercisable at SMU without deep crypto proof
- OWNS: AES/OTBN/KM SMU-visible ports only
- Evidence/Tier: frontdoor-func / B
- Allocated scenarios: ['SEP-CRYPTO-PORT-OBS.S1', 'SEP-CRYPTO-PORT-OBS.S2', 'SEP-CRYPTO-PORT-OBS.S3']
- Rationale: One path: SEP programs crypto CSRs/memories observed on SMU passthrough ports

### SEP_SMU_014 — `smu_sep_dma_test` (given)
- Intent: SEP DMA CSR kickoff and TCM preload complete at the SMU-visible fabric/memory boundary
- OWNS: DMA CSR and TCM preload only
- Evidence/Tier: strict-e2e / B
- Allocated scenarios: ['SEP-DMA-PORT-OBS.S1', 'SEP-DMA-PORT-OBS.S2']
- Rationale: One path: SEP DMA master moving data into TCM/SRAM observed at boundary

### SEP_SMU_015 — `smu_sep_spi_bridge_test` (given)
- Intent: SEP SPI host request and muxed SPI IRQ are visible at SMU
- OWNS: SPI req/IRQ mux only
- Evidence/Tier: frontdoor-func / B
- Allocated scenarios: ['SEP-SPI-PORT-OBS.S1', 'SEP-SPI-PORT-OBS.S2']
- Rationale: One path: SEP SPI programming to SMU SPI pads/IRQ mux

### SEP_SMU_016 — `smu_sep_efuse_test` (given)
- Intent: SEP eFuse bank/command and JTAG-OTP paths complete at SMU eFuse ports
- OWNS: eFuse bank/command/JTAG-OTP only
- Evidence/Tier: strict-e2e / A
- Allocated scenarios: ['SEP-EFUSE-PORT-OBS.S1', 'SEP-EFUSE-PORT-OBS.S2', 'SEP-EFUSE-PORT-OBS.S3']
- Rationale: One path: SEP/DTP eFuse transactions through SMU passthrough to eFuse shim

## Unallocated

| Key | Reason | Downstream | Detail |
|---|---|---|---|
| `SEP-COMPOSE-ENABLE.S2` | OUT-OF-MILESTONE | out-of-scope | SEP=0 compile-time tie-off matrix deferred to P3 |
| `SEP-RESET-CONTROL.S4` | OUT-OF-MILESTONE | out-of-scope | reset-mid-window contested stress deferred to P3 |
| `SEP-XBAR-APERTURE.S3` | OUT-OF-MILESTONE | out-of-scope | live aperture reprogram-under-traffic deferred to P3 |
| `SEP-LC-STATE-EXPORT.S2` | OUT-OF-MILESTONE | out-of-scope | SEP=0 lc_state_o=8'hf0 build matrix deferred to P3 |
| `SEP-SECURITY-DISABLE-EXPORT.S2` | BLOCKED-BY-SPEC-FINDING | blocked | blocked by open SF-005 (SEC_DIS token match exactness at SMU bind point) |
| `SEP-SECURITY-DISABLE-EXPORT.S3` | BLOCKED-BY-SPEC-FINDING | blocked | blocked by open SF-005 (SEC_DIS token mismatch exactness) |
| `SEP-TEST-MODE-SECURE-TM.S1` | OUT-OF-MILESTONE | out-of-scope | SECURE_TM latch timing matrix deferred to P3 |
| `SEP-TEST-MODE-SECURE-TM.S2` | OUT-OF-MILESTONE | out-of-scope | SECURE_TM clear-on-reset matrix deferred to P3 |
| `SEP-OUTBOUND-FILTER.S3` | BLOCKED-BY-SPEC-FINDING | blocked | blocked by open SF-001 (SMC-egress vs outbound filter relationship unspecified) |
| `SEP-AXI-EXTENSION.S1` | OUT-OF-MILESTONE | out-of-scope | AXI extension port decode deferred to P3 (review-budget; pinned smu_sep_axi_extension_decode_test unused this rev) |
| `SEP-AXI-EXTENSION.S2` | OUT-OF-MILESTONE | out-of-scope | AXI extension DECERR tie-off deferred to P3 |
| `SEP-DEBUG-BUS-EXPORT.S1` | OUT-OF-MILESTONE | out-of-scope | debug bus export observability deferred to P3 (pinned smu_sep_debug_bus_test unused this rev) |
| `SEP-EXTERNAL-IRQ.S1` | OUT-OF-MILESTONE | out-of-scope | SEP external IRQ pending deferred to P3 (pinned smu_sep_external_irq_test unused this rev) |
| `SEP-EXTERNAL-IRQ.S2` | OUT-OF-MILESTONE | out-of-scope | SEP external IRQ clear deferred to P3 |
| `SEP-IC-RESET-EXT-SLICE.S1` | OUT-OF-MILESTONE | out-of-scope | IC_RESET SEP slice assert deferred to P3 (pinned smu_ic_reset_sep_ext_slice_test unused this rev) |
| `SEP-IC-RESET-EXT-SLICE.S2` | OUT-OF-MILESTONE | out-of-scope | IC_RESET SEP slice release deferred to P3 |
