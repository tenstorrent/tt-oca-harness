---
schema: dv-quality/v1
artifact: spec-audit
artifact_revision: 1
content_sha256: b1484d20e9d3dd8ede81185cf7b5d2b071514ce2e6d11e5d5dcfdf6fbe281917
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
findings:
- id: SF-001
  category: SF-AMBIGUOUS
  severity: High
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Security Considerations ISSUE-16@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - hw/sys/sep/doc/fabric.adoc outbound filter@2ecc7b227e3926b253c65b5aac21239eec24ba5f
  observed: SMU_SPEC flags SMC-egress SEP outbound traffic bypassing the SEP outbound filter as an open
    review item, while SEP fabric requires outbound filter enforcement after remap.
  question: At the SMU integration boundary, must SEP→SMC egress always traverse the SEP outbound filter,
    or is a dedicated unfiltered alias/egress path architecturally required? What exact response is required
    when a filtered rule would deny an SMC-egress beat?
  affects:
    features:
    - SEP-OUTBOUND-FILTER
    scenarios:
    - SEP-OUTBOUND-FILTER.S3
    anchors:
    - smu_sep_filter_rule_matrix_test
    - smu_sep_smc_egress_unfiltered_test
  status: open
  answer: null
  answered_by: null
  answered_at: null
- id: SF-002
  category: SF-AMBIGUOUS
  severity: Medium
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Clock and Reset@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  observed: SMU_SPEC describes the SEP reset chain but does not pin a same-cycle relationship among intermediate/sep/cpu
    reset nets.
  question: Which exact cycle relationship (same-cycle vs bounded N cycles) among sep_intermediate_reset_n
    / sep_reset_n / sep_cpu_reset_n is normative after primary release?
  affects:
    features:
    - SEP-RESET-CONTROL
    scenarios:
    - SEP-RESET-CONTROL.S3
    anchors:
    - smu_sep_smoke_test
  status: open
  answer: null
  answered_by: null
  answered_at: null
- id: SF-003
  category: SF-AMBIGUOUS
  severity: High
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Interfaces SEP mailbox interrupts@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - hw/sys/smc/doc/interrupts.adoc SEP mailbox interrupt 0@2f40548ea787240680a1c45ab75b8729e9620778
  observed: SMU_SPEC notes SEP mailbox interrupts as internal with ISSUE-7 observability caveat; SMC interrupts.adoc
    maps sep_mailbox_interrupts_i[7:0] to concrete peripheral IRQ IDs.
  question: For SMU-level proof, which observation point is authoritative for SEP mailbox IRQ — wrapper-internal
    smc_mailbox_interrupt_o, SMC sep_mailbox_interrupts_i, or the documented cpu_interrupts_o bit indices
    — and what are the exact bit indices for 1-core vs 4-core configs?
  affects:
    features:
    - SEP-MAILBOX-IRQ-TO-SMC
    scenarios:
    - SEP-MAILBOX-IRQ-TO-SMC.S1
    - SEP-MAILBOX-IRQ-TO-SMC.S2
    - SEP-MAILBOX-IRQ-TO-SMC.S3
    anchors:
    - smu_sep_alias_mailbox_interrupt_probe_test
  status: open
  answer: null
  answered_by: null
  answered_at: null
- id: SF-004
  category: SF-MISSING
  severity: Low
  spec_refs:
  - hw/sys/sep/doc/periphs.adoc Fuse Fields BL1_VERSION@2ecc7b227e3926b253c65b5aac21239eec24ba5f
  observed: BL1_VERSION/BL2_VERSION maximum version is written as 240 (TBD).
  question: What is the normative maximum anti-rollback version count for BL1/BL2?
  affects:
    features: []
    scenarios: []
    anchors: []
  status: open
  answer: null
  answered_by: null
  answered_at: null
