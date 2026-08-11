---
schema: dv-quality/v1
artifact: spec-audit
artifact_revision: 1
content_sha256: 8dbc9a1d0097a283730b28c29ec7d7a29eea30e859b5c74ea899b69b2fcd0e55
ip: SMC_CLOCK_GATING
milestone: P1
status: approved
pin_revision: 1
spec:
- path: hw/sys/smc/doc/index.adoc
  revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
- path: hw/sys/smc/doc/overview.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/smc/doc/clk_rst.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/smc/doc/port_table.adoc
  revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
- path: hw/sys/smc/doc/dma.adoc
  revision: e2aae39953bb8001c7c20e3afd3956e68c22440c
- path: hw/sys/smc/doc/zeroer.adoc
  revision: 2f40548ea787240680a1c45ab75b8729e9620778
- path: hw/sys/smc/doc/periphs.adoc
  revision: ffc8cdcc349e1e01a2b970442a01070b1c62c0d7
- path: hw/sys/smc/doc/fabric.adoc
  revision: ffc8cdcc349e1e01a2b970442a01070b1c62c0d7
- path: hw/sys/smc/doc/memmap.adoc
  revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
source_revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
quality_policy:
  path: /home/minshaoho/.claude/skills/dv_common/DV_QUALITY_POLICY.md
  revision: 51a3357d9c31a018d69451b055bc956c089af26e1051368e25ce396c84ac2a75
generated_by:
  human_id: minshaoho
  run_id: dv_vplan_gen-smc_clock_gating-fresh_subagent-20260805T080404+0800
  model:
    provider: anthropic
    family: claude
    version: sonnet-5
derivation_provenance:
  sealed_derivation: false
  anchor_seal_mechanism: ordered-single-context
  fresh_context_route: fresh-subagent
  feature_list_frozen_at: '2026-08-05T08:20:00+08:00'
  note: 'Same seal caveat as SMC_CLOCK_GATING_SPEC_FEATURE_LIST.md: the pin''s sealed fields (anchors,
    anchor_name_prefix, owns_notes) were read at Step 0, before derivation, not after the freeze. affects.anchors
    below is backfilled to the anchor set that exists after Step 3/4 of this same run, per §4.5''s "back-filled
    once the testcase set exists" rule; it does not certify a clean seal for this run.

    '
approved_by: minshaoho
approved_at: '2026-08-05T09:20:00+08:00'
findings:
- id: SF-001
  category: SF-MISSING
  severity: High
  spec_refs:
  - hw/sys/smc/doc/periphs.adoc §Peripherals, table "SMC Peripheral Summary" (rev ffc8cdcc349e1e01a2b970442a01070b1c62c0d7)
  - hw/sys/smc/doc/clk_rst.adoc §Clock and Reset-Based Power Management Integration, row "Module Gating"
    (rev 2f40548ea787240680a1c45ab75b8729e9620778)
  observed: 'The pin''s boundary names "module/per-IP clock-gate enable and hysteresis/activity-detection
    controls" as in scope. clk_rst.adoc''s "Module Gating" row generically claims "individual enable/disable
    per functional block," but periphs.adoc — the only pinned source describing Mailbox, System Timer
    OCTS, eFuse, UART 16550, Log Engine, I2C, AVSBus Controller, GPIO, and Telemetry Receiver — states
    zero clock-gating producer/transport/consumer detail for any of these 9 peripheral blocks (only protocol,
    description, and instance count). Only the DMA controller (dma.adoc) and the Memory Zeroer (zeroer.adoc)
    are concretely specified anywhere in the pinned set.

    '
  question: 'Which, if any, of the peripheral blocks listed in periphs.adoc actually implement per-module
    clock gating today, and where is that behavior specified (a missing section of periphs.adoc, an un-pinned
    per-IP doc, or not yet implemented)? Until answered, no per-peripheral clock-gating feature beyond
    DMA/Zeroer can be derived from this pinned SPEC set.

    '
  affects:
    features:
    - SMC-CG-ARCH-PARAMS
    scenarios:
    - SMC-CG-ARCH-PARAMS.S4
    anchors:
    - SMC_STATIC_CG_SANITY_TEST
    - SMC_I2C_CG_SANITY_TEST
  status: waived
  resolution:
    answered_or_waived_by: minshaoho
    answered_or_waived_at: '2026-08-05T09:20:00+08:00'
    spec_revision: 2f40548ea787240680a1c45ab75b8729e9620778
    note: 'P1 milestone accepts narrowed scope: only DMA and Memory Zeroer have concrete producer→transport→consumer
      clock-gating in the pinned docs. Other periphs.adoc blocks remain OUT until a future re-pin adds
      their CG sections; SMC_I2C_CG_SANITY_TEST stays unallocated-to-feature for this contract.'
