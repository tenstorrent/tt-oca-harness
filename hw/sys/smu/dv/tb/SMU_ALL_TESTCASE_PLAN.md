---
schema: dv-quality/v1
artifact: testcase-plan
artifact_revision: 18
plan_revision: 18
content_sha256: be84741e8818c2d5073ba998d056548fce72d9d9a3669304cf897591b35fc97a
ip: SMU_ALL
milestone: P2
status: approved
pin_revision: 1
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
source_revision: e02d5a97ba46d97eb4469041e115efca949f0184
quality_policy:
  path: hw/sys/smu/dv/tb/SMU_ALL_QUALITY_POLICY.md
  revision: 936b77700909a93bb122f9fb124a3ffb6f5dac5f508c623c5950285a5cefb79a
generated_by:
  human_id: minshaoho
  run_id: dv_vplan_gen-SMU_ALL-P2-optionB-008-pwrgood-only-20260805
  model:
    provider: cursor
    family: grok
    version: '4.5'
derivation_provenance:
  sealed_derivation: true
  anchor_seal_mechanism: ordered-single-context
  fresh_context_route: fresh-subagent
  feature_list_frozen_at: '2026-08-05T07:42:58+08:00'
approved_by: minshaoho
approved_at: '2026-08-05T17:37:56+08:00'
anchor_mode: augment
derived_from:
  feature_list_revision: 3
  feature_list_sha256: 4b37c7ba88aa0234689282eec80604a4181b7fec42e255479eaa83bf8f58455c
testcases:
- id: SMU_ALL_001
  anchor: smu_wrapper_elaboration_test
  origin: given
  revision: 1
  supersedes_revision: null
  current: false
  status: approved
  record_sha256: 2749940a1cf93aa8841d9a5bbcc95b0e8f5b110a87850b52391d71cef78e85e7
  approved_by: minshaoho
  approved_at: '2026-08-03T14:22:00+08:00'
  intent: Prove SMU top composition and SEP parameter effects at the SMU boundary.
  category: SMU composition / SEP parameter / top ports
  owns: SMU compose presence, SEP=0/1 elaboration effects (non-OTP-error), SMU clk/rst port connectivity
    (non-powergood-POR)
  evidence_class: frontdoor-func
  closure_tier: B
  allocated:
    features:
    - SMU-COMPOSE-BLOCKS
    - SMU-PORT-CLK-RST
    - SMU-SEP-PARAM
    scenarios:
    - SMU-COMPOSE-BLOCKS.S1
    - SMU-COMPOSE-BLOCKS.S2
    - SMU-COMPOSE-BLOCKS.S3
    - SMU-PORT-CLK-RST.S1
    - SMU-PORT-CLK-RST.S3
    - SMU-SEP-PARAM.S1
    - SMU-SEP-PARAM.S2
  rationale: 'Single path: SMU composition / SEP parameter / top ports exercised at the SMU integration
    boundary.'
  size_justification: null
  reuse: smu_wrapper_elaboration_test
  blockers: []
- id: SMU_ALL_001
  anchor: smu_wrapper_elaboration_sep_rtl_test
  origin: given
  revision: 2
  supersedes_revision: 1
  current: true
  status: approved
  record_sha256: d093a5fa0100b964afe783af8343c735c5c70e0442ea533666db118fe6164d57
  approved_by: minshaoho
  approved_at: '2026-08-05T17:37:56+08:00'
  intent: Prove SMU top composition, clk/rst bring-up, and SEP=1 elaboration at the SMU boundary (compile-time
    SEP=1).
  category: SMU composition / SEP=1 elaboration / top ports
  owns: SMU compose presence (SEP=1), SEP=1 elaboration (xbar + lc_state_o), SMU clk/rst port connectivity
    (non-powergood-POR)
  evidence_class: frontdoor-func
  closure_tier: B
  allocated:
    features:
    - SMU-COMPOSE-BLOCKS
    - SMU-PORT-CLK-RST
    - SMU-SEP-PARAM
    scenarios:
    - SMU-COMPOSE-BLOCKS.S1
    - SMU-COMPOSE-BLOCKS.S2
    - SMU-COMPOSE-BLOCKS.S3
    - SMU-PORT-CLK-RST.S1
    - SMU-PORT-CLK-RST.S3
    - SMU-SEP-PARAM.S1
  rationale: 'Single path: SEP=1 SMU composition / clk-rst bring-up / SEP-PARAM.S1 at one compile-time
    SEP=1 elaboration; SEP=0 effects live on smu_wrapper_elaboration_no_sep_test.'
  size_justification: null
  reuse: smu_wrapper_elaboration_sep_rtl_test
  blockers: []
- id: SMU_ALL_002
  anchor: smu_axi_external_port_connectivity_test
  origin: given
  revision: 1
  supersedes_revision: null
  current: false
  status: approved
  record_sha256: bc42767567e1489d6eb9424ee9418b435543044dd9221e272bef17ed5bf6c934
  approved_by: minshaoho
  approved_at: '2026-08-03T14:22:00+08:00'
  intent: Prove SMU crossbar and external AXI/SMN routing among SMC/SEP/external.
  category: SMU AXI/SMN crossbar routing
  owns: SMU 3x3 xbar connectivity, SMN AXI ports, ID conversion (SEP path), unmapped DECERR
  evidence_class: frontdoor-func
  closure_tier: B
  allocated:
    features:
    - SMU-PORT-SMN-AXI
    - SMU-XBAR-CONNECT
    - SMU-XBAR-ID-CONV
    - SMU-XBAR-UNMAPPED
    scenarios:
    - SMU-PORT-SMN-AXI.S1
    - SMU-PORT-SMN-AXI.S2
    - SMU-XBAR-CONNECT.S1
    - SMU-XBAR-CONNECT.S2
    - SMU-XBAR-CONNECT.S3
    - SMU-XBAR-ID-CONV.S2
    - SMU-XBAR-UNMAPPED.S1
    - SMU-XBAR-UNMAPPED.S2
  rationale: 'Single path: SMU AXI/SMN crossbar routing exercised at the SMU integration boundary.'
  size_justification: null
  reuse: smu_axi_external_port_connectivity_test
  blockers: []
- id: SMU_ALL_002
  anchor: smu_axi_external_port_connectivity_test
  origin: given
  revision: 2
  supersedes_revision: 1
  current: false
  status: approved
  record_sha256: edade22eba5cd3a0701068eae6019bdd9b3282490209279431855f199e55cd62
  approved_by: minshaoho
  approved_at: '2026-08-03T17:33:00+08:00'
  intent: Prove SEP=0 external SMN AXI inbound connectivity into SMC on bare tb_top (direct IW converters;
    no 3x3 xbar claim).
  category: SMU SEP=0 external AXI inbound / no-SEP converters
  owns: SEP=0 external SMN AXI inbound→SMC via direct IW converters; SEP=0 elaboration (direct SMC↔external
    ID converters; non-OTP-error)
  evidence_class: frontdoor-func
  closure_tier: B
  allocated:
    features:
    - SMU-PORT-SMN-AXI
    - SMU-SEP-PARAM
    scenarios:
    - SMU-PORT-SMN-AXI.S1
    - SMU-SEP-PARAM.S2
  rationale: 'Single path: bare tb_top.sv elaborates smu #(.SEP(0)) with flat s_axi_* BFM into smu_axi_in;
    prove direct SMC↔external converters (SEP=0) and inbound 56/64-bit access reaches SMC. No 3x3 xbar,
    no sep_out, no SEP aperture path on this harness.'
  size_justification: null
  reuse: smu_axi_external_port_connectivity_test
  blockers: []
- id: SMU_ALL_003
  anchor: smu_smc_smoke_test
  origin: given
  revision: 1
  supersedes_revision: null
  current: false
  status: approved
  record_sha256: a0b4acc155e5f58e2b7f284f028c39820cda214aee2655c2efc018851442e11c
  approved_by: minshaoho
  approved_at: '2026-08-03T14:22:00+08:00'
  intent: Prove SMC fabric and decode behaviors exercised through the SMU.
  category: SMC fabric / decode / inbound ports
  owns: SMC dual-network (non-HP-table conflict), fabric in-ports, decode apertures (non-REGION_SIZE),
    SMC powergood PTAP release (non-conflict POR source)
  evidence_class: frontdoor-func
  closure_tier: B
  allocated:
    features:
    - SMC-DECODE-APERTURE
    - SMC-FAB-DUAL-NET
    - SMC-FAB-IN-PORTS
    - SMC-PWRGOOD-DTP-POR
    scenarios:
    - SMC-FAB-DUAL-NET.S2
    - SMC-FAB-DUAL-NET.S3
    - SMC-FAB-IN-PORTS.S1
    - SMC-FAB-IN-PORTS.S2
    - SMC-FAB-IN-PORTS.S3
    - SMC-DECODE-APERTURE.S1
    - SMC-DECODE-APERTURE.S3
    - SMC-PWRGOOD-DTP-POR.S2
  rationale: 'Single path: SMC fabric / decode / inbound ports exercised at the SMU integration boundary.'
  size_justification: null
  reuse: smu_smc_smoke_test
  blockers: []
- id: SMU_ALL_004
  anchor: smc_mailbox_int_test
  origin: given
  revision: 1
  supersedes_revision: null
  current: false
  status: approved
  record_sha256: 92e1f0daa6fd0263706c6ee09ed74ade3726ef35612f7d0e865d009a5312083f
  approved_by: minshaoho
  approved_at: '2026-08-03T14:22:00+08:00'
  intent: Prove mailbox and interrupt crossing between SMC and SEP at SMU.
  category: SMC↔SEP mailbox / interrupts
  owns: SMC mailbox channels, challenge complement path (non-blocked), SEP IRQ vector (1-core map), external
    mailbox IRQ bits
  evidence_class: frontdoor-func
  closure_tier: B
  allocated:
    features:
    - SEP-MBX-IRQ-SMC
    - SMC-MBX-CHANNELS
    - SMC-MBX-IRQ-EXT
    - SMU-MBX-CHALLENGE
    scenarios:
    - SMC-MBX-CHANNELS.S1
    - SMC-MBX-CHANNELS.S2
    - SMC-MBX-CHANNELS.S3
    - SMU-MBX-CHALLENGE.S2
    - SEP-MBX-IRQ-SMC.S2
    - SMC-MBX-IRQ-EXT.S1
    - SMC-MBX-IRQ-EXT.S2
  rationale: 'Single path: SMC↔SEP mailbox / interrupts exercised at the SMU integration boundary.'
  size_justification: null
  reuse: smc_mailbox_int_test
  blockers: []
- id: SMU_ALL_005
  anchor: smu_dtp_jtag_smoke_test
  origin: given
  revision: 1
  supersedes_revision: null
  current: false
  status: approved
  record_sha256: 7aca42edc8d99a71aef718f27cd310a8f67a58719038ed32a84aff545d36cfeb
  approved_by: minshaoho
  approved_at: '2026-08-03T14:22:00+08:00'
  intent: Prove DTP JTAG/JTAG2AXI/OTP/STAP integration with SMC and SEP.
  category: DTP JTAG / JTAG2AXI / OTP / STAP
  owns: DTP PTAP IDCODE/BYPASS/TRST, JTAG2AXI to SMC, OTP AXIL (SEP=1 legal), STAP SMC/SEP selection
  evidence_class: frontdoor-func
  closure_tier: B
  allocated:
    features:
    - DTP-JTAG-PTAP
    - DTP-JTAG2AXI-SMC
    - DTP-OTP-AXIL
    - DTP-STAP-SMC-SEP
    scenarios:
    - DTP-JTAG-PTAP.S1
    - DTP-JTAG-PTAP.S2
    - DTP-JTAG-PTAP.S3
    - DTP-JTAG2AXI-SMC.S1
    - DTP-JTAG2AXI-SMC.S2
    - DTP-OTP-AXIL.S1
    - DTP-OTP-AXIL.S2
    - DTP-STAP-SMC-SEP.S1
    - DTP-STAP-SMC-SEP.S2
    - DTP-STAP-SMC-SEP.S3
  rationale: 'Single path: DTP JTAG / JTAG2AXI / OTP / STAP exercised at the SMU integration boundary.'
  size_justification: SMU_ALL P2 area card aggregates 10 scenarios on one shared producer/transport/consumer
    path (DTP JTAG / JTAG2AXI / OTP / STAP); kept as one record to stay within max_cards_per_packet=8
    for the SMU_ALL board.
  reuse: smu_dtp_jtag_smoke_test
  blockers: []
- id: SMU_ALL_006
  anchor: smu_clock_stop_coordination_test
  origin: given
  revision: 1
  supersedes_revision: null
  current: false
  status: approved
  record_sha256: a9bdf58a5e3a6155b726292d247df199d19a5b6d03cbe99b5a231cff715cbe5a
  approved_by: minshaoho
  approved_at: '2026-08-03T14:22:00+08:00'
  intent: 'Prove DTP control-plane integration: stall, reset override, feat gate, clock-stop, cross-trigger.'
  category: DTP clock-stop / boot-stall / IC-reset / xtrig / feat-gate
  owns: DTP boot-stall, IC-reset (SMC+clear), feat-gate, clock-stop aggregation, feat_ctrl×DTP JTAG2AXI
    interaction
  evidence_class: frontdoor-func
  closure_tier: B
  allocated:
    features:
    - DTP-BOOT-STALL
    - DTP-CLKSTOP-AGG
    - DTP-FEAT-GATE
    - DTP-IC-RESET
    - DTP-JTAG2AXI-SMC
    - SEP-LC-FEAT-EXPORT
    scenarios:
    - DTP-BOOT-STALL.S1
    - DTP-BOOT-STALL.S2
    - DTP-IC-RESET.S1
    - DTP-IC-RESET.S3
    - DTP-FEAT-GATE.S1
    - DTP-FEAT-GATE.S2
    - DTP-FEAT-GATE.S3
    - DTP-CLKSTOP-AGG.S1
    - DTP-CLKSTOP-AGG.S2
    - DTP-CLKSTOP-AGG.S3
    - INT-FEAT-CTRL-DTP-GATE
  rationale: 'Single path: DTP clock-stop / boot-stall / IC-reset / xtrig / feat-gate exercised at the
    SMU integration boundary.'
  size_justification: SMU_ALL P2 area card aggregates 11 scenarios on one shared path; kept undivided
    to honor max_cards_per_packet=8.
  reuse: smu_clock_stop_coordination_test
  blockers: []
