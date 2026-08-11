---
schema: dv-quality/v1
artifact: feature-list
artifact_revision: 1
content_sha256: fd4100e0607d4a4d11e2091041eadb06a16199ffbcf3e0cc0e839fe416fc584b
ip: SMU_ALL
milestone: P2
status: candidate
pin_revision: 1
spec:
- path: hw/sys/smu/doc/SMU_SPEC.md
  revision: 88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
- path: hw/sys/smu/doc/port_table.adoc
  revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
- path: hw/sys/smc/doc/index.adoc
  revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
- path: hw/sys/smc/doc/overview.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/smc/doc/fabric.adoc
  revision: ffc8cdcc349e1e01a2b970442a01070b1c62c0d7
- path: hw/sys/smc/doc/port_table.adoc
  revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
- path: hw/sys/smc/doc/cpu.adoc
  revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
- path: hw/sys/smc/doc/clk_rst.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/smc/doc/interrupts.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/smc/doc/memmap.adoc
  revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
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
  revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
- path: hw/sys/sep/doc/fabric.adoc
  revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
- path: hw/sys/sep/doc/cpu.adoc
  revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
- path: hw/sys/sep/doc/crypto.adoc
  revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
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
- path: hw/sys/dtp/doc/index.adoc
  revision: ffc8cdcc349e1e01a2b970442a01070b1c62c0d7
- path: hw/sys/dtp/doc/overview.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/dtp/doc/jtag.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/dtp/doc/clock_stop.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/dtp/doc/port_table.adoc
  revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
source_revision: 88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
quality_policy:
  path: /home/minshaoho/.claude/skills/dv_common/DV_QUALITY_POLICY.md
  revision: 51a3357d9c31a018d69451b055bc956c089af26e1051368e25ce396c84ac2a75
generated_by:
  human_id: minshaoho
  run_id: revinv-25b762f8bc46
  model:
    provider: cursor
    family: grok
    version: '4.5'
derivation_provenance:
  sealed_derivation: true
  anchor_seal_mechanism: fresh-subagent
  fresh_context_route: fresh-subagent
  feature_list_frozen_at: '2026-08-05T07:30:00+08:00'
  reverse_inventory_candidate: true
  notes: REVERSE-INVENTORY ONLY candidate. Not a replacement for any approved SMU_ALL feature_list. Derived
    forward-from-SPEC with anchors sealed; no testlist/RTL/approved-plan judgment read.
approved_by: null
approved_at: null
features:
- key: SMU-COMPOSITION
  title: SMU integrated block composition
  intent: SMU composes SMC, SEP when enabled, DTP, and the AXI crossbar as one subsystem
  triad:
    producer: SMU top instantiation parameters and block presence
    transport: SMU composition wiring among u_smc/u_sep/u_dtp/u_smu_axi_xbar
    consumer: observable SMU-boundary ports and sub-block interoperability paths
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Overview
  - hw/sys/smu/doc/SMU_SPEC.md Architecture/Sub-Blocks
  record_sha256: 04cb0839cf756e1e0184b1071f3199d7a43fed522a5dc5e0d3d013c2360835ba
  scenarios:
  - key: SMU-COMPOSITION.S1
    intent: SEP=1 exposes SMC+SEP+DTP+xbar composition paths
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Architecture/Sub-Blocks
    - hw/sys/smu/doc/SMU_SPEC.md Specifications
    coverage:
      method: DIRECTED
      required_cells:
      - sep1-composition-present
      random_knobs: []
      coverage_artifact: null
  - key: SMU-COMPOSITION.S2
    intent: SEP=0 removes SEP/xbar and substitutes error-slave and direct SMC-external converters
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Architecture/Block Overview
    - hw/sys/smu/doc/SMU_SPEC.md Configuration Parameters
    coverage:
      method: DIRECTED
      required_cells:
      - sep0-composition-tieoff
      random_knobs: []
      coverage_artifact: null
- key: SMU-TOP-CLK-RST
  title: SMU top clock and reset domains
  intent: SMU clocks and cold/primary resets propagate to composed blocks and SMU reset outputs
  triad:
    producer: clk_smu_i/clk_ref_i/clk_periph_i/clk_telemetry_i/clk_sep_wdt_i and rst_cold_ni/powergood_i
    transport: SMU clock/reset distribution into SMC/SEP/DTP and SMU reset outputs
    consumer: SMC/SEP/DTP domains and rst_primary_*/rst_cold_stable_ref_clk_no consumers
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Clock and Reset
  - hw/sys/smu/doc/port_table.adoc clk/rst rows
  - hw/sys/smc/doc/clk_rst.adoc Clock and Reset Management
  record_sha256: e32288f2555dc5f1205f23feec3aa923217ba2cec24d8c1e668f407f80da1f42
  scenarios:
  - key: SMU-TOP-CLK-RST.S1
    intent: Cold reset and powergood establish DTP pwr_on_rst and SMC powergood_stable path
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Clock and Reset
    - hw/sys/smc/doc/clk_rst.adoc Reset Architecture
    - hw/sys/dtp/doc/jtag.adoc Reset Architecture
    coverage:
      method: DIRECTED
      required_cells:
      - cold-reset-powergood
      random_knobs: []
      coverage_artifact: null
  - key: SMU-TOP-CLK-RST.S2
    intent: Primary SMU clock domain hosts SMC/SEP/DTP/xbar activity after reset release
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Clock and Reset
    coverage:
      method: DIRECTED
      required_cells:
      - clk-smu-shared-domain
      random_knobs: []
      coverage_artifact: null
  - key: SMU-TOP-CLK-RST.S3
    intent: '[BOUNDED-LIVENESS] reset asserted mid-transaction completes-or-errors without hang at SMU
      AXI ports'
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Clock and Reset
    - hw/sys/smu/doc/SMU_SPEC.md Error Handling
    coverage:
      method: DIRECTED
      required_cells:
      - reset-mid-xact-bounded
      random_knobs: []
      coverage_artifact: null
- key: SMU-AXI-XBAR-CONNECTIVITY
  title: SMU 3x3 AXI crossbar connectivity matrix
  intent: CSR-routed AXI4 crossbar connects sep_out/smc_out/ext_in to sep_in/smc_in/ext_out without self-loop
  triad:
    producer: SEP, SMC, or external SMN AXI initiator
    transport: smu_axi_xbar 3x3 fully-connected AXI4 fabric
    consumer: SEP, SMC, or external SMN AXI target excluding own inbound port
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Data Paths/Crossbar routing
  - hw/sys/smu/doc/SMU_SPEC.md Feature 4
  record_sha256: 10dc226a202e80bb7c79f81d1922803c9aa92b9b6458e83c081c610f08f9414f
  scenarios:
  - key: SMU-AXI-XBAR-CONNECTIVITY.S1
    intent: sep_out reaches smc_in and ext_out only
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Data Paths/Crossbar routing
    coverage:
      method: DIRECTED
      required_cells:
      - sep-out-to-smc
      - sep-out-to-ext
      random_knobs: []
      coverage_artifact: null
  - key: SMU-AXI-XBAR-CONNECTIVITY.S2
    intent: smc_out reaches sep_in and ext_out only
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Data Paths/Crossbar routing
    coverage:
      method: DIRECTED
      required_cells:
      - smc-out-to-sep
      - smc-out-to-ext
      random_knobs: []
      coverage_artifact: null
  - key: SMU-AXI-XBAR-CONNECTIVITY.S3
    intent: ext_in reaches sep_in and smc_in only
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Data Paths/Crossbar routing
    coverage:
      method: DIRECTED
      required_cells:
      - ext-in-to-sep
      - ext-in-to-smc
      random_knobs: []
      coverage_artifact: null
  - key: SMU-AXI-XBAR-CONNECTIVITY.S4
    intent: '[BOUNDED-LIVENESS] concurrent multi-initiator traffic completes-or-errors under backpressure'
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Feature 4
    coverage:
      method: RANDOMIZED
      required_cells:
      - concurrent-backpressure
      random_knobs:
      - initiator-mix
      - outstanding-depth
      coverage_artifact: null