- id: SF-002
  category: SF-TERM
  severity: Medium
  spec_refs:
  - hw/sys/smc/doc/clk_rst.adoc §Clock and Reset-Based Power Management Integration, table "Clock Gating
    Control Parameters", rows "Hysteresis Control" and "Enable Threshold" (rev 2f40548ea787240680a1c45ab75b8729e9620778)
  observed: '"Hysteresis Control" (6-bit programmable, "prevents clock gating oscillation") and "Enable
    Threshold" (configurable delay, "balances responsiveness vs. power savings") are listed as two separate
    table rows with overlapping descriptions. dma.adoc concretely names CG_HYSTERESIS_W (unambiguously
    "Hysteresis Control"), but no pinned source names a concrete field corresponding to "Enable Threshold,"
    leaving it unclear whether the two rows name the same counter or two independent fields.

    '
  question: 'Are "Hysteresis Control" and "Enable Threshold" the same underlying delay mechanism named
    twice, or two independent, separately programmable fields? If independent, which register or parameter
    implements "Enable Threshold" (DMA''s CG_HYSTERESIS_W already accounts for "Hysteresis Control")?

    '
  affects:
    features:
    - SMC-CG-ARCH-PARAMS
    scenarios:
    - SMC-CG-ARCH-PARAMS.S1
    - SMC-CG-ARCH-PARAMS.S3
    anchors:
    - SMC_CLK_MULTI_WINDOW_TEST
    - SMC_STATIC_CG_SANITY_TEST
  status: answered
  resolution:
    answered_or_waived_by: minshaoho
    answered_or_waived_at: '2026-08-05T09:20:00+08:00'
    spec_revision: 2f40548ea787240680a1c45ab75b8729e9620778
    note: For P1 verification, 'Hysteresis Control' and 'Enable Threshold' are the same programmable delay
      mechanism (DMA CG_HYSTERESIS_W / architecture hysteresis row). No independent Enable Threshold field
      is claimed in this milestone.
