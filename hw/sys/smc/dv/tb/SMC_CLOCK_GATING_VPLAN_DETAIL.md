---
schema: dv-quality/v1
artifact: checkbox-cards
artifact_revision: 3
content_sha256: c097f008eb7eb94183188970bf1c95c21977bc6c721f0b9bc65d735324834f69
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
  run_id: dv_vplan_gen-SMC_CLOCK_GATING-P1-20260805T132000+0800-amend-int-zeroer-cg-indep
  model:
    provider: cursor
    family: grok
    version: '4.5'
derivation_provenance:
  sealed_derivation: false
  anchor_seal_mechanism: ordered-single-context
  fresh_context_route: fresh-subagent
  feature_list_frozen_at: '2026-08-05T08:20:00+08:00'
  note: 'AMENDMENT 2026-08-05: add card SMC_ZEROER_CG_INDEP_TEST for INT-ZEROER-CG-INDEP (artifact_revision
    3). Existing seven current cards unchanged (still cite plan_revision 1 / their approved parents).
    MERGED-EVIDENCE: interaction checker proves ZEROER-AXICLK-CG + ZEROER-REGCLK-CG jointly; single-feature
    checkers remain on SMC_ZEROER_AXICLK_CG_TEST and SMC_ZEROER_REGCLK_CG_TEST. No force/deposit in stimulus.
    Prior seal caveat retained.'
approved_by: minshaoho
approved_at: '2026-08-05T09:20:00+08:00'
cards:
- id: SMC_CLK_MULTI_WINDOW_TEST
  anchor: smc_clk_multi_window_test
  revision: 1
  supersedes_revision: null
  current: true
  status: approved
  record_sha256: b1458f8522c1c4931dd63acd0c575aef4d60110ac0aa69a77016821f04ac2a86
  approved_by: minshaoho
  approved_at: '2026-08-05T09:20:00+08:00'
  category: SMC clock-gating architecture (generic hysteresis)
  owns: 'SMC-level generic hysteresis-window timing claim only (clk_rst.adoc architecture table); not
    the DMA/Zeroer instance-specific timing owned by SMC_DMA_CG_ACTIVITY_TEST / SMC_ZEROER_AXICLK_CG_TEST
    / SMC_ZEROER_REGCLK_CG_TEST.

    '
  evidence_class: frontdoor-func
  closure_tier: B
  derived_from:
    plan_revision: 1
    testcase_revision: 1
    testcase_record_sha256: 4c7bf76fa91c76e37339db6bfed59f067c146c72a7c9576d0b361ad71211d550
    allocated_scenarios:
    - SMC-CG-ARCH-PARAMS.S1
  description:
    producer: the SMC-level programmable hysteresis-count field named in clk_rst.adoc's power-management
      integration table
    transport: the per-module clock-gating cell within the SMC clock/reset unit
    consumer: the gated module clock, held stable against gating oscillation
  steps:
  - id: S1
    text: 'Program the module''s hysteresis-count field to a value near the low end of its legal range,
      drive the module active then idle, and measure the delay before its gated clock re-gates.

      '
    derived_from:
    - SMC-CG-ARCH-PARAMS.S1
  - id: S2
    text: 'Repeat with the hysteresis-count field programmed to a mid-range value and observe the re-gate
      delay scales accordingly.

      '
    derived_from:
    - SMC-CG-ARCH-PARAMS.S1
  - id: S3
    text: 'Repeat with the hysteresis-count field programmed to the high end of its legal range and observe
      the re-gate delay scales accordingly, with no oscillation of the gated clock during the idle window.

      '
    derived_from:
    - SMC-CG-ARCH-PARAMS.S1
  randomization: 'Rollup of SMC-CG-ARCH-PARAMS.S1''s RANDOMIZED coverage record (random_knobs: programmed_hysteresis_count;
    required_cells: hysteresis_delay_min/mid/max); that scenario record remains authoritative.

    '
  observation: 'Passive hierarchical read/toggle-count of the module''s gated clock net at cycle resolution
    across each hysteresis-window measurement; an X/Z or missing sample on the gated clock during the
    measured window is treated as unobservable and fails the checker.

    '
  checkers:
  - id: CHK-HYST-WINDOW
    checks_steps:
    - S1
    - S2
    - S3
    proves:
    - SMC-CG-ARCH-PARAMS
    covers:
    - SMC-CG-ARCH-PARAMS.S1
    proof_class: LIVE
    expect_source: hw/sys/smc/doc/clk_rst.adoc §Clock and Reset-Based Power Management Integration, row
      "Hysteresis Control" (rev 2f40548ea787240680a1c45ab75b8729e9620778)
    proof: 'CHK-HYST-WINDOW: for each of the low/mid/high programmed hysteresis values, the measured re-gate
      delay equals the programmed value within one clock period, and zero gated-clock toggles are observed
      during any idle window before its delay elapses.

      '
    fail_on: 'any measured re-gate delay differs from its programmed hysteresis value by more than one
      clock period; OR a gated-clock toggle observed before the programmed delay elapses; OR an X/Z or
      missing sample on the gated clock during a measured window; OR the test times out before all three
      windows are measured.

      '
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
    proof: 'CHK-NONVAC: the ordered fence low-window-measured < mid-window-measured < high-window-measured
      < PASS all hold, in that order, before the testcase reports pass.

      '
    fail_on: 'testcase pass with any fence term missing or out of order, or progress logged in place of
      a real PASS.

      '
    lifecycle: null
  guardrails:
  - No internal write/force/deposit on the hysteresis-count field or the gated clock net — closing this
    anchor requires frontdoor CSR programming and passive clock observation only [NO-BACKDOOR-WRITE]
  - No fixed-delay stand-in for the hysteresis-window measurement — the re-gate delay must be measured
    against the actual last-toggle event, not a blind wait [NO-BLIND-DELAY-SYNC]
  blockers: []