- id: SF-005
  category: SF-AMBIGUOUS
  severity: High
  spec_refs:
  - hw/sys/sep/doc/security_disable.adoc SEC_DIS@2ecc7b227e3926b253c65b5aac21239eec24ba5f
  - hw/sys/smu/doc/SMU_SPEC.md SEP_SEC_DISABLE_TOKEN@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  observed: SEC_DIS match compares hash(token) to SEP_SEC_DISABLE_TOKEN_DIGEST; SMU passes SEP_SEC_DISABLE_TOKEN
    (tied 0 at SMU, replaced at synthesis). Exact DV-visible digest bind value and JTAG token register
    access rules for SMU-level proof are not pinned to an exact vector.
  question: What exact digest constant and token presentation path must SMU-level checkers use for SEC_DIS
    match vs mismatch, and is A0-only metal-strap disable in-scope for this pin?
  affects:
    features:
    - SEP-SECURITY-DISABLE-EXPORT
    scenarios:
    - SEP-SECURITY-DISABLE-EXPORT.S2
    - SEP-SECURITY-DISABLE-EXPORT.S3
    anchors:
    - smu_lifecycle_security_handoff_test
  status: open
  answer: null
  answered_by: null
  answered_at: null
- id: SF-006
  category: SF-MISSING
  severity: High
  spec_refs:
  - hw/sys/smu/doc/SMU_SPEC.md Feature 4 AXI Crossbar Fabric@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9
  - hw/sys/sep/doc/fabric.adoc SEP_GLOBAL_BASE_ADDR@2ecc7b227e3926b253c65b5aac21239eec24ba5f
  observed: Aperture programmability is named (SEP_GLOBAL_BASE_ADDR / SEP_REGION_SIZE / SMC GLOBAL_BASE
    / REGION_SIZE) but exact CSR addresses/fields live in generated register adoc which is OUT of authoritative
    scope.
  question: Please publish authoritative (non-generated) absolute addresses, field widths, and reset values
    for SEP/SMC aperture CSRs that SMU xbar decode checkers must use.
  affects:
    features:
    - SEP-XBAR-APERTURE
    scenarios:
    - SEP-XBAR-APERTURE.S1
    - SEP-XBAR-APERTURE.S3
    anchors:
    - smu_sep_smc_xbar_programmable_addr_test
  status: open
  answer: null
  answered_by: null
  answered_at: null
- id: SF-007
  category: SF-AMBIGUOUS
  severity: Medium
  spec_refs:
  - hw/sys/sep/doc/periphs.adoc Watchdog Timer@2ecc7b227e3926b253c65b5aac21239eec24ba5f
  - hw/sys/smc/doc/interrupts.adoc SEP watchdog reset@2f40548ea787240680a1c45ab75b8729e9620778
  observed: SEP exports wdt_timer_rst_req_o (bite); SMC docs show peripheral_interrupts[26] = ~rst_ext_wdt_ni.
    Active level / inversion and bark vs bite mapping into that bit are not jointly specified in one place.
  question: What is the exact polarity and which SEP WDT output (bark vs bite vs wrapper reset) drives
    SMC SEP-watchdog indication bit 26?
  affects:
    features:
    - SEP-WDT-RESET-TO-SMC
    scenarios:
    - SEP-WDT-RESET-TO-SMC.S1
    - SEP-WDT-RESET-TO-SMC.S2
    anchors:
    - smu_sep_wdt_reset_to_smc_test
  status: open
  answer: null
  answered_by: null
  answered_at: null
---

# SMU_SEP — Spec Audit / SPEC_REVIEW (candidate)

## Questions awaiting your answer

### High

**SF-001** (SF-AMBIGUOUS) — blocks ['SEP-OUTBOUND-FILTER.S3']

- Observed: SMU_SPEC flags SMC-egress SEP outbound traffic bypassing the SEP outbound filter as an open review item, while SEP fabric requires outbound filter enforcement after remap.
- Question: At the SMU integration boundary, must SEP→SMC egress always traverse the SEP outbound filter, or is a dedicated unfiltered alias/egress path architecturally required? What exact response is required when a filtered rule would deny an SMC-egress beat?
- Spec refs: ['hw/sys/smu/doc/SMU_SPEC.md Security Considerations ISSUE-16@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9', 'hw/sys/sep/doc/fabric.adoc outbound filter@2ecc7b227e3926b253c65b5aac21239eec24ba5f']

**SF-003** (SF-AMBIGUOUS) — blocks ['SEP-MAILBOX-IRQ-TO-SMC.S1', 'SEP-MAILBOX-IRQ-TO-SMC.S2', 'SEP-MAILBOX-IRQ-TO-SMC.S3']

