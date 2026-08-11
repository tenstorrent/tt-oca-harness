---
schema: dv-quality/v1
artifact: spec-audit
artifact_revision: 3
content_sha256: b7f30ec75462541390b9361bbcf6c515aad232673b9a1f4f6e83b87a10445a1c
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
  path: /home/minshaoho/.claude/skills/dv_common/DV_QUALITY_POLICY.md
  revision: 51a3357d9c31a018d69451b055bc956c089af26e1051368e25ce396c84ac2a75
generated_by:
  human_id: minshaoho
  run_id: dv_vplan_gen-SMU_ALL-P2-20260802T224900+0800-step1-seal-retry
  model:
    provider: cursor
    family: grok
    version: '4.5'
derivation_provenance:
  sealed_derivation: true
  anchor_seal_mechanism: fresh-subagent
  fresh_context_route: fresh-subagent
  feature_list_frozen_at: '2026-08-02T22:55:00+08:00'
approved_by: minshaoho
approved_at: '2026-08-05T17:16:48+08:00'
findings:
- id: SF-001
  category: SF-CONFLICT
  severity: Critical
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md §Clock and Reset (DTP uses pwr_on_rst_ni = powergood_stable) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - hw/sys/smu/doc/port_table.adoc §SMU Port Declaration (rst_cold_ni 'Also serves as DTP power-on reset')
    @2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/smc/doc/clk_rst.adoc §Reset Architecture (BP_POWERGOOD → pwr_on_rst_ni) @2f40548ea787240680a1c45ab75b8729e9620778
  observed: SMU_SPEC and SMC clk_rst state DTP pwr_on_rst_ni comes from SMC powergood_stable, but the
    SMU port table states rst_cold_ni also serves as DTP power-on reset.
  question: Which signal is the normative DTP pwr_on_rst_ni source at SMU — powergood_stable, rst_cold_ni,
    or a boolean combination? Please reconcile SMU_SPEC, SMC clk_rst, and SMU port_table.
  affects:
    features:
    - SMC-PWRGOOD-DTP-POR
    - SMU-PORT-CLK-RST
    - DTP-JTAG-PTAP
    scenarios:
    - SMC-PWRGOOD-DTP-POR.S1
    - SMU-PORT-CLK-RST.S2
    anchors: []
  status: answered
  resolution:
    answered_or_waived_by: minshaoho
    answered_or_waived_at: '2026-08-05T08:31:07+08:00'
    spec_revision: 88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    note: Normative DTP pwr_on_rst_ni source is SMC powergood_stable (SMC powergood_stable_o), not rst_cold_ni
      and not a documented boolean combination. SMU_SPEC §Clock and Reset states "DTP uses pwr_on_rst_ni
      = powergood_stable (from SMC powergood_stable_o)"; SMC clk_rst.adoc §Reset Architecture agrees BP_POWERGOOD
      is stretched to powergood_stable and passed into the JTAG/DTP stack as pwr_on_rst_ni, while BP_RESETN/functional
      cold reset is a separate path that excludes JTAG/TDR reset state. The SMU port_table.adoc note that
      rst_cold_ni "Also serves as DTP power-on reset" is overruled as a stale/incorrect annotation relative
      to SMU_SPEC + SMC clk_rst (integration authority).
- id: SF-002
  category: SF-CONFLICT
  severity: Critical
  spec_refs:
  - 'hw/sys/smu/doc/SMU_SPEC.md §Specifications (Crossbar ID widths: 8-bit max input → 10-bit crossbar
    → 6-bit SMC/SEP outputs) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9'
  - hw/sys/smc/doc/fabric.adoc §AXI ID Widths by Fabric Stage (System AXI input ID 6; System AXI output
    ID 8) @ffc8cdcc349e1e01a2b970442a01070b1c62c0d7
  - hw/sys/smu/doc/port_table.adoc §SMU Port Declaration (smu_axi_in axi_56_64; smu_axi_out axi_out) @2f40548ea787240680a1c45ab75b8729e9620778
  observed: SMU_SPEC claims 8-bit max input ID into the SMU crossbar and 10-bit internal, while SMC fabric
    documents system AXI input ID width 6 and output 8. The SMU port typedef names alone do not resolve
    the inbound ID width.
  question: What are the normative AXI ID widths at SMU smu_axi_in, crossbar internal, smu_axi_out, and
    the SMC/SEP facing converters?
  affects:
    features:
    - SMU-PORT-SMN-AXI
    - SMU-XBAR-ID-CONV
    scenarios:
    - SMU-PORT-SMN-AXI.S3
    - SMU-XBAR-ID-CONV.S1
    anchors: []
  status: answered
  resolution:
    answered_or_waived_by: minshaoho
    answered_or_waived_at: '2026-08-05T08:31:07+08:00'
    spec_revision: 88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    note: 'At the SMU boundary, SMU_SPEC is normative: smu_axi_in (axi_56_64) uses 8-bit ID; the SMU crossbar
      internal ID is 10-bit; smu_axi_out (axi_out) uses 10-bit ID; IW converters narrow crossbar 10-bit
      → SMC/SEP-facing 6-bit ("8-bit max input → 10-bit crossbar → 6-bit SMC/SEP outputs"). SMC fabric.adoc
      §AXI ID Widths by Fabric Stage describes SMC-internal stages and is consistent with those SMU converter
      edges, not a competing SMU top-port width table. Port typedef names alone are insufficient; widths
      come from SMU_SPEC.'