- id: SMC_CLK_RUNNING_TEST
  anchor: smc_clk_running_test
  revision: 1
  supersedes_revision: null
  current: true
  status: approved
  record_sha256: f62af0cbf3bba2af20a2d632e3c7e626e5896e25a0867957e0d140d99a1cb8fd
  approved_by: minshaoho
  approved_at: '2026-08-05T09:20:00+08:00'
  category: SMC clock-gating architecture (generic activity detection)
  owns: SMC-level generic activity-detection-keeps-clock-running claim only.
  evidence_class: frontdoor-func
  closure_tier: B
  derived_from:
    plan_revision: 1
    testcase_revision: 1
    testcase_record_sha256: c91b2feb06e2c2e916109dce085fddfea9c7b7dbb65d87e33775ac08caba6e32
    allocated_scenarios:
    - SMC-CG-ARCH-PARAMS.S2
  description:
    producer: per-module activity-detection signals named in clk_rst.adoc's power-management integration
      table
    transport: the per-module clock-gating cell within the SMC clock/reset unit
    consumer: each named functional block's independently gated clock
  steps:
  - id: S1
    text: 'Drive one functional module''s activity indicator asserted (active) and observe its own gated
      clock output continues toggling every cycle.

      '
    derived_from:
    - SMC-CG-ARCH-PARAMS.S2
  - id: S2
    text: 'With that module still asserted active, drive an independent second module''s activity indicator
      deasserted (idle) and observe the second module''s gated clock gates off while the first module''s
      stays running.

      '
    derived_from:
    - SMC-CG-ARCH-PARAMS.S2
  randomization: None — SMC-CG-ARCH-PARAMS.S2's coverage record is DIRECTED (module_active_clock_running,
    module_idle_clock_gated).
  observation: 'Passive hierarchical toggle observation of both modules'' gated clock nets at cycle resolution,
    sampled concurrently so the two modules'' states are compared in the same observation window; an X/Z
    or missing sample on either clock is unobservable and fails the checker.

    '
  checkers:
  - id: CHK-ACTIVE-RUNNING
    checks_steps:
    - S1
    - S2
    proves:
    - SMC-CG-ARCH-PARAMS
    covers:
    - SMC-CG-ARCH-PARAMS.S2
    proof_class: LIVE
    expect_source: hw/sys/smc/doc/clk_rst.adoc §Clock and Reset-Based Power Management Integration, row
      "Activity Detection" (rev 2f40548ea787240680a1c45ab75b8729e9620778)
    proof: 'CHK-ACTIVE-RUNNING: the active module''s gated clock toggles every cycle for the full observed
      active window while the concurrently idle module''s gated clock stops toggling in the same window,
      evidencing independent per-module gating decisions.

      '
    fail_on: 'the active module''s clock shows any missing toggle or X/Z during the active window; OR
      the idle module''s clock fails to gate off in the same window; OR the two modules'' states are not
      observed concurrently.

      '
    lifecycle: null
  - id: CHK-NONVAC
    checks_steps:
    - S1
    - S2
    proves: []
    covers: []
    proof_class: INTEGRITY
    expect_source: approved card ordering contract
    proof: 'CHK-NONVAC: the ordered fence active-module-observed < idle-module-observed < PASS all hold,
      in that order, before the testcase reports pass.

      '
    fail_on: 'testcase pass with any fence term missing or out of order, or progress logged in place of
      a real PASS.

      '
    lifecycle: null
  guardrails:
  - No internal write/force/deposit on either module's activity indicator or gated clock net — frontdoor
    stimulus and passive observation only [NO-BACKDOOR-WRITE]
  blockers: []
- id: SMC_STATIC_CG_SANITY_TEST
  anchor: smc_static_cg_sanity_test
  revision: 1
  supersedes_revision: null
  current: true
  status: approved
  record_sha256: dd59e7b200aba458784d03f8e04dfcd55377243446a0b2a61397f8a9ec99afc5
  approved_by: minshaoho
  approved_at: '2026-08-05T09:20:00+08:00'
  category: SMC clock-gating architecture (generic static module gating)
  owns: SMC-level generic static module-gating enable/disable and enable-threshold delay claims only.
  evidence_class: frontdoor-func
  closure_tier: B
  derived_from:
    plan_revision: 1
    testcase_revision: 1
    testcase_record_sha256: bd3ff0d4488f120d7b6b9e08981e7d9570a8aaa947582e08951b40df609f6ff8
    allocated_scenarios:
    - SMC-CG-ARCH-PARAMS.S3
    - SMC-CG-ARCH-PARAMS.S4
  description:
    producer: per-module gating-enable/disable bits and the enable-threshold delay field named in clk_rst.adoc's
      power-management integration table
    transport: the per-module clock-gating cell within the SMC clock/reset unit
    consumer: each named functional block's gated clock, in its statically configured state
  steps:
  - id: S1
    text: 'Program a module''s individual gating-enable bit to disabled and observe its gated clock stays
      continuously enabled regardless of activity.

      '
    derived_from:
    - SMC-CG-ARCH-PARAMS.S4
  - id: S2
    text: 'Program that module''s gating-enable bit to enabled, with a second independent module''s gating-enable
      bit left at the opposite setting, and observe each module''s gating state follows only its own bit.

      '
    derived_from:
    - SMC-CG-ARCH-PARAMS.S4
  - id: S3
    text: 'With gating enabled, program the enable-threshold delay field to its minimum legal value and
      observe the measured threshold delay before the clock''s enable decision responds to new activity
      matches the programmed minimum.

      '
    derived_from:
    - SMC-CG-ARCH-PARAMS.S3
  - id: S4
    text: 'Repeat S3 with the enable-threshold delay field programmed to its maximum legal value and observe
      the measured delay scales accordingly.

      '
    derived_from:
    - SMC-CG-ARCH-PARAMS.S3
  randomization: 'Rollup of SMC-CG-ARCH-PARAMS.S3''s RANDOMIZED coverage record (random_knobs: programmed_enable_threshold;
    required_cells: enable_threshold_delay_min/max) exercised at its two boundary values here; SMC-CG-ARCH-PARAMS.S4''s
    coverage record is DIRECTED (module_gating_enabled, module_gating_disabled). Both scenario records
    remain authoritative.

    '
  observation: 'Passive hierarchical toggle observation of both modules'' gated clock nets at cycle resolution;
    an X/Z or missing sample on either clock is unobservable and fails the checker.

    '
  checkers:
  - id: CHK-MODULE-GATING
    checks_steps:
    - S1
    - S2
    proves:
    - SMC-CG-ARCH-PARAMS
    covers:
    - SMC-CG-ARCH-PARAMS.S4
    proof_class: LIVE
    expect_source: hw/sys/smc/doc/clk_rst.adoc §Clock and Reset-Based Power Management Integration, row
      "Module Gating" (rev 2f40548ea787240680a1c45ab75b8729e9620778)
    proof: 'CHK-MODULE-GATING: the disabled-gating module''s clock is observed continuously toggling for
      the entire idle window, and the two independently configured modules'' gating states never track
      each other''s bit across the observed window.

      '
    fail_on: 'the disabled-gating module''s clock gates off at any point; OR the two modules'' gating
      states move together instead of independently; OR X/Z or missing sample on either clock.

      '
    lifecycle: null
  - id: CHK-ENABLE-THRESHOLD
    checks_steps:
    - S3
    - S4
    proves:
    - SMC-CG-ARCH-PARAMS
    covers:
    - SMC-CG-ARCH-PARAMS.S3
    proof_class: LIVE
    expect_source: hw/sys/smc/doc/clk_rst.adoc §Clock and Reset-Based Power Management Integration, row
      "Enable Threshold" (rev 2f40548ea787240680a1c45ab75b8729e9620778)
    proof: 'CHK-ENABLE-THRESHOLD: the measured enable-threshold delay at the minimum and at the maximum
      programmed field value each equal the programmed value within one clock period.

      '
    fail_on: 'either measured delay differs from its programmed threshold value by more than one clock
      period; OR X/Z or missing sample; OR the test times out before both boundary delays are measured.

      '
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
    proof: 'CHK-NONVAC: the ordered fence module-gating-observed < enable-threshold-min-measured < enable-threshold-max-measured
      < PASS all hold, in that order, before the testcase reports pass.

      '
    fail_on: 'testcase pass with any fence term missing or out of order, or progress logged in place of
      a real PASS.

      '
    lifecycle: null
  guardrails:
  - No internal write/force/deposit on either module's gating-enable bit, the enable-threshold field,
    or any gated clock net — frontdoor CSR programming and passive observation only [NO-BACKDOOR-WRITE]
  - No fixed-delay stand-in for the enable-threshold measurement — the delay must be measured against
    the actual response event, not a blind wait [NO-BLIND-DELAY-SYNC]
  blockers: []