- key: SMU-AXI-APERTURE
  title: Programmable SEP/SMC apertures on SMU crossbar
  intent: CSR-programmed SEP/SMC apertures and global-base remap steer SMU-level address decode
  triad:
    producer: aperture/global-base CSR programmers
    transport: smu_axi_xbar address map from CSR base/size
    consumer: routed AXI targets selected by programmed apertures
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Feature 4
  - hw/sys/smu/doc/SMU_SPEC.md Specifications
  - hw/sys/smc/doc/fabric.adoc GLOBAL_BASE/REGION_SIZE
  - hw/sys/sep/doc/fabric.adoc SEP_GLOBAL_BASE_ADDR/SEP_REGION_SIZE
  record_sha256: 1f7b7e72a88a99f9b8466cea7b4a7c0df9c6efaa1b375a7b4d9049e95d901e36
  scenarios:
  - key: SMU-AXI-APERTURE.S1
    intent: Default/reset aperture sizes 16 MiB steer decode before reprogram
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/fabric.adoc GLOBAL_BASE/REGION_SIZE
    - hw/sys/sep/doc/fabric.adoc SEP_REGION_SIZE
    coverage:
      method: DIRECTED
      required_cells:
      - reset-aperture-16mib
      random_knobs: []
      coverage_artifact: null
  - key: SMU-AXI-APERTURE.S2
    intent: Reprogrammed SMC/SEP apertures change SMU-level hit/miss routing
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Feature 4
    - hw/sys/smc/doc/fabric.adoc GLOBAL_BASE/REGION_SIZE
    coverage:
      method: DIRECTED
      required_cells:
      - reprogram-aperture-hit
      - reprogram-aperture-miss
      random_knobs: []
      coverage_artifact: null
  - key: SMU-AXI-APERTURE.S3
    intent: '[BOUNDED-LIVENESS] aperture CSR change versus in-flight transactions yields complete-or-error'
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Clock and Reset/CDC notes
    coverage:
      method: DIRECTED
      required_cells:
      - aperture-change-inflight
      random_knobs: []
      coverage_artifact: null
- key: SMU-AXI-EXT-SMN
  title: External SMN AXI ports at SMU boundary
  intent: External SMN-facing AXI inbound and outbound ports exchange traffic with the SMU crossbar
  triad:
    producer: external SMN master/slave peers on smu_axi_in/out
    transport: SMU top AXI SMN ports into/from smu_axi_xbar
    consumer: SMC/SEP fabrics inbound or SMN target outbound
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Interfaces
  - hw/sys/smu/doc/port_table.adoc smu_axi_in/out
  record_sha256: e7f363eb935267352e022d51a9d06c7d12c016131ee8715001dd877b54b90941
  scenarios:
  - key: SMU-AXI-EXT-SMN.S1
    intent: External inbound AXI reaches SMC and/or SEP through programmed decode
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Interfaces
    - hw/sys/smu/doc/SMU_SPEC.md Data Paths/Crossbar routing
    coverage:
      method: DIRECTED
      required_cells:
      - ext-in-live-access
      random_knobs: []
      coverage_artifact: null
  - key: SMU-AXI-EXT-SMN.S2
    intent: SMC or SEP outbound reaches external SMN outbound port
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Interfaces
    - hw/sys/smu/doc/SMU_SPEC.md Data Paths/Crossbar routing
    coverage:
      method: DIRECTED
      required_cells:
      - ext-out-live-access
      random_knobs: []
      coverage_artifact: null
- key: SMU-AXI-DECODE-ERR
  title: SMU crossbar decode and default-port error responses
  intent: Unmatched ext_in accesses decode-error; unmatched sep_out/smc_out fall through to ext_out default
  triad:
    producer: AXI initiator presenting unmatched address
    transport: smu_axi_xbar address decode / default-master selection
    consumer: DECERR to ext_in initiator or ext_out catch-all for sep/smc
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Data Paths/Crossbar routing
  - hw/sys/smu/doc/SMU_SPEC.md Error Handling
  record_sha256: 9035f8fb62a9131c30bb7be5a89be93bd98ad89619e3a403b7afb1972b476694
  scenarios:
  - key: SMU-AXI-DECODE-ERR.S1
    intent: Unmatched ext_in access returns DECERR
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Error Handling
    - hw/sys/smu/doc/SMU_SPEC.md Data Paths/Crossbar routing
    coverage:
      method: DIRECTED
      required_cells:
      - ext-in-decerr
      random_knobs: []
      coverage_artifact: null
  - key: SMU-AXI-DECODE-ERR.S2
    intent: Unmatched sep_out/smc_out routed to ext_out default master
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Data Paths/Crossbar routing
    coverage:
      method: DIRECTED
      required_cells:
      - default-ext-out
      random_knobs: []
      coverage_artifact: null
- key: SMU-AXI-ATOP
  title: AXI atomic operation rejection on SMU crossbar
  intent: SMU crossbar configures ATOPs=0 so AXI atomic operations are unsupported/rejected
  triad:
    producer: AXI initiator issuing ATOP transaction
    transport: smu_axi_xbar with ATOPs disabled
    consumer: rejection / non-support response at initiator
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Specifications
  - hw/sys/smu/doc/SMU_SPEC.md Error Handling
  record_sha256: ef079d4dd9c4b88496e677d6868689087d9dcdaf21353227fa836c58192b0399
  scenarios:
  - key: SMU-AXI-ATOP.S1
    intent: Atomic AXI operation is rejected / not supported
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Error Handling
    coverage:
      method: DIRECTED
      required_cells:
      - atop-rejected
      random_knobs: []
      coverage_artifact: null
- key: SMU-AXI-ID-WIDTH
  title: SMU crossbar AXI ID-width conversion
  intent: Crossbar ID path 8-bit max input to 10-bit crossbar to 6-bit SMC/SEP outputs is converted
  triad:
    producer: AXI transactions with source IDs entering the crossbar
    transport: u_iw_conv_sep/u_iw_conv_smc and SEP=0 direct converters
    consumer: SMC/SEP or external AXI ID field width at boundary
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Specifications
  - hw/sys/smu/doc/SMU_SPEC.md Architecture/Sub-Blocks
  record_sha256: f2111cf7f7cb5db59d13e90d89050a85f93db0dafc571a4ce70c39246584ec15
  scenarios:
  - key: SMU-AXI-ID-WIDTH.S1
    intent: SEP=1 converts crossbar 10-bit IDs to 6-bit SMC/SEP ports
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Specifications
    - hw/sys/smu/doc/SMU_SPEC.md Architecture/Sub-Blocks
    coverage:
      method: DIRECTED
      required_cells:
      - id-10-to-6-sep1
      random_knobs: []
      coverage_artifact: null
  - key: SMU-AXI-ID-WIDTH.S2
    intent: SEP=0 uses direct SMC-external ID converters without crossbar
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Architecture/Block Overview
    coverage:
      method: DIRECTED
      required_cells:
      - id-conv-sep0-direct
      random_knobs: []
      coverage_artifact: null
- key: SMU-SEP-SMC-ALIAS
  title: Dedicated SEP to SMC alias window remap
  intent: Fixed SEP_SMC_REGION_BASE 0x4000_0000 size 1GB remaps to 0x0 on a dedicated path bypassing the
    crossbar
  triad:
    producer: SEP initiator targeting SMC alias window 0x4000_0000
    transport: sep_ext_to_smc_axi_local_alias_remap bypassing smu_axi_xbar
    consumer: SMC sep_axi_in fabric subordinate
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Data Paths/SEP-SMC alias remap
  - hw/sys/sep/doc/memory_map.adoc SMC region 0x4000_0000
  - hw/sys/sep/doc/port_table.adoc sep_ext_to_smc_axi
  record_sha256: 99c45c5ff65ac3fb60bb8160921bcb8243e7559a2bbdc0347ff89cc8b8c50e91
  scenarios:
  - key: SMU-SEP-SMC-ALIAS.S1
    intent: SEP access in fixed 0x4000_0000/1GB window reaches SMC at aliased 0x0 base
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Data Paths/SEP-SMC alias remap
    - hw/sys/sep/doc/memory_map.adoc SMC Resources
    coverage:
      method: DIRECTED
      required_cells:
      - alias-hit-live
      random_knobs: []
      coverage_artifact: null
  - key: SMU-SEP-SMC-ALIAS.S2
    intent: Alias path remains independent of crossbar aperture programming
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Data Paths/SEP-SMC alias remap
    coverage:
      method: DIRECTED
      required_cells:
      - alias-bypasses-xbar
      random_knobs: []
      coverage_artifact: null
- key: SMU-SEP-PARAM
  title: SEP enable parameter effects at SMU boundary
  intent: Compile-time SEP parameter selects real SEP+xbar versus SEP=0 tie-offs, OTP error slave, and
    lc_state default
  triad:
    producer: SMU top parameter SEP 0|1
    transport: generate/tie-off structure inside SMU
    consumer: SMU boundary SEP ports, OTP AXI-Lite path, lc_state_o encoding
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Configuration Parameters
  - hw/sys/smu/doc/SMU_SPEC.md Operating Modes
  - hw/sys/smu/doc/port_table.adoc lc_state_o
  record_sha256: ab31b4f2af61031b71dfe7527a104764c6b59fed4c6447010a93b2b7ec09253d
  scenarios:
  - key: SMU-SEP-PARAM.S1
    intent: SEP=1 enables real SEP instance and crossbar routing paths
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Configuration Parameters
    - hw/sys/smu/doc/SMU_SPEC.md Architecture/Sub-Blocks
    coverage:
      method: DIRECTED
      required_cells:
      - sep-param-1
      random_knobs: []
      coverage_artifact: null
  - key: SMU-SEP-PARAM.S2
    intent: SEP=0 SEP-OTP path returns DECERR with 0xBADCAB1E via error slave
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Error Handling
    - hw/sys/smu/doc/SMU_SPEC.md Architecture/Sub-Blocks
    coverage:
      method: DIRECTED
      required_cells:
      - sep0-otp-decerr-badcab1e
      random_knobs: []
      coverage_artifact: null
  - key: SMU-SEP-PARAM.S3
    intent: SEP=0 drives lc_state_o to 8'hf0 at SMU boundary
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Security Considerations
    - hw/sys/smu/doc/port_table.adoc lc_state_o
    coverage:
      method: DIRECTED
      required_cells:
      - sep0-lc-state-f0
      random_knobs: []
      coverage_artifact: null