- id: SF-003
  category: SF-CONFLICT
  severity: Critical
  spec_refs:
  - hw/sys/smc/doc/memmap.adoc §Memory Map (REGION_SIZE CSR reset 16 MiB; LOCAL_ALIAS_REGION_SIZE 16 MiB)
    @2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/smc/doc/memmap.adoc §Detailed Address Map (PLIC BASE+0x400_0000; CLINT BASE+0x800_0000) @2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/smc/doc/fabric.adoc §Local and Remote Resource Access (REGION_SIZE reset 0x0100_0000) @ffc8cdcc349e1e01a2b970442a01070b1c62c0d7
  observed: Both local-alias and chiplet-global apertures are documented as 16 MiB, yet PLIC/CLINT component
    offsets lie far outside a 16 MiB window.
  question: What aperture actually claims PLIC (BASE+0x400_0000) and CLINT/BEU (BASE+0x800_0000)? Is the
    local window larger, is REGION_SIZE expected to be reprogrammed above 128 MiB, or is another path
    used?
  affects:
    features:
    - SMC-DECODE-APERTURE
    - SMC-FAB-DUAL-NET
    scenarios:
    - SMC-DECODE-APERTURE.S2
    - SMC-FAB-DUAL-NET.S1
    anchors: []
  status: answered
  resolution:
    answered_or_waived_by: minshaoho
    answered_or_waived_at: '2026-08-05T08:31:07+08:00'
    spec_revision: ffc8cdcc349e1e01a2b970442a01070b1c62c0d7
    note: PLIC (BASE+0x400_0000) and CLINT/BEU (BASE+0x800_0000) are SMC map offsets; they are claimed
      only by an aperture large enough to include those offsets. At reset, neither chiplet-global REGION_SIZE
      (16 MiB) nor LOCAL_ALIAS_REGION_SIZE (fixed 16 MiB) covers them. fabric.adoc allows firmware to
      reprogram REGION_SIZE during early boot so the global aperture can include them. The fixed local-alias
      window is not larger. Separately, SMU_SPEC §Data Paths defines a dedicated SEP→SMC alias remap (1
      GiB at 0x4000_0000 → 0x0000_0000) that can reach those offsets for that SEP path. Exact boot-time
      REGION_SIZE value is not prescribed.
- id: SF-004
  category: SF-MISSING
  severity: Critical
  spec_refs:
  - 'hw/sys/sep/doc/fabric.adoc §SEP Interconnect (Write strobe WSTRB for partial write is not supported:
    TBD how to handle) @2f40548ea787240680a1c45ab75b8729e9620778'
  observed: Normative bridging-shim obligations leave AXI4 WSTRB partial-write handling as TBD, so partial
    writes from SEP crossbar initiators to bridged subordinates have no defined outcome.
  question: What is the required shim behavior for WSTRB not all-ones — RMW, per-byte replay, error response
    (which code), or illegal stimulus?
  affects:
    features:
    - SEP-SYSIF-SMU-XBAR
    - SMC-FAB-IN-PORTS
    scenarios:
    - SEP-SYSIF-SMU-XBAR.S1
    anchors: []
  status: waived
  resolution:
    answered_or_waived_by: minshaoho
    answered_or_waived_at: '2026-08-05T08:31:07+08:00'
    spec_revision: 2f40548ea787240680a1c45ab75b8729e9620778
    note: sep/doc/fabric.adoc §SEP Interconnect explicitly leaves WSTRB partial-write handling as "TBD
      how to handle". No pinned SPEC defines RMW, per-byte replay, error response code, or illegal-stimulus
      classification. P2 defers this checker contract until SPEC fills the TBD; do not invent a handling
      rule.