- id: SMC_DMA_CG_ACTIVITY_TEST
  anchor: smc_dma_cg_activity_test
  revision: 1
  supersedes_revision: null
  current: false
  status: approved
  record_sha256: 789b6359195836efde49953707a27da94421761aa137bcadcd6d41157e870303
  approved_by: minshaoho
  approved_at: '2026-08-05T09:20:00+08:00'
  category: DMA controller clock gating
  owns: 'The DMA controller''s own activity/enable clock-gating decision (frontend wakeup, backend busy,
    cg_enable_i) for the shared frontend+request-manager+backend clock domain, at P1 nominal function.

    '
  evidence_class: strict-e2e
  closure_tier: A
  derived_from:
    plan_revision: 1
    testcase_revision: 1
    testcase_record_sha256: 392d53ae853d76a3fdfbc7f31a4099290100b25a06fbbd51f47fbd7a09a12469
    allocated_scenarios:
    - DMA-CG-CTRL.S1
    - DMA-CG-CTRL.S2
    - DMA-CG-CTRL.S3
    - DMA-CG-CTRL.S4
  description:
    producer: cg_enable_i configuration input plus DMA activity signals (idma_frontend_wrapper wakeup
      event, idma_backend_wrapper busy status)
    transport: the single prim_clk_gater_hysteresis instance gating the shared DMA clock domain
    consumer: the gated clock feeding idma_frontend_wrapper, idma_request_manager_wrapper, and idma_backend_wrapper
      as one clock domain
  steps:
  - id: S1
    text: 'With cg_enable_i asserted (gating enabled) and neither frontend wakeup nor backend busy asserted,
      hold that idle condition for the programmed hysteresis window and observe the shared DMA clock gates
      off.

      '
    derived_from:
    - DMA-CG-CTRL.S1
  - id: S2
    text: 'With the DMA clock gated off, assert a frontend wakeup event and observe the shared DMA clock
      resumes continuous toggling.

      '
    derived_from:
    - DMA-CG-CTRL.S2
  - id: S3
    text: 'Return the DMA clock to gated-off, then assert a backend busy indication (with no frontend
      wakeup) and observe the shared DMA clock resumes continuous toggling.

      '
    derived_from:
    - DMA-CG-CTRL.S3
  - id: S4
    text: 'Deassert cg_enable_i (gating disabled) with neither frontend wakeup nor backend busy asserted,
      and observe the shared DMA clock stays continuously enabled.

      '
    derived_from:
    - DMA-CG-CTRL.S4
  randomization: None — all four allocated DMA-CG-CTRL scenarios (S1-S4) are DIRECTED.
  observation: 'Passive hierarchical toggle observation of the shared DMA gated clock net at cycle resolution
    across each step''s window; an X/Z or missing sample is unobservable and fails the checker.

    '
  checkers:
  - id: CHK-DMA-GATE-OFF
    checks_steps:
    - S1
    proves:
    - DMA-CG-CTRL
    covers:
    - DMA-CG-CTRL.S1
    proof_class: LIVE
    expect_source: hw/sys/smc/doc/dma.adoc §Performance Optimization and Power Management, table "Clock
      Gating Configuration", rows "Clock Gating Implementation"/"Hysteresis Width" (rev e2aae39953bb8001c7c20e3afd3956e68c22440c)
    proof: 'CHK-DMA-GATE-OFF: the shared DMA clock''s last toggle occurs at most one programmed-hysteresis-window''s
      worth of cycles after the idle condition begins, and the clock stays gated (zero toggles) for the
      remainder of the observed idle window.

      '
    fail_on: 'a toggle observed on the DMA clock beyond the programmed hysteresis window while the idle
      condition persists; OR X/Z or missing sample; OR the test times out before the window elapses.

      '
    lifecycle: null
  - id: CHK-DMA-WAKEUP-FRONTEND
    checks_steps:
    - S2
    proves:
    - DMA-CG-CTRL
    covers:
    - DMA-CG-CTRL.S2
    proof_class: LIVE
    expect_source: hw/sys/smc/doc/dma.adoc §Performance Optimization and Power Management, table "Clock
      Gating Configuration", row "Activity Detection" (rev e2aae39953bb8001c7c20e3afd3956e68c22440c)
    proof: 'CHK-DMA-WAKEUP-FRONTEND: the shared DMA clock resumes toggling every cycle starting within
      one cycle of the frontend wakeup event.

      '
    fail_on: 'the clock stays gated after the wakeup event; OR a toggle is missing in the cycle immediately
      after wakeup; OR X/Z or missing sample.

      '
    lifecycle: null
  - id: CHK-DMA-WAKEUP-BACKEND
    checks_steps:
    - S3
    proves:
    - DMA-CG-CTRL
    covers:
    - DMA-CG-CTRL.S3
    proof_class: LIVE
    expect_source: hw/sys/smc/doc/dma.adoc §Performance Optimization and Power Management, table "Clock
      Gating Configuration", row "Activity Detection" (rev e2aae39953bb8001c7c20e3afd3956e68c22440c)
    proof: 'CHK-DMA-WAKEUP-BACKEND: the shared DMA clock resumes toggling every cycle starting within
      one cycle of the backend busy indication asserting.

      '
    fail_on: 'the clock stays gated after backend busy asserts; OR a toggle is missing in the cycle immediately
      after; OR X/Z or missing sample.

      '
    lifecycle: null
  - id: CHK-DMA-GATING-DISABLED
    checks_steps:
    - S4
    proves:
    - DMA-CG-CTRL
    covers:
    - DMA-CG-CTRL.S4
    proof_class: LIVE
    expect_source: hw/sys/smc/doc/dma.adoc §Performance Optimization and Power Management, table "Clock
      Gating Configuration", row "Gating Control" (rev e2aae39953bb8001c7c20e3afd3956e68c22440c)
    proof: 'CHK-DMA-GATING-DISABLED: the shared DMA clock toggles every cycle for the entire observed
      idle window while cg_enable_i is deasserted, with zero gated intervals.

      '
    fail_on: 'any missing toggle or gated interval observed on the DMA clock while cg_enable_i is deasserted;
      OR X/Z or missing sample.

      '
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
    proof: 'CHK-NONVAC: the ordered fence gate-off-observed < frontend-wakeup-observed < backend-wakeup-observed
      < gating-disabled-observed < PASS all hold, in that order, before the testcase reports pass.

      '
    fail_on: 'testcase pass with any fence term missing or out of order, or progress logged in place of
      a real PASS.

      '
    lifecycle: null
  guardrails:
  - No internal write/force/deposit on cg_enable_i, the frontend wakeup/backend busy signals, or the DMA
    gated clock net — frontdoor configuration and stimulus, passive clock observation only [NO-BACKDOOR-WRITE]
  - No fixed-delay stand-in for the hysteresis re-gate measurement — gate-off timing is measured against
    the actual last-toggle event, not a blind wait [NO-BLIND-DELAY-SYNC]
  blockers: []
