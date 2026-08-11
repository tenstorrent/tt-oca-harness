---
schema: dv-quality/v1
artifact: feature-list
artifact_revision: 1
content_sha256: a78ab08448e2271e9a4c9f9b4e85538f40fb53a553b5046d66d42732f8a5dcd4
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
features:
- key: SEP-COMPOSE-ENABLE
  title: SEP composed under SMU when SEP=1
  intent: With SEP=1 the real SEP block is instantiated under SMU and participates in SMU composition
  triad:
    producer: SMU build/config with SEP=1
    transport: SMU composition of u_sep beside SMC/DTP/xbar
    consumer: SEP ports and sysif become SMU-visible
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Architecture / Sub-Blocks / Feature 2@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  record_sha256: 593bb3645d08830e40c5ef2a615df461cfc426fc00a7c52f17635c690518460f
  scenarios:
  - key: SEP-COMPOSE-ENABLE.S1
    intent: SEP instance present and not tied-off under SEP=1
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Configuration Parameters SEP@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - sep1-composed
      random_knobs: []
      coverage_artifact: null
  - key: SEP-COMPOSE-ENABLE.S2
    intent: SEP=0 ties off SEP outputs and substitutes SEP-OTP error slave
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Architecture When SEP=0@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - sep0-tied-off
      random_knobs: []
      coverage_artifact: null
- key: SEP-RESET-CONTROL
  title: SMC-controlled SEP primary reset
  intent: SMC reset logic holds and releases the SEP primary reset at the SMU boundary
  triad:
    producer: powergood/cold-reset into SMC reset unit
    transport: rst_primary_smc_clk_no / sep reset chain into u_sep.rst_ni
    consumer: SEP CPU held out of / released into execution
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Clock and Reset@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  record_sha256: 1f8268de5cf155d1773542d6430d00ea9fb7a7c00cb92d8ea52a0bb48d81b6da
  scenarios:
  - key: SEP-RESET-CONTROL.S1
    intent: SEP held in reset while primary reset asserted
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Clock and Reset@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - held-reset
      random_knobs: []
      coverage_artifact: null
  - key: SEP-RESET-CONTROL.S2
    intent: SEP primary-reset release edge observed at SMU boundary
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Clock and Reset@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - release-edge
      random_knobs: []
      coverage_artifact: null
  - key: SEP-RESET-CONTROL.S3
    intent: SEP intermediate/cpu reset chain completes after primary release
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Clock and Reset@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - cpu-reset-chain
      random_knobs: []
      coverage_artifact: null
  - key: SEP-RESET-CONTROL.S4
    intent: Reset asserted mid post-release window completes or errors boundedly
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Clock and Reset@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - reset-mid-window
      random_knobs: []
      coverage_artifact: null
- key: SEP-FUSE-SENSE-HANDSHAKE
  title: SMC-SEP fuse-sense handshake
  intent: SMC fuse-sense completion crosses to SEP and SEP fuse-sense completion is exported at SMU
  triad:
    producer: SMC fuse sense FSM completion
    transport: smc_fuse_sense_done_i into SEP / sep_fuse_sense_done_o out of SMU
    consumer: SEP fuse controller / system integration observes ordered sense completion
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Security Considerations@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  record_sha256: d8e996b5ad73140af90a6532e608bb042b2cb4971b6df44af0be10f19717e079
  scenarios:
  - key: SEP-FUSE-SENSE-HANDSHAKE.S1
    intent: SMC fuse_sense_done authorizes SEP fuse path
    requires: LIVE
    spec_refs:
    - hw/sys/sep/doc/port_table.adoc smc_fuse_sense_done_i@2ecc7b227e3926b253c65b5aac21239eec24ba5f
    coverage:
      method: DIRECTED
      required_cells:
      - smc-fuse-done
      random_knobs: []
      coverage_artifact: null
  - key: SEP-FUSE-SENSE-HANDSHAKE.S2
    intent: SEP fuse_sense_done exported at SMU boundary
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/port_table.adoc sep_fuse_sense_done_o@2ecc7b227e3926b253c65b5aac21239eec24ba5f
    coverage:
      method: DIRECTED
      required_cells:
      - sep-fuse-done-export
      random_knobs: []
      coverage_artifact: null
- key: SEP-ROM-BOOT-ENABLE
  title: SEP fuse completion enables BL0 ROM fetch
  intent: After fuse sensing and memory-repair/bypass, SEP CPU is enabled and fetches BL0 from Boot ROM
  triad:
    producer: SEP fuse-sense / ext_boot_seq_done completion
    transport: SEP boot-path release into EL2
    consumer: SEP EL2 fetches and retires BL0 Boot ROM
  spec_refs:
  - hw/sys/sep/doc/periphs.adoc Fuse Controller (OTP)@2ecc7b227e3926b253c65b5aac21239eec24ba5f
  record_sha256: 272fc256421699b3de3449ba5d2afeb14ea3818f83574a2de7ebeccf891a5dde
  scenarios:
  - key: SEP-ROM-BOOT-ENABLE.S1
    intent: Post fuse-sense SEP retires BL0 at Boot ROM base
    requires: LIVE
    spec_refs:
    - hw/sys/sep/doc/cpu.adoc Boot ROM@2ecc7b227e3926b253c65b5aac21239eec24ba5f
    coverage:
      method: DIRECTED
      required_cells:
      - bl0-rom-fetch
      random_knobs: []
      coverage_artifact: null
  - key: SEP-ROM-BOOT-ENABLE.S2
    intent: ext_boot_seq_done gates reset release before first fetch
    requires: LIVE
    spec_refs:
    - hw/sys/sep/doc/port_table.adoc ext_boot_seq_done_i@2ecc7b227e3926b253c65b5aac21239eec24ba5f
    coverage:
      method: DIRECTED
      required_cells:
      - ext-boot-gate
      random_knobs: []
      coverage_artifact: null
- key: SEP-XBAR-SYSIF
  title: SEP sysif onto SMU AXI crossbar
  intent: SEP outbound/inbound AXI participates in the SMU 3x3 crossbar with ID-width conversion
  triad:
    producer: SEP smn/sysif AXI traffic
    transport: smu_axi_xbar sep_out/sep_in with iw converters
    consumer: SMC/external targets see correctly ID-converted SEP traffic
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Data Paths Crossbar routing@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  record_sha256: 6803551e97b6ffc1348ce4fe525e07ac3e175ec8ce7b11629e898fc218daf37e
  scenarios:
  - key: SEP-XBAR-SYSIF.S1
    intent: SEP-initiated access reaches SMC via xbar sep_out to smc_in
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Data Paths Crossbar routing@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - sep-to-smc-xbar
      random_knobs: []
      coverage_artifact: null
  - key: SEP-XBAR-SYSIF.S2
    intent: External/SMN access reaches SEP via xbar ext_in to sep_in
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Data Paths Crossbar routing@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - ext-to-sep-xbar
      random_knobs: []
      coverage_artifact: null
  - key: SEP-XBAR-SYSIF.S3
    intent: Crossbar 10-bit to SEP 6-bit ID conversion preserves response routing
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Specifications Crossbar ID widths@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - id-width-conv
      random_knobs: []
      coverage_artifact: null
- key: SEP-XBAR-APERTURE
  title: CSR-programmed SEP/SMC apertures on SMU xbar
  intent: SMU crossbar routes using CSR-programmed SEP and SMC apertures including global-base remap
  triad:
    producer: SMC aperture CSR programming
    transport: smu_axi_xbar addr_map from base/size CSRs
    consumer: SEP/SMC/ext decode follows programmed apertures
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Feature 4 AXI Crossbar Fabric@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  record_sha256: dd07d75454031c45fea758325512a949ac26f1aaf2e4b251c219346468234e6b
  scenarios:
  - key: SEP-XBAR-APERTURE.S1
    intent: Programmed SEP aperture admits intended SEP region decode
    requires: LIVE
    spec_refs:
    - hw/sys/sep/doc/fabric.adoc Address Remapping SEP_GLOBAL_BASE_ADDR@2ecc7b227e3926b253c65b5aac21239eec24ba5f
    coverage:
      method: DIRECTED
      required_cells:
      - sep-aperture-hit
      random_knobs: []
      coverage_artifact: null
  - key: SEP-XBAR-APERTURE.S2
    intent: Unmatched ext_in access returns DECERR (no default master)
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Error Handling Unmapped crossbar@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - ext-in-decerr
      random_knobs: []
      coverage_artifact: null
  - key: SEP-XBAR-APERTURE.S3
    intent: Aperture reprogram then MMIO after barrier uses new map
    requires: LIVE
    spec_refs:
    - hw/sys/sep/doc/fabric.adoc Address Remapping barrier recommended@2ecc7b227e3926b253c65b5aac21239eec24ba5f
    coverage:
      method: DIRECTED
      required_cells:
      - aperture-reprogram
      random_knobs: []
      coverage_artifact: null
- key: SEP-XBAR-CONNECTIVITY
  title: SMU xbar connectivity matrix for SEP ports
  intent: Crossbar connectivity forbids a master reaching its own inbound port; SEP reaches smc_in and
    ext_out only
  triad:
    producer: SEP/SMC/ext initiators
    transport: smu_axi_xbar connectivity matrix
    consumer: Illegal self-inbound path blocked; legal SEP targets reachable
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Data Paths Crossbar routing@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  record_sha256: dedc309e71c1553a8f1a56edbb375010779e9da130ab475469244ddd239d5e74
  scenarios:
  - key: SEP-XBAR-CONNECTIVITY.S1
    intent: sep_out reaches smc_in and ext_out only
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Data Paths Crossbar routing@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - sep-out-legal
      random_knobs: []
      coverage_artifact: null
  - key: SEP-XBAR-CONNECTIVITY.S2
    intent: sep_out cannot reach sep_in (no self inbound)
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Data Paths Crossbar routing@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - sep-no-self
      random_knobs: []
      coverage_artifact: null
  - key: SEP-XBAR-CONNECTIVITY.S3
    intent: ATOPs rejected when ATOPs disabled
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Error Handling AXI atomic@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - atop-reject
      random_knobs: []
      coverage_artifact: null
- key: SEP-SMC-ALIAS-REMAP
  title: SEP to SMC fixed alias remap bypassing xbar
  intent: Dedicated SEP-to-SMC path remaps fixed 0x4000_0000/1GB to 0x0, bypassing the crossbar
  triad:
    producer: SEP CPU/DMA access in SMC resource window 0x4000_0000
    transport: sep_ext_to_smc_axi + axi_window_remap
    consumer: SMC sep_axi_in sees aliased local/global SMC addresses
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Data Paths SEP to SMC alias remap@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  record_sha256: 419351617e64a231eea9e113df8b428175db05b546ddc9570d65502324f3cab9
  scenarios:
  - key: SEP-SMC-ALIAS-REMAP.S1
    intent: Access at 0x4000_0000+offset reaches SMC base+offset
    requires: LIVE
    spec_refs:
    - hw/sys/sep/doc/memory_map.adoc 0x4000_0000 SMC Resources@2ecc7b227e3926b253c65b5aac21239eec24ba5f
    coverage:
      method: DIRECTED
      required_cells:
      - alias-hit
      random_knobs: []
      coverage_artifact: null
  - key: SEP-SMC-ALIAS-REMAP.S2
    intent: Alias path bypasses smu_axi_xbar (dedicated port)
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/sep/doc/port_table.adoc sep_ext_to_smc_axi_req_o@2ecc7b227e3926b253c65b5aac21239eec24ba5f
    coverage:
      method: DIRECTED
      required_cells:
      - alias-bypass-xbar
      random_knobs: []
      coverage_artifact: null
  - key: SEP-SMC-ALIAS-REMAP.S3
    intent: SMC GLOBAL_BASE/REGION_SIZE aperture bounds SEP-to-SMC decode
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/fabric.adoc Traffic Routing GLOBAL_BASE REGION_SIZE@ffc8cdcc349e1e01a2b970442a01070b1c62c0d7
    coverage:
      method: DIRECTED
      required_cells:
      - smc-aperture-bound
      random_knobs: []
      coverage_artifact: null