- key: SMC-BOOT
  title: SMC boot and firmware execution under SMU
  intent: SMC boots from ROM, releases resets, runs firmware, and reports status via scratch/mailbox paths
  triad:
    producer: SMC ROM/firmware after SMU/SMC reset release and fuse/repair gating
    transport: SMC CPU/ROM/scratch and SMU-exported control/status ports
    consumer: observable SMC execution progress and downstream reset releases
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Feature 1
  - hw/sys/smc/doc/cpu.adoc Boot Sequence Integration
  - hw/sys/smc/doc/rom.adoc
  record_sha256: 477224938d8fa60148b74e79c1e3e3add31b91b477c2407fb1645eb878a0952a
  scenarios:
  - key: SMC-BOOT.S1
    intent: After reset/fuse/repair gating, SMC fetches from ROM and progresses execution
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Feature 1
    - hw/sys/smc/doc/cpu.adoc Boot Sequence Integration
    coverage:
      method: DIRECTED
      required_cells:
      - smc-rom-fetch-progress
      random_knobs: []
      coverage_artifact: null
  - key: SMC-BOOT.S2
    intent: ext_boot_seq_done_i and mem-repair status gate reset release as specified
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/port_table.adoc ext_boot_seq_done_i
    - hw/sys/smc/doc/cpu.adoc Boot Sequence Integration
    coverage:
      method: DIRECTED
      required_cells:
      - boot-seq-gate
      random_knobs: []
      coverage_artifact: null
  - key: SMC-BOOT.S3
    intent: SEP=0 no-SEP configuration still boots SMC
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Feature 1
    - hw/sys/smu/doc/SMU_SPEC.md Operating Modes
    coverage:
      method: DIRECTED
      required_cells:
      - smc-boot-sep0
      random_knobs: []
      coverage_artifact: null
- key: SEP-BOOT
  title: Real SEP boot and execution under SMU
  intent: With SEP=1, real SEP RTL boots from TCM/ROM under SMU with reset release and observable CPU
    progress
  triad:
    producer: SEP TCM/ROM contents and SEP reset release under SMU
    transport: SMU-SEP reset and memory passthrough ports
    consumer: SEP CPU execution progress observability
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Feature 2
  - hw/sys/smu/doc/port_table.adoc sep memory/reset
  - hw/sys/sep/doc/cpu.adoc
  record_sha256: aee751d46607165cc482acc94c56790530a9c50923a99f8edbaf36d659249a59
  scenarios:
  - key: SEP-BOOT.S1
    intent: SEP TCM preload plus reset release yields observable CPU progress under SMU
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Feature 2
    coverage:
      method: DIRECTED
      required_cells:
      - sep-tcm-boot-progress
      random_knobs: []
      coverage_artifact: null
  - key: SEP-BOOT.S2
    intent: sep_reset_n_o and sep_cpu_reset_n_o reflect post fuse-sense / WDT combine at SMU boundary
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/port_table.adoc sep_reset_n_o/sep_cpu_reset_n_o
    coverage:
      method: DIRECTED
      required_cells:
      - sep-reset-exports
      random_knobs: []
      coverage_artifact: null
- key: SMC-SEP-MAILBOX
  title: SMC-SEP mailbox challenge-response interoperability
  intent: SMC and SEP exchange mailbox tokens/responses as the primary real interoperability path
  triad:
    producer: SMC outbound mailbox writer and SEP inbound reader/responder
    transport: SMC mailbox 32 and SEP mailbox 8 interconnect across SMU
    consumer: peer mailbox FIFO/pop and software-visible completion on the opposite agent
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Data Paths/Mailbox challenge-response
  - hw/sys/smu/doc/SMU_SPEC.md Feature 5
  - hw/sys/smu/doc/SMU_SPEC.md Specifications
  - hw/sys/sep/doc/fabric.adoc Mailboxes
  - hw/sys/smc/doc/memmap.adoc Mailbox
  record_sha256: fc20cfc45f19d15e079e19e27ceb35df141e3cbcbea50dfc07931c56ede2ecb4
  scenarios:
  - key: SMC-SEP-MAILBOX.S1
    intent: SMC to SEP token write becomes readable on SEP inbound mailbox
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Data Paths/Mailbox challenge-response
    - hw/sys/sep/doc/fabric.adoc Mailboxes
    coverage:
      method: DIRECTED
      required_cells:
      - smc-to-sep-token
      random_knobs: []
      coverage_artifact: null
  - key: SMC-SEP-MAILBOX.S2
    intent: SEP response write is poppable by SMC on the return mailbox path
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Data Paths/Mailbox challenge-response
    coverage:
      method: DIRECTED
      required_cells:
      - sep-to-smc-response
      random_knobs: []
      coverage_artifact: null
  - key: SMC-SEP-MAILBOX.S3
    intent: Bidirectional routing works while apertures/xbar are programmed for interop
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Feature 5
    coverage:
      method: DIRECTED
      required_cells:
      - bidir-with-aperture
      random_knobs: []
      coverage_artifact: null
  - key: SMC-SEP-MAILBOX.S4
    intent: '[BOUNDED-LIVENESS] SMC executes while SEP is stalled still completes-or-errors mailbox exchange'
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Feature 5
    coverage:
      method: DIRECTED
      required_cells:
      - smc-run-sep-stall
      random_knobs: []
      coverage_artifact: null
  - key: SMC-SEP-MAILBOX.S5
    intent: Mailbox protocol mismatch is detectable as failure
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Error Handling
    coverage:
      method: DIRECTED
      required_cells:
      - protocol-mismatch-fail
      random_knobs: []
      coverage_artifact: null
- key: SMC-SEP-MBX-IRQ
  title: Mailbox interrupt crossing between SMC and SEP
  intent: SEP mailbox interrupts enter SMC interrupt aggregation; SMC external mailbox interrupts export
    at SMU
  triad:
    producer: SEP smc_mailbox_interrupt_o / SMC mailbox controller
    transport: SEP to SMC sep_mailbox_interrupts_i and SMC ext_mailbox_interrupts_o export
    consumer: SMC CPU interrupt vector / external mailbox IRQ consumers
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Interfaces
  - hw/sys/smc/doc/port_table.adoc sep_mailbox_interrupts_i
  - hw/sys/smc/doc/interrupts.adoc SEP mailbox interrupt map
  - hw/sys/sep/doc/port_table.adoc smc_mailbox_interrupt_o
  - hw/sys/smu/doc/port_table.adoc ext_mailbox_interrupts_o
  record_sha256: b28048488a1f0f8abc0512d4e2341069e8c6f781f37604b85f55a09e9ac7d642
  scenarios:
  - key: SMC-SEP-MBX-IRQ.S1
    intent: SEP mailbox channel IRQ appears on SMC cpu_interrupts_o peripheral slice
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/interrupts.adoc SEP mailbox interrupt map
    - hw/sys/smc/doc/port_table.adoc sep_mailbox_interrupts_i
    coverage:
      method: DIRECTED
      required_cells:
      - sep-mbx-irq-to-smc
      random_knobs: []
      coverage_artifact: null
  - key: SMC-SEP-MBX-IRQ.S2
    intent: SMC external mailbox interrupts visible on SMU ext_mailbox_interrupts_o
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/port_table.adoc ext_mailbox_interrupts_o
    - hw/sys/smu/doc/SMU_SPEC.md Interfaces
    coverage:
      method: DIRECTED
      required_cells:
      - smc-ext-mbx-irq-export
      random_knobs: []
      coverage_artifact: null
- key: SEP-WDT-SMC
  title: SEP watchdog event into SMC
  intent: SEP WDT timeout produces reset request / interrupt into SMC aggregation at SMU boundary
  triad:
    producer: SEP watchdog timer timeout
    transport: sep_wdt_timer_rst_req / sep_wdt_reset_n_i into SMC
    consumer: SMC interrupt aggregator and/or SEP reset combine path
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Error Handling
  - hw/sys/smc/doc/port_table.adoc sep_wdt_reset_n_i
  - hw/sys/sep/doc/periphs.adoc Watchdog
  record_sha256: 9b59767709ae4624effe49616af8122139b2c9bbc109b0be8bb7e7dc39e7794f
  scenarios:
  - key: SEP-WDT-SMC.S1
    intent: SEP WDT bite/reset request observed at SMC/SMU integration path
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Error Handling
    - hw/sys/smc/doc/port_table.adoc sep_wdt_reset_n_i
    coverage:
      method: DIRECTED
      required_cells:
      - sep-wdt-to-smc
      random_knobs: []
      coverage_artifact: null