- id: SMC_DMA_CG_ACTIVITY_TEST
  anchor: smc_dma_cg_activity_test
  revision: 2
  supersedes_revision: 1
  current: true
  status: approved
  record_sha256: b1f928140c5123ae1298877e726f91b309ba15c3b287fb236f723b3582d51653
  approved_by: minshaoho
  approved_at: '2026-08-05T11:20:00+08:00'
  category: DMA controller clock gating
  owns: 'The DMA controller''s own activity/enable clock-gating decision (frontend wakeup, backend busy,
    cg_enable_i) for the shared frontend+request-manager+backend clock domain, at P1 nominal function.

    '
  evidence_class: strict-e2e
  closure_tier: A
  derived_from:
    plan_revision: 1
    testcase_revision: 1
    testcase_record_sha256: 392d53ae853d76a3fdfbc7f31a4099290100b25a06fbbd51f47fbd7a09a12469
    allocated_scenarios:
    - DMA-CG-CTRL.S1
    - DMA-CG-CTRL.S2
    - DMA-CG-CTRL.S3
    - DMA-CG-CTRL.S4
  description:
    producer: cg_enable_i configuration input plus DMA activity signals (idma_frontend_wrapper wakeup
      event, idma_backend_wrapper busy status)
    transport: the single prim_clk_gater_hysteresis instance gating the shared DMA clock domain
    consumer: the gated clock feeding idma_frontend_wrapper, idma_request_manager_wrapper, and idma_backend_wrapper
      as one clock domain
  steps:
  - id: S1
    text: 'With cg_enable_i asserted (gating enabled) and neither frontend wakeup nor backend busy asserted,
      hold that idle condition for the programmed hysteresis window and observe the shared DMA clock gates
      off.

      '
    derived_from:
    - DMA-CG-CTRL.S1
  - id: S2
    text: 'With the DMA clock gated off, assert a frontend wakeup event and observe the shared DMA clock
      resumes continuous toggling.

      '
    derived_from:
    - DMA-CG-CTRL.S2
  - id: S3
    text: 'With gating enabled, after a prior activity wake has the shared DMA clock free-running, establish
      a backend-only window (backend_busy=1 and frontend_busy=0) and observe the shared DMA clock keeps
      toggling every cycle for that entire window (keep-enabled under backend-only — not gated-off then
      resume).

      '
    derived_from:
    - DMA-CG-CTRL.S3
  - id: S4
    text: 'Deassert cg_enable_i (gating disabled) with neither frontend wakeup nor backend busy asserted,
      and observe the shared DMA clock stays continuously enabled.

      '
    derived_from:
    - DMA-CG-CTRL.S4
  randomization: None — all four allocated DMA-CG-CTRL scenarios (S1-S4) are DIRECTED.
  observation: 'LIVE observation via existing tb_top lifts tb_dma_gated_clk, tb_dma_frontend_busy, and
    tb_dma_backend_busy (owner-authorized 2026-08-05 option 2); frontdoor stimulus and passive observe
    only — no force/deposit. Cycle-resolution samples across each step window; an X/Z or missing sample
    is unobservable and fails the checker.

    '
  checkers:
  - id: CHK-DMA-GATE-OFF
    checks_steps:
    - S1
    proves:
    - DMA-CG-CTRL
    covers:
    - DMA-CG-CTRL.S1
    proof_class: LIVE
    expect_source: hw/sys/smc/doc/dma.adoc §Performance Optimization and Power Management, table "Clock
      Gating Configuration", rows "Clock Gating Implementation"/"Hysteresis Width" (rev e2aae39953bb8001c7c20e3afd3956e68c22440c)
    proof: 'CHK-DMA-GATE-OFF: the shared DMA clock''s last toggle occurs at most one programmed-hysteresis-window''s
      worth of cycles after the idle condition begins, and the clock stays gated (zero toggles) for the
      remainder of the observed idle window.

      '
    fail_on: 'a toggle observed on the DMA clock beyond the programmed hysteresis window while the idle
      condition persists; OR X/Z or missing sample; OR the test times out before the window elapses.

      '
    lifecycle: null
  - id: CHK-DMA-WAKEUP-FRONTEND
    checks_steps:
    - S2
    proves:
    - DMA-CG-CTRL
    covers:
    - DMA-CG-CTRL.S2
    proof_class: LIVE
    expect_source: hw/sys/smc/doc/dma.adoc §Performance Optimization and Power Management, table "Clock
      Gating Configuration", row "Activity Detection" (rev e2aae39953bb8001c7c20e3afd3956e68c22440c)
    proof: 'CHK-DMA-WAKEUP-FRONTEND: the shared DMA clock resumes toggling every cycle starting within
      one cycle of the frontend wakeup event.

      '
    fail_on: 'the clock stays gated after the wakeup event; OR a toggle is missing in the cycle immediately
      after wakeup; OR X/Z or missing sample.

      '
    lifecycle: null
  - id: CHK-DMA-WAKEUP-BACKEND
    checks_steps:
    - S3
    proves:
    - DMA-CG-CTRL
    covers:
    - DMA-CG-CTRL.S3
    proof_class: LIVE
    expect_source: hw/sys/smc/doc/dma.adoc §Performance Optimization and Power Management, table "Clock
      Gating Configuration", row "Activity Detection" (rev e2aae39953bb8001c7c20e3afd3956e68c22440c)
    proof: 'CHK-DMA-WAKEUP-BACKEND: during a backend-only window (backend_busy=1 && frontend_busy=0),
      the shared DMA clock toggles every cycle for the entire observed window.

      '
    fail_on: 'frontend_busy asserts during the claimed backend-only window; OR any missing toggle on the
      DMA clock during that window; OR X/Z or missing sample.

      '
    lifecycle: null
  - id: CHK-DMA-GATING-DISABLED
    checks_steps:
    - S4
    proves:
    - DMA-CG-CTRL
    covers:
    - DMA-CG-CTRL.S4
    proof_class: LIVE
    expect_source: hw/sys/smc/doc/dma.adoc §Performance Optimization and Power Management, table "Clock
      Gating Configuration", row "Gating Control" (rev e2aae39953bb8001c7c20e3afd3956e68c22440c)
    proof: 'CHK-DMA-GATING-DISABLED: the shared DMA clock toggles every cycle for the entire observed
      idle window while cg_enable_i is deasserted, with zero gated intervals.

      '
    fail_on: 'any missing toggle or gated interval observed on the DMA clock while cg_enable_i is deasserted;
      OR X/Z or missing sample.

      '
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
    proof: 'CHK-NONVAC: the ordered fence gate-off-observed < frontend-wakeup-observed < backend-only-keep-enabled-observed
      < gating-disabled-observed < PASS all hold, in that order, before the testcase reports pass.

      '
    fail_on: 'testcase pass with any fence term missing or out of order, or progress logged in place of
      a real PASS.

      '
    lifecycle: null
  guardrails:
  - No internal write/force/deposit on cg_enable_i, the frontend wakeup/backend busy signals, or the DMA
    gated clock net — frontdoor configuration and stimulus, passive clock observation only [NO-BACKDOOR-WRITE]
  - No fixed-delay stand-in for the hysteresis re-gate measurement — gate-off timing is measured against
    the actual last-toggle event, not a blind wait [NO-BLIND-DELAY-SYNC]
  blockers: []