- key: SEP-MAILBOX-IRQ-TO-SMC
  title: SEP mailbox interrupts cross into SMC
  intent: SEP mailbox events raise smc_mailbox_interrupt_o which SMC maps into CPU interrupt space
  triad:
    producer: SEP mailbox write event
    transport: smc_mailbox_interrupt_o into SMC sep_mailbox_interrupts_i
    consumer: SMC CPU interrupt aggregator sees SEP mailbox IRQs at documented IDs
  spec_refs:
  - hw/sys/smc/doc/interrupts.adoc SEP mailbox interrupt 0@2f40548ea787240680a1c45ab75b8729e9620778
  record_sha256: 54cc7d29092c7fd6e057bb24bc05f3a03e154ed28822e77dd7686d6eeaaf2597
  scenarios:
  - key: SEP-MAILBOX-IRQ-TO-SMC.S1
    intent: SEP mailbox channel interrupt asserts corresponding SMC IRQ bit
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/interrupts.adoc SEP mailbox interrupt 0-7@2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - mbx-irq-assert
      random_knobs: []
      coverage_artifact: null
  - key: SEP-MAILBOX-IRQ-TO-SMC.S2
    intent: Cleared/idle mailbox leaves corresponding SMC IRQ deasserted
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/interrupts.adoc SEP mailbox interrupt 0-7@2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - mbx-irq-clear
      random_knobs: []
      coverage_artifact: null
  - key: SEP-MAILBOX-IRQ-TO-SMC.S3
    intent: Multi-channel representative of 8 IRQ fan-out
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Specifications SEP mailboxes equals 8@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - mbx-irq-multi
      random_knobs: []
      coverage_artifact: null
- key: SEP-MAILBOX-DATA-EXCHANGE
  title: SMC-SEP mailbox challenge-response data path
  intent: SMC and SEP exchange mailbox payload words as the primary real interoperability path
  triad:
    producer: SMC outbound mailbox write / SEP inbound read
    transport: SMC-SEP mailbox inbox/outbox pair
    consumer: Complement/response observable in peer mailbox
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Data Paths Mailbox challenge-response@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  record_sha256: d34fb33bc0d03ce1a869815560cc3d3d167555794662fcd33656426ce566d155
  scenarios:
  - key: SEP-MAILBOX-DATA-EXCHANGE.S1
    intent: SMC to SEP token write is readable on SEP inbound mailbox
    requires: LIVE
    spec_refs:
    - hw/sys/sep/doc/fabric.adoc Mailboxes@2ecc7b227e3926b253c65b5aac21239eec24ba5f
    coverage:
      method: DIRECTED
      required_cells:
      - smc-to-sep-payload
      random_knobs: []
      coverage_artifact: null
  - key: SEP-MAILBOX-DATA-EXCHANGE.S2
    intent: SEP to SMC response write is readable on SMC mailbox
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Feature 5 SMC-SEP Interoperability@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - sep-to-smc-payload
      random_knobs: []
      coverage_artifact: null
  - key: SEP-MAILBOX-DATA-EXCHANGE.S3
    intent: 64-bit mailbox word accessible as two 32-bit halves from SEP
    requires: DECODE
    spec_refs:
    - hw/sys/sep/doc/fabric.adoc Mailboxes 64-bit data@2ecc7b227e3926b253c65b5aac21239eec24ba5f
    coverage:
      method: DIRECTED
      required_cells:
      - mbx-64b-halves
      random_knobs: []
      coverage_artifact: null
- key: SEP-FEAT-CTRL-EXPORT
  title: SEP feat_ctrl export at SMU boundary
  intent: SEP LCC drives feat_ctrl_o into SMC and DTP to gate debug/test/function features
  triad:
    producer: SEP LCC / OTP shadow LC+disable vectors
    transport: feat_ctrl_o across SMU to SMC/DTP
    consumer: Downstream consumers observe feature-control vector matching LC profile
  spec_refs:
  - hw/sys/sep/doc/lifecycle_controller.adoc Life Cycle Controller (LCC)@2ecc7b227e3926b253c65b5aac21239eec24ba5f
  record_sha256: fabc80e742f78a6d55147b2f3c71c91c039c6a746437400ebb867bc30e19969b
  scenarios:
  - key: SEP-FEAT-CTRL-EXPORT.S1
    intent: feat_ctrl_o reflects OTP-derived LC feature profile at SMU
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Feature 7 Lifecycle and Security@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - feat-ctrl-profile
      random_knobs: []
      coverage_artifact: null
  - key: SEP-FEAT-CTRL-EXPORT.S2
    intent: Signal-integrity fail-closed forces feat_ctrl_o to 0
    requires: LIVE
    spec_refs:
    - hw/sys/sep/doc/lifecycle_controller.adoc Detect signal-integrity errors@2ecc7b227e3926b253c65b5aac21239eec24ba5f
    coverage:
      method: DIRECTED
      required_cells:
      - feat-ctrl-fail-closed
      random_knobs: []
      coverage_artifact: null
  - key: SEP-FEAT-CTRL-EXPORT.S3
    intent: Demote CSRs alter exported feat_ctrl profile without changing OTP LC_STATE
    requires: LIVE
    spec_refs:
    - hw/sys/sep/doc/lifecycle_controller.adoc Demotion 1 and Demotion 2@2ecc7b227e3926b253c65b5aac21239eec24ba5f
    coverage:
      method: DIRECTED
      required_cells:
      - feat-ctrl-demote
      random_knobs: []
      coverage_artifact: null
- key: SEP-LC-STATE-EXPORT
  title: Lifecycle state export at SMU boundary
  intent: SEP drives differentially encoded lc_state_o and demote state visible at SMU outputs
  triad:
    producer: SEP LCC LC_STATE shadow
    transport: lc_state_o / lcc_demote_state across SMU
    consumer: External/SMC observers see encoded LC state; SEP=0 yields 8'hf0
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Interfaces Lifecycle / feature control@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  record_sha256: 3d26930660b0e84a471cbb050d9c336a18d8b39bcfc6e90b34148b9a78755477
  scenarios:
  - key: SEP-LC-STATE-EXPORT.S1
    intent: SEP=1 lc_state_o tracks SEP LCC encoded state
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/port_table.adoc lc_state_o@2ecc7b227e3926b253c65b5aac21239eec24ba5f
    coverage:
      method: DIRECTED
      required_cells:
      - lc-state-sep1
      random_knobs: []
      coverage_artifact: null
  - key: SEP-LC-STATE-EXPORT.S2
    intent: SEP=0 lc_state_o is 8'hf0
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Security Considerations SEP=0@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - lc-state-sep0
      random_knobs: []
      coverage_artifact: null
  - key: SEP-LC-STATE-EXPORT.S3
    intent: lcc_demote_state_1/2 exported at SMU
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/sep/doc/port_table.adoc lcc_demote_state_1_o@2ecc7b227e3926b253c65b5aac21239eec24ba5f
    coverage:
      method: DIRECTED
      required_cells:
      - demote-export
      random_knobs: []
      coverage_artifact: null
- key: SEP-SECURITY-DISABLE-EXPORT
  title: Security-disable export and token digest binding
  intent: SEP security_disable_o is exported to SMC; SMU binds SEP_SEC_DISABLE_TOKEN digest into SEP
  triad:
    producer: SEC_DIS token match / security-disable logic
    transport: security_disable_o and SEP_SEC_DISABLE_TOKEN parameter
    consumer: SMC observes security_disable; token digest path enables SEC_DIS override rules
  spec_refs:
  - hw/sys/sep/doc/security_disable.adoc Security Disable (SEC_DIS)@2ecc7b227e3926b253c65b5aac21239eec24ba5f
  record_sha256: d7923bd8bda567565953b9bb06c483508c102684f18cfc05323aa6f070fa0f76
  scenarios:
  - key: SEP-SECURITY-DISABLE-EXPORT.S1
    intent: security_disable_o visible at SMU/SMC boundary
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/sep/doc/port_table.adoc security_disable_o@2ecc7b227e3926b253c65b5aac21239eec24ba5f
    coverage:
      method: DIRECTED
      required_cells:
      - sec-dis-export
      random_knobs: []
      coverage_artifact: null
  - key: SEP-SECURITY-DISABLE-EXPORT.S2
    intent: Matching SEC_DIS token overrides LC feature control per LCC rules
    requires: LIVE
    spec_refs:
    - hw/sys/sep/doc/security_disable.adoc SEC_DIS activated by secret token@2ecc7b227e3926b253c65b5aac21239eec24ba5f
    coverage:
      method: DIRECTED
      required_cells:
      - sec-dis-token-match
      random_knobs: []
      coverage_artifact: null
  - key: SEP-SECURITY-DISABLE-EXPORT.S3
    intent: Non-matching token leaves security-disable inactive
    requires: LIVE
    spec_refs:
    - hw/sys/sep/doc/token_processing.adoc Token Matching@2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - sec-dis-token-mismatch
      random_knobs: []
      coverage_artifact: null
- key: SEP-TEST-MODE-SECURE-TM
  title: SECURE_TM latch from TEST_EN
  intent: TEST_EN strap latched at fuse-sense-done or cold-reset if SEC_DIS becomes SECURE_TM qualifying
    test enables
  triad:
    producer: TEST_EN strap / SEC_DIS condition
    transport: SEP test-mode latch into SECURE_TM
    consumer: Test feature enables to TAP qualified by SECURE_TM equals 1
  spec_refs:
  - hw/sys/sep/doc/test_mode.adoc Test Mode Entry@2ecc7b227e3926b253c65b5aac21239eec24ba5f
  record_sha256: f34d0f66eb57cf77013a4b870ca8809deff163159dcd48b958d3dbd035520a77
  scenarios:
  - key: SEP-TEST-MODE-SECURE-TM.S1
    intent: TEST_EN latched at fuse-sense-done when SEC_DIS inactive
    requires: LIVE
    spec_refs:
    - hw/sys/sep/doc/test_mode.adoc TEST_EN latched when SEP fuse sensing is done@2ecc7b227e3926b253c65b5aac21239eec24ba5f
    coverage:
      method: DIRECTED
      required_cells:
      - tm-latch-fuse
      random_knobs: []
      coverage_artifact: null
  - key: SEP-TEST-MODE-SECURE-TM.S2
    intent: SECURE_TM cleared only by chip reset
    requires: LIVE
    spec_refs:
    - hw/sys/sep/doc/test_mode.adoc latched SECURE_TM cleared by chip reset@2ecc7b227e3926b253c65b5aac21239eec24ba5f
    coverage:
      method: DIRECTED
      required_cells:
      - tm-clear-reset
      random_knobs: []
      coverage_artifact: null
- key: SEP-WDT-RESET-TO-SMC
  title: SEP WDT bite/reset indication into SMC
  intent: SEP WDT second-stage bite asserts reset request that SMC aggregates as SEP watchdog indication
  triad:
    producer: SEP aon_timer WDT second timeout
    transport: wdt_timer_rst_req / sep_wdt_reset into SMC peripheral_interrupts
    consumer: SMC CPU interrupt path sees SEP watchdog reset indication
  spec_refs:
  - hw/sys/sep/doc/periphs.adoc Watchdog Timer (WDT)@2ecc7b227e3926b253c65b5aac21239eec24ba5f
  record_sha256: 367828f7cc4a3893858ad3b5231b7cca18df7b2afc6c500d88b54bb685552839
  scenarios:
  - key: SEP-WDT-RESET-TO-SMC.S1
    intent: WDT bite asserts SMC SEP-watchdog interrupt path
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/interrupts.adoc SEP watchdog reset@2f40548ea787240680a1c45ab75b8729e9620778
    coverage:
      method: DIRECTED
      required_cells:
      - wdt-bite-irq
      random_knobs: []
      coverage_artifact: null
  - key: SEP-WDT-RESET-TO-SMC.S2
    intent: WDT bark interrupt is distinct from bite reset request
    requires: LIVE
    spec_refs:
    - hw/sys/sep/doc/periphs.adoc intr_wdog_timer_bark_o vs wdt_timer_rst_req_o@2ecc7b227e3926b253c65b5aac21239eec24ba5f
    coverage:
      method: DIRECTED
      required_cells:
      - wdt-bark-vs-bite
      random_knobs: []
      coverage_artifact: null
  - key: SEP-WDT-RESET-TO-SMC.S3
    intent: WDT domain uses clk_sep_wdt_i at SMU
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Clock and Reset SEP WDT@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - wdt-clock-domain
      random_knobs: []
      coverage_artifact: null