- key: DTP-JTAG-ACCESS
  title: DTP primary JTAG TAP access through SMU
  intent: Primary JTAG PTAP provides IDCODE/BYPASS and TAP state/instruction observability at SMU pads
  triad:
    producer: external JTAG host on jtag_ptap_client pins
    transport: DTP PTAP inside SMU
    consumer: TDO/tdo_oen and jtag_ptap_state_o / jtag_ptap_inst_decoded_o
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Feature 3
  - hw/sys/dtp/doc/overview.adoc Key Features
  - hw/sys/dtp/doc/jtag.adoc
  - hw/sys/smu/doc/port_table.adoc jtag_ptap
  record_sha256: a3c87bace72c0ea7cff22cca1492ae7529b9cb50b75469c8523fa849e4fcd797
  scenarios:
  - key: DTP-JTAG-ACCESS.S1
    intent: IDCODE/BYPASS instructions complete with legal TAP state transitions
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Feature 3
    - hw/sys/dtp/doc/overview.adoc JTAG Interface
    coverage:
      method: DIRECTED
      required_cells:
      - idcode
      - bypass
      - tap-states
      random_knobs: []
      coverage_artifact: null
  - key: DTP-JTAG-ACCESS.S2
    intent: TRST/POR returns TAP to Test-Logic-Reset and clock-stop output to clocks-running
    requires: LIVE
    spec_refs:
    - hw/sys/dtp/doc/jtag.adoc Reset Architecture
    coverage:
      method: DIRECTED
      required_cells:
      - tap-reset-safe
      random_knobs: []
      coverage_artifact: null
- key: DTP-JTAG2AXI-SMC
  title: DTP JTAG2AXI bridge into SMC fabric
  intent: JTAG2AXI issues debug AXI traffic into SMC fabric subject to lifecycle gating
  triad:
    producer: JTAG debugger via DTP JTAG2AXI
    transport: DTP axi_smc_dbg into SMC jtag_axi_in
    consumer: SMC fabric subordinates reachable on the debug path
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Feature 3
  - hw/sys/dtp/doc/jtag.adoc DTP JTAG Topology
  - hw/sys/dtp/doc/port_table.adoc axi_smc_dbg
  - hw/sys/smc/doc/fabric.adoc JTAG2AXI Bridge
  record_sha256: b94ec4c307f9f451f1a88c08f12a5f769aea9d4012158808a2a49eeaedfbf381
  scenarios:
  - key: DTP-JTAG2AXI-SMC.S1
    intent: Allowed lifecycle/debug policy permits JTAG2AXI read/write into SMC fabric
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Feature 3
    - hw/sys/dtp/doc/port_table.adoc axi_smc_dbg
    coverage:
      method: DIRECTED
      required_cells:
      - jtag2axi-smc-allowed
      random_knobs: []
      coverage_artifact: null
  - key: DTP-JTAG2AXI-SMC.S2
    intent: Lifecycle-gated deny blocks debug AXI traffic
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Error Handling
    - hw/sys/dtp/doc/jtag.adoc Security Integration
    coverage:
      method: DIRECTED
      required_cells:
      - jtag2axi-smc-denied
      random_knobs: []
      coverage_artifact: null
- key: DTP-OTP-JTAG
  title: OTP-over-JTAG bridges to SMC and SEP
  intent: DTP JTAG2AXI-Lite OTP bridges access SMC and SEP OTP debug ports, with SEP=0 error-slave substitution
  triad:
    producer: JTAG debugger via DTP OTP AXI-Lite bridges
    transport: axil_smc_otp_jtag and axil_sep_otp_jtag through SMU/DTP
    consumer: SMC/SEP OTP controllers or SEP=0 error slave
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Feature 3
  - hw/sys/dtp/doc/jtag.adoc DTP JTAG Topology
  - hw/sys/dtp/doc/port_table.adoc axil otp jtag
  - hw/sys/sep/doc/port_table.adoc axil_sep_otp_jtag
  record_sha256: 5cc0547d95e55917bcaa7afea945b68977483d3f52c67f3e92ed94708c53b3fe
  scenarios:
  - key: DTP-OTP-JTAG.S1
    intent: JTAG OTP path reaches SMC OTP debug port when enabled
    requires: LIVE
    spec_refs:
    - hw/sys/dtp/doc/port_table.adoc axil_smc_otp_jtag
    - hw/sys/smu/doc/SMU_SPEC.md Feature 3
    coverage:
      method: DIRECTED
      required_cells:
      - otp-jtag-smc
      random_knobs: []
      coverage_artifact: null
  - key: DTP-OTP-JTAG.S2
    intent: JTAG OTP path reaches SEP OTP debug port when SEP=1 and enabled
    requires: LIVE
    spec_refs:
    - hw/sys/dtp/doc/port_table.adoc axil_sep_otp_jtag
    - hw/sys/sep/doc/port_table.adoc axil_sep_otp_jtag
    coverage:
      method: DIRECTED
      required_cells:
      - otp-jtag-sep1
      random_knobs: []
      coverage_artifact: null
  - key: DTP-OTP-JTAG.S3
    intent: SEP=0 substitutes error slave DECERR on SEP OTP path
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Error Handling
    coverage:
      method: DIRECTED
      required_cells:
      - otp-jtag-sep0-err
      random_knobs: []
      coverage_artifact: null
- key: DTP-IC-RESET
  title: DTP IC_RESET TDR override of SMC/SEP/external resets
  intent: IC_RESET TDR override slices force SMC/SEP/external reset values when override enables are set
  triad:
    producer: JTAG IC_RESET TDR programming in DTP
    transport: jtag_ic_reset_smc/sep/ext override structs
    consumer: SMC/SEP reset controls and external integrator reset overrides
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Feature 3
  - hw/sys/smu/doc/SMU_SPEC.md Operating Modes
  - hw/sys/dtp/doc/port_table.adoc jtag_ic_reset
  - hw/sys/smu/doc/port_table.adoc jtag_ic_reset_ext_o
  record_sha256: 86dced66cee15ba7eea6c122a1e67c2f5ff31b0e6d44ad0b656046da107cb439
  scenarios:
  - key: DTP-IC-RESET.S1
    intent: IC_RESET override asserts programmed active-low reset values into SMC/SEP paths
    requires: LIVE
    spec_refs:
    - hw/sys/dtp/doc/port_table.adoc jtag_ic_reset_smc/sep
    - hw/sys/smu/doc/SMU_SPEC.md Operating Modes
    coverage:
      method: DIRECTED
      required_cells:
      - ic-reset-override-assert
      random_knobs: []
      coverage_artifact: null
  - key: DTP-IC-RESET.S2
    intent: Clearing override or TRST/POR removes reset override
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Operating Modes
    coverage:
      method: DIRECTED
      required_cells:
      - ic-reset-override-clear
      random_knobs: []
      coverage_artifact: null
- key: DTP-BOOT-STALL
  title: DTP boot-stall interaction with SMC boot
  intent: JTAG boot-stall override holds or releases SMC boot progression under debug/test mode
  triad:
    producer: DTP jtag_boot_stall_ovrd_o / jtag_boot_stall_o
    transport: DTP to SMC boot-control integration inside SMU
    consumer: SMC boot progression held or released
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Feature 3
  - hw/sys/dtp/doc/port_table.adoc jtag_boot_stall
  record_sha256: 285efef5e4890808944a5b5bccf502f1aaa049fb234ac78dd60db55f0f812c42
  scenarios:
  - key: DTP-BOOT-STALL.S1
    intent: Boot-stall override asserted holds SMC boot before stall release
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Feature 3
    - hw/sys/dtp/doc/port_table.adoc jtag_boot_stall
    coverage:
      method: DIRECTED
      required_cells:
      - boot-stall-hold
      random_knobs: []
      coverage_artifact: null
  - key: DTP-BOOT-STALL.S2
    intent: Boot-stall release allows SMC boot to proceed
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Feature 3
    coverage:
      method: DIRECTED
      required_cells:
      - boot-stall-release
      random_knobs: []
      coverage_artifact: null