- id: SMC_ZEROER_AXICLK_CG_TEST
  anchor: smc_zeroer_axiclk_cg_test
  revision: 1
  supersedes_revision: null
  current: true
  status: approved
  record_sha256: 67c81eca9fc764cc694026df6a7da34a406f4c5528305cc17e43d9d6b9a045db
  approved_by: minshaoho
  approved_at: '2026-08-05T09:20:00+08:00'
  category: Memory Zeroer clock gating (AXI clock)
  owns: 'The Memory Zeroer''s axi_clk gating decision (zeroer_busy_o, disable_cg, rst_ni) at P1 nominal
    function.

    '
  evidence_class: strict-e2e
  closure_tier: A
  derived_from:
    plan_revision: 1
    testcase_revision: 1
    testcase_record_sha256: 5b2f4fe439dc4b09edbcad1945ca1abc3a2e3aa354c37a9000e8c4dd6f7b0ed3
    allocated_scenarios:
    - ZEROER-AXICLK-CG.S1
    - ZEROER-AXICLK-CG.S2
    - ZEROER-AXICLK-CG.S3
    - ZEROER-AXICLK-CG.S4
  description:
    producer: zeroer_busy_o busy status, the disable_cg configuration bit, and rst_ni reset, combined
      per axi_clk_enable = disable_cg | zeroer_busy_o | ~rst_ni
    transport: a prim_clkgater instance on the axi_clk domain
    consumer: the gated axi_clk feeding the Memory Zeroer's AXI4 master datapath
  steps:
  - id: S1
    text: 'With disable_cg=0 and zeroer_busy_o=0, out of reset, hold that idle condition and observe axi_clk
      gates off.

      '
    derived_from:
    - ZEROER-AXICLK-CG.S1
  - id: S2
    text: 'With axi_clk gated off, trigger a zeroing operation so zeroer_busy_o asserts, with disable_cg
      left at 0, and observe axi_clk resumes and stays enabled for the whole busy window.

      '
    derived_from:
    - ZEROER-AXICLK-CG.S2
  - id: S3
    text: 'With zeroer_busy_o=0, program disable_cg=1 and observe axi_clk stays continuously enabled despite
      the idle condition.

      '
    derived_from:
    - ZEROER-AXICLK-CG.S3
  - id: S4
    text: 'With disable_cg=0 and zeroer_busy_o=0 (axi_clk gated off), assert reset (deassert rst_ni) and
      observe axi_clk becomes/stays enabled for the duration of the reset assertion.

      '
    derived_from:
    - ZEROER-AXICLK-CG.S4
  randomization: None — all four allocated ZEROER-AXICLK-CG scenarios (S1-S4) are DIRECTED.
  observation: 'Passive hierarchical toggle observation of the axi_clk gated clock net at cycle resolution
    across each step''s window; an X/Z or missing sample is unobservable and fails the checker.

    '
  checkers:
  - id: CHK-ZAXI-GATE-OFF-IDLE
    checks_steps:
    - S1
    proves:
    - ZEROER-AXICLK-CG
    covers:
    - ZEROER-AXICLK-CG.S1
    proof_class: LIVE
    expect_source: hw/sys/smc/doc/zeroer.adoc §Clock Gating, table "Clock Gating Control", row "AXI Clock"
      (rev 2f40548ea787240680a1c45ab75b8729e9620778)
    proof: 'CHK-ZAXI-GATE-OFF-IDLE: axi_clk stops toggling within one cycle of the idle condition (disable_cg=0,
      zeroer_busy_o=0, out of reset) being established, and stays gated for the whole observed idle window.

      '
    fail_on: 'axi_clk continues toggling into the idle window past one cycle; OR it gates and then resumes
      without a qualifying cause; OR X/Z or missing sample.

      '
    lifecycle: null
  - id: CHK-ZAXI-BUSY-ENABLE
    checks_steps:
    - S2
    proves:
    - ZEROER-AXICLK-CG
    covers:
    - ZEROER-AXICLK-CG.S2
    proof_class: LIVE
    expect_source: hw/sys/smc/doc/zeroer.adoc §Clock Gating, table "Clock Gating Control", row "AXI Clock"
      (rev 2f40548ea787240680a1c45ab75b8729e9620778)
    proof: 'CHK-ZAXI-BUSY-ENABLE: axi_clk resumes toggling every cycle within one cycle of zeroer_busy_o
      asserting, and continues toggling every cycle for the entire busy window.

      '
    fail_on: 'axi_clk stays gated after busy asserts; OR any missing toggle during the busy window; OR
      X/Z or missing sample.

      '
    lifecycle: null
  - id: CHK-ZAXI-DISABLE-CG
    checks_steps:
    - S3
    proves:
    - ZEROER-AXICLK-CG
    covers:
    - ZEROER-AXICLK-CG.S3
    proof_class: LIVE
    expect_source: hw/sys/smc/doc/zeroer.adoc §Clock Gating, table "Clock Gating Control", row "AXI Clock"
      (rev 2f40548ea787240680a1c45ab75b8729e9620778)
    proof: 'CHK-ZAXI-DISABLE-CG: axi_clk toggles every cycle for the entire observed window with disable_cg=1
      and zeroer_busy_o=0, with zero gated intervals.

      '
    fail_on: 'any gated interval observed on axi_clk while disable_cg=1; OR X/Z or missing sample.

      '
    lifecycle: null
  - id: CHK-ZAXI-RESET-OVERRIDE
    checks_steps:
    - S4
    proves:
    - ZEROER-AXICLK-CG
    covers:
    - ZEROER-AXICLK-CG.S4
    proof_class: LIVE
    expect_source: hw/sys/smc/doc/zeroer.adoc §Clock Gating, table "Clock Gating Control", row "Reset
      Override" (rev 2f40548ea787240680a1c45ab75b8729e9620778)
    proof: 'CHK-ZAXI-RESET-OVERRIDE: axi_clk is observed toggling, or resumes toggling within one cycle
      of reset asserting, and continues toggling throughout the asserted-reset window despite disable_cg=0
      and zeroer_busy_o=0.

      '
    fail_on: 'axi_clk stays gated at any point while rst_ni is deasserted; OR X/Z or missing sample.

      '
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
    proof: 'CHK-NONVAC: the ordered fence idle-gate-off-observed < busy-enable-observed < disable-cg-observed
      < reset-override-observed < PASS all hold, in that order, before the testcase reports pass.

      '
    fail_on: 'testcase pass with any fence term missing or out of order, or progress logged in place of
      a real PASS.

      '
    lifecycle: null
  guardrails:
  - No internal write/force/deposit on zeroer_busy_o, disable_cg, rst_ni, or the axi_clk gated clock net
    — frontdoor stimulus/configuration and passive clock observation only [NO-BACKDOOR-WRITE]
  blockers: []