- id: SF-005
  category: SF-AMBIGUOUS
  severity: High
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md §Error Handling (AXI atomic operation | Rejected / not supported) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - hw/sys/smu/doc/SMU_SPEC.md §Specifications (ATOPs = 1'b0) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  observed: ATOP rejection is required, but the exact AXI response code / channel behavior (DECERR vs
    SLVERR vs ignored AWATOP) is not stated.
  question: What exact AXI response and channel handshake sequence constitutes 'rejected' for ATOP at
    the SMU crossbar?
  affects:
    features:
    - SMU-XBAR-ATOP-REJECT
    scenarios:
    - SMU-XBAR-ATOP-REJECT.S1
    - SMU-XBAR-ATOP-REJECT.S2
    anchors: []
  status: waived
  resolution:
    answered_or_waived_by: minshaoho
    answered_or_waived_at: '2026-08-05T17:16:48+08:00'
    spec_revision: 88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    note: 'Owner-reviewed P2 waiver: SMU_SPEC requires ATOP rejected/unsupported but does not define AXI
      response code or AW/W/B handshake sequence. Precise checker contract deferred with SPEC fill; P2
      does not invent DECERR/SLVERR/sequence.'
- id: SF-006
  category: SF-AMBIGUOUS
  severity: High
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md §Data Paths (Mailbox challenge-response) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - hw/sys/sep/doc/fabric.adoc §Mailboxes (inbox/outbox; outbox only for AP cores; otherwise inboxes on
    both ends) @2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/smu/doc/SMU_SPEC.md §Specifications (SMC mailboxes 32 / SEP mailboxes 8) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  observed: Challenge-response is described at SMU level, but the exact SMC channel ↔ SEP mailbox pairing,
    which side uses outbox vs inbox-only, and which of the 8 SEP interrupts map to which SMC channels
    are not pinned.
  question: Please specify the normative SMC↔SEP mailbox channel pairing, directionality (inbox/outbox),
    and interrupt mapping for the challenge-response protocol.
  affects:
    features:
    - SMU-MBX-CHALLENGE
    - SEP-MBX-IRQ-SMC
    - SMC-MBX-CHANNELS
    scenarios:
    - SMU-MBX-CHALLENGE.S1
    - SEP-MBX-IRQ-SMC.S1
    anchors: []
  status: waived
  resolution:
    answered_or_waived_by: minshaoho
    answered_or_waived_at: '2026-08-05T17:16:48+08:00'
    spec_revision: 88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    note: 'Owner-reviewed P2 waiver: pinned SPEC gives challenge-response shape and IRQ width constraints
      but not exact SMC↔SEP mailbox channel pairing/index map. Pairing deferred to unpinned CSR/TB docs
      or later SPEC; P2 does not invent indices.'
- id: SF-007
  category: SF-AMBIGUOUS
  severity: High
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md §CDC notes (SEP=0 SEP-OTP error slave on clk_ref_i while DTP AXI-Lite on
    clk_smu_i) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - hw/sys/smu/doc/SMU_SPEC.md §Error Handling (SEP=0 SEP-OTP | DECERR 0xBADCAB1E) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  observed: SEP=0 OTP error-slave response is specified, but CDC correctness when clk_ref != clk_smu is
    called out as a review item without a normative synchronizer/response contract.
  question: When clk_ref_i != clk_smu_i, what is the normative CDC/response contract for DTP→SEP-OTP error-slave
    accesses in SEP=0?
  affects:
    features:
    - SMU-SEP-PARAM
    - DTP-OTP-AXIL
    scenarios:
    - SMU-SEP-PARAM.S3
    - DTP-OTP-AXIL.S3
    anchors: []
  status: waived
  resolution:
    answered_or_waived_by: minshaoho
    answered_or_waived_at: '2026-08-05T17:16:48+08:00'
    spec_revision: 88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    note: 'Owner-reviewed P2 waiver: SEP=0 OTP error-slave DECERR/0xBADCAB1E is stated when access completes;
      CDC contract when clk_ref_i != clk_smu_i remains a review note only. CDC handshake deferred until
      SPEC norms it.'