- key: DTP-CLOCK-STOP
  title: DTP clock-stop aggregation with JTAG and CLA sources
  intent: JTAG DEBUG_CONTROL clock-stop OR-combined with CLA xtrig_clk_stop_req produces stop_clks_o;
    CLA-only status remains distinct
  triad:
    producer: JTAG jtag_clock_stop and/or xtrig_clk_stop_req_i sources
    transport: DTP CTN clock-stop controller
    consumer: dtp_stop_clks_o to PLL clock gates and CLA status readback
  spec_refs:
  - hw/sys/dtp/doc/clock_stop.adoc
  - hw/sys/smu/doc/SMU_SPEC.md Feature 6
  - hw/sys/smu/doc/port_table.adoc dtp_stop_clks_o/xtrig_clk_stop_req_i
  - hw/sys/dtp/doc/port_table.adoc stop_clks_o
  record_sha256: fdc9d31a7429483e08b31a72aeb747367498d085be037a37cb85642a9fc6c99e
  scenarios:
  - key: DTP-CLOCK-STOP.S1
    intent: JTAG clock-stop alone asserts stop_clks_o
    requires: LIVE
    spec_refs:
    - hw/sys/dtp/doc/clock_stop.adoc
    coverage:
      method: DIRECTED
      required_cells:
      - jtag-stop-clks
      random_knobs: []
      coverage_artifact: null
  - key: DTP-CLOCK-STOP.S2
    intent: CLA clock-stop request aggregate asserts stop_clks_o and CLA-only status readback
    requires: LIVE
    spec_refs:
    - hw/sys/dtp/doc/clock_stop.adoc
    - hw/sys/smu/doc/SMU_SPEC.md Feature 6
    coverage:
      method: DIRECTED
      required_cells:
      - cla-stop-clks
      - cla-status-readback
      random_knobs: []
      coverage_artifact: null
  - key: DTP-CLOCK-STOP.S3
    intent: cla_clock_stop_en export is independent of stop_clks_o aggregation
    requires: LIVE
    spec_refs:
    - hw/sys/dtp/doc/clock_stop.adoc
    coverage:
      method: DIRECTED
      required_cells:
      - cla-en-export-independent
      random_knobs: []
      coverage_artifact: null
  - key: DTP-CLOCK-STOP.S4
    intent: '[BOUNDED-LIVENESS] clock-stop assert/deassert during active traffic completes-or-errors'
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Feature 6
    coverage:
      method: DIRECTED
      required_cells:
      - clock-stop-contested
      random_knobs: []
      coverage_artifact: null
- key: DTP-XTRIG-CTM
  title: DTP cross-trigger CTM external ports
  intent: Cross-trigger matrix source/destination req/ack arrays are exported at SMU with DTP[1:0] reserved
    for SMC
  triad:
    producer: CTM internal sources or external destination requesters
    transport: DTP CTM inside SMU cross-trigger network
    consumer: xtrig_ctm_src_req_o / xtrig_ctm_dst_ack_o peers at SMU boundary
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Feature 6
  - hw/sys/smu/doc/SMU_SPEC.md Specifications
  - hw/sys/dtp/doc/overview.adoc Cross Trigger Network
  - hw/sys/smu/doc/port_table.adoc xtrig_ctm
  record_sha256: 2590e462090eb6e8ecd833745417c19b1ed3b675425ffda5e72ee09533cf553a
  scenarios:
  - key: DTP-XTRIG-CTM.S1
    intent: CTM source request pulses appear on SMU external CTM ports
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/port_table.adoc xtrig_ctm_src_req_o
    - hw/sys/smu/doc/SMU_SPEC.md Feature 6
    coverage:
      method: DIRECTED
      required_cells:
      - ctm-src-export
      random_knobs: []
      coverage_artifact: null
  - key: DTP-XTRIG-CTM.S2
    intent: External CTM destination request is handled per configured mode
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/port_table.adoc xtrig_ctm_dst
    - hw/sys/dtp/doc/overview.adoc Cross Trigger Network
    coverage:
      method: DIRECTED
      required_cells:
      - ctm-dst-path
      random_knobs: []
      coverage_artifact: null
- key: DTP-XTRIG-CTP
  title: DTP cross-trigger CTP GPIO pad protocols
  intent: CTP request/ack pad vectors support wire-OR and point-to-point signaling modes through SMU GPIO
    pad ring ports
  triad:
    producer: DTP CTP engine and/or external pad peers
    transport: xtrig_ctp dout/din/en vectors at SMU/DTP boundary
    consumer: GPIO pad ring / remote CTP peers
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Feature 6
  - hw/sys/dtp/doc/overview.adoc Cross Trigger Network
  - hw/sys/smu/doc/port_table.adoc xtrig_ctp
  record_sha256: 2fc25bb22662a8e753d179ec60f42eabc82960c7815084ebd25332ac3e00fa7b
  scenarios:
  - key: DTP-XTRIG-CTP.S1
    intent: CTP request-out/ack paths toggle pad-facing enables and data as configured
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/port_table.adoc xtrig_ctp
    - hw/sys/smu/doc/SMU_SPEC.md Feature 6
    coverage:
      method: DIRECTED
      required_cells:
      - ctp-pad-protocol
      random_knobs: []
      coverage_artifact: null
  - key: DTP-XTRIG-CTP.S2
    intent: Wire-OR and P2P modes are both exercisable
    requires: LIVE
    spec_refs:
    - hw/sys/dtp/doc/overview.adoc Cross Trigger Network
    - hw/sys/smu/doc/SMU_SPEC.md Feature 6
    coverage:
      method: RANDOMIZED
      required_cells:
      - ctp-wire-or
      - ctp-p2p
      random_knobs:
      - ctp-mode
      coverage_artifact: null
- key: DTP-STAP-HOSTS
  title: DTP secondary TAP hosts for SMC/SEP/IO/extra
  intent: DTP hosts SMC/SEP/IO/extra STAPs for debug TAP connectivity, gated by lifecycle/security disables
  triad:
    producer: PTAP/STAP selection and JTAG IR path in DTP
    transport: jtag_stap_smc/sep/io/extra host ports
    consumer: SMC/SEP/IO/extra debug TAP targets
  spec_refs:
  - hw/sys/dtp/doc/overview.adoc Secondary TAPs
  - hw/sys/dtp/doc/jtag.adoc Security Integration
  - hw/sys/dtp/doc/port_table.adoc jtag_stap
  - hw/sys/smu/doc/SMU_SPEC.md Security Considerations
  record_sha256: d6cfad0e5d4841fa5e71cfc4607910c6d763a084e4fe381d620e075e7323711a
  scenarios:
  - key: DTP-STAP-HOSTS.S1
    intent: SMC and SEP debug STAPs selectable when feat_ctrl/security policy allows
    requires: LIVE
    spec_refs:
    - hw/sys/dtp/doc/port_table.adoc jtag_stap_smc/sep
    - hw/sys/dtp/doc/jtag.adoc Security Integration
    coverage:
      method: DIRECTED
      required_cells:
      - stap-smc-sep-allowed
      random_knobs: []
      coverage_artifact: null
  - key: DTP-STAP-HOSTS.S2
    intent: Security/lifecycle gating blocks STAP selection when disabled
    requires: LIVE
    spec_refs:
    - hw/sys/dtp/doc/jtag.adoc Security Integration
    - hw/sys/smu/doc/SMU_SPEC.md Security Considerations
    coverage:
      method: DIRECTED
      required_cells:
      - stap-gated-denied
      random_knobs: []
      coverage_artifact: null
- key: SEP-FEAT-CTRL
  title: SEP feature-control gating into SMC and DTP
  intent: SEP feat_ctrl_o gates DTP debug resources and is consumed by SMC as lifecycle feature control
  triad:
    producer: SEP lifecycle controller feat_ctrl_o
    transport: SMU wiring of feat_ctrl into DTP and SMC
    consumer: DTP debug gates and SMC feature-control consumers
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Feature 7
  - hw/sys/smu/doc/SMU_SPEC.md Security Considerations
  - hw/sys/sep/doc/lifecycle_controller.adoc feat_ctrl_o
  - hw/sys/dtp/doc/port_table.adoc feat_ctrl_i
  - hw/sys/smc/doc/port_table.adoc feat_ctrl_i
  record_sha256: 01fbb508c6eb099ca101abf456a4da61999fcfcb3dff161305d93302141b54f1
  scenarios:
  - key: SEP-FEAT-CTRL.S1
    intent: Permissive feat_ctrl enables gated debug resource access in DTP
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Feature 7
    - hw/sys/dtp/doc/jtag.adoc Security Integration
    coverage:
      method: DIRECTED
      required_cells:
      - feat-ctrl-allow-debug
      random_knobs: []
      coverage_artifact: null
  - key: SEP-FEAT-CTRL.S2
    intent: Restrictive feat_ctrl blocks gated debug STAP/JTAG2AXI per policy
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Error Handling
    - hw/sys/smu/doc/SMU_SPEC.md Feature 7
    coverage:
      method: DIRECTED
      required_cells:
      - feat-ctrl-deny-debug
      random_knobs: []
      coverage_artifact: null
  - key: SEP-FEAT-CTRL.S3
    intent: SMC_FUSE_TEST bit in feat_ctrl is visible/consumed at SMC boundary
    requires: LIVE
    spec_refs:
    - hw/sys/sep/doc/lifecycle_controller.adoc SMC_FUSE_TEST
    - hw/sys/smc/doc/port_table.adoc feat_ctrl_i
    coverage:
      method: DIRECTED
      required_cells:
      - feat-ctrl-smc-fuse-test
      random_knobs: []
      coverage_artifact: null