- id: SMC_ZEROER_REGCLK_CG_TEST
  anchor: smc_zeroer_regclk_cg_test
  revision: 1
  supersedes_revision: null
  current: true
  status: approved
  record_sha256: 47e3381f135bfb76907ef06f89d4eb70bb30c6c7bb0232bb56dee36072ecbd1b
  approved_by: minshaoho
  approved_at: '2026-08-05T09:20:00+08:00'
  category: Memory Zeroer clock gating (register clock)
  owns: 'The Memory Zeroer''s reg_clk gating decision (register_activity, disable_cg, rst_ni) at P1 nominal
    function.

    '
  evidence_class: strict-e2e
  closure_tier: A
  derived_from:
    plan_revision: 1
    testcase_revision: 1
    testcase_record_sha256: 69210848a8214010c3e43e43a032d700ee9d0061b6bb8512de2c73b83db44b42
    allocated_scenarios:
    - ZEROER-REGCLK-CG.S1
    - ZEROER-REGCLK-CG.S2
    - ZEROER-REGCLK-CG.S3
    - ZEROER-REGCLK-CG.S4
  description:
    producer: register_activity signal, the disable_cg configuration bit, and rst_ni reset, combined per
      reg_clk_enable = disable_cg | register_activity | ~rst_ni
    transport: a prim_clkgater instance on the reg_clk domain
    consumer: the gated reg_clk feeding the Memory Zeroer's register interface
  steps:
  - id: S1
    text: 'With disable_cg=0 and no register activity, out of reset, hold that idle condition and observe
      reg_clk gates off.

      '
    derived_from:
    - ZEROER-REGCLK-CG.S1
  - id: S2
    text: 'With reg_clk gated off, issue a register access to the Zeroer so register_activity asserts,
      with disable_cg left at 0, and observe reg_clk resumes and stays enabled for the access window.

      '
    derived_from:
    - ZEROER-REGCLK-CG.S2
  - id: S3
    text: 'With no register activity, program disable_cg=1 and observe reg_clk stays continuously enabled
      despite the idle condition.

      '
    derived_from:
    - ZEROER-REGCLK-CG.S3
  - id: S4
    text: 'With disable_cg=0 and no register activity (reg_clk gated off), assert reset (deassert rst_ni)
      and observe reg_clk becomes/stays enabled for the duration of the reset assertion.

      '
    derived_from:
    - ZEROER-REGCLK-CG.S4
  randomization: None — all four allocated ZEROER-REGCLK-CG scenarios (S1-S4) are DIRECTED.
  observation: 'Passive hierarchical toggle observation of the reg_clk gated clock net at cycle resolution
    across each step''s window; an X/Z or missing sample is unobservable and fails the checker. Per open
    finding SF-004, the exact condition that asserts register_activity is not stated by the pinned SPEC;
    S2/CHK-ZREG-ACTIVITY-ENABLE below use "any AXI4-Lite access to the Zeroer''s register block" as the
    exercised stimulus pending that finding''s resolution, and the observation/PROOF text does not claim
    a narrower definition SPEC does not state.

    '
  checkers:
  - id: CHK-ZREG-GATE-OFF-IDLE
    checks_steps:
    - S1
    proves:
    - ZEROER-REGCLK-CG
    covers:
    - ZEROER-REGCLK-CG.S1
    proof_class: LIVE
    expect_source: hw/sys/smc/doc/zeroer.adoc §Clock Gating, table "Clock Gating Control", row "Register
      Clock" (rev 2f40548ea787240680a1c45ab75b8729e9620778)
    proof: 'CHK-ZREG-GATE-OFF-IDLE: reg_clk stops toggling within one cycle of the idle condition (disable_cg=0,
      no register activity, out of reset) being established, and stays gated for the whole observed idle
      window.

      '
    fail_on: 'reg_clk continues toggling into the idle window past one cycle; OR it gates and then resumes
      without a qualifying cause; OR X/Z or missing sample.

      '
    lifecycle: null
  - id: CHK-ZREG-ACTIVITY-ENABLE
    checks_steps:
    - S2
    proves:
    - ZEROER-REGCLK-CG
    covers:
    - ZEROER-REGCLK-CG.S2
    proof_class: LIVE
    expect_source: hw/sys/smc/doc/zeroer.adoc §Clock Gating, table "Clock Gating Control", row "Register
      Clock" (rev 2f40548ea787240680a1c45ab75b8729e9620778)
    proof: 'CHK-ZREG-ACTIVITY-ENABLE: reg_clk resumes toggling every cycle within one cycle of the register
      access being issued, and continues toggling every cycle for the entire access window.

      '
    fail_on: 'reg_clk stays gated after the register access is issued; OR any missing toggle during the
      access window; OR X/Z or missing sample.

      '
    lifecycle: null
  - id: CHK-ZREG-DISABLE-CG
    checks_steps:
    - S3
    proves:
    - ZEROER-REGCLK-CG
    covers:
    - ZEROER-REGCLK-CG.S3
    proof_class: LIVE
    expect_source: hw/sys/smc/doc/zeroer.adoc §Clock Gating, table "Clock Gating Control", row "Register
      Clock" (rev 2f40548ea787240680a1c45ab75b8729e9620778)
    proof: 'CHK-ZREG-DISABLE-CG: reg_clk toggles every cycle for the entire observed window with disable_cg=1
      and no register activity, with zero gated intervals.

      '
    fail_on: 'any gated interval observed on reg_clk while disable_cg=1; OR X/Z or missing sample.

      '
    lifecycle: null
  - id: CHK-ZREG-RESET-OVERRIDE
    checks_steps:
    - S4
    proves:
    - ZEROER-REGCLK-CG
    covers:
    - ZEROER-REGCLK-CG.S4
    proof_class: LIVE
    expect_source: hw/sys/smc/doc/zeroer.adoc §Clock Gating, table "Clock Gating Control", row "Reset
      Override" (rev 2f40548ea787240680a1c45ab75b8729e9620778)
    proof: 'CHK-ZREG-RESET-OVERRIDE: reg_clk is observed toggling, or resumes toggling within one cycle
      of reset asserting, and continues toggling throughout the asserted-reset window despite disable_cg=0
      and no register activity.

      '
    fail_on: 'reg_clk stays gated at any point while rst_ni is deasserted; OR X/Z or missing sample.

      '
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
    proof: 'CHK-NONVAC: the ordered fence idle-gate-off-observed < activity-enable-observed < disable-cg-observed
      < reset-override-observed < PASS all hold, in that order, before the testcase reports pass.

      '
    fail_on: 'testcase pass with any fence term missing or out of order, or progress logged in place of
      a real PASS.

      '
    lifecycle: null
  guardrails:
  - No internal write/force/deposit on register_activity, disable_cg, rst_ni, or the reg_clk gated clock
    net — frontdoor AXI4-Lite register access/configuration and passive clock observation only [NO-BACKDOOR-WRITE]
  blockers: []