- id: SMU_ALL_007
  anchor: smu_sep_smoke_test
  origin: given
  revision: 1
  supersedes_revision: null
  current: false
  status: approved
  record_sha256: e14d2cadea7aee22f5463d9f55758fe06eaabd59e6399dcbad35b5b8bcb7c6e5
  approved_by: minshaoho
  approved_at: '2026-08-03T14:22:00+08:00'
  intent: 'Prove SEP SMU-visible boundary behaviors: fabric, lifecycle, WDT, fuse, memory ports.'
  category: SEP boundary / lifecycle / security / WDT / fuse / memory
  owns: SEP sysif to SMU xbar (non-blocked neighbor path), LC/feat export, SEC_DIS (non-retain)
  evidence_class: frontdoor-func
  closure_tier: B
  allocated:
    features:
    - SEP-LC-FEAT-EXPORT
    - SEP-SEC-DIS
    - SEP-SYSIF-SMU-XBAR
    scenarios:
    - SEP-SYSIF-SMU-XBAR.S2
    - SEP-SYSIF-SMU-XBAR.S3
    - SEP-LC-FEAT-EXPORT.S1
    - SEP-LC-FEAT-EXPORT.S2
    - SEP-LC-FEAT-EXPORT.S3
    - SEP-SEC-DIS.S1
    - SEP-SEC-DIS.S2
  rationale: 'Single path: SEP boundary / lifecycle / security / WDT / fuse / memory exercised at the
    SMU integration boundary.'
  size_justification: null
  reuse: smu_sep_smoke_test
  blockers: []
- id: SMU_ALL_007
  anchor: smu_sep_smoke_test
  origin: given
  revision: 2
  supersedes_revision: 1
  current: false
  status: approved
  record_sha256: 75189f462bc0684d5d0b7fe3ed166989b06d1c050f856ad889bff2f0e7ed444a
  approved_by: minshaoho
  approved_at: '2026-08-03T15:31:00+08:00'
  intent: Prove SEP SMU-visible boundary behaviors plus residual SMU interoperability paths previously
    on SMU_ALL_008 (SEP=1 compile).
  category: SEP boundary / lifecycle / security / residual SMU interop
  owns: SEP sysif to SMU xbar (non-blocked neighbor path), LC/feat export, SEC_DIS (non-retain); plus
    residual SMC reset/DTP CSR/xtrig/fuse/WDT/mem/alias interop absorbed from retired SMU_ALL_008 residual
    grouping
  evidence_class: frontdoor-func
  closure_tier: B
  allocated:
    features:
    - DTP-CLKSTOP-AGG
    - DTP-XTRIG-CTM
    - DTP-XTRIG-CTP
    - SEP-FUSE-SENSE-HS
    - SEP-LC-FEAT-EXPORT
    - SEP-MEM-BOUND-PASSTHROUGH
    - SEP-SEC-DIS
    - SEP-SYSIF-SMU-XBAR
    - SEP-WDT-RST-SMC
    - SMC-DTP-CSR
    - SMC-FAB-OUT-SMN
    - SMC-RST-PRIMARY-EXPORT
    - SMU-SEP-SMC-ALIAS
    - SMU-XBAR-CONNECT
    scenarios:
    - SEP-SYSIF-SMU-XBAR.S2
    - SEP-SYSIF-SMU-XBAR.S3
    - SEP-LC-FEAT-EXPORT.S1
    - SEP-LC-FEAT-EXPORT.S2
    - SEP-LC-FEAT-EXPORT.S3
    - SEP-SEC-DIS.S1
    - SEP-SEC-DIS.S2
    - SMC-FAB-OUT-SMN.S1
    - SMC-DTP-CSR.S1
    - SMC-DTP-CSR.S2
    - SMC-RST-PRIMARY-EXPORT.S1
    - SMC-RST-PRIMARY-EXPORT.S2
    - DTP-XTRIG-CTM.S1
    - DTP-XTRIG-CTM.S2
    - DTP-XTRIG-CTM.S3
    - DTP-XTRIG-CTP.S1
    - INT-CLKSTOP-SMC-CLA
    - SEP-MEM-BOUND-PASSTHROUGH.S1
    - SEP-MEM-BOUND-PASSTHROUGH.S2
    - SEP-FUSE-SENSE-HS.S1
    - SEP-FUSE-SENSE-HS.S2
    - SEP-WDT-RST-SMC.S1
    - SEP-WDT-RST-SMC.S2
    - INT-ALIAS-VS-XBAR-SMC
    - SMU-SEP-SMC-ALIAS.S1
    - SMU-SEP-SMC-ALIAS.S3
  rationale: SEP=1 smoke path plus residual interop consumers; absorbs former SMU_ALL_008 allocation so
    that id can own SEP=0 elaboration after the compile-time SEP split (max_cards_per_packet=8).
  size_justification: Absorbs 19 residual scenarios from superseded SMU_ALL_008 so that id can be reallocated
    to smu_wrapper_elaboration_no_sep_test (SEP=0); keeps milestone at max_cards_per_packet=8 after the
    mandatory SEP generate split of SMU_ALL_001.
  reuse: smu_sep_smoke_test
  blockers: []
- id: SMU_ALL_008
  anchor: smu_interop_negative_recovery_test
  origin: given
  revision: 1
  supersedes_revision: null
  current: false
  status: approved
  record_sha256: 9850996353d6db09817f3a2fbaffa0bb959a98327e8eb2e040bef41f91c479ab
  approved_by: minshaoho
  approved_at: '2026-08-03T14:22:00+08:00'
  intent: Prove residual SMU interoperability paths (reset/CSR/xtrig/fuse/WDT/mem/alias) for P2 breadth.
  category: 'SMU interop residual: reset export, DTP CSR, xtrig, fuse/WDT/mem, alias'
  owns: SMC primary-reset export; SMC DTP CSR/CTM program; DTP CTM/CTP routing; SEP fuse-sense/WDT/memory
    passthrough; SEP↔SMC alias interaction — disjoint from cards 001–007
  evidence_class: frontdoor-func
  closure_tier: B
  allocated:
    features:
    - DTP-CLKSTOP-AGG
    - DTP-XTRIG-CTM
    - DTP-XTRIG-CTP
    - SEP-FUSE-SENSE-HS
    - SEP-MEM-BOUND-PASSTHROUGH
    - SEP-SYSIF-SMU-XBAR
    - SEP-WDT-RST-SMC
    - SMC-DTP-CSR
    - SMC-FAB-OUT-SMN
    - SMC-RST-PRIMARY-EXPORT
    - SMU-SEP-SMC-ALIAS
    - SMU-XBAR-CONNECT
    scenarios:
    - SMC-FAB-OUT-SMN.S1
    - SMC-DTP-CSR.S1
    - SMC-DTP-CSR.S2
    - SMC-RST-PRIMARY-EXPORT.S1
    - SMC-RST-PRIMARY-EXPORT.S2
    - DTP-XTRIG-CTM.S1
    - DTP-XTRIG-CTM.S2
    - DTP-XTRIG-CTM.S3
    - DTP-XTRIG-CTP.S1
    - INT-CLKSTOP-SMC-CLA
    - SEP-MEM-BOUND-PASSTHROUGH.S1
    - SEP-MEM-BOUND-PASSTHROUGH.S2
    - SEP-FUSE-SENSE-HS.S1
    - SEP-FUSE-SENSE-HS.S2
    - SEP-WDT-RST-SMC.S1
    - SEP-WDT-RST-SMC.S2
    - INT-ALIAS-VS-XBAR-SMC
    - SMU-SEP-SMC-ALIAS.S1
    - SMU-SEP-SMC-ALIAS.S3
  rationale: Single residual interop path at the SMU boundary spanning control-plane and SEP boundary
    consumers not owned by smoke cards.
  size_justification: SMU_ALL P2 residual interop card aggregates 19 scenarios; kept as one record for
    max_cards_per_packet=8.
  reuse: smu_interop_negative_recovery_test
  blockers: []
- id: SMU_ALL_008
  anchor: smu_wrapper_elaboration_no_sep_test
  origin: given
  revision: 2
  supersedes_revision: 1
  current: false
  status: approved
  record_sha256: 60b5418e6f8099f8b877744807ab3977c2d1967380b7b50da4bf29c064c6d116
  approved_by: minshaoho
  approved_at: '2026-08-03T15:31:00+08:00'
  intent: Prove SEP=0 SMU elaboration replaces crossbar/SEP with direct SMC↔external ID converters (compile-time
    SEP=0).
  category: SMU SEP=0 elaboration
  owns: SEP=0 elaboration (direct SMC↔external ID converters; non-OTP-error)
  evidence_class: frontdoor-func
  closure_tier: B
  allocated:
    features:
    - SMU-SEP-PARAM
    scenarios:
    - SMU-SEP-PARAM.S2
  rationale: 'Single path: compile-time SEP=0 generate (gen_no_sep) at the SMU boundary; mutually exclusive
    with SEP=1 elaboration owned by smu_wrapper_elaboration_sep_rtl_test.'
  size_justification: null
  reuse: smu_wrapper_elaboration_no_sep_test
  blockers: []
- id: SMU_ALL_008
  anchor: smu_axi_crossbar_error_handling_test
  origin: given
  revision: 3
  supersedes_revision: 2
  current: false
  status: approved
  record_sha256: e96e6e7835d86970b91d267a5a9f3c247d0dcb2cae8b3b93bacb6dabeb6d149d
  approved_by: minshaoho
  approved_at: '2026-08-03T17:33:00+08:00'
  intent: Prove SEP=1 SMU 3x3 xbar connectivity/ID-conv/unmapped/outbound default paths among SMC/SEP/external
    (wrapper harness).
  category: SMU AXI/SMN crossbar routing (SEP=1)
  owns: SMU 3x3 xbar connectivity matrix, SMN AXI outbound default, ID conversion (SEP path), unmapped
    DECERR (ext_in); excludes SEP=0 inbound owned by SMU_ALL_002
  evidence_class: frontdoor-func
  closure_tier: B
  allocated:
    features:
    - SMU-PORT-SMN-AXI
    - SMU-XBAR-CONNECT
    - SMU-XBAR-ID-CONV
    - SMU-XBAR-UNMAPPED
    scenarios:
    - SMU-PORT-SMN-AXI.S2
    - SMU-XBAR-CONNECT.S1
    - SMU-XBAR-CONNECT.S2
    - SMU-XBAR-CONNECT.S3
    - SMU-XBAR-ID-CONV.S2
    - SMU-XBAR-UNMAPPED.S1
    - SMU-XBAR-UNMAPPED.S2
  rationale: 'Single path: SEP=1 smu_axi_xbar routing at the SMU wrapper boundary. Intended harness is
    tb_wrapper_top.sv after TB-only unbind of assign smu_axi_in_req=''0 so ext_in can be frontdoor-driven.
    Legal sep_out producer requires live SEP CPU fetch; residual #3582 and no force/deposit forgery mean
    sep_out-legged scenarios stay allocation-intent with blockers until RTL/harness escalates — not closable
    by weakening checkers.'
  size_justification: null
  reuse: smu_axi_crossbar_error_handling_test
  blockers:
  - ISSUE-3582-sep_out-producer-unavailable
  - WRAPPER-smu_axi_in-tied-off-needs-TB-unbind
- id: SMU_ALL_002
  anchor: smu_axi_external_port_connectivity_test
  origin: given
  revision: 3
  supersedes_revision: 2
  current: true
  status: approved
  record_sha256: 68670b83ed1825edffb684356e0e887488144ba3dfd3b7a17c25a7a30bedf0b9
  approved_by: minshaoho
  approved_at: '2026-08-05T17:37:56+08:00'
  intent: Prove SEP=0 external SMN AXI inbound connectivity into SMC on bare tb_top (direct IW converters;
    no 3x3 xbar / no SEP aperture claim).
  category: SMU SEP=0 external AXI inbound / no-SEP converters
  owns: SEP=0 external SMN AXI inbound→SMC aperture via direct IW converters; SEP=0 elaboration (direct
    SMC↔external ID converters; non-OTP-error)
  evidence_class: frontdoor-func
  closure_tier: B
  allocated:
    features:
    - SMU-PORT-SMN-AXI
    - SMU-SEP-PARAM
    scenarios:
    - SMU-PORT-SMN-AXI.S1
    - SMU-SEP-PARAM.S2
  rationale: 'Single path: bare tb_top.sv elaborates smu #(.SEP(0)) with flat s_axi_* BFM into smu_axi_in;
    prove direct SMC↔external converters (SEP=0) and inbound 56/64-bit access reaches SMC aperture. SEP
    aperture inbound is independently owned as SMU-PORT-SMN-AXI.S4 on SMU_ALL_008 (SEP=1).'
  size_justification: null
  reuse: smu_axi_external_port_connectivity_test
  blockers: []
- id: SMU_ALL_008
  anchor: smu_axi_crossbar_error_handling_test
  origin: given
  revision: 4
  supersedes_revision: 3
  current: false
  status: approved
  record_sha256: 036fd3e263eeb4c625f77c69fe33e04e30ad90ea0b360ab7edbee60d91c52f86
  approved_by: minshaoho
  approved_at: '2026-08-03T18:38:00+08:00'
  intent: Prove SEP=1 SMU 3x3 xbar connectivity/ID-conv/unmapped/outbound default paths and SEP-aperture
    inbound among SMC/SEP/external (wrapper harness).
  category: SMU AXI/SMN crossbar routing (SEP=1)
  owns: SMU 3x3 xbar connectivity matrix, SMN AXI outbound default, SEP aperture inbound (ext_in→sep_in),
    ID conversion (SEP path), unmapped DECERR (ext_in); excludes SEP=0 SMC inbound owned by SMU_ALL_002
  evidence_class: frontdoor-func
  closure_tier: B
  allocated:
    features:
    - SMU-PORT-SMN-AXI
    - SMU-XBAR-CONNECT
    - SMU-XBAR-ID-CONV
    - SMU-XBAR-UNMAPPED
    scenarios:
    - SMU-PORT-SMN-AXI.S2
    - SMU-PORT-SMN-AXI.S4
    - SMU-XBAR-CONNECT.S1
    - SMU-XBAR-CONNECT.S2
    - SMU-XBAR-CONNECT.S3
    - SMU-XBAR-ID-CONV.S2
    - SMU-XBAR-UNMAPPED.S1
    - SMU-XBAR-UNMAPPED.S2
  rationale: 'Single path: SEP=1 smu_axi_xbar routing at the SMU wrapper boundary, including ext_in→sep_in
    aperture inbound (SMU-PORT-SMN-AXI.S4) split from former compound S1. Intended harness is tb_wrapper_top.sv
    after TB-only unbind of assign smu_axi_in_req=''0 so ext_in can be frontdoor-driven. Legal sep_out
    producer requires live SEP CPU fetch; residual #3582 and no force/deposit forgery mean sep_out-legged
    scenarios stay allocation-intent with blockers until RTL/harness escalates — not closable by weakening
    checkers.'
  size_justification: null
  reuse: smu_axi_crossbar_error_handling_test
  blockers:
  - ISSUE-3582-sep_out-producer-unavailable
  - WRAPPER-smu_axi_in-tied-off-needs-TB-unbind