- key: SEP-MEMORY-PORT-OBS
  title: SEP memory macro ports observable at SMU
  intent: SEP TCM/SRAM/Boot-ROM request/response ports passthrough the SMU wrapper for integration memories
  triad:
    producer: SEP CPU/LSU/IFI memory accesses
    transport: sep_cpu_tcm / sep_sram / sep_boot_rom ports at SMU
    consumer: External memory models respond; SEP observes correct data path at boundary
  spec_refs:
  - hw/sys/smu/doc/port_table.adoc sep_cpu_tcm_req_o@2ecc7b227e3926b253c65b5aac21239eec24ba5f
  record_sha256: 5c891fa82520f1a4614fec2a61c06d149824a9c8bc00428792a229527c9f99ea
  scenarios:
  - key: SEP-MEMORY-PORT-OBS.S1
    intent: ICCM/DCCM TCM port activity during SEP execution
    requires: LIVE
    spec_refs:
    - hw/sys/sep/doc/memory_map.adoc ICCM DCCM@2ecc7b227e3926b253c65b5aac21239eec24ba5f
    coverage:
      method: DIRECTED
      required_cells:
      - tcm-activity
      random_knobs: []
      coverage_artifact: null
  - key: SEP-MEMORY-PORT-OBS.S2
    intent: Scratch SRAM port activity for SEP-local SRAM window
    requires: LIVE
    spec_refs:
    - hw/sys/sep/doc/memory_map.adoc Scratch SRAM@2ecc7b227e3926b253c65b5aac21239eec24ba5f
    coverage:
      method: DIRECTED
      required_cells:
      - sram-activity
      random_knobs: []
      coverage_artifact: null
  - key: SEP-MEMORY-PORT-OBS.S3
    intent: Boot ROM port serves BL0 fetch window
    requires: LIVE
    spec_refs:
    - hw/sys/sep/doc/memory_map.adoc BL0 ROM@2ecc7b227e3926b253c65b5aac21239eec24ba5f
    coverage:
      method: DIRECTED
      required_cells:
      - rom-port
      random_knobs: []
      coverage_artifact: null
- key: SEP-CRYPTO-PORT-OBS
  title: SEP crypto/KM/OTBN ports observable at SMU
  intent: AES/OTBN/KM memory and CSR paths that appear at SMU integration ports are exercisable
  triad:
    producer: SEP CPU/DMA programmed crypto ops
    transport: crypto AXI decode + KM/OTBN SRAM ports at SMU
    consumer: Boundary-visible crypto completion/status without deep algorithm proof
  spec_refs:
  - hw/sys/sep/doc/crypto.adoc Cryptographic Subsystem@06ed854b2f40c7a31468fdcd6e535d21378ede5e
  record_sha256: 1df619920aead6f374e27217807bb30c2e4f5a8fc2a312d0abbfa52c9fef27c8
  scenarios:
  - key: SEP-CRYPTO-PORT-OBS.S1
    intent: AES CSR window reachable and completes a boundary-visible op
    requires: LIVE
    spec_refs:
    - hw/sys/sep/doc/memory_map.adoc AES 0x1091_0000@2ecc7b227e3926b253c65b5aac21239eec24ba5f
    coverage:
      method: DIRECTED
      required_cells:
      - aes-csr-op
      random_knobs: []
      coverage_artifact: null
  - key: SEP-CRYPTO-PORT-OBS.S2
    intent: OTBN IMEM/DMEM ports toggle under a programmed execute flow
    requires: LIVE
    spec_refs:
    - hw/sys/sep/doc/crypto.adoc OTBN PKA@06ed854b2f40c7a31468fdcd6e535d21378ede5e
    coverage:
      method: DIRECTED
      required_cells:
      - otbn-mem-ports
      random_knobs: []
      coverage_artifact: null
  - key: SEP-CRYPTO-PORT-OBS.S3
    intent: KM ROM/SRAM ports observable at SMU passthrough
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/port_table.adoc sep_km_rom_mem_req_o@2ecc7b227e3926b253c65b5aac21239eec24ba5f
    coverage:
      method: DIRECTED
      required_cells:
      - km-mem-ports
      random_knobs: []
      coverage_artifact: null
- key: SEP-DMA-PORT-OBS
  title: SEP DMA engine observable at SMU fabric boundary
  intent: SEP DMA CSR programming moves data on SEP fabric paths visible at SMU-integrated memories
  triad:
    producer: SEP CPU programs DMA CSR
    transport: DMA master on SEP AXI fabric to TCM/SRAM/extension
    consumer: Completed DMA transfer observed in destination memory at boundary
  spec_refs:
  - hw/sys/sep/doc/memory_map.adoc DMA CSR 0x1080_0000@2ecc7b227e3926b253c65b5aac21239eec24ba5f
  record_sha256: ef1c98e8c3d298dbcdc929a51aa361a3dbfe0308be753dcaee510d3b72d9c85e
  scenarios:
  - key: SEP-DMA-PORT-OBS.S1
    intent: DMA CSR decode and kickoff from SEP
    requires: LIVE
    spec_refs:
    - hw/sys/sep/doc/fabric.adoc Top Level AXI4 DMA master@2ecc7b227e3926b253c65b5aac21239eec24ba5f
    coverage:
      method: DIRECTED
      required_cells:
      - dma-csr
      random_knobs: []
      coverage_artifact: null
  - key: SEP-DMA-PORT-OBS.S2
    intent: DMA preload into CPU TCM backdoor path completes
    requires: LIVE
    spec_refs:
    - hw/sys/sep/doc/fabric.adoc CPU TCM backdoor AXI path@2ecc7b227e3926b253c65b5aac21239eec24ba5f
    coverage:
      method: DIRECTED
      required_cells:
      - dma-tcm-preload
      random_knobs: []
      coverage_artifact: null
- key: SEP-SPI-PORT-OBS
  title: SEP SPI host port and IRQ mux at SMU
  intent: SEP SPI host request/response and muxed SPI IRQ are visible at SMU boundary
  triad:
    producer: SEP CPU SPI programming
    transport: sep_io_spi / ot_spi_irq_o / spi_irq_i at SMU
    consumer: SPI pad-facing traffic or IRQ observed at boundary
  spec_refs:
  - hw/sys/sep/doc/periphs.adoc Serial Peripheral Interface (SPI)@2ecc7b227e3926b253c65b5aac21239eec24ba5f
  record_sha256: c1c2b825c755abadd9b3256d95b803f9bdb7777380f0982aa27fa10a971d47e6
  scenarios:
  - key: SEP-SPI-PORT-OBS.S1
    intent: SPI host CSR window reachable and drives sep_io_spi_req_o
    requires: LIVE
    spec_refs:
    - hw/sys/sep/doc/port_table.adoc sep_io_spi_req_o@2ecc7b227e3926b253c65b5aac21239eec24ba5f
    coverage:
      method: DIRECTED
      required_cells:
      - spi-req
      random_knobs: []
      coverage_artifact: null
  - key: SEP-SPI-PORT-OBS.S2
    intent: Muxed SPI IRQ appears on SMU spi_irq path
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/port_table.adoc spi_irq_i ot_spi_irq_o@2ecc7b227e3926b253c65b5aac21239eec24ba5f
    coverage:
      method: DIRECTED
      required_cells:
      - spi-irq-mux
      random_knobs: []
      coverage_artifact: null
- key: SEP-EFUSE-PORT-OBS
  title: SEP eFuse bank/command ports at SMU
  intent: SEP eFuse AXI-Lite bank control and fuse command interfaces passthrough SMU to the eFuse shim
  triad:
    producer: SEP OTP/fuse controller transactions
    transport: sep_efuse_bank_ctrl / sep_efuse_shim_command at SMU
    consumer: eFuse shim responds; shadow/sense side effects observable per fuse chapter
  spec_refs:
  - hw/sys/sep/doc/periphs.adoc Fuse Controller (OTP)@2ecc7b227e3926b253c65b5aac21239eec24ba5f
  record_sha256: 2aa7850c3899d67464afc8c410304cac2efa381177d75f30918e1a94ec807e90
  scenarios:
  - key: SEP-EFUSE-PORT-OBS.S1
    intent: eFuse bank-control AXI-Lite transaction completes at boundary
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/port_table.adoc sep_efuse_bank_ctrl_req_o@2ecc7b227e3926b253c65b5aac21239eec24ba5f
    coverage:
      method: DIRECTED
      required_cells:
      - efuse-bank
      random_knobs: []
      coverage_artifact: null
  - key: SEP-EFUSE-PORT-OBS.S2
    intent: eFuse command interface handshake completes
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/port_table.adoc sep_efuse_shim_command_req_o@2ecc7b227e3926b253c65b5aac21239eec24ba5f
    coverage:
      method: DIRECTED
      required_cells:
      - efuse-cmd
      random_knobs: []
      coverage_artifact: null
  - key: SEP-EFUSE-PORT-OBS.S3
    intent: JTAG OTP debug AXI-Lite path into SEP eFuse
    requires: LIVE
    spec_refs:
    - hw/sys/sep/doc/port_table.adoc axil_sep_otp_jtag_req_i@2ecc7b227e3926b253c65b5aac21239eec24ba5f
    coverage:
      method: DIRECTED
      required_cells:
      - efuse-jtag-otp
      random_knobs: []
      coverage_artifact: null
- key: SEP-INBOUND-FILTER
  title: SEP inbound traffic filter at system interface
  intent: Inbound filter is block-by-default after POR; only SEP CPU programs allow rules by addr/NS/source
    ID
  triad:
    producer: External/SMN inbound master
    transport: smn_inbound + inbound traffic filter
    consumer: Blocked addresses get filter deny response; allowed addresses reach SEP targets
  spec_refs:
  - hw/sys/sep/doc/fabric.adoc System Interface initiator / inbound filter@2ecc7b227e3926b253c65b5aac21239eec24ba5f
  record_sha256: d3ef4e66aca2588c5c1cedcabcb5bedeb8b2fcf9d022a9ccf3a1c5821cb56943
  scenarios:
  - key: SEP-INBOUND-FILTER.S1
    intent: Post-POR inbound default deny blocks unprogrammed address
    requires: LIVE
    spec_refs:
    - hw/sys/sep/doc/fabric.adoc block-by-default after POR@2ecc7b227e3926b253c65b5aac21239eec24ba5f
    coverage:
      method: DIRECTED
      required_cells:
      - inbound-default-deny
      random_knobs: []
      coverage_artifact: null
  - key: SEP-INBOUND-FILTER.S2
    intent: SEP-programmed allow rule admits matching inbound transaction
    requires: LIVE
    spec_refs:
    - hw/sys/sep/doc/fabric.adoc filters based on address NS source ID@2ecc7b227e3926b253c65b5aac21239eec24ba5f
    coverage:
      method: DIRECTED
      required_cells:
      - inbound-allow
      random_knobs: []
      coverage_artifact: null
  - key: SEP-INBOUND-FILTER.S3
    intent: STEE-only access rule for STEE remapper region
    requires: LIVE
    spec_refs:
    - hw/sys/sep/doc/fabric.adoc inbound filter ensures only STEE has access to STEE remapper@2ecc7b227e3926b253c65b5aac21239eec24ba5f
    coverage:
      method: DIRECTED
      required_cells:
      - inbound-stee
      random_knobs: []
      coverage_artifact: null
- key: SEP-OUTBOUND-DEMUX
  title: SEP outbound demux to SMC vs SMN
  intent: SEP outbound routing distinguishes SMC-neighbor path vs SMN/NoC path after local/alias decode
  triad:
    producer: SEP CPU/DMA outbound address
    transport: system peripherals outbound demux
    consumer: Transaction appears on sep_ext_to_smc or smn_outbound as selected by address map
  spec_refs:
  - hw/sys/sep/doc/fabric.adoc Transaction Routing@2ecc7b227e3926b253c65b5aac21239eec24ba5f
  record_sha256: 7e578d0fd4f35a21ed2ea7e0db8a1437bf74c9d38718eeb4b37ab48378152aa2
  scenarios:
  - key: SEP-OUTBOUND-DEMUX.S1
    intent: SMC-window address emerges on sep_ext_to_smc path
    requires: LIVE
    spec_refs:
    - hw/sys/sep/doc/memory_map.adoc 0x4000_0000 SMC@2ecc7b227e3926b253c65b5aac21239eec24ba5f
    coverage:
      method: DIRECTED
      required_cells:
      - demux-to-smc
      random_knobs: []
      coverage_artifact: null
  - key: SEP-OUTBOUND-DEMUX.S2
    intent: Non-SMC external address emerges on smn_outbound
    requires: LIVE
    spec_refs:
    - hw/sys/sep/doc/fabric.adoc routed out to the SMN@2ecc7b227e3926b253c65b5aac21239eec24ba5f
    coverage:
      method: DIRECTED
      required_cells:
      - demux-to-smn
      random_knobs: []
      coverage_artifact: null
  - key: SEP-OUTBOUND-DEMUX.S3
    intent: Local SEP resource stays inside SEP
    requires: LIVE
    spec_refs:
    - hw/sys/sep/doc/memory_map.adoc SEP Local 0x1000_0000@2ecc7b227e3926b253c65b5aac21239eec24ba5f
    coverage:
      method: DIRECTED
      required_cells:
      - demux-local
      random_knobs: []
      coverage_artifact: null