- Observed: SMU_SPEC notes SEP mailbox interrupts as internal with ISSUE-7 observability caveat; SMC interrupts.adoc maps sep_mailbox_interrupts_i[7:0] to concrete peripheral IRQ IDs.
- Question: For SMU-level proof, which observation point is authoritative for SEP mailbox IRQ — wrapper-internal smc_mailbox_interrupt_o, SMC sep_mailbox_interrupts_i, or the documented cpu_interrupts_o bit indices — and what are the exact bit indices for 1-core vs 4-core configs?
- Spec refs: ['hw/sys/smu/doc/SMU_SPEC.md Interfaces SEP mailbox interrupts@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9', 'hw/sys/smc/doc/interrupts.adoc SEP mailbox interrupt 0@2f40548ea787240680a1c45ab75b8729e9620778']

**SF-005** (SF-AMBIGUOUS) — blocks ['SEP-SECURITY-DISABLE-EXPORT.S2', 'SEP-SECURITY-DISABLE-EXPORT.S3']

- Observed: SEC_DIS match compares hash(token) to SEP_SEC_DISABLE_TOKEN_DIGEST; SMU passes SEP_SEC_DISABLE_TOKEN (tied 0 at SMU, replaced at synthesis). Exact DV-visible digest bind value and JTAG token register access rules for SMU-level proof are not pinned to an exact vector.
- Question: What exact digest constant and token presentation path must SMU-level checkers use for SEC_DIS match vs mismatch, and is A0-only metal-strap disable in-scope for this pin?
- Spec refs: ['hw/sys/sep/doc/security_disable.adoc SEC_DIS@2ecc7b227e3926b253c65b5aac21239eec24ba5f', 'hw/sys/smu/doc/SMU_SPEC.md SEP_SEC_DISABLE_TOKEN@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9']

**SF-006** (SF-MISSING) — blocks ['SEP-XBAR-APERTURE.S1', 'SEP-XBAR-APERTURE.S3']

- Observed: Aperture programmability is named (SEP_GLOBAL_BASE_ADDR / SEP_REGION_SIZE / SMC GLOBAL_BASE / REGION_SIZE) but exact CSR addresses/fields live in generated register adoc which is OUT of authoritative scope.
- Question: Please publish authoritative (non-generated) absolute addresses, field widths, and reset values for SEP/SMC aperture CSRs that SMU xbar decode checkers must use.
- Spec refs: ['hw/sys/smu/doc/SMU_SPEC.md Feature 4 AXI Crossbar Fabric@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9', 'hw/sys/sep/doc/fabric.adoc SEP_GLOBAL_BASE_ADDR@2ecc7b227e3926b253c65b5aac21239eec24ba5f']

### Medium

**SF-002** (SF-AMBIGUOUS) — blocks ['SEP-RESET-CONTROL.S3']

- Observed: SMU_SPEC describes the SEP reset chain but does not pin a same-cycle relationship among intermediate/sep/cpu reset nets.
- Question: Which exact cycle relationship (same-cycle vs bounded N cycles) among sep_intermediate_reset_n / sep_reset_n / sep_cpu_reset_n is normative after primary release?
- Spec refs: ['hw/sys/smu/doc/SMU_SPEC.md Clock and Reset@88ddf2482d1e542c0801722975e1f4171907b4fcb68cb511574a88ea9efe88c9']

**SF-007** (SF-AMBIGUOUS) — blocks ['SEP-WDT-RESET-TO-SMC.S1', 'SEP-WDT-RESET-TO-SMC.S2']

- Observed: SEP exports wdt_timer_rst_req_o (bite); SMC docs show peripheral_interrupts[26] = ~rst_ext_wdt_ni. Active level / inversion and bark vs bite mapping into that bit are not jointly specified in one place.
- Question: What is the exact polarity and which SEP WDT output (bark vs bite vs wrapper reset) drives SMC SEP-watchdog indication bit 26?
- Spec refs: ['hw/sys/sep/doc/periphs.adoc Watchdog Timer@2ecc7b227e3926b253c65b5aac21239eec24ba5f', 'hw/sys/smc/doc/interrupts.adoc SEP watchdog reset@2f40548ea787240680a1c45ab75b8729e9620778']

### Low

**SF-004** (SF-MISSING) — blocks n/a

- Observed: BL1_VERSION/BL2_VERSION maximum version is written as 240 (TBD).
- Question: What is the normative maximum anti-rollback version count for BL1/BL2?
- Spec refs: ['hw/sys/sep/doc/periphs.adoc Fuse Fields BL1_VERSION@2ecc7b227e3926b253c65b5aac21239eec24ba5f']