- id: SMU_ALL_003
  anchor: smu_smc_smoke_test
  origin: given
  revision: 2
  supersedes_revision: 1
  current: false
  status: approved
  record_sha256: 5bb4666b1968bc9c6a6bbe0200c11673870cf8ac3c5aa66e5458582aec731be2
  approved_by: minshaoho
  approved_at: '2026-08-04T13:03:00+08:00'
  intent: Prove SMC fabric and decode behaviors exercised through the SMU.
  category: SMC fabric / decode / inbound ports
  owns: SMC dual-network (non-HP-table conflict), fabric in-ports (sys_axi_in / jtag_axi_in; excludes
    sep_axi_in LIVE owned by SMU_ALL_008), decode apertures (non-REGION_SIZE), SMC powergood PTAP release
    (non-conflict POR source)
  evidence_class: frontdoor-func
  closure_tier: B
  allocated:
    features:
    - SMC-DECODE-APERTURE
    - SMC-FAB-DUAL-NET
    - SMC-FAB-IN-PORTS
    - SMC-PWRGOOD-DTP-POR
    scenarios:
    - SMC-FAB-DUAL-NET.S2
    - SMC-FAB-DUAL-NET.S3
    - SMC-FAB-IN-PORTS.S1
    - SMC-FAB-IN-PORTS.S2
    - SMC-DECODE-APERTURE.S1
    - SMC-DECODE-APERTURE.S3
    - SMC-PWRGOOD-DTP-POR.S2
  rationale: 'Single path: SMC fabric / decode / inbound ports exercised at the SMU integration boundary
    on bare tb_top SEP=0. sep_axi_in default-filter→allow LIVE (SMC-FAB-IN-PORTS.S3) is independently
    owned on SMU_ALL_008 (SEP=1), because gen_no_sep ties smc_sep_axi_in_req=''0 with no TB drive port.'
  size_justification: null
  reuse: smu_smc_smoke_test
  blockers: []
- id: SMU_ALL_008
  anchor: smu_axi_crossbar_error_handling_test
  origin: given
  revision: 5
  supersedes_revision: 4
  current: false
  status: approved
  record_sha256: 795fc721636ceaed4c5db01ed9f05089f395b39d25fa41bd55087d0ce77767ff
  approved_by: minshaoho
  approved_at: '2026-08-04T13:03:00+08:00'
  intent: Prove SEP=1 SMU 3x3 xbar connectivity/ID-conv/unmapped/outbound default paths, SEP-aperture
    inbound, and SMC sep_axi_in default-filter→allow LIVE among SMC/SEP/external (wrapper harness).
  category: SMU AXI/SMN crossbar routing (SEP=1)
  owns: SMU 3x3 xbar connectivity matrix, SMN AXI outbound default, SEP aperture inbound (ext_in→sep_in),
    SMC sep_axi_in default-filter→allow LIVE (SMC-FAB-IN-PORTS.S3), ID conversion (SEP path), unmapped
    DECERR (ext_in); excludes SEP=0 SMC inbound owned by SMU_ALL_002 and SEP=0 sys/jtag in-ports owned
    by SMU_ALL_003
  evidence_class: frontdoor-func
  closure_tier: B
  allocated:
    features:
    - SMC-FAB-IN-PORTS
    - SMU-PORT-SMN-AXI
    - SMU-XBAR-CONNECT
    - SMU-XBAR-ID-CONV
    - SMU-XBAR-UNMAPPED
    scenarios:
    - SMU-PORT-SMN-AXI.S2
    - SMU-PORT-SMN-AXI.S4
    - SMC-FAB-IN-PORTS.S3
    - SMU-XBAR-CONNECT.S1
    - SMU-XBAR-CONNECT.S2
    - SMU-XBAR-CONNECT.S3
    - SMU-XBAR-ID-CONV.S2
    - SMU-XBAR-UNMAPPED.S1
    - SMU-XBAR-UNMAPPED.S2
  rationale: 'Single path: SEP=1 smu_axi_xbar routing at the SMU wrapper boundary, including ext_in→sep_in
    aperture inbound (SMU-PORT-SMN-AXI.S4) and SMC sep_axi_in default-filter→allow LIVE (SMC-FAB-IN-PORTS.S3)
    re-homed from SMU_ALL_003 because bare tb_top SEP=0 has no driveable sep_axi_in. Intended harness
    is tb_wrapper_top.sv after TB-only unbind of assign smu_axi_in_req=''0 so ext_in can be frontdoor-driven.
    Legal sep_out / live SEP→SMC sep_axi_in producer requires live SEP traffic; residual #3582 and no
    force/deposit forgery mean sep_out-legged and sep_axi_in-LIVE scenarios stay allocation-intent with
    blockers until RTL/harness escalates — not closable by weakening checkers.'
  size_justification: null
  reuse: smu_axi_crossbar_error_handling_test
  blockers:
  - ISSUE-3582-sep_out-producer-unavailable
  - WRAPPER-smu_axi_in-tied-off-needs-TB-unbind
- id: SMU_ALL_003
  anchor: smu_smc_smoke_test
  origin: given
  revision: 3
  supersedes_revision: 2
  current: true
  status: approved
  record_sha256: 5e984fcfcb941c7eccfa5a9a0f2c78adc1006e1becc960317d9d802fe682b024
  approved_by: minshaoho
  approved_at: '2026-08-05T17:37:56+08:00'
  intent: Prove SMC dual-network AXI4-Lite LP delivery and 64-bit width at the SMU boundary via hierarchical
    CONNECTIVITY (no external-port / decode / leave-TLR dependency).
  category: SMC fabric dual-network (hierarchical)
  owns: SMC dual-network AXI4-Lite LP subordinates and 64-bit data width (SMC-FAB-DUAL-NET.S2/S3); excludes
    fabric in-ports, decode apertures, and PWRGOOD leave-TLR owned by SMU_ALL_008 after Option-B re-home
  evidence_class: frontdoor-func
  closure_tier: B
  allocated:
    features:
    - SMC-FAB-DUAL-NET
    scenarios:
    - SMC-FAB-DUAL-NET.S2
    - SMC-FAB-DUAL-NET.S3
  rationale: 'Single path: hierarchical CONNECTIVITY of SMC dual-network LP + 64-bit width on authorized
    bare/wrapper harness without requiring driveable sys_axi_in, JTAG2AXI, filter programming, or TAP
    leave-TLR. Prior in-ports/decode/pwrgood scenarios are not legally frontdoor-observable on the exhausted
    SEP=1 wrapper (axi_in tied, JTAG hardwired TMS=1, skip_fuse_sense leaves feat_ctrl closed) without
    Force.'
  size_justification: null
  reuse: smu_smc_smoke_test
  blockers: []
- id: SMU_ALL_008
  anchor: smu_axi_crossbar_error_handling_test
  origin: given
  revision: 6
  supersedes_revision: 5
  current: false
  status: approved
  record_sha256: f30ec3a2fc44f99d9d833b198c28fb125fddb5d9d54afcdeaaa6584267ae8a71
  approved_by: minshaoho
  approved_at: '2026-08-04T13:21:00+08:00'
  intent: Prove SEP=1 SMU 3x3 xbar connectivity/ID-conv/unmapped/outbound paths, SEP-aperture inbound,
    SMC fabric in-ports (sys/jtag/sep), SMC decode apertures, and PWRGOOD PTAP leave-TLR among SMC/SEP/external
    (wrapper harness).
  category: SMU AXI/SMN crossbar + SMC fabric ingress/decode (SEP=1)
  owns: SMU 3x3 xbar connectivity matrix, SMN AXI outbound default, SEP aperture inbound (ext_in→sep_in),
    SMC fabric in-ports sys/jtag/sep (SMC-FAB-IN-PORTS.S1/S2/S3), SMC decode apertures (SMC-DECODE-APERTURE.S1/S3),
    SMC powergood PTAP leave-TLR (SMC-PWRGOOD-DTP-POR.S2), ID conversion (SEP path), unmapped DECERR (ext_in);
    excludes SEP=0 SMC inbound owned by SMU_ALL_002 and hierarchical dual-net owned by SMU_ALL_003
  evidence_class: frontdoor-func
  closure_tier: B
  allocated:
    features:
    - SMC-DECODE-APERTURE
    - SMC-FAB-IN-PORTS
    - SMC-PWRGOOD-DTP-POR
    - SMU-PORT-SMN-AXI
    - SMU-XBAR-CONNECT
    - SMU-XBAR-ID-CONV
    - SMU-XBAR-UNMAPPED
    scenarios:
    - SMU-PORT-SMN-AXI.S2
    - SMU-PORT-SMN-AXI.S4
    - SMC-FAB-IN-PORTS.S3
    - SMU-XBAR-CONNECT.S1
    - SMU-XBAR-CONNECT.S2
    - SMU-XBAR-CONNECT.S3
    - SMU-XBAR-ID-CONV.S2
    - SMU-XBAR-UNMAPPED.S1
    - SMU-XBAR-UNMAPPED.S2
    - SMC-FAB-IN-PORTS.S1
    - SMC-FAB-IN-PORTS.S2
    - SMC-DECODE-APERTURE.S1
    - SMC-DECODE-APERTURE.S3
    - SMC-PWRGOOD-DTP-POR.S2
  rationale: 'Single path: SEP=1 smu_axi_xbar / fabric-ingress / decode at the SMU wrapper boundary. Absorbs
    sys_axi_in (S1), jtag_axi_in (S2), LOCAL/GLOBAL decode (DECODE.S1/S3), and PWRGOOD leave-TLR (PWRGOOD.S2)
    re-homed from SMU_ALL_003 because Skill 1.5 exhausted authorized wrapper SEP=1 for that card: smu_axi_in
    tied off, JTAG hardwired TMS=1 (cannot leave TLR), +skip_fuse_sense leaves feat_ctrl closed — LIVE/DECODE/in-port
    proofs need Force. Allocation is intent; residual #3582 / tied axi_in / hardwired JTAG remain blockers,
    not waivers to forge.'
  size_justification: 'Option-B re-home sink: absorbs 5 scenarios from SMU_ALL_003 (sys/jtag in-ports,
    decode S1/S3, PWRGOOD.S2) onto the existing SEP=1/xbar blocker card so 003 retains only hierarchical
    dual-net OWNS. Shared producer/transport/consumer path is SEP=1 wrapper fabric/xbar; kept undivided
    with explicit size_justification rather than minting a ninth area card mid-milestone.'
  reuse: smu_axi_crossbar_error_handling_test
  blockers:
  - ISSUE-3582-sep_out-producer-unavailable
  - WRAPPER-smu_axi_in-tied-off-needs-TB-unbind
  - WRAPPER-JTAG-TMS-hardwired-high-blocks-leave-TLR
  - WRAPPER-skip_fuse_sense-feat_ctrl-closed