- key: SEP-OUTBOUND-FILTER
  title: SEP outbound filter after remap
  intent: Outbound filter enforces address/NS/source-ID rules so source-ID others cannot access M-mode
    assets
  triad:
    producer: SEP outbound post-remap traffic
    transport: outbound filter
    consumer: Violating transactions filtered; conforming transactions pass
  spec_refs:
  - hw/sys/sep/doc/fabric.adoc outbound filter enables filtering based on address NS and source ID@2ecc7b227e3926b253c65b5aac21239eec24ba5f
  record_sha256: 56fc8fb472aad67392d6906e67a4766517357c6db5b923796a01b7e952cccf05
  scenarios:
  - key: SEP-OUTBOUND-FILTER.S1
    intent: Programmed deny rule blocks matching outbound transaction
    requires: LIVE
    spec_refs:
    - hw/sys/sep/doc/fabric.adoc outbound filter@2ecc7b227e3926b253c65b5aac21239eec24ba5f
    coverage:
      method: DIRECTED
      required_cells:
      - outbound-deny
      random_knobs: []
      coverage_artifact: null
  - key: SEP-OUTBOUND-FILTER.S2
    intent: Conforming source-ID/address passes outbound filter
    requires: LIVE
    spec_refs:
    - hw/sys/sep/doc/fabric.adoc outbound filter@2ecc7b227e3926b253c65b5aac21239eec24ba5f
    coverage:
      method: DIRECTED
      required_cells:
      - outbound-allow
      random_knobs: []
      coverage_artifact: null
  - key: SEP-OUTBOUND-FILTER.S3
    intent: SMC-egress vs filtered outbound path relationship requires exact SPEC answer
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Security Considerations open review ISSUE-16@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - outbound-smc-egress
      random_knobs: []
      coverage_artifact: null
- key: SEP-AP-STEE-REMAP
  title: AP/STEE controlled remap regions
  intent: Writes to AP/STEE remap windows are routed through the corresponding remappers with programmed
    attributes
  triad:
    producer: SEP CPU/DMA write to AP/STEE remap windows
    transport: AP/STEE remappers
    consumer: Remapped output address/cacheable attributes appear on outbound path
  spec_refs:
  - hw/sys/sep/doc/fabric.adoc Address Remapping Sixteen remap regions@2ecc7b227e3926b253c65b5aac21239eec24ba5f
  record_sha256: 26b6d07688e87e8bfa1d572b53b278c5a2617c2484955c14f8bcfde2d6628afe
  scenarios:
  - key: SEP-AP-STEE-REMAP.S1
    intent: Invalid-out-of-reset remapper behaves as transparent pass-through
    requires: LIVE
    spec_refs:
    - hw/sys/sep/doc/fabric.adoc programmable remap entries invalid out of reset@2ecc7b227e3926b253c65b5aac21239eec24ba5f
    coverage:
      method: DIRECTED
      required_cells:
      - remap-passthrough
      random_knobs: []
      coverage_artifact: null
  - key: SEP-AP-STEE-REMAP.S2
    intent: Programmed AP remap region translates input range to output offset
    requires: LIVE
    spec_refs:
    - hw/sys/sep/doc/memory_map.adoc AP Remap Region@2ecc7b227e3926b253c65b5aac21239eec24ba5f
    coverage:
      method: DIRECTED
      required_cells:
      - ap-remap
      random_knobs: []
      coverage_artifact: null
  - key: SEP-AP-STEE-REMAP.S3
    intent: Programmed STEE remap region translates with STEE qualification
    requires: LIVE
    spec_refs:
    - hw/sys/sep/doc/memory_map.adoc STEE Remap Region@2ecc7b227e3926b253c65b5aac21239eec24ba5f
    coverage:
      method: DIRECTED
      required_cells:
      - stee-remap
      random_knobs: []
      coverage_artifact: null
- key: SEP-AXI-EXTENSION
  title: SEP AXI extension port at SMU
  intent: SEP AXI extension region/master port is passthrough at SMU for adopter peripherals
  triad:
    producer: SEP access to extension region or extension master
    transport: sep_axi_extension at SMU
    consumer: Adopter peripheral model responds or DECERR if unused tie-off
  spec_refs:
  - hw/sys/sep/doc/memory_map.adoc AXI Extension Region@2ecc7b227e3926b253c65b5aac21239eec24ba5f
  record_sha256: 9182af7b28f2cf9b06b048438a96f8a9295aad2699443523c9da0470bf26a53a
  scenarios:
  - key: SEP-AXI-EXTENSION.S1
    intent: Extension port request toggles for in-window access
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/port_table.adoc sep_axi_extension_req_o@2ecc7b227e3926b253c65b5aac21239eec24ba5f
    coverage:
      method: DIRECTED
      required_cells:
      - ext-port-toggle
      random_knobs: []
      coverage_artifact: null
  - key: SEP-AXI-EXTENSION.S2
    intent: Unused extension response tie-off returns DECERR
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/port_table.adoc sep_axi_extension_resp_i Tie to DECERR@2ecc7b227e3926b253c65b5aac21239eec24ba5f
    coverage:
      method: DIRECTED
      required_cells:
      - ext-decerr
      random_knobs: []
      coverage_artifact: null
- key: SEP-DEBUG-BUS-EXPORT
  title: SEP external debug observation bus
  intent: SEP ext_debug_bus_o is exported for debug infrastructure observation at SMU
  triad:
    producer: SEP debug observation packing
    transport: ext_debug_bus_o
    consumer: Debug infrastructure observes non-X bus after SEP runs
  spec_refs:
  - hw/sys/sep/doc/port_table.adoc ext_debug_bus_o@2ecc7b227e3926b253c65b5aac21239eec24ba5f
  record_sha256: 6d9be9b9ad5264506793af96336e0558eaab834127832a78c3d8323f15fea976
  scenarios:
  - key: SEP-DEBUG-BUS-EXPORT.S1
    intent: Debug bus present and stable while SEP out of reset
    requires: CONNECTIVITY
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md CDC notes SEP debug bus@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - debug-bus-stable
      random_knobs: []
      coverage_artifact: null
- key: SEP-EXTERNAL-IRQ
  title: External interrupts into SEP PIC
  intent: External interrupt sources on extintsrc_req reach SEP PIC at SMU-visible integration
  triad:
    producer: External IRQ stimuli
    transport: extintsrc_req into SEP PIC
    consumer: SEP CPU takes interrupt / PIC pending reflects source
  spec_refs:
  - hw/sys/sep/doc/port_table.adoc extintsrc_req@2ecc7b227e3926b253c65b5aac21239eec24ba5f
  record_sha256: 0eebbf481d89fbe60ebfd674d8da636820600d408365b04ed377c1bf121e86e4
  scenarios:
  - key: SEP-EXTERNAL-IRQ.S1
    intent: Asserted external IRQ becomes pending in SEP PIC
    requires: LIVE
    spec_refs:
    - hw/sys/sep/doc/cpu.adoc PIC supporting external interrupts@2ecc7b227e3926b253c65b5aac21239eec24ba5f
    coverage:
      method: DIRECTED
      required_cells:
      - ext-irq-pending
      random_knobs: []
      coverage_artifact: null
  - key: SEP-EXTERNAL-IRQ.S2
    intent: Deassert/clear path clears pending
    requires: LIVE
    spec_refs:
    - hw/sys/sep/doc/cpu.adoc PIC@2ecc7b227e3926b253c65b5aac21239eec24ba5f
    coverage:
      method: DIRECTED
      required_cells:
      - ext-irq-clear
      random_knobs: []
      coverage_artifact: null
- key: SEP-IC-RESET-EXT-SLICE
  title: DTP IC_RESET external slice affecting SEP reset path
  intent: When JTAG IC_RESET is enabled, SMU exports jtag_ic_reset_ext override slice that can override
    SEP-related resets
  triad:
    producer: DTP IC_RESET TDR override
    transport: jtag_ic_reset_ext_o at SMU
    consumer: SEP reset path follows override value when override enable is set
  spec_refs:
  - hw/sys/smu/doc/port_table.adoc jtag_ic_reset_ext_o@2ecc7b227e3926b253c65b5aac21239eec24ba5f
  record_sha256: 492ddd6b55ec3c63eacf2224e56ae7480d1d9fc1279d6ea2bdb79336298c8a81
  scenarios:
  - key: SEP-IC-RESET-EXT-SLICE.S1
    intent: IC_RESET override asserts SEP-related reset slice
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Operating Modes Reset override@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - ic-reset-assert
      random_knobs: []
      coverage_artifact: null
  - key: SEP-IC-RESET-EXT-SLICE.S2
    intent: Clearing override restores normal SEP reset control
    requires: LIVE
    spec_refs:
    - hw/sys/smu/doc/SMU_SPEC.md Operating Modes Reset override@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
    coverage:
      method: DIRECTED
      required_cells:
      - ic-reset-release
      random_knobs: []
      coverage_artifact: null
interactions:
- key: INT-FUSE-AUTH-TO-ROM
  features:
  - SEP-FUSE-SENSE-HANDSHAKE
  - SEP-ROM-BOOT-ENABLE
  intent: SMC fuse-sense authorization precedes SEP fuse completion and first BL0 ROM fetch
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Security Considerations@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - hw/sys/sep/doc/periphs.adoc Fuse Controller (OTP)@2ecc7b227e3926b253c65b5aac21239eec24ba5f
  record_sha256: faec0bca7f44b2b15a0e5d91c7da28ac7b07aa32f7fe29eb5364149c7364f4dc
  requires: LIVE
  coverage:
    method: DIRECTED
    required_cells:
    - authorized-ordered-rom-fetch
    random_knobs: []
    coverage_artifact: null
- key: INT-ALIAS-MAILBOX
  features:
  - SEP-SMC-ALIAS-REMAP
  - SEP-MAILBOX-DATA-EXCHANGE
  intent: SEP reaches SMC mailbox region through the alias remap path for interop payload exchange
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md SEP to SMC alias remap@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - hw/sys/smu/doc/SMU_SPEC.md Mailbox challenge-response@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  record_sha256: a8ad7deb1dc1692af6c5e4092837566c7ccbe9b31d107016018cf1a5ec690f8f
  requires: LIVE
  coverage:
    method: DIRECTED
    required_cells:
    - alias-mailbox-exchange
    random_knobs: []
    coverage_artifact: null
- key: INT-FEAT-LC-HANDOFF
  features:
  - SEP-FEAT-CTRL-EXPORT
  - SEP-LC-STATE-EXPORT
  intent: Lifecycle state and feat_ctrl are exported together as the security handoff into SMC/DTP
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Feature 7 Lifecycle and Security@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  record_sha256: df9fd7eaf4357719a3eb1f419ac155b4be11fc9b814b4515d163fa2f97d9b9ec
  requires: LIVE
  coverage:
    method: DIRECTED
    required_cells:
    - lc-feat-handoff
    random_knobs: []
    coverage_artifact: null
---

# SMU_SEP — SPEC Feature List (candidate)

- IP: SMU_SEP · Milestone: P2 · Status: **candidate**
- Frozen at: 2026-08-07T17:45:00+08:00
- Provenance: sealed_derivation=false (pin_file.py validate dumped anchors before freeze); anchor_seal_mechanism=ordered-single-context; fresh_context_route=fresh-subagent

## Boundary (behaviors)

IN: SMU-level verification of the SEP block when composed under SMU (SEP=1) and the SMU-visible SEP↔SMC / SEP↔external behaviors named by the pinned SMU_SPEC + SEP docs + the SMC fabric/memmap/interrupt docs required for peer paths — SEP sysif onto the SMU AXI crossbar and apertures, SEP→SMC alias remap, mailbox/IRQ crossing to SMC, lifecycle/feat_ctrl/security-disable exports at the SMU boundary, fuse-sense handshake, WDT reset into SMC, SEP memory/crypto/DMA/SPI/eFuse port behaviors observable at SMU, and SEP-side decode/filter/remap/outbound demux effects that the SMU integration boundary can exercise. This pin closes P0–P2 scenarios (milestone P2); P3 corner/stress remains OUT-OF-MILESTONE unless later re-pinned.