- id: SF-008
  category: SF-TERM
  severity: Medium
  spec_refs:
  - hw/sys/smc/doc/port_table.adoc §SMC Port Declaration (feat_ctrl_i type sep_lcc_pkg::feat_ctrl_t) @2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/dtp/doc/port_table.adoc §DTP Port Declaration (feat_ctrl_i type sep_efuse_pkg::sep_efuse_map_lc_disable_reg_t)
    @2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/smu/doc/SMU_SPEC.md §Security Considerations (sep_feat_ctrl type sep_efuse_map_lc_disable_reg_t)
    @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - hw/sys/sep/doc/port_table.adoc §SEP Port Declaration (feat_ctrl_o type sep_efuse_map_lc_disable_reg_t)
    @2f40548ea787240680a1c45ab75b8729e9620778
  observed: Feature-control vector type/name differs across SMC (sep_lcc_pkg::feat_ctrl_t), DTP/SEP/SMU
    (sep_efuse_map_lc_disable_reg_t), risking width/field mismatch at SMU integration.
  question: What is the single normative type/width/field map for feat_ctrl between SEP, SMC, DTP, and
    SMU?
  affects:
    features:
    - SEP-LC-FEAT-EXPORT
    - DTP-FEAT-GATE
    scenarios:
    - SEP-LC-FEAT-EXPORT.S2
    - DTP-FEAT-GATE.S1
    anchors:
    - smu_clock_stop_coordination_test
    - smu_sep_smoke_test
  status: answered
  resolution:
    answered_or_waived_by: minshaoho
    answered_or_waived_at: '2026-08-05T08:31:07+08:00'
    spec_revision: 2f40548ea787240680a1c45ab75b8729e9620778
    note: 'Normative producer/type for the integration wire is SEP feat_ctrl_o as sep_efuse_pkg::sep_efuse_map_lc_disable_reg_t
      (SEP port_table; SMU_SPEC §Security Considerations / Interfaces; DTP port_table feat_ctrl_i). Field
      semantics come from sep/lifecycle_controller.adoc: feat_ctrl_o is derived from 64-bit SIP_DIS/SYS_DIS
      disable vectors with the documented bit map (positive logic enable). SMC port_table''s sep_lcc_pkg::feat_ctrl_t
      is a conflicting type name with no pinned equivalence statement; treat SEP/SMU/DTP sep_efuse_map_lc_disable_reg_t
      + lifecycle bit map as the normative payload, and treat SMC''s type name as a documentation inconsistency
      to reconcile.'
- id: SF-009
  category: SF-MISSING
  severity: High
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md §Feature 4 (programmable global-base remap) / §CDC notes (addr_map from
    CSR base/size) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - hw/sys/smc/doc/fabric.adoc §Local and Remote Resource Access (GLOBAL_BASE and REGION_SIZE) @ffc8cdcc349e1e01a2b970442a01070b1c62c0d7
  - hw/sys/sep/doc/fabric.adoc §Transaction Routing (SEP_GLOBAL_BASE_ADDR and SEP_REGION_SIZE) @2f40548ea787240680a1c45ab75b8729e9620778
  observed: Aperture programming is required for SMU xbar decode, but SMU_SPEC does not cite the authoritative
    CSR addresses/fields for the smu_axi_xbar aperture map (only refers to missing SMU_CSR.md).
  question: Where are the normative CSR addresses/fields and programming sequence for SMU crossbar SEP/SMC
    apertures defined in the pinned SPEC set?
  affects:
    features:
    - SMU-XBAR-APERTURE
    scenarios:
    - SMU-XBAR-APERTURE.S1
    - SMU-XBAR-APERTURE.S2
    anchors: []
  status: waived
  resolution:
    answered_or_waived_by: minshaoho
    answered_or_waived_at: '2026-08-05T17:16:48+08:00'
    spec_revision: 88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    note: 'Owner-reviewed P2 waiver: SMU_SPEC requires CSR-programmed apertures but defers register/address
      detail to SMU_CSR.md (not pinned). Normative SMU xbar aperture CSR map deferred until pin includes
      that source or SPEC adds addresses.'
- id: SF-010
  category: SF-TYPO
  severity: Low
  spec_refs:
  - hw/sys/sep/doc/fabric.adoc §Transaction Routing ('extend its protection to the reset of the system')
    @2f40548ea787240680a1c45ab75b8729e9620778
  observed: Prose appears to typo 'reset of the system' where 'rest of the system' is intended.
  question: Please confirm whether this is a typo for 'rest of the system' and correct the normative text.
  affects:
    features:
    - SEP-SYSIF-SMU-XBAR
    scenarios:
    - SEP-SYSIF-SMU-XBAR.S2
    anchors:
    - smu_sep_smoke_test
  status: answered
  resolution:
    answered_or_waived_by: minshaoho
    answered_or_waived_at: '2026-08-05T08:31:07+08:00'
    spec_revision: 2f40548ea787240680a1c45ab75b8729e9620778
    note: 'Confirmed typo: sep/fabric.adoc §Transaction Routing bullet "extend its protection to the reset
      of the system" is non-normative prose error for "rest of the system". The same document restates
      the identical intent later as "extending its protection to the rest of the system". Normative meaning
      is "rest"; no reset-domain obligation is created by the typo alone.'