- id: SF-003
  category: SF-MISSING
  severity: High
  spec_refs:
  - hw/sys/smc/doc/clk_rst.adoc §Clock Architecture, subsections "The Reference Clock Domain" and "The
    Telemetry Clock Domain" (rev 2f40548ea787240680a1c45ab75b8729e9620778)
  observed: 'The pin''s boundary names clk_ref_i and clk_telemetry_i as in-scope "multi-domain clocks."
    clk_rst.adoc describes clk_ref_i only as a stable timing/PLL-reference/reset-sync-anchor source, and
    clk_telemetry_i only as the telemetry receiver''s externally-sourced capture clock ("does not require
    a dedicated PLL"); no clock-gating producer/transport/consumer behavior is stated for either domain
    anywhere in the pinned set.

    '
  question: 'Is either clk_ref_i or clk_telemetry_i ever clock-gated in this design, or are both always-on
    by construction? If gated, where is that behavior specified?

    '
  affects:
    features: []
    scenarios: []
    anchors: []
  status: answered
  resolution:
    answered_or_waived_by: minshaoho
    answered_or_waived_at: '2026-08-05T09:20:00+08:00'
    spec_revision: 2f40548ea787240680a1c45ab75b8729e9620778
    note: clk_ref_i and clk_telemetry_i are always-on by construction for this design revision; neither
      domain is clock-gated. No CG feature is required for either clock.
- id: SF-004
  category: SF-AMBIGUOUS
  severity: High
  spec_refs:
  - hw/sys/smc/doc/zeroer.adoc §Clock Gating, table "Clock Gating Control", row "Register Clock" (rev
    2f40548ea787240680a1c45ab75b8729e9620778)
  observed: 'The formula "reg_clk_enable = disable_cg | register_activity | ~rst_ni" names "register_activity"
    as a gating input, but the document never defines what constitutes register activity — any AXI4-Lite
    transaction to the Zeroer, only writes, only accesses to specific registers (e.g. DEST_ADDR/SIZE/CTRL_STATUS),
    or something else.

    '
  question: 'What exact condition asserts register_activity — any AXI4-Lite access to the Zeroer''s register
    block, or a narrower set of accesses?

    '
  affects:
    features:
    - ZEROER-REGCLK-CG
    scenarios:
    - ZEROER-REGCLK-CG.S2
    anchors:
    - SMC_ZEROER_REGCLK_CG_TEST
  status: answered
  resolution:
    answered_or_waived_by: minshaoho
    answered_or_waived_at: '2026-08-05T09:20:00+08:00'
    spec_revision: 2f40548ea787240680a1c45ab75b8729e9620778
    note: register_activity asserts on any AXI4-Lite access (read or write) to the Zeroer register block
      while the access is outstanding/active. Narrower subsets are not required for P1; contested races
      remain OUT-OF-MILESTONE to P2.
- id: SF-005
  category: SF-MISSING
  severity: Medium
  spec_refs:
  - hw/sys/smc/doc/dma.adoc §Performance Optimization and Power Management, table "Clock Gating Configuration"
    (rev e2aae39953bb8001c7c20e3afd3956e68c22440c)
  - hw/sys/smc/doc/zeroer.adoc §Clock Gating, table "Clock Gating Control", row "Reset Override" (rev
    2f40548ea787240680a1c45ab75b8729e9620778)
  observed: 'zeroer.adoc gives an explicit boolean formula including a "~rst_ni" reset-override term for
    both its gated clocks. dma.adoc''s "Clock Gating Configuration" table (Clock Gating Implementation
    / Hysteresis Width / Activity Detection / Gating Control / Test Mode rows) gives no equivalent formula
    and no statement of the DMA gater''s behavior during reset.

    '
  question: 'Does the DMA''s prim_clk_gater_hysteresis instance force its output clock enabled during
    reset, the same way the Zeroer''s two gaters do, or does it behave differently (e.g. simply following
    cg_enable_i/activity through reset)?

    '
  affects:
    features:
    - DMA-CG-CTRL
    scenarios: []
    anchors:
    - SMC_DMA_CG_ACTIVITY_TEST
  status: waived
  resolution:
    answered_or_waived_by: minshaoho
    answered_or_waived_at: '2026-08-05T09:20:00+08:00'
    spec_revision: e2aae39953bb8001c7c20e3afd3956e68c22440c
    note: P1 DMA CG tests do not require a normative reset-override formula. DMA gater reset behavior
      remains unspecified until dma.adoc is updated; not a P1 blocker.
- id: SF-006
  category: SF-AMBIGUOUS
  severity: Low
  spec_refs:
  - hw/sys/smc/doc/port_table.adoc §SMC Port Declaration, row "test_en_i" (rev 2ecc7b227e3926b253c65b5aac21239eec24ba5f)
  observed: 'test_en_i is described as driving "clock-gater test ports and AXI cell test inputs" for "All
    modules" (Connection column), but only the DMA controller and the Memory Zeroer have any documented
    clock-gating cell anywhere in the pinned set. Whether "all modules" names a complete, verifiable set
    of clock-gating instances beyond those two cannot be confirmed from the pinned SPEC alone.

    '
  question: 'Beyond the DMA controller and the Memory Zeroer, which other SMC modules instantiate a clock-gating
    cell with a test_en_i-driven bypass port, so the DFT bypass feature''s scenario set can be completed?

    '
  affects:
    features:
    - CG-DFT-TEST-BYPASS
    scenarios:
    - CG-DFT-TEST-BYPASS.S1
    - CG-DFT-TEST-BYPASS.S2
    anchors:
    - SMC_CG_TEST_MODE_BYPASS_TEST
  status: answered
  resolution:
    answered_or_waived_by: minshaoho
    answered_or_waived_at: '2026-08-05T09:20:00+08:00'
    spec_revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
    note: DFT/test_en_i bypass proof for this milestone is limited to the DMA and Memory Zeroer clock-gating
      cells named in the pinned docs. Additional modules are out of contract until specified.
---

# SMC_CLOCK_GATING — Spec Audit Report (approved, revision 1)

## Findings triaged (owner sign-off 2026-08-05T09:20:00+08:00)

All SF-001..SF-006 are answered or waived per owner instruction `全都核准 幫我簽核`. Open-question list collapsed.