- key: SEP-LC-EXPORT
  title: SEP lifecycle and security-disable exports at SMU
  intent: SEP exports lc_state, demote states, lc_sigint_err, and security_disable through SMU boundary
    ports
  triad:
    producer: SEP lifecycle controller / security-disable logic
    transport: SMU exports lc_state_o, lcc_demote_state, lc_sigint_err_o, security_disable into SMC
    consumer: external lifecycle observers and SMC security/lifecycle inputs
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Feature 7
  - hw/sys/smu/doc/SMU_SPEC.md Security Considerations
  - hw/sys/sep/doc/port_table.adoc lc_state/security_disable
  - hw/sys/smu/doc/port_table.adoc lc_state_o/lcc_demote
  - hw/sys/sep/doc/security_disable.adoc
  record_sha256: b6181512d8a3d409c4ea0672ce029e99a70426e1e7c6b5776fb745e064256efa
  scenarios:
  - key: SEP-LC-EXPORT.S1
    intent: SEP=1 lc_state_o reflects SEP lifecycle encoding at SMU width 8
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/port_table.adoc lc_state_o
    - hw/sys/sep/doc/port_table.adoc lc_state_o
    coverage:
      method: DIRECTED
      required_cells:
      - lc-state-export
      random_knobs: []
      coverage_artifact: null
  - key: SEP-LC-EXPORT.S2
    intent: security_disable_o from SEP is delivered into SMC
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Security Considerations
    - hw/sys/sep/doc/port_table.adoc security_disable_o
    coverage:
      method: DIRECTED
      required_cells:
      - security-disable-to-smc
      random_knobs: []
      coverage_artifact: null
  - key: SEP-LC-EXPORT.S3
    intent: SEC_DIS token path uses SMU-tied SEP_SEC_DISABLE_TOKEN digest parameter
    requires: LIVE
    spec_refs:
    - hw/sys/sep/doc/security_disable.adoc
    - hw/sys/smu/doc/SMU_SPEC.md Configuration Parameters
    coverage:
      method: DIRECTED
      required_cells:
      - sec-dis-token-digest
      random_knobs: []
      coverage_artifact: null
  - key: SEP-LC-EXPORT.S4
    intent: lcc_demote_state_1/2_o are exported at SMU boundary
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/port_table.adoc lcc_demote_state
    - hw/sys/sep/doc/port_table.adoc lcc_demote_state
    coverage:
      method: DIRECTED
      required_cells:
      - demote-state-export
      random_knobs: []
      coverage_artifact: null
- key: SMC-SEP-FUSE-SENSE
  title: SMC-SEP fuse-sense handshake
  intent: SMC fuse_sense_done participates in SEP/SMC security bring-up handshake across the SMU
  triad:
    producer: SMC eFuse sense completion fuse_sense_done_o
    transport: SMU wiring to SEP smc_fuse_sense_done_i and SMU fuse_sense_done_o export
    consumer: SEP fuse-sense dependency / external memory-repair observers
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Security Considerations
  - hw/sys/smc/doc/cpu.adoc fuse_sense_done_o
  - hw/sys/sep/doc/port_table.adoc smc_fuse_sense_done_i
  - hw/sys/smu/doc/port_table.adoc fuse_sense_done_o
  record_sha256: d47d5540997c312917a3c2b6af5be95b8c1bb153d91abc69c6f27d64bb6c3b93
  scenarios:
  - key: SMC-SEP-FUSE-SENSE.S1
    intent: SMC fuse_sense_done asserts and is observed by SEP smc_fuse_sense_done_i
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Security Considerations
    - hw/sys/sep/doc/port_table.adoc smc_fuse_sense_done_i
    coverage:
      method: DIRECTED
      required_cells:
      - fuse-sense-smc-to-sep
      random_knobs: []
      coverage_artifact: null
  - key: SMC-SEP-FUSE-SENSE.S2
    intent: SEP fuse_sense_done_o is exported at SMU boundary after SEP sense
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/port_table.adoc sep_fuse_sense_done_o
    - hw/sys/sep/doc/port_table.adoc sep_fuse_sense_done_o
    coverage:
      method: DIRECTED
      required_cells:
      - sep-fuse-sense-export
      random_knobs: []
      coverage_artifact: null
- key: SMC-FABRIC-PORTS
  title: SMC fabric ports exercised through SMU
  intent: SMC fabric managers/subordinates facing JTAG, SEP, and system AXI are reachable through SMU
    integration
  triad:
    producer: CPU/DMA/JTAG2AXI/SEP/system initiators into SMC fabric
    transport: SMC dual-network fabric inside SMU-integrated SMC
    consumer: SMC local subordinates and SMC output_axi / filter/remap path
  spec_refs:
  - hw/sys/smc/doc/fabric.adoc Traffic Managers and Subordinates
  - hw/sys/smc/doc/port_table.adoc sep_axi_in/sys/jtag
  - hw/sys/smu/doc/SMU_SPEC.md Feature 4
  record_sha256: 418dcc60dff9d460c3805010081b49df7d96495b1ccd8c34053ea86afb1f5c95
  scenarios:
  - key: SMC-FABRIC-PORTS.S1
    intent: SEP to SMC fabric input completes a live transaction to an SMC local subordinate
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/port_table.adoc sep_axi_in
    - hw/sys/smc/doc/fabric.adoc External AXI Input Ports
    coverage:
      method: DIRECTED
      required_cells:
      - sep-into-smc-fabric
      random_knobs: []
      coverage_artifact: null
  - key: SMC-FABRIC-PORTS.S2
    intent: JTAG2AXI into SMC fabric reaches a local subordinate when allowed
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/fabric.adoc JTAG2AXI Bridge
    coverage:
      method: DIRECTED
      required_cells:
      - jtag-into-smc-fabric
      random_knobs: []
      coverage_artifact: null
  - key: SMC-FABRIC-PORTS.S3
    intent: Inbound filter default block-by-default denies unauthorized external access until programmed
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/fabric.adoc Inbound Filtering
    coverage:
      method: DIRECTED
      required_cells:
      - smc-inbound-filter-default-block
      random_knobs: []
      coverage_artifact: null
  - key: SMC-FABRIC-PORTS.S4
    intent: Outbound filtered/remapped SMC traffic reaches SMU external/xbar path
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/fabric.adoc Outbound Traffic Flow
    - hw/sys/smu/doc/SMU_SPEC.md Data Paths/Crossbar routing
    coverage:
      method: DIRECTED
      required_cells:
      - smc-outbound-to-smu
      random_knobs: []
      coverage_artifact: null
- key: SEP-FABRIC-PORTS
  title: SEP system fabric ports exercised through SMU
  intent: SEP inbound system interface and outbound SMC/SMN routing are exercised at the SMU integration
    boundary
  triad:
    producer: external/SMU masters into SEP inbound, or SEP CPU/DMA outbound
    transport: SEP hierarchical AXI fabric plus inbound filter plus system peripherals routing
    consumer: SEP local targets, SMC alias path, or SMN via SMU xbar
  spec_refs:
  - hw/sys/sep/doc/fabric.adoc Top Level AXI4
  - hw/sys/sep/doc/fabric.adoc Transaction Routing
  - hw/sys/sep/doc/memory_map.adoc
  - hw/sys/smu/doc/SMU_SPEC.md Feature 4
  record_sha256: 0a7617e0b8384d3d214085c4b9208b9d6b067663a306a2fe613576ffdec92477
  scenarios:
  - key: SEP-FABRIC-PORTS.S1
    intent: Inbound path is block-by-default after POR until SEP firmware programs filters
    requires: LIVE
    spec_refs:
    - hw/sys/sep/doc/fabric.adoc Top Level AXI4
    coverage:
      method: DIRECTED
      required_cells:
      - sep-inbound-default-block
      random_knobs: []
      coverage_artifact: null
  - key: SEP-FABRIC-PORTS.S2
    intent: After filter programming, external/SMU master reaches allowed SEP target
    requires: LIVE
    spec_refs:
    - hw/sys/sep/doc/fabric.adoc Top Level AXI4
    - hw/sys/sep/doc/fabric.adoc Mailboxes
    coverage:
      method: DIRECTED
      required_cells:
      - sep-inbound-allow
      random_knobs: []
      coverage_artifact: null
  - key: SEP-FABRIC-PORTS.S3
    intent: SEP outbound non-SMC traffic routes to SMN via SMU crossbar ext_out
    requires: LIVE
    spec_refs:
    - hw/sys/sep/doc/fabric.adoc Transaction Routing
    - hw/sys/smu/doc/SMU_SPEC.md Data Paths/Crossbar routing
    coverage:
      method: DIRECTED
      required_cells:
      - sep-outbound-to-smn
      random_knobs: []
      coverage_artifact: null
  - key: SEP-FABRIC-PORTS.S4
    intent: SEP local-alias high window 768 MiB remains SEP-local and distinct from SMC global aperture
    requires: DECODE
    spec_refs:
    - hw/sys/sep/doc/fabric.adoc Transaction Routing
    - hw/sys/sep/doc/memory_map.adoc SEP Local Alias
    coverage:
      method: DIRECTED
      required_cells:
      - sep-local-alias-vs-smc-aperture
      random_knobs: []
      coverage_artifact: null