- id: SMU_ALL_004
  anchor: smc_mailbox_int_test
  origin: given
  revision: 2
  supersedes_revision: 1
  current: false
  status: approved
  record_sha256: 70be6dd45f145e9400bc28126528ce0f70fe8942a2f18e3bb1c05a9047d0a2e4
  approved_by: minshaoho
  approved_at: '2026-08-04T13:52:00+08:00'
  intent: Prove SMC-local mailbox channel decode/inbound IRQ and external mailbox IRQ bits on bare tb_top
    SEP=0 without requiring a live SEP peer producer.
  category: SMC mailbox / external IRQ (SEP=0 frontdoor)
  owns: SMC mailbox inbound IRQ (SMC-MBX-CHANNELS.S2), 32-channel decode map (SMC-MBX-CHANNELS.S3), and
    external mailbox IRQ bits/width (SMC-MBX-IRQ-EXT.S1/S2); excludes peer=sep outbound LIVE, SEP→SMC
    challenge IRQ, and SEP-MBX 1-core vector owned by SMU_ALL_008 after Option-B re-home
  evidence_class: frontdoor-func
  closure_tier: B
  allocated:
    features:
    - SMC-MBX-CHANNELS
    - SMC-MBX-IRQ-EXT
    scenarios:
    - SMC-MBX-CHANNELS.S2
    - SMC-MBX-CHANNELS.S3
    - SMC-MBX-IRQ-EXT.S1
    - SMC-MBX-IRQ-EXT.S2
  rationale: 'Single path: SMC-local mailbox MMIO + ext_mailbox_interrupts_o at the SMU boundary on bare
    SEP=0 harness. Skill 1.5 STOP on SMU_ALL_004: CHANNELS.S1 peer=sep LIVE, CHALLENGE.S2 SEP→SMC IRQ
    LIVE, and SEP-MBX-IRQ-SMC.S2 CONNECTIVITY 1-core are not legally frontdoor-observable without SEP
    CPU producer (#3582); Force/deposit forbidden. S2/S3/EXT.S1/S2 remain honest without SEP peer.'
  size_justification: null
  reuse: smc_mailbox_int_test
  blockers: []
- id: SMU_ALL_004
  anchor: smc_mailbox_int_test
  origin: given
  revision: 3
  supersedes_revision: 2
  current: true
  status: approved
  record_sha256: 9708455a65d08e9b61262724548aec548e35cceee130bb05bc841288641fff94
  approved_by: minshaoho
  approved_at: '2026-08-05T17:37:56+08:00'
  intent: Prove SMC external mailbox interrupt vector width (passive DECODE) on bare tb_top SEP=0 without
    mailbox MMIO stimulus.
  category: SMC mailbox / interrupt (SEP=0 passive)
  owns: SMC external mailbox interrupt port width (32-bit); excludes LIVE channel traffic, filter-gated
    MMIO, and SEP-peer mailbox paths
  evidence_class: frontdoor-func
  closure_tier: B
  allocated:
    features:
    - SMC-MBX-IRQ-EXT
    scenarios:
    - SMC-MBX-IRQ-EXT.S2
  rationale: 'Single path: passive observe ext_mailbox_interrupts[31:0] width/DECODE on bare tb_top after
    Option-B re-homes that require SYS_IN filter program, JTAG2AXI/feat_ctrl, or SEP LIVE producers (CHANNELS.S2/S3,
    EXT.S1, and prior SEP-peer keys on SMU_ALL_008).'
  size_justification: null
  reuse: smc_mailbox_int_test
  blockers: []
- id: SMU_ALL_008
  anchor: smu_axi_crossbar_error_handling_test
  origin: given
  revision: 7
  supersedes_revision: 6
  current: false
  status: approved
  record_sha256: a936ca8acb676f7c8fe86528fe6d66f268224c1cf240421e352e1dde57aed6cc
  approved_by: minshaoho
  approved_at: '2026-08-04T13:52:00+08:00'
  intent: Prove SEP=1 SMU 3x3 xbar connectivity/ID-conv/unmapped/outbound paths, SEP-aperture inbound,
    SMC fabric in-ports (sys/jtag/sep), SMC decode apertures, PWRGOOD PTAP leave-TLR, and SEP-peer mailbox
    / SEP→SMC mailbox IRQ paths among SMC/SEP/external (wrapper harness).
  category: SMU AXI/SMN crossbar + SMC fabric ingress/decode + SEP-peer mailbox (SEP=1)
  owns: SMU 3x3 xbar connectivity matrix, SMN AXI outbound default, SEP aperture inbound (ext_in→sep_in),
    SMC fabric in-ports sys/jtag/sep (SMC-FAB-IN-PORTS.S1/S2/S3), SMC decode apertures (SMC-DECODE-APERTURE.S1/S3),
    SMC powergood PTAP leave-TLR (SMC-PWRGOOD-DTP-POR.S2), ID conversion (SEP path), unmapped DECERR (ext_in),
    SMC↔SEP mailbox peer outbound (SMC-MBX-CHANNELS.S1), SEP→SMC challenge IRQ (SMU-MBX-CHALLENGE.S2),
    SEP mailbox IRQ 1-core vector (SEP-MBX-IRQ-SMC.S2); excludes SEP=0 SMC inbound owned by SMU_ALL_002,
    hierarchical dual-net owned by SMU_ALL_003, and SMC-local mailbox/ext IRQ owned by SMU_ALL_004
  evidence_class: frontdoor-func
  closure_tier: B
  allocated:
    features:
    - SEP-MBX-IRQ-SMC
    - SMC-DECODE-APERTURE
    - SMC-FAB-IN-PORTS
    - SMC-MBX-CHANNELS
    - SMC-PWRGOOD-DTP-POR
    - SMU-MBX-CHALLENGE
    - SMU-PORT-SMN-AXI
    - SMU-XBAR-CONNECT
    - SMU-XBAR-ID-CONV
    - SMU-XBAR-UNMAPPED
    scenarios:
    - SMU-PORT-SMN-AXI.S2
    - SMU-PORT-SMN-AXI.S4
    - SMC-FAB-IN-PORTS.S3
    - SMU-XBAR-CONNECT.S1
    - SMU-XBAR-CONNECT.S2
    - SMU-XBAR-CONNECT.S3
    - SMU-XBAR-ID-CONV.S2
    - SMU-XBAR-UNMAPPED.S1
    - SMU-XBAR-UNMAPPED.S2
    - SMC-FAB-IN-PORTS.S1
    - SMC-FAB-IN-PORTS.S2
    - SMC-DECODE-APERTURE.S1
    - SMC-DECODE-APERTURE.S3
    - SMC-PWRGOOD-DTP-POR.S2
    - SMC-MBX-CHANNELS.S1
    - SMU-MBX-CHALLENGE.S2
    - SEP-MBX-IRQ-SMC.S2
  rationale: 'Single path: SEP=1 smu_axi_xbar / fabric-ingress / decode / SEP-peer mailbox at the SMU
    wrapper boundary. Absorbs CHANNELS.S1, CHALLENGE.S2, and SEP-MBX-IRQ-SMC.S2 re-homed from SMU_ALL_004
    because Skill 1.5 exhausted bare tb_top SEP=0 for that card: no legal SEP CPU producer (#3582); Force/deposit
    forbidden. Allocation is intent; residual #3582 / tied axi_in / hardwired JTAG / skip_fuse_sense feat_ctrl
    remain blockers, not waivers to forge.'
  size_justification: 'Option-B re-home sink: absorbs 3 SEP-peer mailbox scenarios from SMU_ALL_004 (CHANNELS.S1,
    CHALLENGE.S2, SEP-MBX-IRQ-SMC.S2) onto the existing SEP=1/xbar blocker card (prior 14 → 17) so 004
    retains only SMC-local/ext-IRQ OWNS honest on bare SEP=0. Shared producer/transport/consumer path
    is SEP=1 wrapper fabric/xbar/mailbox; kept undivided with explicit size_justification rather than
    minting a ninth area card mid-milestone.'
  reuse: smu_axi_crossbar_error_handling_test
  blockers:
  - ISSUE-3582-sep_out-producer-unavailable
  - WRAPPER-smu_axi_in-tied-off-needs-TB-unbind
  - WRAPPER-JTAG-TMS-hardwired-high-blocks-leave-TLR
  - WRAPPER-skip_fuse_sense-feat_ctrl-closed
- id: SMU_ALL_008
  anchor: smu_axi_crossbar_error_handling_test
  origin: given
  revision: 8
  supersedes_revision: 7
  current: false
  status: approved
  record_sha256: d29360e1524e0912534cd9d7183f866047a657f6dbb1f050a2a561b42e7a67ea
  approved_by: minshaoho
  approved_at: '2026-08-04T14:11:51+08:00'
  intent: Prove SEP=1 SMU 3x3 xbar connectivity/ID-conv/unmapped/outbound paths, SEP-aperture inbound,
    SMC fabric in-ports (sys/jtag/sep), SMC decode apertures, PWRGOOD PTAP leave-TLR, and SEP-peer mailbox
    / SEP→SMC mailbox IRQ paths among SMC/SEP/external (wrapper harness).
  category: SMU AXI/SMN crossbar + SMC fabric ingress/decode + SEP-peer mailbox (SEP=1)
  owns: SMU 3x3 xbar connectivity matrix, SMN AXI outbound default, SEP aperture inbound (ext_in→sep_in),
    SMC fabric in-ports sys/jtag/sep (SMC-FAB-IN-PORTS.S1/S2/S3), SMC decode apertures (SMC-DECODE-APERTURE.S1/S3),
    SMC powergood PTAP leave-TLR (SMC-PWRGOOD-DTP-POR.S2), ID conversion (SEP path), unmapped DECERR (ext_in),
    SMC↔SEP mailbox peer outbound (SMC-MBX-CHANNELS.S1), SEP→SMC challenge IRQ (SMU-MBX-CHALLENGE.S2),
    SEP mailbox IRQ 1-core vector (SEP-MBX-IRQ-SMC.S2), SMC-local mailbox inbound/decode (SMC-MBX-CHANNELS.S2/S3)
    and external mailbox IRQ LIVE bits (SMC-MBX-IRQ-EXT.S1) gated on SYS_IN filter / feat_ctrl / JTAG2AXI;
    excludes SEP=0 SMC inbound owned by SMU_ALL_002, hierarchical dual-net owned by SMU_ALL_003, and passive
    EXT width DECODE owned by SMU_ALL_004
  evidence_class: frontdoor-func
  closure_tier: B
  allocated:
    features:
    - SEP-MBX-IRQ-SMC
    - SMC-DECODE-APERTURE
    - SMC-FAB-IN-PORTS
    - SMC-MBX-CHANNELS
    - SMC-MBX-IRQ-EXT
    - SMC-PWRGOOD-DTP-POR
    - SMU-MBX-CHALLENGE
    - SMU-PORT-SMN-AXI
    - SMU-XBAR-CONNECT
    - SMU-XBAR-ID-CONV
    - SMU-XBAR-UNMAPPED
    scenarios:
    - SMU-PORT-SMN-AXI.S2
    - SMU-PORT-SMN-AXI.S4
    - SMC-FAB-IN-PORTS.S3
    - SMU-XBAR-CONNECT.S1
    - SMU-XBAR-CONNECT.S2
    - SMU-XBAR-CONNECT.S3
    - SMU-XBAR-ID-CONV.S2
    - SMU-XBAR-UNMAPPED.S1
    - SMU-XBAR-UNMAPPED.S2
    - SMC-FAB-IN-PORTS.S1
    - SMC-FAB-IN-PORTS.S2
    - SMC-DECODE-APERTURE.S1
    - SMC-DECODE-APERTURE.S3
    - SMC-PWRGOOD-DTP-POR.S2
    - SMC-MBX-CHANNELS.S1
    - SMU-MBX-CHALLENGE.S2
    - SEP-MBX-IRQ-SMC.S2
    - SMC-MBX-CHANNELS.S2
    - SMC-MBX-CHANNELS.S3
    - SMC-MBX-IRQ-EXT.S1
  rationale: 'Single path: SEP=1 smu_axi_xbar / fabric-ingress / decode / SEP-peer mailbox at the SMU
    wrapper boundary. Absorbs CHANNELS.S2/S3 and EXT.S1 re-homed from SMU_ALL_004 because Skill 1.5 exhausted
    bare tb_top SEP=0: SYS_IN BlockByDefault DECERR and sep_feat_ctrl=''0'' gate JTAG2AXI→mailbox MMIO;
    prior SEP-peer keys already here. Allocation is intent; residual blockers remain, not Force/deposit.'
  size_justification: Absorbs SMU_ALL_004 residual MMIO/LIVE mailbox scenarios (CHANNELS.S2/S3, EXT.S1)
    gated by SYS_IN BlockByDefault and SEP=0 feat_ctrl/JTAG2AXI, plus prior SEP/xbar re-homes; scenario
    count=20 with explicit blockers.
  reuse: smu_axi_crossbar_error_handling_test
  blockers:
  - ISSUE-3582-sep_out-producer-unavailable
  - WRAPPER-smu_axi_in-tied-off-needs-TB-unbind
  - WRAPPER-JTAG-TMS-hardwired-high-blocks-leave-TLR
  - WRAPPER-skip_fuse_sense-feat_ctrl-closed
  - SYS-IN-BlockByDefault-needs-filter-program
  - SEP0-feat_ctrl-tied-off-JTAG2AXI-gated
- id: SMU_ALL_005
  anchor: smu_dtp_jtag_smoke_test
  origin: given
  revision: 2
  supersedes_revision: 1
  current: true
  status: approved
  record_sha256: 98d20efe3a8ebf7aff148b85ed901c7cc1f4056b280fa624fde0ed072ad46392
  approved_by: minshaoho
  approved_at: '2026-08-05T17:37:56+08:00'
  intent: Prove DTP PTAP IDCODE/BYPASS/TRST on bare tb_top SEP=0 via frontdoor JTAG without feat_ctrl-gated
    paths.
  category: DTP PTAP JTAG smoke (SEP=0)
  owns: DTP PTAP IDCODE/BYPASS/TRST (DTP-JTAG-PTAP.S1/S2/S3); excludes JTAG2AXI/OTP/STAP paths gated by
    feat_ctrl or requiring SEP=1 / driveable wrapper JTAG
  evidence_class: frontdoor-func
  closure_tier: B
  allocated:
    features:
    - DTP-JTAG-PTAP
    scenarios:
    - DTP-JTAG-PTAP.S1
    - DTP-JTAG-PTAP.S2
    - DTP-JTAG-PTAP.S3
  rationale: 'Single path: bare tb_top SEP=0 PTAP JTAG frontdoor. Skill 1.5 STOP: JTAG2AXI/OTP/STAP need
    sep_feat_ctrl (tied ''0'' on gen_no_sep) and/or SEP=1 + real LCC; wrapper TMS hardwired high blocks
    leave-TLR. Option B re-homes gated scenarios; Force/deposit forbidden.'
  size_justification: null
  reuse: smu_dtp_jtag_smoke_test
  blockers: []
- id: SMU_ALL_008
  anchor: smu_axi_crossbar_error_handling_test
  origin: given
  revision: 9
  supersedes_revision: 8
  current: false
  status: approved
  record_sha256: 1b4d69809e7b3b6ef1bbd65d33f3bcd022bebe66f34d6e7dfef7878ca59cbc20
  approved_by: minshaoho
  approved_at: '2026-08-04T15:07:37+08:00'
  intent: Prove SEP=1 SMU 3x3 xbar connectivity/ID-conv/unmapped/outbound paths, SEP-aperture inbound,
    SMC fabric in-ports (sys/jtag/sep), SMC decode apertures, PWRGOOD PTAP leave-TLR, and SEP-peer mailbox
    / SEP→SMC mailbox IRQ paths among SMC/SEP/external (wrapper harness).
  category: SMU AXI/SMN crossbar + SMC fabric ingress/decode + SEP-peer mailbox (SEP=1)
  owns: SMU 3x3 xbar connectivity matrix, SMN AXI outbound default, SEP aperture inbound (ext_in→sep_in),
    SMC fabric in-ports sys/jtag/sep (SMC-FAB-IN-PORTS.S1/S2/S3), SMC decode apertures (SMC-DECODE-APERTURE.S1/S3),
    SMC powergood PTAP leave-TLR (SMC-PWRGOOD-DTP-POR.S2), ID conversion (SEP path), unmapped DECERR (ext_in),
    SMC↔SEP mailbox peer outbound (SMC-MBX-CHANNELS.S1), SEP→SMC challenge IRQ (SMU-MBX-CHALLENGE.S2),
    SEP mailbox IRQ 1-core vector (SEP-MBX-IRQ-SMC.S2), SMC-local mailbox inbound/decode (SMC-MBX-CHANNELS.S2/S3)
    and external mailbox IRQ LIVE bits (SMC-MBX-IRQ-EXT.S1) gated on SYS_IN filter / feat_ctrl / JTAG2AXI;
    excludes SEP=0 SMC inbound owned by SMU_ALL_002, hierarchical dual-net owned by SMU_ALL_003, and passive
    EXT width DECODE owned by SMU_ALL_004; also DTP JTAG2AXI-to-SMC, OTP AXIL, and STAP SMC/SEP selection
    re-homed from SMU_ALL_005 (feat_ctrl / SEP=1 / wrapper JTAG blockers)
  evidence_class: frontdoor-func
  closure_tier: B
  allocated:
    features:
    - DTP-JTAG2AXI-SMC
    - DTP-OTP-AXIL
    - DTP-STAP-SMC-SEP
    - SEP-MBX-IRQ-SMC
    - SMC-DECODE-APERTURE
    - SMC-FAB-IN-PORTS
    - SMC-MBX-CHANNELS
    - SMC-MBX-IRQ-EXT
    - SMC-PWRGOOD-DTP-POR
    - SMU-MBX-CHALLENGE
    - SMU-PORT-SMN-AXI
    - SMU-XBAR-CONNECT
    - SMU-XBAR-ID-CONV
    - SMU-XBAR-UNMAPPED
    scenarios:
    - SMU-PORT-SMN-AXI.S2
    - SMU-PORT-SMN-AXI.S4
    - SMC-FAB-IN-PORTS.S3
    - SMU-XBAR-CONNECT.S1
    - SMU-XBAR-CONNECT.S2
    - SMU-XBAR-CONNECT.S3
    - SMU-XBAR-ID-CONV.S2
    - SMU-XBAR-UNMAPPED.S1
    - SMU-XBAR-UNMAPPED.S2
    - SMC-FAB-IN-PORTS.S1
    - SMC-FAB-IN-PORTS.S2
    - SMC-DECODE-APERTURE.S1
    - SMC-DECODE-APERTURE.S3
    - SMC-PWRGOOD-DTP-POR.S2
    - SMC-MBX-CHANNELS.S1
    - SMU-MBX-CHALLENGE.S2
    - SEP-MBX-IRQ-SMC.S2
    - SMC-MBX-CHANNELS.S2
    - SMC-MBX-CHANNELS.S3
    - SMC-MBX-IRQ-EXT.S1
    - DTP-JTAG2AXI-SMC.S1
    - DTP-JTAG2AXI-SMC.S2
    - DTP-OTP-AXIL.S1
    - DTP-OTP-AXIL.S2
    - DTP-STAP-SMC-SEP.S1
    - DTP-STAP-SMC-SEP.S2
    - DTP-STAP-SMC-SEP.S3
  rationale: 'Single path: SEP=1 wrapper / platform-gated DTP+xbar sink. Absorbs DTP-JTAG2AXI-SMC.S1/S2,
    DTP-OTP-AXIL.S1/S2, DTP-STAP-SMC-SEP.S1/S2/S3 from SMU_ALL_005 after Skill 1.5 STOP: bare sep_feat_ctrl=''0'';
    wrapper TMS hardwired / skip_fuse_sense feat_ctrl closed. Allocation is intent.'
  size_justification: Absorbs 7 DTP feat_ctrl/SEP1/JTAG-gated scenarios from SMU_ALL_005 plus prior mailbox/xbar
    re-homes; scenario count=27 with explicit blockers.
  reuse: smu_axi_crossbar_error_handling_test
  blockers:
  - ISSUE-3582-sep_out-producer-unavailable
  - WRAPPER-smu_axi_in-tied-off-needs-TB-unbind
  - WRAPPER-JTAG-TMS-hardwired-high-blocks-leave-TLR
  - WRAPPER-skip_fuse_sense-feat_ctrl-closed
  - SYS-IN-BlockByDefault-needs-filter-program
  - SEP0-feat_ctrl-tied-off-JTAG2AXI-gated
  - DTP-OTP-STAP-needs-SEP1-and-real-LCC-feat_ctrl
- id: SMU_ALL_006
  anchor: smu_clock_stop_coordination_test
  origin: given
  revision: 2
  supersedes_revision: 1
  current: true
  status: approved
  record_sha256: 5e9e020a1de9b5206dd53b9568433a482086201ebdae23bb4d82ab6d4c97d110
  approved_by: minshaoho
  approved_at: '2026-08-05T17:37:56+08:00'
  intent: Prove DTP boot-stall, IC-reset (SMC+clear), and clock-stop aggregation on bare tb_top SEP=0
    via frontdoor JTAG/xtrig without feat_ctrl-gated paths.
  category: DTP boot-stall / IC-reset / clkstop (SEP=0)
  owns: DTP boot-stall (S1/S2), IC-reset SMC+clear (S1/S3), clock-stop aggregation (S1/S2/S3); excludes
    feat-gate and feat_ctrl x JTAG2AXI interaction gated by feat_ctrl/SEP=1
  evidence_class: frontdoor-func
  closure_tier: B
  allocated:
    features:
    - DTP-BOOT-STALL
    - DTP-CLKSTOP-AGG
    - DTP-IC-RESET
    scenarios:
    - DTP-BOOT-STALL.S1
    - DTP-BOOT-STALL.S2
    - DTP-IC-RESET.S1
    - DTP-IC-RESET.S3
    - DTP-CLKSTOP-AGG.S1
    - DTP-CLKSTOP-AGG.S2
    - DTP-CLKSTOP-AGG.S3
  rationale: 'Single path: bare tb_top SEP=0 JTAG DEBUG_CONTROL/IC_RESET/jtag_clock_stop + TB xtrig. Skill
    1.5 STOP: FEAT-GATE and INT-FEAT-CTRL-DTP-GATE need feat_ctrl toggle / JTAG2AXI; sep_feat_ctrl tied
    ''0''; wrapper TMS hardwired; Force forbidden. Option B re-homes.'
  size_justification: null
  reuse: smu_clock_stop_coordination_test
  blockers: []
- id: SMU_ALL_008
  anchor: smu_axi_crossbar_error_handling_test
  origin: given
  revision: 10
  supersedes_revision: 9
  current: false
  status: approved
  record_sha256: d76e39ab446ec6041f65a2ce6742f023055da4c14a8f8be8bf2070f2472f0804
  approved_by: minshaoho
  approved_at: '2026-08-04T16:35:51+08:00'
  intent: Prove SEP=1 SMU 3x3 xbar connectivity/ID-conv/unmapped/outbound paths, SEP-aperture inbound,
    SMC fabric in-ports (sys/jtag/sep), SMC decode apertures, PWRGOOD PTAP leave-TLR, and SEP-peer mailbox
    / SEP→SMC mailbox IRQ paths among SMC/SEP/external (wrapper harness).
  category: SMU AXI/SMN crossbar + SMC fabric ingress/decode + SEP-peer mailbox (SEP=1)
  owns: SMU 3x3 xbar connectivity matrix, SMN AXI outbound default, SEP aperture inbound (ext_in→sep_in),
    SMC fabric in-ports sys/jtag/sep (SMC-FAB-IN-PORTS.S1/S2/S3), SMC decode apertures (SMC-DECODE-APERTURE.S1/S3),
    SMC powergood PTAP leave-TLR (SMC-PWRGOOD-DTP-POR.S2), ID conversion (SEP path), unmapped DECERR (ext_in),
    SMC↔SEP mailbox peer outbound (SMC-MBX-CHANNELS.S1), SEP→SMC challenge IRQ (SMU-MBX-CHALLENGE.S2),
    SEP mailbox IRQ 1-core vector (SEP-MBX-IRQ-SMC.S2), SMC-local mailbox inbound/decode (SMC-MBX-CHANNELS.S2/S3)
    and external mailbox IRQ LIVE bits (SMC-MBX-IRQ-EXT.S1) gated on SYS_IN filter / feat_ctrl / JTAG2AXI;
    excludes SEP=0 SMC inbound owned by SMU_ALL_002, hierarchical dual-net owned by SMU_ALL_003, and passive
    EXT width DECODE owned by SMU_ALL_004; also DTP JTAG2AXI-to-SMC, OTP AXIL, and STAP SMC/SEP selection
    re-homed from SMU_ALL_005 (feat_ctrl / SEP=1 / wrapper JTAG blockers); also DTP feat-gate and feat_ctrl
    x DTP JTAG2AXI interaction re-homed from SMU_ALL_006
  evidence_class: frontdoor-func
  closure_tier: B
  allocated:
    features:
    - DTP-FEAT-GATE
    - DTP-JTAG2AXI-SMC
    - DTP-OTP-AXIL
    - DTP-STAP-SMC-SEP
    - SEP-LC-FEAT-EXPORT
    - SEP-MBX-IRQ-SMC
    - SMC-DECODE-APERTURE
    - SMC-FAB-IN-PORTS
    - SMC-MBX-CHANNELS
    - SMC-MBX-IRQ-EXT
    - SMC-PWRGOOD-DTP-POR
    - SMU-MBX-CHALLENGE
    - SMU-PORT-SMN-AXI
    - SMU-XBAR-CONNECT
    - SMU-XBAR-ID-CONV
    - SMU-XBAR-UNMAPPED
    scenarios:
    - SMU-PORT-SMN-AXI.S2
    - SMU-PORT-SMN-AXI.S4
    - SMC-FAB-IN-PORTS.S3
    - SMU-XBAR-CONNECT.S1
    - SMU-XBAR-CONNECT.S2
    - SMU-XBAR-CONNECT.S3
    - SMU-XBAR-ID-CONV.S2
    - SMU-XBAR-UNMAPPED.S1
    - SMU-XBAR-UNMAPPED.S2
    - SMC-FAB-IN-PORTS.S1
    - SMC-FAB-IN-PORTS.S2
    - SMC-DECODE-APERTURE.S1
    - SMC-DECODE-APERTURE.S3
    - SMC-PWRGOOD-DTP-POR.S2
    - SMC-MBX-CHANNELS.S1
    - SMU-MBX-CHALLENGE.S2
    - SEP-MBX-IRQ-SMC.S2
    - SMC-MBX-CHANNELS.S2
    - SMC-MBX-CHANNELS.S3
    - SMC-MBX-IRQ-EXT.S1
    - DTP-JTAG2AXI-SMC.S1
    - DTP-JTAG2AXI-SMC.S2
    - DTP-OTP-AXIL.S1
    - DTP-OTP-AXIL.S2
    - DTP-STAP-SMC-SEP.S1
    - DTP-STAP-SMC-SEP.S2
    - DTP-STAP-SMC-SEP.S3
    - DTP-FEAT-GATE.S1
    - DTP-FEAT-GATE.S2
    - DTP-FEAT-GATE.S3
    - INT-FEAT-CTRL-DTP-GATE
  rationale: SEP=1/platform-gated sink. Absorbs DTP-FEAT-GATE.S1/S2/S3 and INT-FEAT-CTRL-DTP-GATE from
    SMU_ALL_006 after Skill 1.5 STOP on bare feat_ctrl / wrapper JTAG. Allocation is intent.
  size_justification: Absorbs 4 feat_ctrl-gated scenarios from SMU_ALL_006 plus prior re-homes; scenario
    count=31 with explicit blockers.
  reuse: smu_axi_crossbar_error_handling_test
  blockers:
  - ISSUE-3582-sep_out-producer-unavailable
  - WRAPPER-smu_axi_in-tied-off-needs-TB-unbind
  - WRAPPER-JTAG-TMS-hardwired-high-blocks-leave-TLR
  - WRAPPER-skip_fuse_sense-feat_ctrl-closed
  - SYS-IN-BlockByDefault-needs-filter-program
  - SEP0-feat_ctrl-tied-off-JTAG2AXI-gated
  - DTP-OTP-STAP-needs-SEP1-and-real-LCC-feat_ctrl
  - DTP-FEAT-GATE-needs-SEP1-real-LCC-feat_ctrl
- id: SMU_ALL_007
  anchor: smu_sep_smoke_test
  origin: given
  revision: 3
  supersedes_revision: 2
  current: true
  status: approved
  record_sha256: a93b5b45d68a518caf2f6bfaafafad06b9099ea53b9ad816abbeac0c0d8f1423
  approved_by: minshaoho
  approved_at: '2026-08-05T17:37:56+08:00'
  intent: Prove SMC primary reset export and DTP CTM xtrig observe/clear on bare tb_top SEP=0 without
    SEP producer or wrapper-tied paths.
  category: SMC reset export / DTP CTM (SEP=0)
  owns: 'SMC primary reset export (SMC-RST-PRIMARY-EXPORT.S1/S2) and DTP CTM xtrig S2/S3; excludes SEP
    sysif/LC/SEC_DIS/mem/fuse/WDT/alias, CTM.S1, CTP, DTP CSR, and other #3582/harness-gated paths'
  evidence_class: frontdoor-func
  closure_tier: B
  allocated:
    features:
    - DTP-XTRIG-CTM
    - SMC-RST-PRIMARY-EXPORT
    scenarios:
    - SMC-RST-PRIMARY-EXPORT.S1
    - SMC-RST-PRIMARY-EXPORT.S2
    - DTP-XTRIG-CTM.S2
    - DTP-XTRIG-CTM.S3
  rationale: 'Single path: bare tb_top SEP=0 reset-export + CTM xtrig frontdoor. Skill 1.5 STOP: SEP-sysif/LC/SEC_DIS/mem/fuse/WDT/alias
    and CTM.S1/CTP/DTP-CSR need SEP LIVE (#3582) or wrapper paths with tied axi_in/TMS/xtrig. Option B
    re-homes; Force forbidden.'
  size_justification: null
  reuse: smu_sep_smoke_test
  blockers: []
- id: SMU_ALL_008
  anchor: smu_axi_crossbar_error_handling_test
  origin: given
  revision: 11
  supersedes_revision: 10
  current: false
  status: approved
  record_sha256: fb092161a186e7a4156b7b3e0f32cb5ac1723f15ad1eb7cfc4313b298218ae37
  approved_by: minshaoho
  approved_at: '2026-08-04T17:48:58+08:00'
  intent: Prove SEP=1 SMU 3x3 xbar connectivity/ID-conv/unmapped/outbound paths, SEP-aperture inbound,
    SMC fabric in-ports (sys/jtag/sep), SMC decode apertures, PWRGOOD PTAP leave-TLR, and SEP-peer mailbox
    / SEP→SMC mailbox IRQ paths among SMC/SEP/external (wrapper harness).
  category: SMU AXI/SMN crossbar + SMC fabric ingress/decode + SEP-peer mailbox (SEP=1)
  owns: SMU 3x3 xbar connectivity matrix, SMN AXI outbound default, SEP aperture inbound (ext_in→sep_in),
    SMC fabric in-ports sys/jtag/sep (SMC-FAB-IN-PORTS.S1/S2/S3), SMC decode apertures (SMC-DECODE-APERTURE.S1/S3),
    SMC powergood PTAP leave-TLR (SMC-PWRGOOD-DTP-POR.S2), ID conversion (SEP path), unmapped DECERR (ext_in),
    SMC↔SEP mailbox peer outbound (SMC-MBX-CHANNELS.S1), SEP→SMC challenge IRQ (SMU-MBX-CHALLENGE.S2),
    SEP mailbox IRQ 1-core vector (SEP-MBX-IRQ-SMC.S2), SMC-local mailbox inbound/decode (SMC-MBX-CHANNELS.S2/S3)
    and external mailbox IRQ LIVE bits (SMC-MBX-IRQ-EXT.S1) gated on SYS_IN filter / feat_ctrl / JTAG2AXI;
    excludes SEP=0 SMC inbound owned by SMU_ALL_002, hierarchical dual-net owned by SMU_ALL_003, and passive
    EXT width DECODE owned by SMU_ALL_004; also DTP JTAG2AXI-to-SMC, OTP AXIL, and STAP SMC/SEP selection
    re-homed from SMU_ALL_005 (feat_ctrl / SEP=1 / wrapper JTAG blockers); also DTP feat-gate and feat_ctrl
    x DTP JTAG2AXI interaction re-homed from SMU_ALL_006; also SEP sysif/LC/SEC_DIS/mem/fuse/WDT/alias,
    CTM.S1, CTP, DTP CSR, FAB-OUT-SMN, INT-CLKSTOP, and related residual paths re-homed from SMU_ALL_007
  evidence_class: frontdoor-func
  closure_tier: B
  allocated:
    features:
    - DTP-CLKSTOP-AGG
    - DTP-FEAT-GATE
    - DTP-JTAG2AXI-SMC
    - DTP-OTP-AXIL
    - DTP-STAP-SMC-SEP
    - DTP-XTRIG-CTM
    - DTP-XTRIG-CTP
    - SEP-FUSE-SENSE-HS
    - SEP-LC-FEAT-EXPORT
    - SEP-MBX-IRQ-SMC
    - SEP-MEM-BOUND-PASSTHROUGH
    - SEP-SEC-DIS
    - SEP-SYSIF-SMU-XBAR
    - SEP-WDT-RST-SMC
    - SMC-DECODE-APERTURE
    - SMC-DTP-CSR
    - SMC-FAB-IN-PORTS
    - SMC-FAB-OUT-SMN
    - SMC-MBX-CHANNELS
    - SMC-MBX-IRQ-EXT
    - SMC-PWRGOOD-DTP-POR
    - SMU-MBX-CHALLENGE
    - SMU-PORT-SMN-AXI
    - SMU-SEP-SMC-ALIAS
    - SMU-XBAR-CONNECT
    - SMU-XBAR-ID-CONV
    - SMU-XBAR-UNMAPPED
    scenarios:
    - SMU-PORT-SMN-AXI.S2
    - SMU-PORT-SMN-AXI.S4
    - SMC-FAB-IN-PORTS.S3
    - SMU-XBAR-CONNECT.S1
    - SMU-XBAR-CONNECT.S2
    - SMU-XBAR-CONNECT.S3
    - SMU-XBAR-ID-CONV.S2
    - SMU-XBAR-UNMAPPED.S1
    - SMU-XBAR-UNMAPPED.S2
    - SMC-FAB-IN-PORTS.S1
    - SMC-FAB-IN-PORTS.S2
    - SMC-DECODE-APERTURE.S1
    - SMC-DECODE-APERTURE.S3
    - SMC-PWRGOOD-DTP-POR.S2
    - SMC-MBX-CHANNELS.S1
    - SMU-MBX-CHALLENGE.S2
    - SEP-MBX-IRQ-SMC.S2
    - SMC-MBX-CHANNELS.S2
    - SMC-MBX-CHANNELS.S3
    - SMC-MBX-IRQ-EXT.S1
    - DTP-JTAG2AXI-SMC.S1
    - DTP-JTAG2AXI-SMC.S2
    - DTP-OTP-AXIL.S1
    - DTP-OTP-AXIL.S2
    - DTP-STAP-SMC-SEP.S1
    - DTP-STAP-SMC-SEP.S2
    - DTP-STAP-SMC-SEP.S3
    - DTP-FEAT-GATE.S1
    - DTP-FEAT-GATE.S2
    - DTP-FEAT-GATE.S3
    - INT-FEAT-CTRL-DTP-GATE
    - SEP-SYSIF-SMU-XBAR.S2
    - SEP-SYSIF-SMU-XBAR.S3
    - SEP-LC-FEAT-EXPORT.S1
    - SEP-LC-FEAT-EXPORT.S2
    - SEP-LC-FEAT-EXPORT.S3
    - SEP-SEC-DIS.S1
    - SEP-SEC-DIS.S2
    - SMC-FAB-OUT-SMN.S1
    - SMC-DTP-CSR.S1
    - SMC-DTP-CSR.S2
    - DTP-XTRIG-CTM.S1
    - DTP-XTRIG-CTP.S1
    - INT-CLKSTOP-SMC-CLA
    - SEP-MEM-BOUND-PASSTHROUGH.S1
    - SEP-MEM-BOUND-PASSTHROUGH.S2
    - SEP-FUSE-SENSE-HS.S1
    - SEP-FUSE-SENSE-HS.S2
    - SEP-WDT-RST-SMC.S1
    - SEP-WDT-RST-SMC.S2
    - INT-ALIAS-VS-XBAR-SMC
    - SMU-SEP-SMC-ALIAS.S1
    - SMU-SEP-SMC-ALIAS.S3
  rationale: Platform-gated sink. Absorbs SMU_ALL_007 residual scenarios after Skill 1.5 STOP (#3582 sep_out
    / wrapper TMS/axi_in/xtrig / bare SEP=0). Allocation is intent.
  size_justification: Absorbs 22 scenarios from SMU_ALL_007 plus prior re-homes; scenario count=53 with
    explicit blockers.
  reuse: smu_axi_crossbar_error_handling_test
  blockers:
  - ISSUE-3582-sep_out-producer-unavailable
  - WRAPPER-smu_axi_in-tied-off-needs-TB-unbind
  - WRAPPER-JTAG-TMS-hardwired-high-blocks-leave-TLR
  - WRAPPER-skip_fuse_sense-feat_ctrl-closed
  - SYS-IN-BlockByDefault-needs-filter-program
  - SEP0-feat_ctrl-tied-off-JTAG2AXI-gated
  - DTP-OTP-STAP-needs-SEP1-and-real-LCC-feat_ctrl
  - DTP-FEAT-GATE-needs-SEP1-real-LCC-feat_ctrl
  - WRAPPER-xtrig-tied-off
  - BARE-SEP0-no-sep-sysif-xbar
- id: SMU_ALL_008
  anchor: smu_axi_crossbar_error_handling_test
  origin: given
  revision: 12
  supersedes_revision: 11
  current: false
  status: approved
  record_sha256: 8abe067a44d65d73a5f2bfd12e8ac5f0b67c75d1d7a4cb7c858a1baa189b30f4
  approved_by: minshaoho
  approved_at: '2026-08-05T07:45:45+08:00'
  intent: Prove SEP=1 SMU 3x3 xbar connectivity/ID-conv/unmapped/outbound paths, SEP-aperture inbound,
    SMC fabric in-ports (sys/jtag/sep), SMC decode apertures, PWRGOOD PTAP leave-TLR, SEP-peer mailbox
    / SEP→SMC mailbox IRQ paths, plus reverse-omission SMC/SEP boot, AXI-Lite shims, iJTAG/BSR scan, fuse-sense×boot,
    and aperture×mailbox interop among SMC/SEP/external (wrapper harness).
  category: SMU AXI/SMN crossbar + SMC fabric ingress/decode + SEP-peer mailbox (SEP=1)
  owns: SMU 3x3 xbar connectivity matrix, SMN AXI outbound default, SEP aperture inbound (ext_in→sep_in),
    SMC fabric in-ports sys/jtag/sep (SMC-FAB-IN-PORTS.S1/S2/S3), SMC decode apertures (SMC-DECODE-APERTURE.S1/S3),
    SMC powergood PTAP leave-TLR (SMC-PWRGOOD-DTP-POR.S2), ID conversion (SEP path), unmapped DECERR (ext_in),
    SMC↔SEP mailbox peer outbound (SMC-MBX-CHANNELS.S1), SEP→SMC challenge IRQ (SMU-MBX-CHALLENGE.S2),
    SEP mailbox IRQ 1-core vector (SEP-MBX-IRQ-SMC.S2), SMC-local mailbox inbound/decode (SMC-MBX-CHANNELS.S2/S3)
    and external mailbox IRQ LIVE bits (SMC-MBX-IRQ-EXT.S1) gated on SYS_IN filter / feat_ctrl / JTAG2AXI;
    excludes SEP=0 SMC inbound owned by SMU_ALL_002, hierarchical dual-net owned by SMU_ALL_003, and passive
    EXT width DECODE owned by SMU_ALL_004; also DTP JTAG2AXI-to-SMC, OTP AXIL, and STAP SMC/SEP selection
    re-homed from SMU_ALL_005 (feat_ctrl / SEP=1 / wrapper JTAG blockers); also DTP feat-gate and feat_ctrl
    x DTP JTAG2AXI interaction re-homed from SMU_ALL_006; also SEP sysif/LC/SEC_DIS/mem/fuse/WDT/alias,
    CTM.S1, CTP, DTP CSR, FAB-OUT-SMN, INT-CLKSTOP, and related residual paths re-homed from SMU_ALL_007;
    also SMC-BOOT.S1/S2/S3, SEP-BOOT.S1/S2, SMC-AXI-LITE-SHIMS.S1/S2, DTP-IJTAG-SCAN.S1/S2, INT-FUSE-SENSE-BOOT,
    INT-XBAR-APERTURE-INTEROP re-homed from reverse_diff CONFIRMED-OMISSION amend (platform-gated; not
    new runnable mid-gate cards)
  evidence_class: frontdoor-func
  closure_tier: B
  allocated:
    features:
    - DTP-CLKSTOP-AGG
    - DTP-FEAT-GATE
    - DTP-IJTAG-SCAN
    - DTP-JTAG2AXI-SMC
    - DTP-OTP-AXIL
    - DTP-STAP-SMC-SEP
    - DTP-XTRIG-CTM
    - DTP-XTRIG-CTP
    - SEP-BOOT
    - SEP-FUSE-SENSE-HS
    - SEP-LC-FEAT-EXPORT
    - SEP-MBX-IRQ-SMC
    - SEP-MEM-BOUND-PASSTHROUGH
    - SEP-SEC-DIS
    - SEP-SYSIF-SMU-XBAR
    - SEP-WDT-RST-SMC
    - SMC-AXI-LITE-SHIMS
    - SMC-BOOT
    - SMC-DECODE-APERTURE
    - SMC-DTP-CSR
    - SMC-FAB-IN-PORTS
    - SMC-FAB-OUT-SMN
    - SMC-MBX-CHANNELS
    - SMC-MBX-IRQ-EXT
    - SMC-PWRGOOD-DTP-POR
    - SMU-MBX-CHALLENGE
    - SMU-PORT-SMN-AXI
    - SMU-SEP-SMC-ALIAS
    - SMU-XBAR-APERTURE
    - SMU-XBAR-CONNECT
    - SMU-XBAR-ID-CONV
    - SMU-XBAR-UNMAPPED
    scenarios:
    - SMU-PORT-SMN-AXI.S2
    - SMU-PORT-SMN-AXI.S4
    - SMC-FAB-IN-PORTS.S3
    - SMU-XBAR-CONNECT.S1
    - SMU-XBAR-CONNECT.S2
    - SMU-XBAR-CONNECT.S3
    - SMU-XBAR-ID-CONV.S2
    - SMU-XBAR-UNMAPPED.S1
    - SMU-XBAR-UNMAPPED.S2
    - SMC-FAB-IN-PORTS.S1
    - SMC-FAB-IN-PORTS.S2
    - SMC-DECODE-APERTURE.S1
    - SMC-DECODE-APERTURE.S3
    - SMC-PWRGOOD-DTP-POR.S2
    - SMC-MBX-CHANNELS.S1
    - SMU-MBX-CHALLENGE.S2
    - SEP-MBX-IRQ-SMC.S2
    - SMC-MBX-CHANNELS.S2
    - SMC-MBX-CHANNELS.S3
    - SMC-MBX-IRQ-EXT.S1
    - DTP-JTAG2AXI-SMC.S1
    - DTP-JTAG2AXI-SMC.S2
    - DTP-OTP-AXIL.S1
    - DTP-OTP-AXIL.S2
    - DTP-STAP-SMC-SEP.S1
    - DTP-STAP-SMC-SEP.S2
    - DTP-STAP-SMC-SEP.S3
    - DTP-FEAT-GATE.S1
    - DTP-FEAT-GATE.S2
    - DTP-FEAT-GATE.S3
    - INT-FEAT-CTRL-DTP-GATE
    - SEP-SYSIF-SMU-XBAR.S2
    - SEP-SYSIF-SMU-XBAR.S3
    - SEP-LC-FEAT-EXPORT.S1
    - SEP-LC-FEAT-EXPORT.S2
    - SEP-LC-FEAT-EXPORT.S3
    - SEP-SEC-DIS.S1
    - SEP-SEC-DIS.S2
    - SMC-FAB-OUT-SMN.S1
    - SMC-DTP-CSR.S1
    - SMC-DTP-CSR.S2
    - DTP-XTRIG-CTM.S1
    - DTP-XTRIG-CTP.S1
    - INT-CLKSTOP-SMC-CLA
    - SEP-MEM-BOUND-PASSTHROUGH.S1
    - SEP-MEM-BOUND-PASSTHROUGH.S2
    - SEP-FUSE-SENSE-HS.S1
    - SEP-FUSE-SENSE-HS.S2
    - SEP-WDT-RST-SMC.S1
    - SEP-WDT-RST-SMC.S2
    - INT-ALIAS-VS-XBAR-SMC
    - SMU-SEP-SMC-ALIAS.S1
    - SMU-SEP-SMC-ALIAS.S3
    - SMC-BOOT.S1
    - SMC-BOOT.S2
    - SMC-BOOT.S3
    - SEP-BOOT.S1
    - SEP-BOOT.S2
    - SMC-AXI-LITE-SHIMS.S1
    - SMC-AXI-LITE-SHIMS.S2
    - DTP-IJTAG-SCAN.S1
    - DTP-IJTAG-SCAN.S2
    - INT-FUSE-SENSE-BOOT
    - INT-XBAR-APERTURE-INTEROP
  rationale: Platform-gated sink. Absorbs SMU_ALL_007 residual scenarios after Skill 1.5 STOP (#3582 sep_out
    / wrapper TMS/axi_in/xtrig / bare SEP=0). Amendment r12 absorbs reverse_diff omission keys (boot/shims/ijtag/fuse-boot/aperture-interop)
    onto 008 with explicit blockers rather than inventing new runnable cards mid-gate. Allocation is intent.
  size_justification: Absorbs prior Option-B re-homes plus 11 reverse-omission scenarios/interactions;
    scenario count=64 with explicit blockers; review-budget overshoot justified by single platform-gated
    sink (no mid-gate new anchors).
  reuse: smu_axi_crossbar_error_handling_test
  blockers:
  - ISSUE-3582-sep_out-producer-unavailable
  - WRAPPER-smu_axi_in-tied-off-needs-TB-unbind
  - WRAPPER-JTAG-TMS-hardwired-high-blocks-leave-TLR
  - WRAPPER-skip_fuse_sense-feat_ctrl-closed
  - SYS-IN-BlockByDefault-needs-filter-program
  - SEP0-feat_ctrl-tied-off-JTAG2AXI-gated
  - DTP-OTP-STAP-needs-SEP1-and-real-LCC-feat_ctrl
  - DTP-FEAT-GATE-needs-SEP1-real-LCC-feat_ctrl
  - WRAPPER-xtrig-tied-off
  - BARE-SEP0-no-sep-sysif-xbar
  - SMC-BOOT-needs-ROM-firmware-or-wrapper-harness
  - SEP-BOOT-needs-SEP1-TCM-preload-and-ISSUE-3582
  - AXIL-SHIM-needs-external-PLL-PVT-or-VIP-model
  - IJTAG-BSR-needs-scan-loopback-or-scan-model
  - INT-FUSE-SENSE-BOOT-needs-real-fuse-bringup
  - INT-XBAR-APERTURE-INTEROP-needs-aperture-CSR-SF009
- id: SMU_ALL_008
  anchor: smu_axi_crossbar_error_handling_test
  origin: given
  revision: 13
  supersedes_revision: 12
  current: false
  status: candidate
  record_sha256: 8571709d7a5d5e31d6ee5d9c66f51dc62e1763b69c64af21dcc22ac7a7a5d995
  approved_by: null
  approved_at: null
  intent: 'P2 placeholder: former platform-gated residual sink; all scenarios deferred to P3.'
  category: deferred residual sink (empty at P2)
  owns: none — all former SMU_ALL_008 scenarios accepted OUT-OF-MILESTONE to P3
  evidence_class: frontdoor-func
  closure_tier: B
  allocated:
    features: []
    scenarios: []
  rationale: 'Standing order: do not implement 008 on blocked platform. P2 owner accepts OUT-OF-MILESTONE
    deferral of residual keys to P3; allocation emptied.'
  size_justification: null
  reuse: smu_axi_crossbar_error_handling_test
  blockers:
  - ISSUE-3582-sep_out-producer-unavailable
  - WRAPPER-smu_axi_in-tied-off-needs-TB-unbind
  - WRAPPER-JTAG-TMS-hardwired-high-blocks-leave-TLR
  - WRAPPER-skip_fuse_sense-feat_ctrl-closed
  - SYS-IN-BlockByDefault-needs-filter-program
  - SEP0-feat_ctrl-tied-off-JTAG2AXI-gated
  - DTP-OTP-STAP-needs-SEP1-and-real-LCC-feat_ctrl
  - DTP-FEAT-GATE-needs-SEP1-real-LCC-feat_ctrl
  - WRAPPER-xtrig-tied-off
  - BARE-SEP0-no-sep-sysif-xbar
  - SMC-BOOT-needs-ROM-firmware-or-wrapper-harness
  - SEP-BOOT-needs-SEP1-TCM-preload-and-ISSUE-3582
  - AXIL-SHIM-needs-external-PLL-PVT-or-VIP-model
  - IJTAG-BSR-needs-scan-loopback-or-scan-model
  - INT-FUSE-SENSE-BOOT-needs-real-fuse-bringup
  - INT-XBAR-APERTURE-INTEROP-needs-aperture-CSR-SF009
- id: SMU_ALL_008
  anchor: smu_axi_crossbar_error_handling_test
  origin: given
  revision: 14
  supersedes_revision: 12
  current: false
  status: approved
  record_sha256: a094fe30331cba18fe5254291c416526b062790ef09d11aaf5ba2fa4cb4cba16
  approved_by: minshaoho
  approved_at: '2026-08-05T08:32:38+08:00'
  intent: Prove SEP=1 SMU 3x3 xbar connectivity/ID-conv/unmapped/outbound paths, SEP-aperture inbound,
    SMC fabric in-ports (sys/jtag/sep), SMC decode apertures, PWRGOOD PTAP leave-TLR, SEP-peer mailbox
    / SEP→SMC mailbox IRQ paths, plus reverse-omission SMC/SEP boot, AXI-Lite shims, iJTAG/BSR scan, fuse-sense×boot,
    and aperture×mailbox interop among SMC/SEP/external (wrapper harness).
  category: SMU AXI/SMN crossbar + SMC fabric ingress/decode + SEP-peer mailbox (SEP=1)
  owns: SMU 3x3 xbar connectivity matrix, SMN AXI outbound default, SEP aperture inbound (ext_in→sep_in),
    SMC fabric in-ports sys/jtag/sep (SMC-FAB-IN-PORTS.S1/S2/S3), SMC decode apertures (SMC-DECODE-APERTURE.S1/S3),
    SMC powergood PTAP leave-TLR (SMC-PWRGOOD-DTP-POR.S2), ID conversion (SEP path), unmapped DECERR (ext_in),
    SMC↔SEP mailbox peer outbound (SMC-MBX-CHANNELS.S1), SEP→SMC challenge IRQ (SMU-MBX-CHALLENGE.S2),
    SEP mailbox IRQ 1-core vector (SEP-MBX-IRQ-SMC.S2), SMC-local mailbox inbound/decode (SMC-MBX-CHANNELS.S2/S3)
    and external mailbox IRQ LIVE bits (SMC-MBX-IRQ-EXT.S1) gated on SYS_IN filter / feat_ctrl / JTAG2AXI;
    excludes SEP=0 SMC inbound owned by SMU_ALL_002, hierarchical dual-net owned by SMU_ALL_003, and passive
    EXT width DECODE owned by SMU_ALL_004; also DTP JTAG2AXI-to-SMC, OTP AXIL, and STAP SMC/SEP selection
    re-homed from SMU_ALL_005 (feat_ctrl / SEP=1 / wrapper JTAG blockers); also DTP feat-gate and feat_ctrl
    x DTP JTAG2AXI interaction re-homed from SMU_ALL_006; also SEP sysif/LC/SEC_DIS/mem/fuse/WDT/alias,
    CTM.S1, CTP, DTP CSR, FAB-OUT-SMN, INT-CLKSTOP, and related residual paths re-homed from SMU_ALL_007;
    also SMC-BOOT.S1/S2/S3, SEP-BOOT.S1/S2, SMC-AXI-LITE-SHIMS.S1/S2, DTP-IJTAG-SCAN.S1/S2, INT-FUSE-SENSE-BOOT,
    INT-XBAR-APERTURE-INTEROP re-homed from reverse_diff CONFIRMED-OMISSION amend (platform-gated; not
    new runnable mid-gate cards)
  evidence_class: frontdoor-func
  closure_tier: B
  allocated:
    features:
    - DTP-CLKSTOP-AGG
    - DTP-FEAT-GATE
    - DTP-IJTAG-SCAN
    - DTP-JTAG2AXI-SMC
    - DTP-OTP-AXIL
    - DTP-STAP-SMC-SEP
    - DTP-XTRIG-CTM
    - DTP-XTRIG-CTP
    - SEP-BOOT
    - SEP-FUSE-SENSE-HS
    - SEP-LC-FEAT-EXPORT
    - SEP-MBX-IRQ-SMC
    - SEP-MEM-BOUND-PASSTHROUGH
    - SEP-SEC-DIS
    - SEP-SYSIF-SMU-XBAR
    - SEP-WDT-RST-SMC
    - SMC-AXI-LITE-SHIMS
    - SMC-BOOT
    - SMC-DECODE-APERTURE
    - SMC-DTP-CSR
    - SMC-FAB-IN-PORTS
    - SMC-FAB-OUT-SMN
    - SMC-MBX-CHANNELS
    - SMC-MBX-IRQ-EXT
    - SMC-PWRGOOD-DTP-POR
    - SMU-MBX-CHALLENGE
    - SMU-PORT-SMN-AXI
    - SMU-SEP-SMC-ALIAS
    - SMU-XBAR-APERTURE
    - SMU-XBAR-CONNECT
    - SMU-XBAR-ID-CONV
    - SMU-XBAR-UNMAPPED
    scenarios:
    - SMU-PORT-SMN-AXI.S2
    - SMU-PORT-SMN-AXI.S4
    - SMC-FAB-IN-PORTS.S3
    - SMU-XBAR-CONNECT.S1
    - SMU-XBAR-CONNECT.S2
    - SMU-XBAR-CONNECT.S3
    - SMU-XBAR-ID-CONV.S2
    - SMU-XBAR-UNMAPPED.S1
    - SMU-XBAR-UNMAPPED.S2
    - SMC-FAB-IN-PORTS.S1
    - SMC-FAB-IN-PORTS.S2
    - SMC-DECODE-APERTURE.S1
    - SMC-DECODE-APERTURE.S3
    - SMC-PWRGOOD-DTP-POR.S2
    - SMC-MBX-CHANNELS.S1
    - SMU-MBX-CHALLENGE.S2
    - SEP-MBX-IRQ-SMC.S2
    - SMC-MBX-CHANNELS.S2
    - SMC-MBX-CHANNELS.S3
    - SMC-MBX-IRQ-EXT.S1
    - DTP-JTAG2AXI-SMC.S1
    - DTP-JTAG2AXI-SMC.S2
    - DTP-OTP-AXIL.S1
    - DTP-OTP-AXIL.S2
    - DTP-STAP-SMC-SEP.S1
    - DTP-STAP-SMC-SEP.S2
    - DTP-STAP-SMC-SEP.S3
    - DTP-FEAT-GATE.S1
    - DTP-FEAT-GATE.S2
    - DTP-FEAT-GATE.S3
    - INT-FEAT-CTRL-DTP-GATE
    - SEP-SYSIF-SMU-XBAR.S2
    - SEP-SYSIF-SMU-XBAR.S3
    - SEP-LC-FEAT-EXPORT.S1
    - SEP-LC-FEAT-EXPORT.S2
    - SEP-LC-FEAT-EXPORT.S3
    - SEP-SEC-DIS.S1
    - SEP-SEC-DIS.S2
    - SMC-FAB-OUT-SMN.S1
    - SMC-DTP-CSR.S1
    - SMC-DTP-CSR.S2
    - DTP-XTRIG-CTM.S1
    - DTP-XTRIG-CTP.S1
    - INT-CLKSTOP-SMC-CLA
    - SEP-MEM-BOUND-PASSTHROUGH.S1
    - SEP-MEM-BOUND-PASSTHROUGH.S2
    - SEP-FUSE-SENSE-HS.S1
    - SEP-FUSE-SENSE-HS.S2
    - SEP-WDT-RST-SMC.S1
    - SEP-WDT-RST-SMC.S2
    - INT-ALIAS-VS-XBAR-SMC
    - SMU-SEP-SMC-ALIAS.S1
    - SMU-SEP-SMC-ALIAS.S3
    - SMC-BOOT.S1
    - SMC-BOOT.S2
    - SMC-BOOT.S3
    - SEP-BOOT.S1
    - SEP-BOOT.S2
    - SMC-AXI-LITE-SHIMS.S1
    - SMC-AXI-LITE-SHIMS.S2
    - DTP-IJTAG-SCAN.S1
    - DTP-IJTAG-SCAN.S2
    - INT-FUSE-SENSE-BOOT
    - INT-XBAR-APERTURE-INTEROP
  rationale: Platform-gated sink. Absorbs SMU_ALL_007 residual scenarios after Skill 1.5 STOP (#3582 sep_out
    / wrapper TMS/axi_in/xtrig / bare SEP=0). Amendment r12 absorbs reverse_diff omission keys (boot/shims/ijtag/fuse-boot/aperture-interop)
    onto 008 with explicit blockers rather than inventing new runnable cards mid-gate. Allocation is intent.
    Plan_revision 13 SF-row reclass after SPEC_REVIEW partial close; 008 remains allocated platform sink
    (packet budget prevents bulk P3 defer rows).
  size_justification: Absorbs prior Option-B re-homes plus 11 reverse-omission scenarios/interactions;
    scenario count=64 with explicit blockers; review-budget overshoot justified by single platform-gated
    sink (no mid-gate new anchors).
  reuse: smu_axi_crossbar_error_handling_test
  blockers:
  - ISSUE-3582-sep_out-producer-unavailable
  - WRAPPER-smu_axi_in-tied-off-needs-TB-unbind
  - WRAPPER-JTAG-TMS-hardwired-high-blocks-leave-TLR
  - WRAPPER-skip_fuse_sense-feat_ctrl-closed
  - SYS-IN-BlockByDefault-needs-filter-program
  - SEP0-feat_ctrl-tied-off-JTAG2AXI-gated
  - DTP-OTP-STAP-needs-SEP1-and-real-LCC-feat_ctrl
  - DTP-FEAT-GATE-needs-SEP1-real-LCC-feat_ctrl
  - WRAPPER-xtrig-tied-off
  - BARE-SEP0-no-sep-sysif-xbar
  - SMC-BOOT-needs-ROM-firmware-or-wrapper-harness
  - SEP-BOOT-needs-SEP1-TCM-preload-and-ISSUE-3582
  - AXIL-SHIM-needs-external-PLL-PVT-or-VIP-model
  - IJTAG-BSR-needs-scan-loopback-or-scan-model
  - INT-FUSE-SENSE-BOOT-needs-real-fuse-bringup
  - INT-XBAR-APERTURE-INTEROP-needs-aperture-CSR-SF009
- id: SMU_ALL_008
  anchor: smu_axi_crossbar_error_handling_test
  origin: given
  revision: 15
  supersedes_revision: 14
  current: false
  status: approved
  record_sha256: 0cbcac3e2998c025fff8f637aef6688de0ba54aefbf79cf74d6fbd78b91e2c4b
  approved_by: minshaoho
  approved_at: '2026-08-05T17:27:00+08:00'
  intent: Prove honest bare-tb_top SEP=0 SMC fabric decode + sys_axi_in ingress + DTP PTAP leave-TLR under
    power-good (Option-B 008a after Skill 1.5 STOP on monolithic 64-scenario sink).
  category: SMC fabric decode / sys ingress / PTAP leave-TLR (bare SEP=0)
  owns: SMC-PWRGOOD-DTP-POR.S2 (PTAP leave-TLR with power-good+TRST released), SMC-FAB-IN-PORTS.S1 (sys_axi_in
    reaches allowed SMC resource), SMC-DECODE-APERTURE.S1 (LOCAL vs GLOBAL same-component), SMC-DECODE-APERTURE.S3
    (mailbox + DTP ctrl decode). Platform-gated residuals from prior 008 sink are OUT-OF-MILESTONE (P3)
    on this plan.
  evidence_class: frontdoor-func
  closure_tier: B
  allocated:
    features:
    - SMC-DECODE-APERTURE
    - SMC-FAB-IN-PORTS
    - SMC-PWRGOOD-DTP-POR
    scenarios:
    - SMC-PWRGOOD-DTP-POR.S2
    - SMC-FAB-IN-PORTS.S1
    - SMC-DECODE-APERTURE.S1
    - SMC-DECODE-APERTURE.S3
  rationale: 'Option-B Skill 1 amend after Skill 1.5 STOP: keep only 4 honest bare-SEP=0 scenarios; 60
    platform-gated residuals signed OUT-OF-MILESTONE (P3) — packet budget uses SMU_ALL quality-policy
    fork (max_rows=120). Allocation is intent; no Force/deposit.'
  size_justification: null
  reuse: smu_axi_crossbar_error_handling_test
  blockers: []
- id: SMU_ALL_008
  anchor: smu_axi_crossbar_error_handling_test
  origin: given
  revision: 16
  supersedes_revision: 15
  current: false
  status: approved
  record_sha256: 73c662b203e1a3cb19aa4bd00fbbabe6b5b8023948f0335d7e30e1975628d35b
  approved_by: minshaoho
  approved_at: '2026-08-05T17:36:57+08:00'
  intent: 'Prove honest bare-tb_top SEP=0 SMC sys_axi_in ingress + DTP PTAP leave-TLR under power-good
    (Option-B after Skill 1.5 STOP: DECODE apertures need filter allow / JTAG2AXI — deferred P3).'
  category: SMC sys ingress + PTAP leave-TLR (bare SEP=0)
  owns: 'SMC-PWRGOOD-DTP-POR.S2 (PTAP leave-TLR with power-good+TRST released), SMC-FAB-IN-PORTS.S1 (sys_axi_in
    reaches SMU/SMC boundary path with documented widths). SMC-DECODE-APERTURE.S1/S3 OUT-OF-MILESTONE
    (P3): SYS_IN BlockByDefault poison + SEP=0 JTAG2AXI gated.'
  evidence_class: frontdoor-func
  closure_tier: B
  allocated:
    features:
    - SMC-FAB-IN-PORTS
    - SMC-PWRGOOD-DTP-POR
    scenarios:
    - SMC-PWRGOOD-DTP-POR.S2
    - SMC-FAB-IN-PORTS.S1
  rationale: 'Option-B after Skill 1.5 STOP on 008a: DECODE.S1/S3 cannot prove same-component identity
    under universal SYS_IN DECERR poison without filter allow or JTAG2AXI (SEP=0 feat_ctrl tied). Keep
    PWRGOOD.S2 + FAB-IN.S1 which produced PASS tokens. No Force/deposit; checker strength retained.'
  size_justification: null
  reuse: smu_axi_crossbar_error_handling_test
  blockers: []
- id: SMU_ALL_008
  anchor: smu_axi_crossbar_error_handling_test
  origin: given
  revision: 17
  supersedes_revision: 16
  current: true
  status: approved
  record_sha256: f79c50aeaa5d0c5aa0afb34c305d2e5763cc2a5af8ba95d7df377cc53c2f8859
  approved_by: minshaoho
  approved_at: '2026-08-05T17:37:56+08:00'
  intent: 'Prove honest bare-tb_top SEP=0 DTP PTAP leave-TLR under power-good+TRST released (Option-B
    after Skill 1.5: FAB-IN.S1 DECERR-poison is not "allowed resource"; DECODE deferred).'
  category: DTP PTAP leave-TLR (bare SEP=0)
  owns: 'SMC-PWRGOOD-DTP-POR.S2 only. SMC-FAB-IN-PORTS.S1 OUT-OF-MILESTONE (P3): SYS_IN BlockByDefault
    poison is not an allowed SMC resource. SMC-DECODE-APERTURE.S1/S3 already OOM.'
  evidence_class: frontdoor-func
  closure_tier: B
  allocated:
    features:
    - SMC-PWRGOOD-DTP-POR
    scenarios:
    - SMC-PWRGOOD-DTP-POR.S2
  rationale: 'Option-B honesty fix: prior 008a logged FAB-IN.S1 PASS with rresp=DECERR/0xBADCAB1E — contradicts
    card proof "reaches an allowed SMC resource". Defer FAB+DECODE to P3; keep only PWRGOOD.S2 which honestly
    left TLR. No Force; do not weaken checker.'
  size_justification: null
  reuse: smu_axi_crossbar_error_handling_test
  blockers: []
