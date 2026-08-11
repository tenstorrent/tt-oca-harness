---
schema: dv-quality/v1
artifact: spec-audit
artifact_revision: 1
content_sha256: 058877bbc8e54be6ae55653a799eb38b6459f3c26970986625cac3fd7b893343
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
  notes: REVERSE-INVENTORY ONLY candidate spec-audit from the same sealed Step-1 read. Does not overwrite
    any approved SPEC_REVIEW. affects.anchors left empty.
approved_by: null
approved_at: null
findings:
- id: SF-001
  category: SF-MISSING
  severity: High
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Data Paths/Mailbox challenge-response
  - hw/sys/sep/doc/fabric.adoc Mailboxes
  observed: SMU_SPEC names a challenge-response (token then complement) as the primary SMC↔SEP interop
    path and points to SMU_TB_ARCH.md/SMU_CSR.md (outside this pin) for detail; SEP fabric.adoc describes
    inbox/outbox interrupt semantics and says non-AP peers use inboxes on both ends, without stating the
    complement algorithm or exact register offsets.
  question: What exact token/complement values, mailbox channel pairing, and completion observation are
    normative for SMC↔SEP challenge-response at the SMU boundary?
  affects:
    features:
    - SMC-SEP-MAILBOX
    scenarios:
    - SMC-SEP-MAILBOX.S1
    - SMC-SEP-MAILBOX.S2
    - SMC-SEP-MAILBOX.S5
    anchors: []
  status: open
  resolution: null
- id: SF-002
  category: SF-AMBIGUOUS
  severity: Medium
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Feature 4
  - hw/sys/smu/doc/SMU_SPEC.md Clock and Reset/CDC notes
  observed: Feature 4 lists performance/backpressure as verification concerns; CDC notes say crossbar
    addr_map built combinationally from CSR base/size is not stability-checked against in-flight transactions,
    but no bound or expected response class is stated.
  question: What bounded completion-or-error contract applies to concurrent backpressure and to aperture
    CSR updates while transactions are in flight?
  affects:
    features:
    - SMU-AXI-XBAR-CONNECTIVITY
    - SMU-AXI-APERTURE
    scenarios:
    - SMU-AXI-XBAR-CONNECTIVITY.S4
    - SMU-AXI-APERTURE.S3
    anchors: []
  status: open
  resolution: null
- id: SF-003
  category: SF-TERM
  severity: Medium
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Security Considerations
  - hw/sys/smc/doc/port_table.adoc feat_ctrl_i
  - hw/sys/dtp/doc/port_table.adoc feat_ctrl_i
  - hw/sys/sep/doc/port_table.adoc feat_ctrl_o
  observed: SMU_SPEC and DTP/SEP port tables type feat_ctrl as sep_efuse_map_lc_disable_reg_t / sep_efuse_pkg::sep_efuse_map_lc_disable_reg_t,
    while SMC port_table types feat_ctrl_i as sep_lcc_pkg::feat_ctrl_t.
  question: Which type name is authoritative for the SMU-integrated feat_ctrl vector, and are the types
    required to be identical bit-for-bit?
  affects:
    features:
    - SEP-FEAT-CTRL
    scenarios:
    - SEP-FEAT-CTRL.S1
    - SEP-FEAT-CTRL.S2
    - SEP-FEAT-CTRL.S3
    anchors: []
  status: open
  resolution: null
- id: SF-004
  category: SF-AMBIGUOUS
  severity: Medium
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Interfaces
  - hw/sys/smc/doc/interrupts.adoc SEP mailbox interrupt map
  observed: SMU_SPEC Interfaces notes SEP mailbox interrupts as internal and says observe via wrapper
    with note ISSUE-7, while SMC docs give exact cpu_interrupts_o bit indices for sep_mailbox_interrupts_i[7:0].
  question: At SMU-level verification, is the normative observation point the SMC cpu_interrupts_o map,
    a wrapper-only probe, or both?
  affects:
    features:
    - SMC-SEP-MBX-IRQ
    scenarios:
    - SMC-SEP-MBX-IRQ.S1
    anchors: []
  status: open
  resolution: null
- id: SF-005
  category: SF-AMBIGUOUS
  severity: Low
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Error Handling
  - hw/sys/smu/doc/SMU_SPEC.md Specifications
  observed: ATOPs=0 is stated as unsupported/rejected, but the exact AXI response code (DECERR vs SLVERR
    vs silent drop) is not pinned in the SPEC text.
  question: Which exact AXI response (and channel) must an ATOP initiator observe on the SMU crossbar?
  affects:
    features:
    - SMU-AXI-ATOP
    scenarios:
    - SMU-AXI-ATOP.S1
    anchors: []
  status: open
  resolution: null
- id: SF-006
  category: SF-MISSING
  severity: Medium
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Feature 3
  - hw/sys/dtp/doc/port_table.adoc jtag_boot_stall
  observed: Boot-stall is named as a DTP↔SMC interaction, and DTP ports expose jtag_boot_stall_ovrd_o/jtag_boot_stall_o,
    but the pinned docs do not state the exact SMC observable (which reset/PC/stall signal) that proves
    hold versus release.
  question: Which SMC-side observable must prove boot-stall hold and release under SMU integration?
  affects:
    features:
    - DTP-BOOT-STALL
    - SMC-BOOT
    scenarios:
    - DTP-BOOT-STALL.S1
    - DTP-BOOT-STALL.S2
    - INT-BOOT-STALL-SMC
    anchors: []
  status: open
  resolution: null