OUT: deep SEP-internal crypto/CPU behaviors that never appear at the SMU boundary; pure SMC-only and DTP-only paths (except where a SEP peer leg is required); DV/VPLAN/testplan/testlist prose; generated register adoc; RTL-as-spec; threat-model prose without a producer→transport→consumer triad.

## Features

### Bring-up / reset / fuse

**SEP-COMPOSE-ENABLE — SEP composed under SMU when SEP=1:** With SEP=1 the real SEP block is instantiated under SMU and participates in SMU composition
  - Spec: hw/sys/smu/doc/SMU_SPEC.md Architecture / Sub-Blocks / Feature 2@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - Triad: producer SMU build/config with SEP=1 | transport SMU composition of u_sep beside SMC/DTP/xbar | consumer SEP ports and sysif become SMU-visible
  - Required scenarios:
    - SEP-COMPOSE-ENABLE.S1 [REQUIRES: CONNECTIVITY]: SEP instance present and not tied-off under SEP=1
      SPEC: hw/sys/smu/doc/SMU_SPEC.md Configuration Parameters SEP@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
      COVERAGE: {method: DIRECTED, required_cells: ['sep1-composed'], random_knobs: [], coverage_artifact: None}
    - SEP-COMPOSE-ENABLE.S2 [REQUIRES: CONNECTIVITY]: SEP=0 ties off SEP outputs and substitutes SEP-OTP error slave
      SPEC: hw/sys/smu/doc/SMU_SPEC.md Architecture When SEP=0@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
      COVERAGE: {method: DIRECTED, required_cells: ['sep0-tied-off'], random_knobs: [], coverage_artifact: None}

**SEP-RESET-CONTROL — SMC-controlled SEP primary reset:** SMC reset logic holds and releases the SEP primary reset at the SMU boundary
  - Spec: hw/sys/smu/doc/SMU_SPEC.md Clock and Reset@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - Triad: producer powergood/cold-reset into SMC reset unit | transport rst_primary_smc_clk_no / sep reset chain into u_sep.rst_ni | consumer SEP CPU held out of / released into execution
  - Required scenarios:
    - SEP-RESET-CONTROL.S1 [REQUIRES: LIVE]: SEP held in reset while primary reset asserted
      SPEC: hw/sys/smu/doc/SMU_SPEC.md Clock and Reset@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
      COVERAGE: {method: DIRECTED, required_cells: ['held-reset'], random_knobs: [], coverage_artifact: None}
    - SEP-RESET-CONTROL.S2 [REQUIRES: LIVE]: SEP primary-reset release edge observed at SMU boundary
      SPEC: hw/sys/smu/doc/SMU_SPEC.md Clock and Reset@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
      COVERAGE: {method: DIRECTED, required_cells: ['release-edge'], random_knobs: [], coverage_artifact: None}
    - SEP-RESET-CONTROL.S3 [REQUIRES: LIVE]: SEP intermediate/cpu reset chain completes after primary release
      SPEC: hw/sys/smu/doc/SMU_SPEC.md Clock and Reset@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
      COVERAGE: {method: DIRECTED, required_cells: ['cpu-reset-chain'], random_knobs: [], coverage_artifact: None}
    - SEP-RESET-CONTROL.S4 [REQUIRES: LIVE]: Reset asserted mid post-release window completes or errors boundedly
      SPEC: hw/sys/smu/doc/SMU_SPEC.md Clock and Reset@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
      COVERAGE: {method: DIRECTED, required_cells: ['reset-mid-window'], random_knobs: [], coverage_artifact: None}

**SEP-FUSE-SENSE-HANDSHAKE — SMC-SEP fuse-sense handshake:** SMC fuse-sense completion crosses to SEP and SEP fuse-sense completion is exported at SMU
  - Spec: hw/sys/smu/doc/SMU_SPEC.md Security Considerations@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - Triad: producer SMC fuse sense FSM completion | transport smc_fuse_sense_done_i into SEP / sep_fuse_sense_done_o out of SMU | consumer SEP fuse controller / system integration observes ordered sense completion
  - Required scenarios:
    - SEP-FUSE-SENSE-HANDSHAKE.S1 [REQUIRES: LIVE]: SMC fuse_sense_done authorizes SEP fuse path
      SPEC: hw/sys/sep/doc/port_table.adoc smc_fuse_sense_done_i@2ecc7b227e3926b253c65b5aac21239eec24ba5f
      COVERAGE: {method: DIRECTED, required_cells: ['smc-fuse-done'], random_knobs: [], coverage_artifact: None}
    - SEP-FUSE-SENSE-HANDSHAKE.S2 [REQUIRES: CONNECTIVITY]: SEP fuse_sense_done exported at SMU boundary
      SPEC: hw/sys/smu/doc/port_table.adoc sep_fuse_sense_done_o@2ecc7b227e3926b253c65b5aac21239eec24ba5f
      COVERAGE: {method: DIRECTED, required_cells: ['sep-fuse-done-export'], random_knobs: [], coverage_artifact: None}

**SEP-ROM-BOOT-ENABLE — SEP fuse completion enables BL0 ROM fetch:** After fuse sensing and memory-repair/bypass, SEP CPU is enabled and fetches BL0 from Boot ROM
  - Spec: hw/sys/sep/doc/periphs.adoc Fuse Controller (OTP)@2ecc7b227e3926b253c65b5aac21239eec24ba5f
  - Triad: producer SEP fuse-sense / ext_boot_seq_done completion | transport SEP boot-path release into EL2 | consumer SEP EL2 fetches and retires BL0 Boot ROM
  - Required scenarios:
    - SEP-ROM-BOOT-ENABLE.S1 [REQUIRES: LIVE]: Post fuse-sense SEP retires BL0 at Boot ROM base
      SPEC: hw/sys/sep/doc/cpu.adoc Boot ROM@2ecc7b227e3926b253c65b5aac21239eec24ba5f
      COVERAGE: {method: DIRECTED, required_cells: ['bl0-rom-fetch'], random_knobs: [], coverage_artifact: None}
    - SEP-ROM-BOOT-ENABLE.S2 [REQUIRES: LIVE]: ext_boot_seq_done gates reset release before first fetch
      SPEC: hw/sys/sep/doc/port_table.adoc ext_boot_seq_done_i@2ecc7b227e3926b253c65b5aac21239eec24ba5f
      COVERAGE: {method: DIRECTED, required_cells: ['ext-boot-gate'], random_knobs: [], coverage_artifact: None}

### AXI fabric / alias

**SEP-XBAR-SYSIF — SEP sysif onto SMU AXI crossbar:** SEP outbound/inbound AXI participates in the SMU 3x3 crossbar with ID-width conversion
  - Spec: hw/sys/smu/doc/SMU_SPEC.md Data Paths Crossbar routing@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - Triad: producer SEP smn/sysif AXI traffic | transport smu_axi_xbar sep_out/sep_in with iw converters | consumer SMC/external targets see correctly ID-converted SEP traffic
  - Required scenarios:
    - SEP-XBAR-SYSIF.S1 [REQUIRES: LIVE]: SEP-initiated access reaches SMC via xbar sep_out to smc_in
      SPEC: hw/sys/smu/doc/SMU_SPEC.md Data Paths Crossbar routing@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
      COVERAGE: {method: DIRECTED, required_cells: ['sep-to-smc-xbar'], random_knobs: [], coverage_artifact: None}
    - SEP-XBAR-SYSIF.S2 [REQUIRES: LIVE]: External/SMN access reaches SEP via xbar ext_in to sep_in
      SPEC: hw/sys/smu/doc/SMU_SPEC.md Data Paths Crossbar routing@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
      COVERAGE: {method: DIRECTED, required_cells: ['ext-to-sep-xbar'], random_knobs: [], coverage_artifact: None}
    - SEP-XBAR-SYSIF.S3 [REQUIRES: CONNECTIVITY]: Crossbar 10-bit to SEP 6-bit ID conversion preserves response routing
      SPEC: hw/sys/smu/doc/SMU_SPEC.md Specifications Crossbar ID widths@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
      COVERAGE: {method: DIRECTED, required_cells: ['id-width-conv'], random_knobs: [], coverage_artifact: None}

**SEP-XBAR-APERTURE — CSR-programmed SEP/SMC apertures on SMU xbar:** SMU crossbar routes using CSR-programmed SEP and SMC apertures including global-base remap
  - Spec: hw/sys/smu/doc/SMU_SPEC.md Feature 4 AXI Crossbar Fabric@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - Triad: producer SMC aperture CSR programming | transport smu_axi_xbar addr_map from base/size CSRs | consumer SEP/SMC/ext decode follows programmed apertures
  - Required scenarios:
    - SEP-XBAR-APERTURE.S1 [REQUIRES: LIVE]: Programmed SEP aperture admits intended SEP region decode
      SPEC: hw/sys/sep/doc/fabric.adoc Address Remapping SEP_GLOBAL_BASE_ADDR@2ecc7b227e3926b253c65b5aac21239eec24ba5f
      COVERAGE: {method: DIRECTED, required_cells: ['sep-aperture-hit'], random_knobs: [], coverage_artifact: None}
    - SEP-XBAR-APERTURE.S2 [REQUIRES: LIVE]: Unmatched ext_in access returns DECERR (no default master)
      SPEC: hw/sys/smu/doc/SMU_SPEC.md Error Handling Unmapped crossbar@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
      COVERAGE: {method: DIRECTED, required_cells: ['ext-in-decerr'], random_knobs: [], coverage_artifact: None}
    - SEP-XBAR-APERTURE.S3 [REQUIRES: LIVE]: Aperture reprogram then MMIO after barrier uses new map
      SPEC: hw/sys/sep/doc/fabric.adoc Address Remapping barrier recommended@2ecc7b227e3926b253c65b5aac21239eec24ba5f
      COVERAGE: {method: DIRECTED, required_cells: ['aperture-reprogram'], random_knobs: [], coverage_artifact: None}

**SEP-XBAR-CONNECTIVITY — SMU xbar connectivity matrix for SEP ports:** Crossbar connectivity forbids a master reaching its own inbound port; SEP reaches smc_in and ext_out only
  - Spec: hw/sys/smu/doc/SMU_SPEC.md Data Paths Crossbar routing@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - Triad: producer SEP/SMC/ext initiators | transport smu_axi_xbar connectivity matrix | consumer Illegal self-inbound path blocked; legal SEP targets reachable
  - Required scenarios:
    - SEP-XBAR-CONNECTIVITY.S1 [REQUIRES: LIVE]: sep_out reaches smc_in and ext_out only
      SPEC: hw/sys/smu/doc/SMU_SPEC.md Data Paths Crossbar routing@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
      COVERAGE: {method: DIRECTED, required_cells: ['sep-out-legal'], random_knobs: [], coverage_artifact: None}
    - SEP-XBAR-CONNECTIVITY.S2 [REQUIRES: LIVE]: sep_out cannot reach sep_in (no self inbound)
      SPEC: hw/sys/smu/doc/SMU_SPEC.md Data Paths Crossbar routing@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
      COVERAGE: {method: DIRECTED, required_cells: ['sep-no-self'], random_knobs: [], coverage_artifact: None}
    - SEP-XBAR-CONNECTIVITY.S3 [REQUIRES: LIVE]: ATOPs rejected when ATOPs disabled
      SPEC: hw/sys/smu/doc/SMU_SPEC.md Error Handling AXI atomic@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
      COVERAGE: {method: DIRECTED, required_cells: ['atop-reject'], random_knobs: [], coverage_artifact: None}