- id: SF-011
  category: SF-AMBIGUOUS
  severity: Medium
  spec_refs:
  - hw/sys/sep/doc/test_mode.adoc §Test Mode Entry ('While Table tbd defines the static enablement') @2f40548ea787240680a1c45ab75b8729e9620778
  observed: Test-mode static enablement table is literally 'Table tbd', so SECURE_TM qualification against
    the static matrix cannot be pinned.
  question: What is the normative test-feature static enablement table that SECURE_TM qualifies?
  affects:
    features:
    - SEP-FUSE-SENSE-HS
    - SEP-SEC-DIS
    scenarios:
    - SEP-FUSE-SENSE-HS.S3
    anchors: []
  status: waived
  resolution:
    answered_or_waived_by: minshaoho
    answered_or_waived_at: '2026-08-05T08:31:07+08:00'
    spec_revision: 2f40548ea787240680a1c45ab75b8729e9620778
    note: sep/test_mode.adoc §Test Mode Entry literally cites "Table tbd" for static test-feature enablement;
      SECURE_TM is only defined as a dynamic qualifier on top of that missing table. No pinned SPEC supplies
      the static enablement matrix. P2 defers SECURE_TM×static-matrix qualification until SPEC fills Table
      tbd; do not invent the table.
- id: SF-012
  category: SF-MISSING
  severity: Medium
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md §Interfaces (SEP mailbox interrupts internal; Observe via wrapper (note
    ISSUE-7)) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - hw/sys/sep/doc/port_table.adoc §SEP Port Declaration (smc_mailbox_interrupt_o) @2f40548ea787240680a1c45ab75b8729e9620778
  - hw/sys/smc/doc/port_table.adoc §SMC Port Declaration (sep_mailbox_interrupts_i) @2f40548ea787240680a1c45ab75b8729e9620778
  observed: SMU_SPEC marks SEP mailbox interrupts as internal with an ISSUE-7 observation note, while
    SEP/SMC port tables show an explicit 8-bit port. Observability at SMU core vs wrapper is unclear.
  question: At the SMU verification boundary, are SEP mailbox interrupts architecturally observable on
    a named port, only inside the wrapper, or only via SMC cpu_interrupts_o?
  affects:
    features:
    - SEP-MBX-IRQ-SMC
    - SMU-MBX-CHALLENGE
    scenarios:
    - SEP-MBX-IRQ-SMC.S1
    anchors: []
  status: answered
  resolution:
    answered_or_waived_by: minshaoho
    answered_or_waived_at: '2026-08-05T08:31:07+08:00'
    spec_revision: 88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    note: 'At the SMU core verification boundary, SEP mailbox interrupts are internal (not a named SMU
      top port): SMU_SPEC §Interfaces lists them as "internal [7:0]" with policy "Observe via wrapper
      (note ISSUE-7)". SEP smc_mailbox_interrupt_o and SMC sep_mailbox_interrupts_i are subsystem ports
      wired inside SMU; SMC then folds them into peripheral_interrupts → cpu_interrupts_o. Observability
      is via wrapper hierarchy and/or SMC cpu_interrupts_o aggregation—not a dedicated SMU-core named
      port.'
---

# SMU_ALL Spec Audit Report (candidate)

Questions awaiting spec-owner answer. Sorted by severity. `affects.anchors` is empty by sealed-derivation construction.

## Findings

SF-ID:     SF-001
CATEGORY:  SF-CONFLICT
SEVERITY:  Critical
SPEC-REF:  hw/sys/smu/doc/SMU_SPEC.md §Clock and Reset (DTP uses pwr_on_rst_ni = powergood_stable) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9 | hw/sys/smu/doc/port_table.adoc §SMU Port Declaration (rst_cold_ni 'Also serves as DTP power-on reset') @2f40548ea787240680a1c45ab75b8729e9620778 | hw/sys/smc/doc/clk_rst.adoc §Reset Architecture (BP_POWERGOOD → pwr_on_rst_ni) @2f40548ea787240680a1c45ab75b8729e9620778
OBSERVED:  SMU_SPEC and SMC clk_rst state DTP pwr_on_rst_ni comes from SMC powergood_stable, but the SMU port table states rst_cold_ni also serves as DTP power-on reset.
QUESTION:  Which signal is the normative DTP pwr_on_rst_ni source at SMU — powergood_stable, rst_cold_ni, or a boolean combination? Please reconcile SMU_SPEC, SMC clk_rst, and SMU port_table.
AFFECTS:   features=SMC-PWRGOOD-DTP-POR,SMU-PORT-CLK-RST,DTP-JTAG-PTAP; scenarios=SMC-PWRGOOD-DTP-POR.S1,SMU-PORT-CLK-RST.S2; anchors=[]
STATUS:    open