- id: SF-007
  category: SF-CONFLICT
  severity: Low
  spec_refs:
  - hw/sys/smu/doc/port_table.adoc rst_cold_ni
  - hw/sys/smu/doc/SMU_SPEC.md Clock and Reset
  - hw/sys/dtp/doc/jtag.adoc Reset Architecture
  observed: SMU port_table says rst_cold_ni also serves as DTP power-on reset; SMU_SPEC Clock and Reset
    says DTP uses pwr_on_rst_ni = powergood_stable from SMC; DTP jtag.adoc distinguishes rst_n_i vs pwr_on_rst_ni.
  question: 'What is the normative SMU-level POR root into DTP JTAG logic: rst_cold_ni, powergood_stable,
    or an AND of both with TRST?'
  affects:
    features:
    - SMU-TOP-CLK-RST
    - DTP-JTAG-ACCESS
    scenarios:
    - SMU-TOP-CLK-RST.S1
    - DTP-JTAG-ACCESS.S2
    anchors: []
  status: open
  resolution: null
---

# SMU_ALL Spec Audit — REVERSE-INVENTORY CANDIDATE

> **STATUS: candidate — reverse-inventory only**
>
> Same sealed Step-1 read as `SMU_ALL_SPEC_FEATURE_LIST_REVERSE_CANDIDATE.md`.
> Does **not** replace any approved `SMU_ALL_SPEC_REVIEW.md`.
> `affects.anchors: []` on every finding (anchor seal intact).

## Questions awaiting owner answer

### SF-001 (High / SF-MISSING)

- **Observed:** SMU_SPEC names a challenge-response (token then complement) as the primary SMC↔SEP interop path and points to SMU_TB_ARCH.md/SMU_CSR.md (outside this pin) for detail; SEP fabric.adoc describes inbox/outbox interrupt semantics and says non-AP peers use inboxes on both ends, without stating the complement algorithm or exact register offsets.
- **Question:** What exact token/complement values, mailbox channel pairing, and completion observation are normative for SMC↔SEP challenge-response at the SMU boundary?
- **Blocks features:** SMC-SEP-MAILBOX

### SF-002 (Medium / SF-AMBIGUOUS)

- **Observed:** Feature 4 lists performance/backpressure as verification concerns; CDC notes say crossbar addr_map built combinationally from CSR base/size is not stability-checked against in-flight transactions, but no bound or expected response class is stated.
- **Question:** What bounded completion-or-error contract applies to concurrent backpressure and to aperture CSR updates while transactions are in flight?
- **Blocks features:** SMU-AXI-XBAR-CONNECTIVITY, SMU-AXI-APERTURE

### SF-003 (Medium / SF-TERM)

- **Observed:** SMU_SPEC and DTP/SEP port tables type feat_ctrl as sep_efuse_map_lc_disable_reg_t / sep_efuse_pkg::sep_efuse_map_lc_disable_reg_t, while SMC port_table types feat_ctrl_i as sep_lcc_pkg::feat_ctrl_t.
- **Question:** Which type name is authoritative for the SMU-integrated feat_ctrl vector, and are the types required to be identical bit-for-bit?
- **Blocks features:** SEP-FEAT-CTRL

### SF-004 (Medium / SF-AMBIGUOUS)

- **Observed:** SMU_SPEC Interfaces notes SEP mailbox interrupts as internal and says observe via wrapper with note ISSUE-7, while SMC docs give exact cpu_interrupts_o bit indices for sep_mailbox_interrupts_i[7:0].
- **Question:** At SMU-level verification, is the normative observation point the SMC cpu_interrupts_o map, a wrapper-only probe, or both?
- **Blocks features:** SMC-SEP-MBX-IRQ

### SF-005 (Low / SF-AMBIGUOUS)

- **Observed:** ATOPs=0 is stated as unsupported/rejected, but the exact AXI response code (DECERR vs SLVERR vs silent drop) is not pinned in the SPEC text.
- **Question:** Which exact AXI response (and channel) must an ATOP initiator observe on the SMU crossbar?
- **Blocks features:** SMU-AXI-ATOP

### SF-006 (Medium / SF-MISSING)

- **Observed:** Boot-stall is named as a DTP↔SMC interaction, and DTP ports expose jtag_boot_stall_ovrd_o/jtag_boot_stall_o, but the pinned docs do not state the exact SMC observable (which reset/PC/stall signal) that proves hold versus release.
- **Question:** Which SMC-side observable must prove boot-stall hold and release under SMU integration?
- **Blocks features:** DTP-BOOT-STALL, SMC-BOOT

### SF-007 (Low / SF-CONFLICT)

- **Observed:** SMU port_table says rst_cold_ni also serves as DTP power-on reset; SMU_SPEC Clock and Reset says DTP uses pwr_on_rst_ni = powergood_stable from SMC; DTP jtag.adoc distinguishes rst_n_i vs pwr_on_rst_ni.
- **Question:** What is the normative SMU-level POR root into DTP JTAG logic: rst_cold_ni, powergood_stable, or an AND of both with TRST?
- **Blocks features:** SMU-TOP-CLK-RST, DTP-JTAG-ACCESS

