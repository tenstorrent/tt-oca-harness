---
schema: dv-quality/v1
artifact: checkbox-cards
artifact_revision: 1
content_sha256: 4050055c70d00e6ffc6f10104fd5d90adabdb5f6d803324d867a008669a6970b
ip: SMC_CLOCK_GATING_P0
milestone: P0
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
  run_id: dv_vplan_gen-SMC_CLOCK_GATING_P0-P0-20260805T151500+0800-fresh
  model:
    provider: anthropic
    family: claude
    version: sonnet-5
derivation_provenance:
  sealed_derivation: true
  anchor_seal_mechanism: ordered-single-context
  fresh_context_route: fresh-subagent
  feature_list_frozen_at: '2026-08-05T15:30:00+08:00'
approved_by: minshaoho
approved_at: '2026-08-05T15:52:00+08:00'
cards:
- id: SMCCGP0_001
  anchor: smc_clk_running_test
  revision: 1
  supersedes_revision: null
  current: true
  status: approved
  record_sha256: c9a8f2011802914da1e11a25c66a37abbfcfed17058830392c07cfd14228c33c
  approved_by: minshaoho
  approved_at: '2026-08-05T15:52:00+08:00'
  category: DMA activity-driven gating + concurrent Zeroer idle-gate + CG-enable CSR reachability
  owns: DMA activity-driven ungate/idle-gate behavior, concurrent Zeroer idle-gate reinforcement, and
    DMA/Zeroer clock-gate-enable register reachability
  evidence_class: frontdoor-func
  closure_tier: A
  derived_from:
    plan_revision: 1
    testcase_revision: 1
    testcase_record_sha256: 0d033ae30973d5d21f601d2782614dbdaad3d7fa560ff3cd922534e826ce3ca9
    allocated_scenarios:
    - SMC-CG-DMA.S2
    - SMC-CG-DMA.S3
    - SMC-CG-ZEROER.S3
    - SMC-CG-ENABLE-CTRL.S1
    - SMC-CG-ENABLE-CTRL.S2
    testcase_id: SMCCGP0_001
  description:
    producer: firmware/frontdoor CLOCK_GATE_CONTROL register write, plus a DMA descriptor that drives
      frontend wakeup / backend busy
    transport: the CSR write path into cg_enable_i/disable_cg, and the DMA activity-detection path into
      its own hysteresis-gated clock branch
    consumer: DMA gated clock branch and Zeroer axi_clk domain
  steps:
  - id: S1
    text: frontdoor-write CLOCK_GATE_CONTROL with DMA_CG_EN=1, ZEROER_CG_EN=1, then read the register
      back and compare against the written value
    derived_from:
    - SMC-CG-ENABLE-CTRL.S1
    - SMC-CG-ENABLE-CTRL.S2
  - id: S2
    text: with gating enabled and no DMA descriptor programmed yet, sample dma_gated_clk and zeroer_axi_gated_clk
      for a fixed window
    derived_from:
    - SMC-CG-DMA.S2
    - SMC-CG-ZEROER.S3
  - id: S3
    text: program and trigger one DMA transfer descriptor (frontend wakeup, then backend busy) and sample
      dma_gated_clk through the transfer while continuing to sample zeroer_axi_gated_clk
    derived_from:
    - SMC-CG-DMA.S3
  - id: S4
    text: bounded wait for DMA transfer completion, TIMEOUT fails with last state
    derived_from: []
  randomization: DIRECTED rollup of five scenario records
  observation: cycle-accurate sampling of dma_gated_clk / zeroer_axi_gated_clk TB observation taps; frontdoor
    CSR readback for the enable bits
  checkers:
  - id: CHK-CG-ENABLE-READBACK
    checks_steps:
    - S1
    proves:
    - SMC-CG-ENABLE-CTRL
    covers:
    - SMC-CG-ENABLE-CTRL.S1
    - SMC-CG-ENABLE-CTRL.S2
    proof_class: CONNECTIVITY
    expect_source: hw/sys/smc/doc/clk_rst.adoc "Clock and Reset-Based Power Management Integration"
    proof: CLOCK_GATE_CONTROL readback DMA_CG_EN=1 and ZEROER_CG_EN=1, matching the written value
    fail_on: readback mismatch, X on either field, or write not observed
    lifecycle: null
  - id: CHK-IDLE-GATED-BASELINE
    checks_steps:
    - S2
    proves:
    - SMC-CG-DMA
    - SMC-CG-ZEROER
    covers:
    - SMC-CG-DMA.S2
    - SMC-CG-ZEROER.S3
    proof_class: LIVE
    expect_source: hw/sys/smc/doc/dma.adoc "Clock Gating Configuration - Activity Detection"; hw/sys/smc/doc/zeroer.adoc
      "Clock Gating - AXI Clock"
    proof: dma_gated_clk toggle_count=0 and zeroer_axi_gated_clk toggle_count=0 across the full sample
      window
    fail_on: any toggle observed on either clock, X, or wrong sample count
    lifecycle: null
  - id: CHK-DMA-ACTIVITY-UNGATE
    checks_steps:
    - S3
    proves:
    - SMC-CG-DMA
    covers:
    - SMC-CG-DMA.S3
    proof_class: LIVE
    expect_source: hw/sys/smc/doc/dma.adoc "Clock Gating Configuration - Activity Detection"
    proof: dma_gated_clk toggles continuously from frontend-wakeup assertion through backend-busy deassertion
    fail_on: toggle gap during the activity window, toggle_count below expected, or X
    lifecycle: null
  - id: CHK-NONVAC
    checks_steps:
    - S1
    - S2
    - S3
    proves: []
    covers: []
    proof_class: INTEGRITY
    expect_source: approved card ordering contract
    proof: CG-ENABLE-READBACK < IDLE-GATED-BASELINE < DMA-ACTIVITY-UNGATE, each with its own timestamp
    fail_on: testcase pass with any term missing or out of order
    lifecycle: null
  - id: CHK-TIMEOUT-PATHS
    checks_steps:
    - S4
    proves: []
    covers: []
    proof_class: INTEGRITY
    expect_source: approved card timeout contract
    proof: the DMA-completion wait logs a finite bound, its fail-on-expiry path, and last state
    fail_on: unbounded wait, ignored timeout, or expiry without testcase failure
    lifecycle: null
  guardrails:
  - no internal write/force/deposit; passive hierarchical reads allowed (tb_* observation ports); frontdoor
    CSR access only
  blockers: []