unallocated:
- key: DTP-OTP-AXIL.S3
  reason: OUT-OF-MILESTONE
  detail: 'P3: formerly BLOCKED-BY-SPEC-FINDING (SF-007 now waived); closes in milestone P3 after SPEC/platform
    readiness.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:16:48+08:00'
- key: INT-MBX-CHALLENGE-IRQ
  reason: OUT-OF-MILESTONE
  detail: 'P3: formerly BLOCKED-BY-SPEC-FINDING (SF-006 now waived); closes in milestone P3 after SPEC/platform
    readiness.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:16:48+08:00'
- key: INT-PWRGOOD-DTP-POR
  reason: OUT-OF-MILESTONE
  detail: 'P3: formerly BLOCKED-BY-SPEC-FINDING (SF-001 now answered); closes in milestone P3 after platform/SPEC
    readiness.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T08:32:03+08:00'
- key: INT-SEP0-OTP-ERR
  reason: OUT-OF-MILESTONE
  detail: 'P3: formerly BLOCKED-BY-SPEC-FINDING (SF-007 now waived); closes in milestone P3 after SPEC/platform
    readiness.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:16:48+08:00'
- key: SEP-MBX-IRQ-SMC.S1
  reason: OUT-OF-MILESTONE
  detail: 'P3: formerly BLOCKED-BY-SPEC-FINDING (SF-006 now waived); closes in milestone P3 after SPEC/platform
    readiness.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:16:48+08:00'