SF-ID:     SF-002
CATEGORY:  SF-CONFLICT
SEVERITY:  Critical
SPEC-REF:  hw/sys/smu/doc/SMU_SPEC.md §Specifications (Crossbar ID widths: 8-bit max input → 10-bit crossbar → 6-bit SMC/SEP outputs) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9 | hw/sys/smc/doc/fabric.adoc §AXI ID Widths by Fabric Stage (System AXI input ID 6; System AXI output ID 8) @ffc8cdcc349e1e01a2b970442a01070b1c62c0d7 | hw/sys/smu/doc/port_table.adoc §SMU Port Declaration (smu_axi_in axi_56_64; smu_axi_out axi_out) @2f40548ea787240680a1c45ab75b8729e9620778
OBSERVED:  SMU_SPEC claims 8-bit max input ID into the SMU crossbar and 10-bit internal, while SMC fabric documents system AXI input ID width 6 and output 8. The SMU port typedef names alone do not resolve the inbound ID width.
QUESTION:  What are the normative AXI ID widths at SMU smu_axi_in, crossbar internal, smu_axi_out, and the SMC/SEP facing converters?
AFFECTS:   features=SMU-PORT-SMN-AXI,SMU-XBAR-ID-CONV; scenarios=SMU-PORT-SMN-AXI.S3,SMU-XBAR-ID-CONV.S1; anchors=[]
STATUS:    open

SF-ID:     SF-003
CATEGORY:  SF-CONFLICT
SEVERITY:  Critical
SPEC-REF:  hw/sys/smc/doc/memmap.adoc §Memory Map (REGION_SIZE CSR reset 16 MiB; LOCAL_ALIAS_REGION_SIZE 16 MiB) @2f40548ea787240680a1c45ab75b8729e9620778 | hw/sys/smc/doc/memmap.adoc §Detailed Address Map (PLIC BASE+0x400_0000; CLINT BASE+0x800_0000) @2f40548ea787240680a1c45ab75b8729e9620778 | hw/sys/smc/doc/fabric.adoc §Local and Remote Resource Access (REGION_SIZE reset 0x0100_0000) @ffc8cdcc349e1e01a2b970442a01070b1c62c0d7
OBSERVED:  Both local-alias and chiplet-global apertures are documented as 16 MiB, yet PLIC/CLINT component offsets lie far outside a 16 MiB window.
QUESTION:  What aperture actually claims PLIC (BASE+0x400_0000) and CLINT/BEU (BASE+0x800_0000)? Is the local window larger, is REGION_SIZE expected to be reprogrammed above 128 MiB, or is another path used?
AFFECTS:   features=SMC-DECODE-APERTURE,SMC-FAB-DUAL-NET; scenarios=SMC-DECODE-APERTURE.S2,SMC-FAB-DUAL-NET.S1; anchors=[]
STATUS:    open

SF-ID:     SF-004
CATEGORY:  SF-MISSING
SEVERITY:  Critical
SPEC-REF:  hw/sys/sep/doc/fabric.adoc §SEP Interconnect (Write strobe WSTRB for partial write is not supported: TBD how to handle) @2f40548ea787240680a1c45ab75b8729e9620778
OBSERVED:  Normative bridging-shim obligations leave AXI4 WSTRB partial-write handling as TBD, so partial writes from SEP crossbar initiators to bridged subordinates have no defined outcome.
QUESTION:  What is the required shim behavior for WSTRB not all-ones — RMW, per-byte replay, error response (which code), or illegal stimulus?
AFFECTS:   features=SEP-SYSIF-SMU-XBAR,SMC-FAB-IN-PORTS; scenarios=SEP-SYSIF-SMU-XBAR.S1; anchors=[]
STATUS:    open