**SEP-SMC-ALIAS-REMAP — SEP to SMC fixed alias remap bypassing xbar:** Dedicated SEP-to-SMC path remaps fixed 0x4000_0000/1GB to 0x0, bypassing the crossbar
  - Spec: hw/sys/smu/doc/SMU_SPEC.md Data Paths SEP to SMC alias remap@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - Triad: producer SEP CPU/DMA access in SMC resource window 0x4000_0000 | transport sep_ext_to_smc_axi + axi_window_remap | consumer SMC sep_axi_in sees aliased local/global SMC addresses
  - Required scenarios:
    - SEP-SMC-ALIAS-REMAP.S1 [REQUIRES: LIVE]: Access at 0x4000_0000+offset reaches SMC base+offset
      SPEC: hw/sys/sep/doc/memory_map.adoc 0x4000_0000 SMC Resources@2ecc7b227e3926b253c65b5aac21239eec24ba5f
      COVERAGE: {method: DIRECTED, required_cells: ['alias-hit'], random_knobs: [], coverage_artifact: None}
    - SEP-SMC-ALIAS-REMAP.S2 [REQUIRES: CONNECTIVITY]: Alias path bypasses smu_axi_xbar (dedicated port)
      SPEC: hw/sys/sep/doc/port_table.adoc sep_ext_to_smc_axi_req_o@2ecc7b227e3926b253c65b5aac21239eec24ba5f
      COVERAGE: {method: DIRECTED, required_cells: ['alias-bypass-xbar'], random_knobs: [], coverage_artifact: None}
    - SEP-SMC-ALIAS-REMAP.S3 [REQUIRES: LIVE]: SMC GLOBAL_BASE/REGION_SIZE aperture bounds SEP-to-SMC decode
      SPEC: hw/sys/smc/doc/fabric.adoc Traffic Routing GLOBAL_BASE REGION_SIZE@ffc8cdcc349e1e01a2b970442a01070b1c62c0d7
      COVERAGE: {method: DIRECTED, required_cells: ['smc-aperture-bound'], random_knobs: [], coverage_artifact: None}

### Mailbox / IRQ

**SEP-MAILBOX-IRQ-TO-SMC — SEP mailbox interrupts cross into SMC:** SEP mailbox events raise smc_mailbox_interrupt_o which SMC maps into CPU interrupt space
  - Spec: hw/sys/smc/doc/interrupts.adoc SEP mailbox interrupt 0@2f40548ea787240680a1c45ab75b8729e9620778
  - Triad: producer SEP mailbox write event | transport smc_mailbox_interrupt_o into SMC sep_mailbox_interrupts_i | consumer SMC CPU interrupt aggregator sees SEP mailbox IRQs at documented IDs
  - Required scenarios:
    - SEP-MAILBOX-IRQ-TO-SMC.S1 [REQUIRES: LIVE]: SEP mailbox channel interrupt asserts corresponding SMC IRQ bit
      SPEC: hw/sys/smc/doc/interrupts.adoc SEP mailbox interrupt 0-7@2f40548ea787240680a1c45ab75b8729e9620778
      COVERAGE: {method: DIRECTED, required_cells: ['mbx-irq-assert'], random_knobs: [], coverage_artifact: None}
    - SEP-MAILBOX-IRQ-TO-SMC.S2 [REQUIRES: LIVE]: Cleared/idle mailbox leaves corresponding SMC IRQ deasserted
      SPEC: hw/sys/smc/doc/interrupts.adoc SEP mailbox interrupt 0-7@2f40548ea787240680a1c45ab75b8729e9620778
      COVERAGE: {method: DIRECTED, required_cells: ['mbx-irq-clear'], random_knobs: [], coverage_artifact: None}
    - SEP-MAILBOX-IRQ-TO-SMC.S3 [REQUIRES: LIVE]: Multi-channel representative of 8 IRQ fan-out
      SPEC: hw/sys/smu/doc/SMU_SPEC.md Specifications SEP mailboxes equals 8@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
      COVERAGE: {method: DIRECTED, required_cells: ['mbx-irq-multi'], random_knobs: [], coverage_artifact: None}

**SEP-MAILBOX-DATA-EXCHANGE — SMC-SEP mailbox challenge-response data path:** SMC and SEP exchange mailbox payload words as the primary real interoperability path
  - Spec: hw/sys/smu/doc/SMU_SPEC.md Data Paths Mailbox challenge-response@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - Triad: producer SMC outbound mailbox write / SEP inbound read | transport SMC-SEP mailbox inbox/outbox pair | consumer Complement/response observable in peer mailbox
  - Required scenarios:
    - SEP-MAILBOX-DATA-EXCHANGE.S1 [REQUIRES: LIVE]: SMC to SEP token write is readable on SEP inbound mailbox
      SPEC: hw/sys/sep/doc/fabric.adoc Mailboxes@2ecc7b227e3926b253c65b5aac21239eec24ba5f
      COVERAGE: {method: DIRECTED, required_cells: ['smc-to-sep-payload'], random_knobs: [], coverage_artifact: None}
    - SEP-MAILBOX-DATA-EXCHANGE.S2 [REQUIRES: LIVE]: SEP to SMC response write is readable on SMC mailbox
      SPEC: hw/sys/smu/doc/SMU_SPEC.md Feature 5 SMC-SEP Interoperability@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
      COVERAGE: {method: DIRECTED, required_cells: ['sep-to-smc-payload'], random_knobs: [], coverage_artifact: None}
    - SEP-MAILBOX-DATA-EXCHANGE.S3 [REQUIRES: DECODE]: 64-bit mailbox word accessible as two 32-bit halves from SEP
      SPEC: hw/sys/sep/doc/fabric.adoc Mailboxes 64-bit data@2ecc7b227e3926b253c65b5aac21239eec24ba5f
      COVERAGE: {method: DIRECTED, required_cells: ['mbx-64b-halves'], random_knobs: [], coverage_artifact: None}

### Lifecycle / security exports

**SEP-FEAT-CTRL-EXPORT — SEP feat_ctrl export at SMU boundary:** SEP LCC drives feat_ctrl_o into SMC and DTP to gate debug/test/function features
  - Spec: hw/sys/sep/doc/lifecycle_controller.adoc Life Cycle Controller (LCC)@2ecc7b227e3926b253c65b5aac21239eec24ba5f
  - Triad: producer SEP LCC / OTP shadow LC+disable vectors | transport feat_ctrl_o across SMU to SMC/DTP | consumer Downstream consumers observe feature-control vector matching LC profile
  - Required scenarios:
    - SEP-FEAT-CTRL-EXPORT.S1 [REQUIRES: LIVE]: feat_ctrl_o reflects OTP-derived LC feature profile at SMU
      SPEC: hw/sys/smu/doc/SMU_SPEC.md Feature 7 Lifecycle and Security@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
      COVERAGE: {method: DIRECTED, required_cells: ['feat-ctrl-profile'], random_knobs: [], coverage_artifact: None}
    - SEP-FEAT-CTRL-EXPORT.S2 [REQUIRES: LIVE]: Signal-integrity fail-closed forces feat_ctrl_o to 0
      SPEC: hw/sys/sep/doc/lifecycle_controller.adoc Detect signal-integrity errors@2ecc7b227e3926b253c65b5aac21239eec24ba5f
      COVERAGE: {method: DIRECTED, required_cells: ['feat-ctrl-fail-closed'], random_knobs: [], coverage_artifact: None}
    - SEP-FEAT-CTRL-EXPORT.S3 [REQUIRES: LIVE]: Demote CSRs alter exported feat_ctrl profile without changing OTP LC_STATE
      SPEC: hw/sys/sep/doc/lifecycle_controller.adoc Demotion 1 and Demotion 2@2ecc7b227e3926b253c65b5aac21239eec24ba5f
      COVERAGE: {method: DIRECTED, required_cells: ['feat-ctrl-demote'], random_knobs: [], coverage_artifact: None}

**SEP-LC-STATE-EXPORT — Lifecycle state export at SMU boundary:** SEP drives differentially encoded lc_state_o and demote state visible at SMU outputs
  - Spec: hw/sys/smu/doc/SMU_SPEC.md Interfaces Lifecycle / feature control@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - Triad: producer SEP LCC LC_STATE shadow | transport lc_state_o / lcc_demote_state across SMU | consumer External/SMC observers see encoded LC state; SEP=0 yields 8'hf0
  - Required scenarios:
    - SEP-LC-STATE-EXPORT.S1 [REQUIRES: CONNECTIVITY]: SEP=1 lc_state_o tracks SEP LCC encoded state
      SPEC: hw/sys/smu/doc/port_table.adoc lc_state_o@2ecc7b227e3926b253c65b5aac21239eec24ba5f
      COVERAGE: {method: DIRECTED, required_cells: ['lc-state-sep1'], random_knobs: [], coverage_artifact: None}
    - SEP-LC-STATE-EXPORT.S2 [REQUIRES: CONNECTIVITY]: SEP=0 lc_state_o is 8'hf0
      SPEC: hw/sys/smu/doc/SMU_SPEC.md Security Considerations SEP=0@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
      COVERAGE: {method: DIRECTED, required_cells: ['lc-state-sep0'], random_knobs: [], coverage_artifact: None}
    - SEP-LC-STATE-EXPORT.S3 [REQUIRES: CONNECTIVITY]: lcc_demote_state_1/2 exported at SMU
      SPEC: hw/sys/sep/doc/port_table.adoc lcc_demote_state_1_o@2ecc7b227e3926b253c65b5aac21239eec24ba5f
      COVERAGE: {method: DIRECTED, required_cells: ['demote-export'], random_knobs: [], coverage_artifact: None}

**SEP-SECURITY-DISABLE-EXPORT — Security-disable export and token digest binding:** SEP security_disable_o is exported to SMC; SMU binds SEP_SEC_DISABLE_TOKEN digest into SEP
  - Spec: hw/sys/sep/doc/security_disable.adoc Security Disable (SEC_DIS)@2ecc7b227e3926b253c65b5aac21239eec24ba5f
  - Triad: producer SEC_DIS token match / security-disable logic | transport security_disable_o and SEP_SEC_DISABLE_TOKEN parameter | consumer SMC observes security_disable; token digest path enables SEC_DIS override rules
  - Required scenarios:
    - SEP-SECURITY-DISABLE-EXPORT.S1 [REQUIRES: CONNECTIVITY]: security_disable_o visible at SMU/SMC boundary
      SPEC: hw/sys/sep/doc/port_table.adoc security_disable_o@2ecc7b227e3926b253c65b5aac21239eec24ba5f
      COVERAGE: {method: DIRECTED, required_cells: ['sec-dis-export'], random_knobs: [], coverage_artifact: None}
    - SEP-SECURITY-DISABLE-EXPORT.S2 [REQUIRES: LIVE]: Matching SEC_DIS token overrides LC feature control per LCC rules
      SPEC: hw/sys/sep/doc/security_disable.adoc SEC_DIS activated by secret token@2ecc7b227e3926b253c65b5aac21239eec24ba5f
      COVERAGE: {method: DIRECTED, required_cells: ['sec-dis-token-match'], random_knobs: [], coverage_artifact: None}
    - SEP-SECURITY-DISABLE-EXPORT.S3 [REQUIRES: LIVE]: Non-matching token leaves security-disable inactive
      SPEC: hw/sys/sep/doc/token_processing.adoc Token Matching@2f40548ea787240680a1c45ab75b8729e9620778
      COVERAGE: {method: DIRECTED, required_cells: ['sec-dis-token-mismatch'], random_knobs: [], coverage_artifact: None}

**SEP-TEST-MODE-SECURE-TM — SECURE_TM latch from TEST_EN:** TEST_EN strap latched at fuse-sense-done or cold-reset if SEC_DIS becomes SECURE_TM qualifying test enables
  - Spec: hw/sys/sep/doc/test_mode.adoc Test Mode Entry@2ecc7b227e3926b253c65b5aac21239eec24ba5f
  - Triad: producer TEST_EN strap / SEC_DIS condition | transport SEP test-mode latch into SECURE_TM | consumer Test feature enables to TAP qualified by SECURE_TM equals 1
  - Required scenarios:
    - SEP-TEST-MODE-SECURE-TM.S1 [REQUIRES: LIVE]: TEST_EN latched at fuse-sense-done when SEC_DIS inactive
      SPEC: hw/sys/sep/doc/test_mode.adoc TEST_EN latched when SEP fuse sensing is done@2ecc7b227e3926b253c65b5aac21239eec24ba5f
      COVERAGE: {method: DIRECTED, required_cells: ['tm-latch-fuse'], random_knobs: [], coverage_artifact: None}
    - SEP-TEST-MODE-SECURE-TM.S2 [REQUIRES: LIVE]: SECURE_TM cleared only by chip reset
      SPEC: hw/sys/sep/doc/test_mode.adoc latched SECURE_TM cleared by chip reset@2ecc7b227e3926b253c65b5aac21239eec24ba5f
      COVERAGE: {method: DIRECTED, required_cells: ['tm-clear-reset'], random_knobs: [], coverage_artifact: None}

### WDT