- key: SEP-SYSIF-SMU-XBAR.S1
  reason: OUT-OF-MILESTONE
  detail: 'P3: formerly BLOCKED-BY-SPEC-FINDING (SF-004 now waived); closes in milestone P3 after platform/SPEC
    readiness.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T08:32:03+08:00'
- key: SMC-DECODE-APERTURE.S2
  reason: OUT-OF-MILESTONE
  detail: 'P3: formerly BLOCKED-BY-SPEC-FINDING (SF-003 now answered); closes in milestone P3 after platform/SPEC
    readiness.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T08:32:03+08:00'
- key: SMC-FAB-DUAL-NET.S1
  reason: OUT-OF-MILESTONE
  detail: 'P3: formerly BLOCKED-BY-SPEC-FINDING (SF-003 now answered); closes in milestone P3 after platform/SPEC
    readiness.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T08:32:03+08:00'
- key: SMC-PWRGOOD-DTP-POR.S1
  reason: OUT-OF-MILESTONE
  detail: 'P3: formerly BLOCKED-BY-SPEC-FINDING (SF-001 now answered); closes in milestone P3 after platform/SPEC
    readiness.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T08:32:03+08:00'
- key: SMU-MBX-CHALLENGE.S1
  reason: OUT-OF-MILESTONE
  detail: 'P3: formerly BLOCKED-BY-SPEC-FINDING (SF-006 now waived); closes in milestone P3 after SPEC/platform
    readiness.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:16:48+08:00'