- id: SMC_ZEROER_CG_INDEP_TEST
  anchor: smc_zeroer_cg_indep_test
  revision: 1
  supersedes_revision: null
  current: true
  status: approved
  record_sha256: 46ad998bc85c45be9ff0180d25267976c65047f0d983dec945caf0e9eebee833
  approved_by: minshaoho
  approved_at: '2026-08-05T13:50:00+08:00'
  category: Memory Zeroer clock gating (AXI/REG independence)
  owns: The cross-domain independence of Memory Zeroer axi_clk vs reg_clk gating (INT-ZEROER-CG-INDEP)
    only; not the single-domain formula cells owned by SMC_ZEROER_AXICLK_CG_TEST / SMC_ZEROER_REGCLK_CG_TEST.
  evidence_class: strict-e2e
  closure_tier: A
  derived_from:
    plan_revision: 1
    testcase_revision: 1
    testcase_record_sha256: af246ccaaec1265a4b108f970b90726c58b7506ea70db7292939077909a69da0
    allocated_scenarios:
    - INT-ZEROER-CG-INDEP
  description:
    producer: 'Asymmetric Zeroer activity: zeroer_busy_o (AXI path) vs register_activity (AXI4-Lite register
      access; SF-004 answered as any AXI4-Lite access), with disable_cg=0 and out of reset'
    transport: the two prim_clkgater instances on axi_clk and reg_clk, observed jointly
    consumer: gated axi_clk and gated reg_clk — each must follow its own enable formula without the other
      domain's activity coupling them
  steps:
  - id: S1
    text: 'With disable_cg=0 and out of reset: establish axi-active (zeroer_busy_o=1 via a frontdoor-triggered
      zeroing operation) while register-idle (no AXI4-Lite access during the observation window after
      programming completes), and observe axi_clk stays enabled while reg_clk gates off.'
    derived_from:
    - INT-ZEROER-CG-INDEP
  - id: S2
    text: 'With disable_cg=0 and out of reset: establish register-active (issue an AXI4-Lite access to
      the Zeroer register block) while axi-idle (zeroer_busy_o=0, no zeroing in progress), and observe
      reg_clk stays enabled while axi_clk gates off.'
    derived_from:
    - INT-ZEROER-CG-INDEP
  randomization: None — INT-ZEROER-CG-INDEP is DIRECTED; the scenario/interaction coverage record remains
    authoritative for required_cells.
  observation: Passive hierarchical toggle observation of BOTH the axi_clk and reg_clk gated clock nets
    at cycle resolution across each asymmetric-activity window; an X/Z or missing sample on either clock
    is unobservable and fails the checker. No force/deposit on busy, register_activity, disable_cg, rst_ni,
    or either gated clock net.
  checkers:
  - id: CHK-ZINDEP-DECOUPLE
    checks_steps:
    - S1
    - S2
    proves:
    - ZEROER-AXICLK-CG
    - ZEROER-REGCLK-CG
    covers:
    - INT-ZEROER-CG-INDEP
    proof_class: LIVE
    expect_source: hw/sys/smc/doc/zeroer.adoc §Clock Domains row "Register Clock … independent of AXI
      activity"; §Clock Gating formulas axi_clk_enable = disable_cg | zeroer_busy_o | ~rst_ni and reg_clk_enable
      = disable_cg | register_activity | ~rst_ni (rev 2f40548ea787240680a1c45ab75b8729e9620778)
    proof: 'CHK-ZINDEP-DECOUPLE: (S1 axi-active-reg-idle-decoupled) with disable_cg=0 and out of reset,
      during the axi-active / register-idle window axi_clk toggles every cycle and reg_clk is gated off
      for the whole window; (S2 reg-active-axi-idle-decoupled) during the register-active / axi-idle window
      reg_clk toggles every cycle and axi_clk is gated off for the whole window.'
    fail_on: 'S1: axi_clk gated or missing toggles while busy, OR reg_clk keeps toggling through the register-idle
      window; S2: reg_clk gated or missing toggles during the register access window, OR axi_clk keeps
      toggling while zeroer_busy_o=0; OR either clock shows X/Z or a missing sample; OR the two domain
      outcomes are coupled (both enabled or both gated) under either asymmetric cell.'
    lifecycle: null
  - id: CHK-NONVAC
    checks_steps:
    - S1
    - S2
    proves: []
    covers: []
    proof_class: INTEGRITY
    expect_source: approved card ordering contract
    proof: 'CHK-NONVAC: the ordered fence axi-active-reg-idle-decoupled-observed < reg-active-axi-idle-decoupled-observed
      < PASS all hold, in that order, before the testcase reports pass.'
    fail_on: testcase pass with any fence term missing or out of order, or progress logged in place of
      a real PASS.
    lifecycle: null
  guardrails:
  - No internal write/force/deposit on zeroer_busy_o, register_activity, disable_cg, rst_ni, axi_clk,
    or reg_clk — frontdoor stimulus/configuration and passive clock observation only [NO-BACKDOOR-WRITE]
  - No aggregate PASS line standing in for CHK-ZINDEP-DECOUPLE; single-feature proofs for ZEROER-AXICLK-CG
    / ZEROER-REGCLK-CG remain on their dedicated cards [MERGED-EVIDENCE]
  blockers: []