- id: SMCCGP0_002
  anchor: smc_static_cg_sanity_test
  revision: 1
  supersedes_revision: null
  current: true
  status: approved
  record_sha256: 3e58481e3b0cf7321a51f26a98560768603af989a54bb69cf5e776f5b9e6d34b
  approved_by: minshaoho
  approved_at: '2026-08-05T15:52:00+08:00'
  category: DMA and Zeroer gate-disabled free-running (module-level enable/disable boundary)
  owns: DMA gate-disabled free-running and Zeroer gate-disabled free-running (module-level enable/disable
    boundary)
  evidence_class: frontdoor-func
  closure_tier: A
  derived_from:
    plan_revision: 1
    testcase_revision: 1
    testcase_record_sha256: 1f5b76cb4385fb6652f42dce64b040c578e5722f373560b5a6143f493b19060c
    allocated_scenarios:
    - SMC-CG-DMA.S4
    - SMC-CG-ZEROER.S7
    testcase_id: SMCCGP0_002
  description:
    producer: firmware/frontdoor CLOCK_GATE_CONTROL register write clearing one module's gate-enable bit
      at a time
    transport: the CSR write path into cg_enable_i / disable_cg
    consumer: DMA gated clock branch and Zeroer axi_clk/reg_clk domains
  steps:
  - id: S1
    text: frontdoor-write CLOCK_GATE_CONTROL with DMA_CG_EN=0, ZEROER_CG_EN=1, and no DMA activity
    derived_from: []
  - id: S2
    text: sample dma_gated_clk for a fixed window with no DMA activity
    derived_from:
    - SMC-CG-DMA.S4
  - id: S3
    text: frontdoor-write CLOCK_GATE_CONTROL with ZEROER_CG_EN=0, DMA_CG_EN=1, and no Zeroer activity
    derived_from: []
  - id: S4
    text: sample zeroer_axi_gated_clk and zeroer_reg_gated_clk for a fixed window with no Zeroer activity
    derived_from:
    - SMC-CG-ZEROER.S7
  randomization: DIRECTED rollup of two scenario records
  observation: cycle-accurate sampling of dma_gated_clk / zeroer_axi_gated_clk / zeroer_reg_gated_clk
    TB observation taps
  checkers:
  - id: CHK-DMA-GATE-DISABLED-FREE-RUN
    checks_steps:
    - S2
    proves:
    - SMC-CG-DMA
    covers:
    - SMC-CG-DMA.S4
    proof_class: LIVE
    expect_source: hw/sys/smc/doc/dma.adoc "Clock Gating Configuration - Gating Control"
    proof: dma_gated_clk toggles continuously for the full sample window with cg_enable_i deasserted and
      no frontend/backend activity
    fail_on: any gated interval, toggle_count below expected, or X
    lifecycle: null
  - id: CHK-ZEROER-GATE-DISABLED-FREE-RUN
    checks_steps:
    - S4
    proves:
    - SMC-CG-ZEROER
    covers:
    - SMC-CG-ZEROER.S7
    proof_class: LIVE
    expect_source: hw/sys/smc/doc/zeroer.adoc "Clock Gating"
    proof: zeroer_axi_gated_clk and zeroer_reg_gated_clk both toggle continuously for the full sample
      window with disable_cg asserted and no busy/register activity
    fail_on: any gated interval on either clock, toggle_count below expected, or X
    lifecycle: null
  - id: CHK-NONVAC
    checks_steps:
    - S1
    - S2
    - S3
    - S4
    proves: []
    covers: []
    proof_class: INTEGRITY
    expect_source: approved card ordering contract
    proof: DMA-GATE-DISABLED-FREE-RUN < ZEROER-GATE-DISABLED-FREE-RUN, each with its own timestamp
    fail_on: testcase pass with any term missing or out of order
    lifecycle: null
  guardrails:
  - no internal write/force/deposit; passive hierarchical reads allowed (tb_* observation ports); frontdoor
    CSR access only
  blockers: []