- key: SMU-PORT-CLK-RST.S2
  reason: OUT-OF-MILESTONE
  detail: 'P3: formerly BLOCKED-BY-SPEC-FINDING (SF-001 now answered); closes in milestone P3 after platform/SPEC
    readiness.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T08:32:03+08:00'
- key: SMU-PORT-SMN-AXI.S3
  reason: OUT-OF-MILESTONE
  detail: 'P3: formerly BLOCKED-BY-SPEC-FINDING (SF-002 now answered); closes in milestone P3 after platform/SPEC
    readiness.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T08:32:03+08:00'
- key: SMU-SEP-PARAM.S3
  reason: OUT-OF-MILESTONE
  detail: 'P3: formerly BLOCKED-BY-SPEC-FINDING (SF-007 now waived); closes in milestone P3 after SPEC/platform
    readiness.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:16:48+08:00'
- key: SMU-XBAR-APERTURE.S1
  reason: OUT-OF-MILESTONE
  detail: 'P3: formerly BLOCKED-BY-SPEC-FINDING (SF-009 now waived); closes in milestone P3 after SPEC/platform
    readiness.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:16:48+08:00'
- key: SMU-XBAR-APERTURE.S2
  reason: OUT-OF-MILESTONE
  detail: 'P3: formerly BLOCKED-BY-SPEC-FINDING (SF-009 now waived); closes in milestone P3 after SPEC/platform
    readiness.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:16:48+08:00'