- id: SMC_CG_TEST_MODE_BYPASS_TEST
  anchor: smc_cg_test_mode_bypass_test
  revision: 1
  supersedes_revision: null
  current: true
  status: approved
  record_sha256: c4d8b90225e96f8c7796fabb3370409dc3db39898ca34e52d486363aef52ff49
  approved_by: minshaoho
  approved_at: '2026-08-05T09:20:00+08:00'
  category: DFT test-mode clock-gating bypass
  owns: The test_en_i DFT bypass of the DMA and Zeroer clock gaters only.
  evidence_class: strict-e2e
  closure_tier: B
  derived_from:
    plan_revision: 1
    testcase_revision: 1
    testcase_record_sha256: 3168d8b18d1afd7b31f6d5ae4780534e509da9dd543115098f4847f9df5355a0
    allocated_scenarios:
    - CG-DFT-TEST-BYPASS.S1
    - CG-DFT-TEST-BYPASS.S2
  description:
    producer: test_en_i DFT/scan test-enable input
    transport: the clock-gater test ports each instantiated clock-gating cell exposes (DMA, Zeroer axi_clk,
      Zeroer reg_clk)
    consumer: each gated consumer clock, forced continuously enabled regardless of the normal gating decision
  steps:
  - id: S1
    text: 'Configure the DMA gating path so that, absent test_en_i, it would gate the DMA clock off (cg_enable_i
      asserted, no frontend wakeup/backend busy); then assert test_en_i and observe the DMA clock stays
      continuously enabled.

      '
    derived_from:
    - CG-DFT-TEST-BYPASS.S1
  - id: S2
    text: 'Configure the Zeroer''s axi_clk gating path so that, absent test_en_i, it would gate axi_clk
      off (disable_cg=0, zeroer_busy_o=0, out of reset); then assert test_en_i and observe axi_clk stays
      continuously enabled.

      '
    derived_from:
    - CG-DFT-TEST-BYPASS.S2
  - id: S3
    text: 'Configure the Zeroer''s reg_clk gating path so that, absent test_en_i, it would gate reg_clk
      off (disable_cg=0, no register activity, out of reset); then assert test_en_i and observe reg_clk
      stays continuously enabled.

      '
    derived_from:
    - CG-DFT-TEST-BYPASS.S2
  randomization: None — both allocated CG-DFT-TEST-BYPASS scenarios (S1-S2) are DIRECTED.
  observation: 'Passive hierarchical toggle observation of the DMA clock, axi_clk, and reg_clk gated clock
    nets at cycle resolution while test_en_i is asserted; an X/Z or missing sample on any of the three
    is unobservable and fails the checker.

    '
  checkers:
  - id: CHK-DFT-BYPASS-DMA
    checks_steps:
    - S1
    proves:
    - CG-DFT-TEST-BYPASS
    covers:
    - CG-DFT-TEST-BYPASS.S1
    proof_class: LIVE
    expect_source: hw/sys/smc/doc/dma.adoc §Performance Optimization and Power Management, table "Clock
      Gating Configuration", row "Test Mode" (rev e2aae39953bb8001c7c20e3afd3956e68c22440c)
    proof: 'CHK-DFT-BYPASS-DMA: the DMA clock toggles every cycle for the entire observed test_en_i-asserted
      window despite the otherwise-gating configuration, with zero gated intervals.

      '
    fail_on: 'any gated interval observed on the DMA clock while test_en_i is asserted; OR X/Z or missing
      sample.

      '
    lifecycle: null
  - id: CHK-DFT-BYPASS-ZEROER
    checks_steps:
    - S2
    - S3
    proves:
    - CG-DFT-TEST-BYPASS
    covers:
    - CG-DFT-TEST-BYPASS.S2
    proof_class: LIVE
    expect_source: hw/sys/smc/doc/zeroer.adoc §Clock Gating, table "Clock Gating Control", row "Test Support"
      (rev 2f40548ea787240680a1c45ab75b8729e9620778)
    proof: 'CHK-DFT-BYPASS-ZEROER: both axi_clk and reg_clk toggle every cycle for the entire observed
      test_en_i-asserted window despite their otherwise-gating configurations, with zero gated intervals
      on either clock.

      '
    fail_on: 'any gated interval observed on axi_clk or reg_clk while test_en_i is asserted; OR X/Z or
      missing sample on either.

      '
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
    proof: 'CHK-NONVAC: the ordered fence dma-bypass-observed < zeroer-bypass-observed < PASS all hold,
      in that order, before the testcase reports pass.

      '
    fail_on: 'testcase pass with any fence term missing or out of order, or progress logged in place of
      a real PASS.

      '
    lifecycle: null
  guardrails:
  - No internal write/force/deposit on test_en_i or any gated clock net — frontdoor DFT-pin stimulus and
    passive clock observation only [NO-BACKDOOR-WRITE]
  - test_en_i is a scan/DFT pin with a real silicon equivalent (the SMC scan chain test-enable) — this
    is not a no-HW-equivalent shortcut, but each configured otherwise-gating precondition must itself
    be independently proven gating with test_en_i deasserted elsewhere in this milestone (SMC_DMA_CG_ACTIVITY_TEST
    / SMC_ZEROER_AXICLK_CG_TEST / SMC_ZEROER_REGCLK_CG_TEST), so the bypass claim has a positive gating
    control to bypass [NEGATIVE-NEEDS-POSITIVE-CONTROL]
  blockers: []
---
**Amendment 2026-08-05 — INT-ZEROER-CG-INDEP:** approved card `SMC_ZEROER_CG_INDEP_TEST` / `smc_zeroer_cg_indep_test`. Approved by minshaoho @ 2026-08-05T13:50:00+08:00. Other seven cards unchanged and still approved.


# SMC_CLOCK_GATING — Checkbox Cards (mixed, artifact_revision 3) — 8 current cards

Normative YAML above. Card mechanics (steps/checkers) are rendered in
`SMC_CLOCK_GATING_CARD_REVIEW.md`. Amendment 2026-08-05: `SMC_DMA_CG_ACTIVITY_TEST` revision 2
supersedes revision 1 (S3 backend-only keep-enabled; LIVE via tb_top lifts).

| Card | Steps | Checkers (incl. CHK-NONVAC) | Tier |
|---|---|---|---|
| SMC_CLK_MULTI_WINDOW_TEST | 3 | 2 | B |
| SMC_CLK_RUNNING_TEST | 2 | 2 | B |
| SMC_STATIC_CG_SANITY_TEST | 4 | 3 | B |
| SMC_DMA_CG_ACTIVITY_TEST | 4 | 5 | A |
| SMC_ZEROER_AXICLK_CG_TEST | 4 | 5 | A |
| SMC_ZEROER_REGCLK_CG_TEST | 4 | 5 | A |
| SMC_CG_TEST_MODE_BYPASS_TEST | 3 | 3 | B |

All within the pinned budget (max 12 steps / 12 checkers per card, max 8 cards per packet); no
`size_justification` was needed on any testcase record.

---
*Appendix: rendered from `SMC_CLOCK_GATING_TESTCASE_PLAN.md` @ candidate plan revision 1,
`SMC_CLOCK_GATING_SPEC_FEATURE_LIST.md` @ candidate revision 1, pin revision 1, spec source
revision 2ecc7b227e3926b253c65b5aac21239eec24ba5f.*