**SEP-WDT-RESET-TO-SMC — SEP WDT bite/reset indication into SMC:** SEP WDT second-stage bite asserts reset request that SMC aggregates as SEP watchdog indication
  - Spec: hw/sys/sep/doc/periphs.adoc Watchdog Timer (WDT)@2ecc7b227e3926b253c65b5aac21239eec24ba5f
  - Triad: producer SEP aon_timer WDT second timeout | transport wdt_timer_rst_req / sep_wdt_reset into SMC peripheral_interrupts | consumer SMC CPU interrupt path sees SEP watchdog reset indication
  - Required scenarios:
    - SEP-WDT-RESET-TO-SMC.S1 [REQUIRES: LIVE]: WDT bite asserts SMC SEP-watchdog interrupt path
      SPEC: hw/sys/smc/doc/interrupts.adoc SEP watchdog reset@2f40548ea787240680a1c45ab75b8729e9620778
      COVERAGE: {method: DIRECTED, required_cells: ['wdt-bite-irq'], random_knobs: [], coverage_artifact: None}
    - SEP-WDT-RESET-TO-SMC.S2 [REQUIRES: LIVE]: WDT bark interrupt is distinct from bite reset request
      SPEC: hw/sys/sep/doc/periphs.adoc intr_wdog_timer_bark_o vs wdt_timer_rst_req_o@2ecc7b227e3926b253c65b5aac21239eec24ba5f
      COVERAGE: {method: DIRECTED, required_cells: ['wdt-bark-vs-bite'], random_knobs: [], coverage_artifact: None}
    - SEP-WDT-RESET-TO-SMC.S3 [REQUIRES: CONNECTIVITY]: WDT domain uses clk_sep_wdt_i at SMU
      SPEC: hw/sys/smu/doc/SMU_SPEC.md Clock and Reset SEP WDT@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
      COVERAGE: {method: DIRECTED, required_cells: ['wdt-clock-domain'], random_knobs: [], coverage_artifact: None}

### Ports observable at SMU

**SEP-MEMORY-PORT-OBS — SEP memory macro ports observable at SMU:** SEP TCM/SRAM/Boot-ROM request/response ports passthrough the SMU wrapper for integration memories
  - Spec: hw/sys/smu/doc/port_table.adoc sep_cpu_tcm_req_o@2ecc7b227e3926b253c65b5aac21239eec24ba5f
  - Triad: producer SEP CPU/LSU/IFI memory accesses | transport sep_cpu_tcm / sep_sram / sep_boot_rom ports at SMU | consumer External memory models respond; SEP observes correct data path at boundary
  - Required scenarios:
    - SEP-MEMORY-PORT-OBS.S1 [REQUIRES: LIVE]: ICCM/DCCM TCM port activity during SEP execution
      SPEC: hw/sys/sep/doc/memory_map.adoc ICCM DCCM@2ecc7b227e3926b253c65b5aac21239eec24ba5f
      COVERAGE: {method: DIRECTED, required_cells: ['tcm-activity'], random_knobs: [], coverage_artifact: None}
    - SEP-MEMORY-PORT-OBS.S2 [REQUIRES: LIVE]: Scratch SRAM port activity for SEP-local SRAM window
      SPEC: hw/sys/sep/doc/memory_map.adoc Scratch SRAM@2ecc7b227e3926b253c65b5aac21239eec24ba5f
      COVERAGE: {method: DIRECTED, required_cells: ['sram-activity'], random_knobs: [], coverage_artifact: None}
    - SEP-MEMORY-PORT-OBS.S3 [REQUIRES: LIVE]: Boot ROM port serves BL0 fetch window
      SPEC: hw/sys/sep/doc/memory_map.adoc BL0 ROM@2ecc7b227e3926b253c65b5aac21239eec24ba5f
      COVERAGE: {method: DIRECTED, required_cells: ['rom-port'], random_knobs: [], coverage_artifact: None}

**SEP-CRYPTO-PORT-OBS — SEP crypto/KM/OTBN ports observable at SMU:** AES/OTBN/KM memory and CSR paths that appear at SMU integration ports are exercisable
  - Spec: hw/sys/sep/doc/crypto.adoc Cryptographic Subsystem@06ed854b2f40c7a31468fdcd6e535d21378ede5e
  - Triad: producer SEP CPU/DMA programmed crypto ops | transport crypto AXI decode + KM/OTBN SRAM ports at SMU | consumer Boundary-visible crypto completion/status without deep algorithm proof
  - Required scenarios:
    - SEP-CRYPTO-PORT-OBS.S1 [REQUIRES: LIVE]: AES CSR window reachable and completes a boundary-visible op
      SPEC: hw/sys/sep/doc/memory_map.adoc AES 0x1091_0000@2ecc7b227e3926b253c65b5aac21239eec24ba5f
      COVERAGE: {method: DIRECTED, required_cells: ['aes-csr-op'], random_knobs: [], coverage_artifact: None}
    - SEP-CRYPTO-PORT-OBS.S2 [REQUIRES: LIVE]: OTBN IMEM/DMEM ports toggle under a programmed execute flow
      SPEC: hw/sys/sep/doc/crypto.adoc OTBN PKA@06ed854b2f40c7a31468fdcd6e535d21378ede5e
      COVERAGE: {method: DIRECTED, required_cells: ['otbn-mem-ports'], random_knobs: [], coverage_artifact: None}
    - SEP-CRYPTO-PORT-OBS.S3 [REQUIRES: CONNECTIVITY]: KM ROM/SRAM ports observable at SMU passthrough
      SPEC: hw/sys/smu/doc/port_table.adoc sep_km_rom_mem_req_o@2ecc7b227e3926b253c65b5aac21239eec24ba5f
      COVERAGE: {method: DIRECTED, required_cells: ['km-mem-ports'], random_knobs: [], coverage_artifact: None}

**SEP-DMA-PORT-OBS — SEP DMA engine observable at SMU fabric boundary:** SEP DMA CSR programming moves data on SEP fabric paths visible at SMU-integrated memories
  - Spec: hw/sys/sep/doc/memory_map.adoc DMA CSR 0x1080_0000@2ecc7b227e3926b253c65b5aac21239eec24ba5f
  - Triad: producer SEP CPU programs DMA CSR | transport DMA master on SEP AXI fabric to TCM/SRAM/extension | consumer Completed DMA transfer observed in destination memory at boundary
  - Required scenarios:
    - SEP-DMA-PORT-OBS.S1 [REQUIRES: LIVE]: DMA CSR decode and kickoff from SEP
      SPEC: hw/sys/sep/doc/fabric.adoc Top Level AXI4 DMA master@2ecc7b227e3926b253c65b5aac21239eec24ba5f
      COVERAGE: {method: DIRECTED, required_cells: ['dma-csr'], random_knobs: [], coverage_artifact: None}
    - SEP-DMA-PORT-OBS.S2 [REQUIRES: LIVE]: DMA preload into CPU TCM backdoor path completes
      SPEC: hw/sys/sep/doc/fabric.adoc CPU TCM backdoor AXI path@2ecc7b227e3926b253c65b5aac21239eec24ba5f
      COVERAGE: {method: DIRECTED, required_cells: ['dma-tcm-preload'], random_knobs: [], coverage_artifact: None}

**SEP-SPI-PORT-OBS — SEP SPI host port and IRQ mux at SMU:** SEP SPI host request/response and muxed SPI IRQ are visible at SMU boundary
  - Spec: hw/sys/sep/doc/periphs.adoc Serial Peripheral Interface (SPI)@2ecc7b227e3926b253c65b5aac21239eec24ba5f
  - Triad: producer SEP CPU SPI programming | transport sep_io_spi / ot_spi_irq_o / spi_irq_i at SMU | consumer SPI pad-facing traffic or IRQ observed at boundary
  - Required scenarios:
    - SEP-SPI-PORT-OBS.S1 [REQUIRES: LIVE]: SPI host CSR window reachable and drives sep_io_spi_req_o
      SPEC: hw/sys/sep/doc/port_table.adoc sep_io_spi_req_o@2ecc7b227e3926b253c65b5aac21239eec24ba5f
      COVERAGE: {method: DIRECTED, required_cells: ['spi-req'], random_knobs: [], coverage_artifact: None}
    - SEP-SPI-PORT-OBS.S2 [REQUIRES: CONNECTIVITY]: Muxed SPI IRQ appears on SMU spi_irq path
      SPEC: hw/sys/smu/doc/port_table.adoc spi_irq_i ot_spi_irq_o@2ecc7b227e3926b253c65b5aac21239eec24ba5f
      COVERAGE: {method: DIRECTED, required_cells: ['spi-irq-mux'], random_knobs: [], coverage_artifact: None}

**SEP-EFUSE-PORT-OBS — SEP eFuse bank/command ports at SMU:** SEP eFuse AXI-Lite bank control and fuse command interfaces passthrough SMU to the eFuse shim
  - Spec: hw/sys/sep/doc/periphs.adoc Fuse Controller (OTP)@2ecc7b227e3926b253c65b5aac21239eec24ba5f
  - Triad: producer SEP OTP/fuse controller transactions | transport sep_efuse_bank_ctrl / sep_efuse_shim_command at SMU | consumer eFuse shim responds; shadow/sense side effects observable per fuse chapter
  - Required scenarios:
    - SEP-EFUSE-PORT-OBS.S1 [REQUIRES: LIVE]: eFuse bank-control AXI-Lite transaction completes at boundary
      SPEC: hw/sys/smu/doc/port_table.adoc sep_efuse_bank_ctrl_req_o@2ecc7b227e3926b253c65b5aac21239eec24ba5f
      COVERAGE: {method: DIRECTED, required_cells: ['efuse-bank'], random_knobs: [], coverage_artifact: None}
    - SEP-EFUSE-PORT-OBS.S2 [REQUIRES: LIVE]: eFuse command interface handshake completes
      SPEC: hw/sys/smu/doc/port_table.adoc sep_efuse_shim_command_req_o@2ecc7b227e3926b253c65b5aac21239eec24ba5f
      COVERAGE: {method: DIRECTED, required_cells: ['efuse-cmd'], random_knobs: [], coverage_artifact: None}
    - SEP-EFUSE-PORT-OBS.S3 [REQUIRES: LIVE]: JTAG OTP debug AXI-Lite path into SEP eFuse
      SPEC: hw/sys/sep/doc/port_table.adoc axil_sep_otp_jtag_req_i@2ecc7b227e3926b253c65b5aac21239eec24ba5f
      COVERAGE: {method: DIRECTED, required_cells: ['efuse-jtag-otp'], random_knobs: [], coverage_artifact: None}

### Decode / filter / remap / demux

**SEP-INBOUND-FILTER — SEP inbound traffic filter at system interface:** Inbound filter is block-by-default after POR; only SEP CPU programs allow rules by addr/NS/source ID
  - Spec: hw/sys/sep/doc/fabric.adoc System Interface initiator / inbound filter@2ecc7b227e3926b253c65b5aac21239eec24ba5f
  - Triad: producer External/SMN inbound master | transport smn_inbound + inbound traffic filter | consumer Blocked addresses get filter deny response; allowed addresses reach SEP targets
  - Required scenarios:
    - SEP-INBOUND-FILTER.S1 [REQUIRES: LIVE]: Post-POR inbound default deny blocks unprogrammed address
      SPEC: hw/sys/sep/doc/fabric.adoc block-by-default after POR@2ecc7b227e3926b253c65b5aac21239eec24ba5f
      COVERAGE: {method: DIRECTED, required_cells: ['inbound-default-deny'], random_knobs: [], coverage_artifact: None}
    - SEP-INBOUND-FILTER.S2 [REQUIRES: LIVE]: SEP-programmed allow rule admits matching inbound transaction
      SPEC: hw/sys/sep/doc/fabric.adoc filters based on address NS source ID@2ecc7b227e3926b253c65b5aac21239eec24ba5f
      COVERAGE: {method: DIRECTED, required_cells: ['inbound-allow'], random_knobs: [], coverage_artifact: None}
    - SEP-INBOUND-FILTER.S3 [REQUIRES: LIVE]: STEE-only access rule for STEE remapper region
      SPEC: hw/sys/sep/doc/fabric.adoc inbound filter ensures only STEE has access to STEE remapper@2ecc7b227e3926b253c65b5aac21239eec24ba5f
      COVERAGE: {method: DIRECTED, required_cells: ['inbound-stee'], random_knobs: [], coverage_artifact: None}