SF-ID:     SF-005
CATEGORY:  SF-AMBIGUOUS
SEVERITY:  High
SPEC-REF:  hw/sys/smu/doc/SMU_SPEC.md §Error Handling (AXI atomic operation | Rejected / not supported) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9 | hw/sys/smu/doc/SMU_SPEC.md §Specifications (ATOPs = 1'b0) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
OBSERVED:  ATOP rejection is required, but the exact AXI response code / channel behavior (DECERR vs SLVERR vs ignored AWATOP) is not stated.
QUESTION:  What exact AXI response and channel handshake sequence constitutes 'rejected' for ATOP at the SMU crossbar?
AFFECTS:   features=SMU-XBAR-ATOP-REJECT; scenarios=SMU-XBAR-ATOP-REJECT.S1,SMU-XBAR-ATOP-REJECT.S2; anchors=[]
STATUS:    open

SF-ID:     SF-006
CATEGORY:  SF-AMBIGUOUS
SEVERITY:  High
SPEC-REF:  hw/sys/smu/doc/SMU_SPEC.md §Data Paths (Mailbox challenge-response) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9 | hw/sys/sep/doc/fabric.adoc §Mailboxes (inbox/outbox; outbox only for AP cores; otherwise inboxes on both ends) @2f40548ea787240680a1c45ab75b8729e9620778 | hw/sys/smu/doc/SMU_SPEC.md §Specifications (SMC mailboxes 32 / SEP mailboxes 8) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
OBSERVED:  Challenge-response is described at SMU level, but the exact SMC channel ↔ SEP mailbox pairing, which side uses outbox vs inbox-only, and which of the 8 SEP interrupts map to which SMC channels are not pinned.
QUESTION:  Please specify the normative SMC↔SEP mailbox channel pairing, directionality (inbox/outbox), and interrupt mapping for the challenge-response protocol.
AFFECTS:   features=SMU-MBX-CHALLENGE,SEP-MBX-IRQ-SMC,SMC-MBX-CHANNELS; scenarios=SMU-MBX-CHALLENGE.S1,SEP-MBX-IRQ-SMC.S1; anchors=[]
STATUS:    open

SF-ID:     SF-007
CATEGORY:  SF-AMBIGUOUS
SEVERITY:  High
SPEC-REF:  hw/sys/smu/doc/SMU_SPEC.md §CDC notes (SEP=0 SEP-OTP error slave on clk_ref_i while DTP AXI-Lite on clk_smu_i) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9 | hw/sys/smu/doc/SMU_SPEC.md §Error Handling (SEP=0 SEP-OTP | DECERR 0xBADCAB1E) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
OBSERVED:  SEP=0 OTP error-slave response is specified, but CDC correctness when clk_ref != clk_smu is called out as a review item without a normative synchronizer/response contract.
QUESTION:  When clk_ref_i != clk_smu_i, what is the normative CDC/response contract for DTP→SEP-OTP error-slave accesses in SEP=0?
AFFECTS:   features=SMU-SEP-PARAM,DTP-OTP-AXIL; scenarios=SMU-SEP-PARAM.S3,DTP-OTP-AXIL.S3; anchors=[]
STATUS:    open

SF-ID:     SF-009
CATEGORY:  SF-MISSING
SEVERITY:  High
SPEC-REF:  hw/sys/smu/doc/SMU_SPEC.md §Feature 4 (programmable global-base remap) / §CDC notes (addr_map from CSR base/size) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9 | hw/sys/smc/doc/fabric.adoc §Local and Remote Resource Access (GLOBAL_BASE and REGION_SIZE) @ffc8cdcc349e1e01a2b970442a01070b1c62c0d7 | hw/sys/sep/doc/fabric.adoc §Transaction Routing (SEP_GLOBAL_BASE_ADDR and SEP_REGION_SIZE) @2f40548ea787240680a1c45ab75b8729e9620778
OBSERVED:  Aperture programming is required for SMU xbar decode, but SMU_SPEC does not cite the authoritative CSR addresses/fields for the smu_axi_xbar aperture map (only refers to missing SMU_CSR.md).
QUESTION:  Where are the normative CSR addresses/fields and programming sequence for SMU crossbar SEP/SMC apertures defined in the pinned SPEC set?
AFFECTS:   features=SMU-XBAR-APERTURE; scenarios=SMU-XBAR-APERTURE.S1,SMU-XBAR-APERTURE.S2; anchors=[]
STATUS:    open

SF-ID:     SF-008
CATEGORY:  SF-TERM
SEVERITY:  Medium
SPEC-REF:  hw/sys/smc/doc/port_table.adoc §SMC Port Declaration (feat_ctrl_i type sep_lcc_pkg::feat_ctrl_t) @2f40548ea787240680a1c45ab75b8729e9620778 | hw/sys/dtp/doc/port_table.adoc §DTP Port Declaration (feat_ctrl_i type sep_efuse_pkg::sep_efuse_map_lc_disable_reg_t) @2f40548ea787240680a1c45ab75b8729e9620778 | hw/sys/smu/doc/SMU_SPEC.md §Security Considerations (sep_feat_ctrl type sep_efuse_map_lc_disable_reg_t) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9 | hw/sys/sep/doc/port_table.adoc §SEP Port Declaration (feat_ctrl_o type sep_efuse_map_lc_disable_reg_t) @2f40548ea787240680a1c45ab75b8729e9620778
OBSERVED:  Feature-control vector type/name differs across SMC (sep_lcc_pkg::feat_ctrl_t), DTP/SEP/SMU (sep_efuse_map_lc_disable_reg_t), risking width/field mismatch at SMU integration.
QUESTION:  What is the single normative type/width/field map for feat_ctrl between SEP, SMC, DTP, and SMU?
AFFECTS:   features=SEP-LC-FEAT-EXPORT,DTP-FEAT-GATE; scenarios=SEP-LC-FEAT-EXPORT.S2,DTP-FEAT-GATE.S1; anchors=[]
STATUS:    open

SF-ID:     SF-011
CATEGORY:  SF-AMBIGUOUS
SEVERITY:  Medium
SPEC-REF:  hw/sys/sep/doc/test_mode.adoc §Test Mode Entry ('While Table tbd defines the static enablement') @2f40548ea787240680a1c45ab75b8729e9620778
OBSERVED:  Test-mode static enablement table is literally 'Table tbd', so SECURE_TM qualification against the static matrix cannot be pinned.
QUESTION:  What is the normative test-feature static enablement table that SECURE_TM qualifies?
AFFECTS:   features=SEP-FUSE-SENSE-HS,SEP-SEC-DIS; scenarios=SEP-FUSE-SENSE-HS.S3; anchors=[]
STATUS:    open

SF-ID:     SF-012
CATEGORY:  SF-MISSING
SEVERITY:  Medium
SPEC-REF:  hw/sys/smu/doc/SMU_SPEC.md §Interfaces (SEP mailbox interrupts internal; Observe via wrapper (note ISSUE-7)) @88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9 | hw/sys/sep/doc/port_table.adoc §SEP Port Declaration (smc_mailbox_interrupt_o) @2f40548ea787240680a1c45ab75b8729e9620778 | hw/sys/smc/doc/port_table.adoc §SMC Port Declaration (sep_mailbox_interrupts_i) @2f40548ea787240680a1c45ab75b8729e9620778
OBSERVED:  SMU_SPEC marks SEP mailbox interrupts as internal with an ISSUE-7 observation note, while SEP/SMC port tables show an explicit 8-bit port. Observability at SMU core vs wrapper is unclear.
QUESTION:  At the SMU verification boundary, are SEP mailbox interrupts architecturally observable on a named port, only inside the wrapper, or only via SMC cpu_interrupts_o?
AFFECTS:   features=SEP-MBX-IRQ-SMC,SMU-MBX-CHALLENGE; scenarios=SEP-MBX-IRQ-SMC.S1; anchors=[]
STATUS:    open

SF-ID:     SF-010
CATEGORY:  SF-TYPO
SEVERITY:  Low
SPEC-REF:  hw/sys/sep/doc/fabric.adoc §Transaction Routing ('extend its protection to the reset of the system') @2f40548ea787240680a1c45ab75b8729e9620778
OBSERVED:  Prose appears to typo 'reset of the system' where 'rest of the system' is intended.
QUESTION:  Please confirm whether this is a typo for 'rest of the system' and correct the normative text.
AFFECTS:   features=SEP-SYSIF-SMU-XBAR; scenarios=SEP-SYSIF-SMU-XBAR.S2; anchors=[]
STATUS:    open

## Underspecified areas (rollup)

- DTP POR source conflict (powergood_stable vs rst_cold_ni)
- SMU vs SMC AXI ID-width tables
- 16 MiB aperture vs PLIC/CLINT map offsets
- SEP fabric WSTRB TBD
- ATOP rejection response code
- SMC↔SEP mailbox pairing/interrupt map
- SEP=0 OTP CDC contract
- feat_ctrl type name mismatch across blocks
- SMU xbar aperture CSR authoritative map missing from pinned set
- Test-mode 'Table tbd'
- SEP mailbox interrupt observability (ISSUE-7 note)