- key: SMC-AXI-LITE-SHIMS
  title: SMC AXI-Lite shim ports at SMU boundary
  intent: SMC AXI-Lite external shims PLL/PVT/GPIO/eFuse/external are presented on SMU top ports
  triad:
    producer: SMC fabric AXI-Lite masters for shim/peripheral control
    transport: SMU top axil and smc_external/gpio/efuse ports
    consumer: external PLL/PVT/GPIO/eFuse/adopter peripheral shims
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Interfaces
  - hw/sys/smu/doc/port_table.adoc axil_pll/pvt/gpio/efuse/smc_external
  record_sha256: 28e02ff7565c6cfe56ac35e5b3b6805eacf5dbf9502ee3ea79688dafc0e9bb25
  scenarios:
  - key: SMC-AXI-LITE-SHIMS.S1
    intent: SMC AXI-Lite shim request/response handshake completes on at least one SMU-exported shim port
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/port_table.adoc axil_pll/pvt/gpio
    - hw/sys/smu/doc/SMU_SPEC.md Interfaces
    coverage:
      method: DIRECTED
      required_cells:
      - axil-shim-handshake
      random_knobs: []
      coverage_artifact: null
  - key: SMC-AXI-LITE-SHIMS.S2
    intent: Unused smc_external port policy expects DECERR tie-off when unused
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/port_table.adoc smc_external_resp_i
    coverage:
      method: DIRECTED
      required_cells:
      - smc-external-decerr-tieoff
      random_knobs: []
      coverage_artifact: null
- key: DTP-IJTAG-SCAN
  title: DTP iJTAG/BSR/DFT/DFD scan host ports
  intent: DTP exports BSR and iJTAG DFD/DFT secure/non-secure/STAP scan host controls at SMU boundary
  triad:
    producer: JTAG/iJTAG scan operations in DTP
    transport: jtag_bsr/dfd/dft/stap_host_scan SMU ports
    consumer: external scan chains loopback or scan model
  spec_refs:
  - hw/sys/dtp/doc/overview.adoc iJTAG Support
  - hw/sys/smu/doc/SMU_SPEC.md Feature 3
  - hw/sys/smu/doc/port_table.adoc jtag scan
  - hw/sys/dtp/doc/port_table.adoc jtag scan
  record_sha256: b5b17386940059046bce630c68dce95b5849ea20e26462e2dfd2a745932a0c9f
  scenarios:
  - key: DTP-IJTAG-SCAN.S1
    intent: BSR host scan path is electrically present under PTAP EXTEST/BSR enable family
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/port_table.adoc jtag_bsr_host_scan
    - hw/sys/dtp/doc/overview.adoc Boundary Scan
    coverage:
      method: DIRECTED
      required_cells:
      - bsr-scan-port
      random_knobs: []
      coverage_artifact: null
  - key: DTP-IJTAG-SCAN.S2
    intent: DFD/DFT iJTAG host scan ports are present for secure and non-secure chains
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/port_table.adoc jtag_dfd/dft
    - hw/sys/dtp/doc/overview.adoc iJTAG Support
    coverage:
      method: DIRECTED
      required_cells:
      - ijtag-dfd-dft-ports
      random_knobs: []
      coverage_artifact: null
interactions:
- key: INT-SMC-SEP-MAILBOX-IRQ
  features:
  - SMC-SEP-MAILBOX
  - SMC-SEP-MBX-IRQ
  intent: Mailbox data challenge-response and the SEP to SMC mailbox interrupt must occur together for
    real interop
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Feature 5
  - hw/sys/smu/doc/SMU_SPEC.md Data Paths/Mailbox challenge-response
  - hw/sys/smc/doc/interrupts.adoc SEP mailbox interrupt map
  record_sha256: 49dea6ef3016f5b7f20fb782ede2be3f75b6fc5b0b657ba9f829cd6f4469f43a
  requires: LIVE
  coverage:
    method: DIRECTED
    required_cells:
    - mailbox-data-plus-irq
    random_knobs: []
    coverage_artifact: null
- key: INT-FEAT-CTRL-DEBUG
  features:
  - SEP-FEAT-CTRL
  - DTP-JTAG2AXI-SMC
  - DTP-STAP-HOSTS
  intent: SEP feat_ctrl must jointly gate DTP JTAG2AXI and STAP debug access
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Security Considerations
  - hw/sys/dtp/doc/jtag.adoc Security Integration
  - hw/sys/smu/doc/SMU_SPEC.md Feature 7
  record_sha256: bdd16196b540def1b3baaef6492bebde18a69cf42e73a6e3812a3c7be3723e24
  requires: LIVE
  coverage:
    method: DIRECTED
    required_cells:
    - feat-ctrl-gates-jtag2axi-and-stap
    random_knobs: []
    coverage_artifact: null
- key: INT-BOOT-STALL-SMC
  features:
  - DTP-BOOT-STALL
  - SMC-BOOT
  intent: DTP boot-stall must hold and then release real SMC boot progression
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Feature 3
  - hw/sys/smu/doc/SMU_SPEC.md Feature 1
  record_sha256: 34be58ee71f631d667f8bb3509f70e09549259b2294f37d93efdeaa52ad342fb
  requires: LIVE
  coverage:
    method: DIRECTED
    required_cells:
    - stall-then-smc-boot
    random_knobs: []
    coverage_artifact: null
- key: INT-CLK-STOP-SMC
  features:
  - DTP-CLOCK-STOP
  - SMC-BOOT
  intent: DTP-SMC clock-stop handshake coordinates functional halt with SMC/CLA path
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Feature 6
  - hw/sys/dtp/doc/clock_stop.adoc
  record_sha256: 5e84ec23f32535788186ff3ed381206153436b2e283605675ebf01060ac0ecda
  requires: LIVE
  coverage:
    method: DIRECTED
    required_cells:
    - clk-stop-with-smc
    random_knobs: []
    coverage_artifact: null
- key: INT-SEP0-OTP-ERR
  features:
  - SMU-SEP-PARAM
  - DTP-OTP-JTAG
  intent: SEP=0 configuration must make SEP OTP-over-JTAG return the specified DECERR error-slave response
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Error Handling
  - hw/sys/smu/doc/SMU_SPEC.md Architecture/Sub-Blocks
  record_sha256: f975f4c5362658be31ba0e863c44df0efcb818a039fc6d5b4295985b3d8fcbf6
  requires: LIVE
  coverage:
    method: DIRECTED
    required_cells:
    - sep0-otp-jtag-decerr
    random_knobs: []
    coverage_artifact: null
- key: INT-FUSE-SENSE-BOOT
  features:
  - SMC-SEP-FUSE-SENSE
  - SMC-BOOT
  - SEP-BOOT
  intent: Fuse-sense handshake participates in SMC/SEP security bring-up before/with boot
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Security Considerations
  - hw/sys/smc/doc/cpu.adoc Boot Sequence Integration
  record_sha256: d6a7297ef1ad0d169ba2a7faed03e63e92d1cb32262110b5223582ab70b797bb
  requires: LIVE
  coverage:
    method: DIRECTED
    required_cells:
    - fuse-sense-then-boot
    random_knobs: []
    coverage_artifact: null
- key: INT-XBAR-APERTURE-INTEROP
  features:
  - SMU-AXI-APERTURE
  - SMC-SEP-MAILBOX
  - SMU-AXI-XBAR-CONNECTIVITY
  intent: Mailbox interop depends on crossbar connectivity plus programmed apertures
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Feature 5
  - hw/sys/smu/doc/SMU_SPEC.md Feature 4
  record_sha256: 1aa032a56830cbf3d6d04f80bef85246151b40af1a24e52ec997676ac99ce176
  requires: LIVE
  coverage:
    method: DIRECTED
    required_cells:
    - aperture-plus-mailbox-routing
    random_knobs: []
    coverage_artifact: null
---

# SMU_ALL SPEC Feature List — REVERSE-INVENTORY CANDIDATE