**SEP-OUTBOUND-DEMUX — SEP outbound demux to SMC vs SMN:** SEP outbound routing distinguishes SMC-neighbor path vs SMN/NoC path after local/alias decode
  - Spec: hw/sys/sep/doc/fabric.adoc Transaction Routing@2ecc7b227e3926b253c65b5aac21239eec24ba5f
  - Triad: producer SEP CPU/DMA outbound address | transport system peripherals outbound demux | consumer Transaction appears on sep_ext_to_smc or smn_outbound as selected by address map
  - Required scenarios:
    - SEP-OUTBOUND-DEMUX.S1 [REQUIRES: LIVE]: SMC-window address emerges on sep_ext_to_smc path
      SPEC: hw/sys/sep/doc/memory_map.adoc 0x4000_0000 SMC@2ecc7b227e3926b253c65b5aac21239eec24ba5f
      COVERAGE: {method: DIRECTED, required_cells: ['demux-to-smc'], random_knobs: [], coverage_artifact: None}
    - SEP-OUTBOUND-DEMUX.S2 [REQUIRES: LIVE]: Non-SMC external address emerges on smn_outbound
      SPEC: hw/sys/sep/doc/fabric.adoc routed out to the SMN@2ecc7b227e3926b253c65b5aac21239eec24ba5f
      COVERAGE: {method: DIRECTED, required_cells: ['demux-to-smn'], random_knobs: [], coverage_artifact: None}
    - SEP-OUTBOUND-DEMUX.S3 [REQUIRES: LIVE]: Local SEP resource stays inside SEP
      SPEC: hw/sys/sep/doc/memory_map.adoc SEP Local 0x1000_0000@2ecc7b227e3926b253c65b5aac21239eec24ba5f
      COVERAGE: {method: DIRECTED, required_cells: ['demux-local'], random_knobs: [], coverage_artifact: None}

**SEP-OUTBOUND-FILTER — SEP outbound filter after remap:** Outbound filter enforces address/NS/source-ID rules so source-ID others cannot access M-mode assets
  - Spec: hw/sys/sep/doc/fabric.adoc outbound filter enables filtering based on address NS and source ID@2ecc7b227e3926b253c65b5aac21239eec24ba5f
  - Triad: producer SEP outbound post-remap traffic | transport outbound filter | consumer Violating transactions filtered; conforming transactions pass
  - Required scenarios:
    - SEP-OUTBOUND-FILTER.S1 [REQUIRES: LIVE]: Programmed deny rule blocks matching outbound transaction
      SPEC: hw/sys/sep/doc/fabric.adoc outbound filter@2ecc7b227e3926b253c65b5aac21239eec24ba5f
      COVERAGE: {method: DIRECTED, required_cells: ['outbound-deny'], random_knobs: [], coverage_artifact: None}
    - SEP-OUTBOUND-FILTER.S2 [REQUIRES: LIVE]: Conforming source-ID/address passes outbound filter
      SPEC: hw/sys/sep/doc/fabric.adoc outbound filter@2ecc7b227e3926b253c65b5aac21239eec24ba5f
      COVERAGE: {method: DIRECTED, required_cells: ['outbound-allow'], random_knobs: [], coverage_artifact: None}
    - SEP-OUTBOUND-FILTER.S3 [REQUIRES: LIVE]: SMC-egress vs filtered outbound path relationship requires exact SPEC answer
      SPEC: hw/sys/smu/doc/SMU_SPEC.md Security Considerations open review ISSUE-16@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
      COVERAGE: {method: DIRECTED, required_cells: ['outbound-smc-egress'], random_knobs: [], coverage_artifact: None}

**SEP-AP-STEE-REMAP — AP/STEE controlled remap regions:** Writes to AP/STEE remap windows are routed through the corresponding remappers with programmed attributes
  - Spec: hw/sys/sep/doc/fabric.adoc Address Remapping Sixteen remap regions@2ecc7b227e3926b253c65b5aac21239eec24ba5f
  - Triad: producer SEP CPU/DMA write to AP/STEE remap windows | transport AP/STEE remappers | consumer Remapped output address/cacheable attributes appear on outbound path
  - Required scenarios:
    - SEP-AP-STEE-REMAP.S1 [REQUIRES: LIVE]: Invalid-out-of-reset remapper behaves as transparent pass-through
      SPEC: hw/sys/sep/doc/fabric.adoc programmable remap entries invalid out of reset@2ecc7b227e3926b253c65b5aac21239eec24ba5f
      COVERAGE: {method: DIRECTED, required_cells: ['remap-passthrough'], random_knobs: [], coverage_artifact: None}
    - SEP-AP-STEE-REMAP.S2 [REQUIRES: LIVE]: Programmed AP remap region translates input range to output offset
      SPEC: hw/sys/sep/doc/memory_map.adoc AP Remap Region@2ecc7b227e3926b253c65b5aac21239eec24ba5f
      COVERAGE: {method: DIRECTED, required_cells: ['ap-remap'], random_knobs: [], coverage_artifact: None}
    - SEP-AP-STEE-REMAP.S3 [REQUIRES: LIVE]: Programmed STEE remap region translates with STEE qualification
      SPEC: hw/sys/sep/doc/memory_map.adoc STEE Remap Region@2ecc7b227e3926b253c65b5aac21239eec24ba5f
      COVERAGE: {method: DIRECTED, required_cells: ['stee-remap'], random_knobs: [], coverage_artifact: None}

**SEP-AXI-EXTENSION — SEP AXI extension port at SMU:** SEP AXI extension region/master port is passthrough at SMU for adopter peripherals
  - Spec: hw/sys/sep/doc/memory_map.adoc AXI Extension Region@2ecc7b227e3926b253c65b5aac21239eec24ba5f
  - Triad: producer SEP access to extension region or extension master | transport sep_axi_extension at SMU | consumer Adopter peripheral model responds or DECERR if unused tie-off
  - Required scenarios:
    - SEP-AXI-EXTENSION.S1 [REQUIRES: CONNECTIVITY]: Extension port request toggles for in-window access
      SPEC: hw/sys/smu/doc/port_table.adoc sep_axi_extension_req_o@2ecc7b227e3926b253c65b5aac21239eec24ba5f
      COVERAGE: {method: DIRECTED, required_cells: ['ext-port-toggle'], random_knobs: [], coverage_artifact: None}
    - SEP-AXI-EXTENSION.S2 [REQUIRES: LIVE]: Unused extension response tie-off returns DECERR
      SPEC: hw/sys/smu/doc/port_table.adoc sep_axi_extension_resp_i Tie to DECERR@2ecc7b227e3926b253c65b5aac21239eec24ba5f
      COVERAGE: {method: DIRECTED, required_cells: ['ext-decerr'], random_knobs: [], coverage_artifact: None}

**SEP-DEBUG-BUS-EXPORT — SEP external debug observation bus:** SEP ext_debug_bus_o is exported for debug infrastructure observation at SMU
  - Spec: hw/sys/sep/doc/port_table.adoc ext_debug_bus_o@2ecc7b227e3926b253c65b5aac21239eec24ba5f
  - Triad: producer SEP debug observation packing | transport ext_debug_bus_o | consumer Debug infrastructure observes non-X bus after SEP runs
  - Required scenarios:
    - SEP-DEBUG-BUS-EXPORT.S1 [REQUIRES: CONNECTIVITY]: Debug bus present and stable while SEP out of reset
      SPEC: hw/sys/smu/doc/SMU_SPEC.md CDC notes SEP debug bus@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
      COVERAGE: {method: DIRECTED, required_cells: ['debug-bus-stable'], random_knobs: [], coverage_artifact: None}

**SEP-EXTERNAL-IRQ — External interrupts into SEP PIC:** External interrupt sources on extintsrc_req reach SEP PIC at SMU-visible integration
  - Spec: hw/sys/sep/doc/port_table.adoc extintsrc_req@2ecc7b227e3926b253c65b5aac21239eec24ba5f
  - Triad: producer External IRQ stimuli | transport extintsrc_req into SEP PIC | consumer SEP CPU takes interrupt / PIC pending reflects source
  - Required scenarios:
    - SEP-EXTERNAL-IRQ.S1 [REQUIRES: LIVE]: Asserted external IRQ becomes pending in SEP PIC
      SPEC: hw/sys/sep/doc/cpu.adoc PIC supporting external interrupts@2ecc7b227e3926b253c65b5aac21239eec24ba5f
      COVERAGE: {method: DIRECTED, required_cells: ['ext-irq-pending'], random_knobs: [], coverage_artifact: None}
    - SEP-EXTERNAL-IRQ.S2 [REQUIRES: LIVE]: Deassert/clear path clears pending
      SPEC: hw/sys/sep/doc/cpu.adoc PIC@2ecc7b227e3926b253c65b5aac21239eec24ba5f
      COVERAGE: {method: DIRECTED, required_cells: ['ext-irq-clear'], random_knobs: [], coverage_artifact: None}

**SEP-IC-RESET-EXT-SLICE — DTP IC_RESET external slice affecting SEP reset path:** When JTAG IC_RESET is enabled, SMU exports jtag_ic_reset_ext override slice that can override SEP-related resets
  - Spec: hw/sys/smu/doc/port_table.adoc jtag_ic_reset_ext_o@2ecc7b227e3926b253c65b5aac21239eec24ba5f
  - Triad: producer DTP IC_RESET TDR override | transport jtag_ic_reset_ext_o at SMU | consumer SEP reset path follows override value when override enable is set
  - Required scenarios:
    - SEP-IC-RESET-EXT-SLICE.S1 [REQUIRES: LIVE]: IC_RESET override asserts SEP-related reset slice
      SPEC: hw/sys/smu/doc/SMU_SPEC.md Operating Modes Reset override@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
      COVERAGE: {method: DIRECTED, required_cells: ['ic-reset-assert'], random_knobs: [], coverage_artifact: None}
    - SEP-IC-RESET-EXT-SLICE.S2 [REQUIRES: LIVE]: Clearing override restores normal SEP reset control
      SPEC: hw/sys/smu/doc/SMU_SPEC.md Operating Modes Reset override@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
      COVERAGE: {method: DIRECTED, required_cells: ['ic-reset-release'], random_knobs: [], coverage_artifact: None}

## Required interactions

- INT-FUSE-AUTH-TO-ROM [FEATURES: ['SEP-FUSE-SENSE-HANDSHAKE', 'SEP-ROM-BOOT-ENABLE']] [REQUIRES: LIVE]: SMC fuse-sense authorization precedes SEP fuse completion and first BL0 ROM fetch
  - Spec: hw/sys/smu/doc/SMU_SPEC.md Security Considerations@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9; hw/sys/sep/doc/periphs.adoc Fuse Controller (OTP)@2ecc7b227e3926b253c65b5aac21239eec24ba5f
  - COVERAGE: {method: DIRECTED, required_cells: ['authorized-ordered-rom-fetch'], random_knobs: [], coverage_artifact: None}

- INT-ALIAS-MAILBOX [FEATURES: ['SEP-SMC-ALIAS-REMAP', 'SEP-MAILBOX-DATA-EXCHANGE']] [REQUIRES: LIVE]: SEP reaches SMC mailbox region through the alias remap path for interop payload exchange
  - Spec: hw/sys/smu/doc/SMU_SPEC.md SEP to SMC alias remap@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9; hw/sys/smu/doc/SMU_SPEC.md Mailbox challenge-response@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - COVERAGE: {method: DIRECTED, required_cells: ['alias-mailbox-exchange'], random_knobs: [], coverage_artifact: None}

- INT-FEAT-LC-HANDOFF [FEATURES: ['SEP-FEAT-CTRL-EXPORT', 'SEP-LC-STATE-EXPORT']] [REQUIRES: LIVE]: Lifecycle state and feat_ctrl are exported together as the security handoff into SMC/DTP
  - Spec: hw/sys/smu/doc/SMU_SPEC.md Feature 7 Lifecycle and Security@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - COVERAGE: {method: DIRECTED, required_cells: ['lc-feat-handoff'], random_knobs: [], coverage_artifact: None}

## Inventory notes
- Mailbox IRQ channels 0–7 are folded into SEP-MAILBOX-IRQ-TO-SMC.S3 as a representative multi-channel scenario.
- Crypto accelerators are folded into SEP-CRYPTO-PORT-OBS as boundary-port observability, not deep KAT proof.
- Contested reset-mid-window is SEP-RESET-CONTROL.S4 (BOUNDED-LIVENESS); stress floods are P3 unallocated in the plan.