- id: SMCCGP0_003
  anchor: smc_cg_dft_reset_bringup_test
  revision: 1
  supersedes_revision: null
  current: true
  status: approved
  record_sha256: 14b3775169e65fc707b9fdcd7c6dec6f9d817c002225fc23bbe4eaeefa702640
  approved_by: minshaoho
  approved_at: '2026-08-05T15:52:00+08:00'
  category: DFT test_en_i bypass (DMA + Zeroer) and Zeroer reset override
  owns: DFT test_en_i bypass for DMA and Zeroer gating, and Zeroer reset-override free-running
  evidence_class: frontdoor-func
  closure_tier: B
  derived_from:
    plan_revision: 1
    testcase_revision: 1
    testcase_record_sha256: 1c1053289e15ccfa6dd29d0e1711bcfd540f51ab071234d456097e9669600b2b
    allocated_scenarios:
    - SMC-CG-DMA.S1
    - SMC-CG-ZEROER.S1
    - SMC-CG-ZEROER.S2
    testcase_id: SMCCGP0_003
  description:
    producer: top-level test_en_i DFT override input, and rst_ni reset input
    transport: the override mux ahead of each per-module clock gater (DMA gater; Zeroer axi_clk/reg_clk
      gaters)
    consumer: DMA gated clock branch and Zeroer axi_clk/reg_clk domains
  steps:
  - id: S1
    text: assert test_en_i; frontdoor-write CLOCK_GATE_CONTROL with DMA_CG_EN=1, ZEROER_CG_EN=1; no module
      activity
    derived_from: []
  - id: S2
    text: sample dma_gated_clk, zeroer_axi_gated_clk, and zeroer_reg_gated_clk for a fixed window with
      test_en_i asserted
    derived_from:
    - SMC-CG-DMA.S1
    - SMC-CG-ZEROER.S2
  - id: S3
    text: deassert test_en_i; assert rst_ni (reset held); gating still enabled
    derived_from: []
  - id: S4
    text: sample zeroer_axi_gated_clk and zeroer_reg_gated_clk for a fixed window with rst_ni asserted
    derived_from:
    - SMC-CG-ZEROER.S1
  randomization: DIRECTED rollup of three scenario records
  observation: cycle-accurate sampling of dma_gated_clk / zeroer_axi_gated_clk / zeroer_reg_gated_clk
    TB observation taps
  checkers:
  - id: CHK-DFT-BYPASS-FREE-RUN
    checks_steps:
    - S2
    proves:
    - SMC-CG-DMA
    - SMC-CG-ZEROER
    covers:
    - SMC-CG-DMA.S1
    - SMC-CG-ZEROER.S2
    proof_class: LIVE
    expect_source: hw/sys/smc/doc/dma.adoc "Clock Gating Configuration - Test Mode"; hw/sys/smc/doc/zeroer.adoc
      "Clock Gating - Test Support"
    proof: dma_gated_clk, zeroer_axi_gated_clk, and zeroer_reg_gated_clk all toggle continuously for the
      full sample window with test_en_i asserted and gating enabled
    fail_on: any gated interval on any of the three clocks, toggle_count below expected, or X
    lifecycle: null
  - id: CHK-RESET-OVERRIDE-FREE-RUN
    checks_steps:
    - S4
    proves:
    - SMC-CG-ZEROER
    covers:
    - SMC-CG-ZEROER.S1
    proof_class: CONNECTIVITY
    expect_source: hw/sys/smc/doc/zeroer.adoc "Clock Gating - Reset Override"
    proof: zeroer_axi_gated_clk and zeroer_reg_gated_clk both toggle continuously for the full sample
      window with rst_ni asserted
    fail_on: any gated interval on either clock, toggle_count below expected, or X
    lifecycle: null
  - id: CHK-NONVAC
    checks_steps:
    - S1
    - S2
    - S3
    - S4
    proves: []
    covers: []
    proof_class: INTEGRITY
    expect_source: approved card ordering contract
    proof: DFT-BYPASS-FREE-RUN < RESET-OVERRIDE-FREE-RUN, each with its own timestamp
    fail_on: testcase pass with any term missing or out of order
    lifecycle: null
  guardrails:
  - no internal write/force/deposit; passive hierarchical reads allowed (tb_* observation ports); frontdoor
    CSR access only
  blockers: []