> **STATUS: candidate — reverse-inventory only**
>
> This artifact is a sealed forward-from-SPEC derivation produced solely for
> Skill 3 reverse-inventory diff. It is **not** a replacement for
> `SMU_ALL_SPEC_FEATURE_LIST.md` and must not be treated as the approved
> feature universe. `approved_by` / `approved_at` remain null (draft-never-bless).

## Scope reminder (behaviors, not tests)

**IN:** SMU-level verification of integrated SMC, SEP, and DTP blocks and their
interoperability as named by the pinned `hw/sys/{smu,smc,sep,dtp}/doc/` sources —
SMU top ports and composition; SMC/SEP/DTP fabrics and port-level behaviors
exercised through the SMU; AXI/SMN crossbar and aperture routing among
SMC/SEP/external; mailbox and interrupt crossing between SMC and SEP;
DTP/JTAG/JTAG2AXI/cross-trigger/clock-stop integration with SMC and SEP; and
SEP=0/1 configuration effects at the SMU boundary.

**OUT:** DV/VPLAN/testplan/testlist docs; generated register adoc under
`regs/gen/`; RTL-as-spec; threat-model prose without a producer→transport→consumer
behavior; deep IP-internal behaviors specified only inside a subsystem doc and
never restated at the SMU integration boundary.

Milestone P2 closes P0–P2 scenarios at the *plan* layer; this feature_list is
**not** trimmed by milestone. Contested `[BOUNDED-LIVENESS]` scenarios are
enumerated here even if later marked OUT-OF-MILESTONE.

## Feature index (candidate)

| Key | Intent (one line) | Scenarios |
|-----|-------------------|-----------|
| `SMU-COMPOSITION` | SMU composes SMC, SEP when enabled, DTP, and the AXI crossbar as one subsystem | 2 |
| `SMU-TOP-CLK-RST` | SMU clocks and cold/primary resets propagate to composed blocks and SMU reset outputs | 3 |
| `SMU-AXI-XBAR-CONNECTIVITY` | CSR-routed AXI4 crossbar connects sep_out/smc_out/ext_in to sep_in/smc_in/ext_out without self-loop | 4 |
| `SMU-AXI-APERTURE` | CSR-programmed SEP/SMC apertures and global-base remap steer SMU-level address decode | 3 |
| `SMU-AXI-EXT-SMN` | External SMN-facing AXI inbound and outbound ports exchange traffic with the SMU crossbar | 2 |
| `SMU-AXI-DECODE-ERR` | Unmatched ext_in accesses decode-error; unmatched sep_out/smc_out fall through to ext_out default | 2 |
| `SMU-AXI-ATOP` | SMU crossbar configures ATOPs=0 so AXI atomic operations are unsupported/rejected | 1 |
| `SMU-AXI-ID-WIDTH` | Crossbar ID path 8-bit max input to 10-bit crossbar to 6-bit SMC/SEP outputs is converted | 2 |
| `SMU-SEP-SMC-ALIAS` | Fixed SEP_SMC_REGION_BASE 0x4000_0000 size 1GB remaps to 0x0 on a dedicated path bypassing the crossbar | 2 |
| `SMU-SEP-PARAM` | Compile-time SEP parameter selects real SEP+xbar versus SEP=0 tie-offs, OTP error slave, and lc_state default | 3 |
| `SMC-BOOT` | SMC boots from ROM, releases resets, runs firmware, and reports status via scratch/mailbox paths | 3 |
| `SEP-BOOT` | With SEP=1, real SEP RTL boots from TCM/ROM under SMU with reset release and observable CPU progress | 2 |
| `SMC-SEP-MAILBOX` | SMC and SEP exchange mailbox tokens/responses as the primary real interoperability path | 5 |
| `SMC-SEP-MBX-IRQ` | SEP mailbox interrupts enter SMC interrupt aggregation; SMC external mailbox interrupts export at SMU | 2 |
| `SEP-WDT-SMC` | SEP WDT timeout produces reset request / interrupt into SMC aggregation at SMU boundary | 1 |
| `DTP-JTAG-ACCESS` | Primary JTAG PTAP provides IDCODE/BYPASS and TAP state/instruction observability at SMU pads | 2 |
| `DTP-JTAG2AXI-SMC` | JTAG2AXI issues debug AXI traffic into SMC fabric subject to lifecycle gating | 2 |
| `DTP-OTP-JTAG` | DTP JTAG2AXI-Lite OTP bridges access SMC and SEP OTP debug ports, with SEP=0 error-slave substitution | 3 |
| `DTP-IC-RESET` | IC_RESET TDR override slices force SMC/SEP/external reset values when override enables are set | 2 |
| `DTP-BOOT-STALL` | JTAG boot-stall override holds or releases SMC boot progression under debug/test mode | 2 |
| `DTP-CLOCK-STOP` | JTAG DEBUG_CONTROL clock-stop OR-combined with CLA xtrig_clk_stop_req produces stop_clks_o; CLA-only status remains distinct | 4 |
| `DTP-XTRIG-CTM` | Cross-trigger matrix source/destination req/ack arrays are exported at SMU with DTP[1:0] reserved for SMC | 2 |
| `DTP-XTRIG-CTP` | CTP request/ack pad vectors support wire-OR and point-to-point signaling modes through SMU GPIO pad ring ports | 2 |
| `DTP-STAP-HOSTS` | DTP hosts SMC/SEP/IO/extra STAPs for debug TAP connectivity, gated by lifecycle/security disables | 2 |
| `SEP-FEAT-CTRL` | SEP feat_ctrl_o gates DTP debug resources and is consumed by SMC as lifecycle feature control | 3 |
| `SEP-LC-EXPORT` | SEP exports lc_state, demote states, lc_sigint_err, and security_disable through SMU boundary ports | 4 |
| `SMC-SEP-FUSE-SENSE` | SMC fuse_sense_done participates in SEP/SMC security bring-up handshake across the SMU | 2 |
| `SMC-FABRIC-PORTS` | SMC fabric managers/subordinates facing JTAG, SEP, and system AXI are reachable through SMU integration | 4 |
| `SEP-FABRIC-PORTS` | SEP inbound system interface and outbound SMC/SMN routing are exercised at the SMU integration boundary | 4 |
| `SMC-AXI-LITE-SHIMS` | SMC AXI-Lite external shims PLL/PVT/GPIO/eFuse/external are presented on SMU top ports | 2 |
| `DTP-IJTAG-SCAN` | DTP exports BSR and iJTAG DFD/DFT secure/non-secure/STAP scan host controls at SMU boundary | 2 |

## Interactions (SPEC-explicit crosses only)

| Key | Features | Intent |
|-----|----------|--------|
| `INT-SMC-SEP-MAILBOX-IRQ` | SMC-SEP-MAILBOX, SMC-SEP-MBX-IRQ | Mailbox data challenge-response and the SEP to SMC mailbox interrupt must occur together for real interop |
| `INT-FEAT-CTRL-DEBUG` | SEP-FEAT-CTRL, DTP-JTAG2AXI-SMC, DTP-STAP-HOSTS | SEP feat_ctrl must jointly gate DTP JTAG2AXI and STAP debug access |
| `INT-BOOT-STALL-SMC` | DTP-BOOT-STALL, SMC-BOOT | DTP boot-stall must hold and then release real SMC boot progression |
| `INT-CLK-STOP-SMC` | DTP-CLOCK-STOP, SMC-BOOT | DTP-SMC clock-stop handshake coordinates functional halt with SMC/CLA path |
| `INT-SEP0-OTP-ERR` | SMU-SEP-PARAM, DTP-OTP-JTAG | SEP=0 configuration must make SEP OTP-over-JTAG return the specified DECERR error-slave response |
| `INT-FUSE-SENSE-BOOT` | SMC-SEP-FUSE-SENSE, SMC-BOOT, SEP-BOOT | Fuse-sense handshake participates in SMC/SEP security bring-up before/with boot |
| `INT-XBAR-APERTURE-INTEROP` | SMU-AXI-APERTURE, SMC-SEP-MAILBOX, SMU-AXI-XBAR-CONNECTIVITY | Mailbox interop depends on crossbar connectivity plus programmed apertures |

## Folding notes

- CTP wire-OR vs P2P are folded into `DTP-XTRIG-CTP.S2` with both modes named in
  `required_cells` (count understates distinct pad protocol variants).
- SEP crypto/peripheral KATs that exist only as deep SEP-IP behaviors and are not
  restated as SMU-boundary producer→transport→consumer paths are omitted per
  boundary OUT (SEP boot/execute under SMU is retained as `SEP-BOOT`).
- SMC dual-network internal TileLink bridging is treated as SMC-internal unless
  exercised via SMU-facing ports (`SMC-FABRIC-PORTS`).

## Spec-audit cross-reference

Open questions from the same sealed read are recorded in
`SMU_ALL_SPEC_REVIEW_REVERSE_CANDIDATE.md` (candidate; does not overwrite any
approved SPEC_REVIEW). `affects.anchors` remain `[]` (seal intact).