- key: SMU-XBAR-ATOP-REJECT.S1
  reason: OUT-OF-MILESTONE
  detail: 'P3: formerly BLOCKED-BY-SPEC-FINDING (SF-005 now waived); closes in milestone P3 after SPEC/platform
    readiness.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:16:48+08:00'
- key: SMU-XBAR-ATOP-REJECT.S2
  reason: OUT-OF-MILESTONE
  detail: 'P3: formerly BLOCKED-BY-SPEC-FINDING (SF-005 now waived); closes in milestone P3 after SPEC/platform
    readiness.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:16:48+08:00'
- key: SMU-XBAR-ID-CONV.S1
  reason: OUT-OF-MILESTONE
  detail: 'P3: formerly BLOCKED-BY-SPEC-FINDING (SF-002 now answered); closes in milestone P3 after platform/SPEC
    readiness.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T08:32:03+08:00'
- key: DTP-IC-RESET.S2
  reason: OUT-OF-MILESTONE
  detail: P3 corner/stress/contested-race; closes in milestone P3.
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-03T14:22:00+08:00'
- key: DTP-XTRIG-CTP.S2
  reason: OUT-OF-MILESTONE
  detail: P3 corner/stress/contested-race; closes in milestone P3.
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-03T14:22:00+08:00'
- key: INT-BOOT-STALL-INTEROP
  reason: OUT-OF-MILESTONE
  detail: P3 corner/stress/contested-race; closes in milestone P3.
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-03T14:22:00+08:00'
- key: SEP-FUSE-SENSE-HS.S3
  reason: OUT-OF-MILESTONE
  detail: P3 corner/stress/contested-race; closes in milestone P3.
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-03T14:22:00+08:00'
- key: SEP-MEM-BOUND-PASSTHROUGH.S3
  reason: OUT-OF-MILESTONE
  detail: P3 corner/stress/contested-race; closes in milestone P3.
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-03T14:22:00+08:00'
- key: SEP-SEC-DIS.S3
  reason: OUT-OF-MILESTONE
  detail: P3 corner/stress/contested-race; closes in milestone P3.
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-03T14:22:00+08:00'
- key: SMC-FAB-OUT-SMN.S2
  reason: OUT-OF-MILESTONE
  detail: P3 corner/stress/contested-race; closes in milestone P3.
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-03T14:22:00+08:00'
- key: SMC-FAB-OUT-SMN.S3
  reason: OUT-OF-MILESTONE
  detail: P3 corner/stress/contested-race; closes in milestone P3.
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-03T14:22:00+08:00'
- key: SMU-MBX-CHALLENGE.S3
  reason: OUT-OF-MILESTONE
  detail: P3 corner/stress/contested-race; closes in milestone P3.
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-03T14:22:00+08:00'
- key: SMU-SEP-SMC-ALIAS.S2
  reason: OUT-OF-MILESTONE
  detail: P3 corner/stress/contested-race; closes in milestone P3.
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-03T14:22:00+08:00'
- key: SMU-XBAR-APERTURE.S3
  reason: OUT-OF-MILESTONE
  detail: P3 corner/stress/contested-race; closes in milestone P3.
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-03T14:22:00+08:00'
- key: SMU-XBAR-BACKPRESSURE.S1
  reason: OUT-OF-MILESTONE
  detail: P3 corner/stress/contested-race; closes in milestone P3.
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-03T14:22:00+08:00'
- key: SMU-XBAR-BACKPRESSURE.S2
  reason: OUT-OF-MILESTONE
  detail: P3 corner/stress/contested-race; closes in milestone P3.
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-03T14:22:00+08:00'
- key: SMU-XBAR-BACKPRESSURE.S3
  reason: OUT-OF-MILESTONE
  detail: P3 corner/stress/contested-race; closes in milestone P3.
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-03T14:22:00+08:00'
- key: SMU-PORT-SMN-AXI.S2
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: SMU-PORT-SMN-AXI.S4
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: SMC-FAB-IN-PORTS.S3
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: SMU-XBAR-CONNECT.S1
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: SMU-XBAR-CONNECT.S2
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: SMU-XBAR-CONNECT.S3
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: SMU-XBAR-ID-CONV.S2
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: SMU-XBAR-UNMAPPED.S1
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: SMU-XBAR-UNMAPPED.S2
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: SMC-FAB-IN-PORTS.S2
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: SMC-MBX-CHANNELS.S1
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: SMU-MBX-CHALLENGE.S2
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: SEP-MBX-IRQ-SMC.S2
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: SMC-MBX-CHANNELS.S2
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: SMC-MBX-CHANNELS.S3
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: SMC-MBX-IRQ-EXT.S1
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: DTP-JTAG2AXI-SMC.S1
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: DTP-JTAG2AXI-SMC.S2
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: DTP-OTP-AXIL.S1
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: DTP-OTP-AXIL.S2
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: DTP-STAP-SMC-SEP.S1
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: DTP-STAP-SMC-SEP.S2
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: DTP-STAP-SMC-SEP.S3
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: DTP-FEAT-GATE.S1
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: DTP-FEAT-GATE.S2
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: DTP-FEAT-GATE.S3
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: INT-FEAT-CTRL-DTP-GATE
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: SEP-SYSIF-SMU-XBAR.S2
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: SEP-SYSIF-SMU-XBAR.S3
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: SEP-LC-FEAT-EXPORT.S1
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: SEP-LC-FEAT-EXPORT.S2
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: SEP-LC-FEAT-EXPORT.S3
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: SEP-SEC-DIS.S1
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: SEP-SEC-DIS.S2
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: SMC-FAB-OUT-SMN.S1
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: SMC-DTP-CSR.S1
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: SMC-DTP-CSR.S2
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: DTP-XTRIG-CTM.S1
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: DTP-XTRIG-CTP.S1
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: INT-CLKSTOP-SMC-CLA
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: SEP-MEM-BOUND-PASSTHROUGH.S1
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: SEP-MEM-BOUND-PASSTHROUGH.S2
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: SEP-FUSE-SENSE-HS.S1
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: SEP-FUSE-SENSE-HS.S2
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: SEP-WDT-RST-SMC.S1
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: SEP-WDT-RST-SMC.S2
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: INT-ALIAS-VS-XBAR-SMC
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: SMU-SEP-SMC-ALIAS.S1
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: SMU-SEP-SMC-ALIAS.S3
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: SMC-BOOT.S1
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: SMC-BOOT.S2
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: SMC-BOOT.S3
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: SEP-BOOT.S1
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: SEP-BOOT.S2
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: SMC-AXI-LITE-SHIMS.S1
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: SMC-AXI-LITE-SHIMS.S2
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: DTP-IJTAG-SCAN.S1
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: DTP-IJTAG-SCAN.S2
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: INT-FUSE-SENSE-BOOT
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: INT-XBAR-APERTURE-INTEROP
  reason: OUT-OF-MILESTONE
  detail: 'P3: platform-gated residual from SMU_ALL_008 Option-B split (Skill 1.5 STOP). Requires SEP=1
    xbar / wrapper axi_in·TMS·xtrig unbind / real LCC feat_ctrl / #3582 sep_out producer / ROM·TCM·scan
    models as applicable; not honest on current tops.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:24:29+08:00'
- key: SMC-DECODE-APERTURE.S1
  reason: OUT-OF-MILESTONE
  detail: 'P3: Option-B after Skill 1.5 STOP on SMU_ALL_008a. Bare SEP=0 SYS_IN BlockByDefault returns
    universal 0xBADCAB1E poison for LOCAL/GLOBAL — cannot prove same-component decode; JTAG2AXI gated
    (feat_ctrl tied). Needs filter-allow program and/or SEP=1 real LCC; no Force.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:36:57+08:00'
- key: SMC-DECODE-APERTURE.S3
  reason: OUT-OF-MILESTONE
  detail: 'P3: Option-B after Skill 1.5 STOP on SMU_ALL_008a. Bare SEP=0 SYS_IN BlockByDefault returns
    universal 0xBADCAB1E poison for LOCAL/GLOBAL — cannot prove same-component decode; JTAG2AXI gated
    (feat_ctrl tied). Needs filter-allow program and/or SEP=1 real LCC; no Force.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:36:57+08:00'
- key: SMC-FAB-IN-PORTS.S1
  reason: OUT-OF-MILESTONE
  detail: 'P3: Option-B after Skill 1.5 STOP honesty review. Bare SEP=0 SYS_IN BlockByDefault returns
    universal DECERR poison (0xBADCAB1E); that is not SPEC "allowed SMC resource". Needs filter allow
    / JTAG2AXI / SEP=1 LCC; no Force.'
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T17:37:56+08:00'
---