- id: SMCCGP0_004
  anchor: smc_cg_zeroer_activity_bringup_test
  revision: 1
  supersedes_revision: null
  current: true
  status: approved
  record_sha256: 91aeaf4f6e050ebe2fa76dca6013bcfd5a9acee9661d87794a275ceb61954acd
  approved_by: minshaoho
  approved_at: '2026-08-05T15:52:00+08:00'
  category: Zeroer axi_clk + reg_clk activity-driven gate/ungate, single zero operation
  owns: Zeroer axi_clk and reg_clk activity-driven idle-gate/ungate behavior triggered by one zero operation
  evidence_class: frontdoor-func
  closure_tier: A
  derived_from:
    plan_revision: 1
    testcase_revision: 1
    testcase_record_sha256: ad90a6ffe25462797477d28fbc5ef3d6bf3c5ab3b38f384757cd94872e3e23f7
    allocated_scenarios:
    - SMC-CG-ZEROER.S4
    - SMC-CG-ZEROER.S5
    - SMC-CG-ZEROER.S6
    testcase_id: SMCCGP0_004
  description:
    producer: one firmware-triggered zero operation (DEST_ADDR/SIZE register programming, then a CTRL_STATUS
      start write) producing register_activity and zeroer_busy_o
    transport: two prim_clkgater instances, one per clock domain (axi_clk, reg_clk), each gated by its
      own activity signal
    consumer: Zeroer AXI master datapath (axi_clk) and Zeroer register interface (reg_clk)
  steps:
  - id: S1
    text: frontdoor-write CLOCK_GATE_CONTROL with ZEROER_CG_EN=1; with no register activity and zeroer_busy_o=0,
      sample zeroer_reg_gated_clk for a fixed window
    derived_from:
    - SMC-CG-ZEROER.S5
  - id: S2
    text: program DEST_ADDR/SIZE and write CTRL_STATUS to start one zero operation over a small region,
      sampling zeroer_reg_gated_clk across the register writes
    derived_from:
    - SMC-CG-ZEROER.S6
  - id: S3
    text: sample zeroer_axi_gated_clk and zeroer_busy_o from operation start through completion
    derived_from:
    - SMC-CG-ZEROER.S4
  - id: S4
    text: bounded wait for zero-operation completion (zeroer_busy_o=0), TIMEOUT fails with last state
    derived_from: []
  randomization: DIRECTED rollup of three scenario records
  observation: cycle-accurate sampling of zeroer_axi_gated_clk / zeroer_reg_gated_clk TB observation taps;
    zeroer_busy_o / CTRL_STATUS frontdoor readback
  checkers:
  - id: CHK-REG-CLK-IDLE-GATED
    checks_steps:
    - S1
    proves:
    - SMC-CG-ZEROER
    covers:
    - SMC-CG-ZEROER.S5
    proof_class: LIVE
    expect_source: hw/sys/smc/doc/zeroer.adoc "Clock Gating - Register Clock"
    proof: zeroer_reg_gated_clk toggle_count=0 across the full sample window with no register activity
    fail_on: any toggle observed, X, or wrong sample count
    lifecycle: null
  - id: CHK-REG-ACCESS-UNGATES-REG-CLK
    checks_steps:
    - S2
    proves:
    - SMC-CG-ZEROER
    covers:
    - SMC-CG-ZEROER.S6
    proof_class: LIVE
    expect_source: hw/sys/smc/doc/zeroer.adoc "Clock Gating - Register Clock"
    proof: zeroer_reg_gated_clk toggles coincident with the DEST_ADDR/ SIZE/CTRL_STATUS register writes
    fail_on: no toggle during the register-write window, X, or toggle starting before the first write
    lifecycle: null
  - id: CHK-BUSY-UNGATES-AXI-CLK
    checks_steps:
    - S3
    proves:
    - SMC-CG-ZEROER
    covers:
    - SMC-CG-ZEROER.S4
    proof_class: LIVE
    expect_source: hw/sys/smc/doc/zeroer.adoc "Clock Gating - AXI Clock"
    proof: zeroer_axi_gated_clk toggles continuously for the full zeroer_busy_o=1 interval
    fail_on: toggle gap while zeroer_busy_o=1, toggle_count below expected, or X
    lifecycle: null
  - id: CHK-NONVAC
    checks_steps:
    - S1
    - S2
    - S3
    proves: []
    covers: []
    proof_class: INTEGRITY
    expect_source: approved card ordering contract
    proof: REG-CLK-IDLE-GATED < REG-ACCESS-UNGATES-REG-CLK < BUSY-UNGATES-AXI-CLK, each with its own timestamp
    fail_on: testcase pass with any term missing or out of order
    lifecycle: null
  - id: CHK-TIMEOUT-PATHS
    checks_steps:
    - S4
    proves: []
    covers: []
    proof_class: INTEGRITY
    expect_source: approved card timeout contract
    proof: the zero-operation-completion wait logs a finite bound, its fail-on-expiry path, and last state
    fail_on: unbounded wait, ignored timeout, or expiry without testcase failure
    lifecycle: null
  guardrails:
  - no internal write/force/deposit; passive hierarchical reads allowed (tb_* observation ports); frontdoor
    CSR access only
  blockers: []
---

# SMC_CLOCK_GATING_P0 — Checkbox Cards (candidate v1)

Four cards, one per testcase in the plan, closing all thirteen frozen
scenarios. No card forces or deposits into RTL state — every producer is a
frontdoor CSR write or a top-level pin (`test_en_i`, `rst_ni`), and every
consumer observation is a passive hierarchical read of a TB clock-observation
tap or a frontdoor CSR readback, per the pin's P0 bring-up boundary.
