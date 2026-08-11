---
schema: dv-quality/v1
artifact: feature-list
artifact_revision: 2
content_sha256: a22b78b40765efe57912f03934312f6b07a8582c351fa97c4ff0169d49bcca20
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
  note: 'AMENDMENT 2026-08-05 (Skill 3 FIND-001): add interaction INT-ZEROER-CG-INDEP from zeroer.adoc
    Clock Domains row "Register Clock … independent of AXI activity" + Clock Gating Control formulas.
    Existing five feature records unchanged (keys/record_sha256 stable). Prior seal caveat retained: sealed_derivation
    false from original generation. This amend run is a fresh-subagent Skill 1 Amendment-mode session;
    it does not re-derive the inventory — only inserts the SPEC-required cross that the reverse inventory
    confirmed was omitted.'
approved_by: minshaoho
approved_at: '2026-08-05T13:50:00+08:00'
features:
- key: SMC-CG-ARCH-PARAMS
  title: SMC architecture-level per-module clock-gating control parameters
  intent: 'Firmware/CSR-programmable per-module clock-gating parameters (hysteresis delay, per-module
    activity detection, enable-threshold delay, and individual module enable/disable) hold each named
    functional block''s gated clock stable against oscillation while it is idle.

    '
  triad:
    producer: 'firmware/CSR-programmable per-module clock-gating control fields (hysteresis count, activity-detection
      basis, enable-threshold delay, module enable/disable) named in clk_rst.adoc''s power-management
      integration table

      '
    transport: 'the per-module clock-gating cell within the SMC clock/reset unit (concrete instances named
      only for DMA and the Memory Zeroer elsewhere in the pinned docs; not otherwise named at this architectural
      level)

      '
    consumer: 'the gated clock delivered to the named functional block, held stable against gating oscillation

      '
  spec_refs:
  - hw/sys/smc/doc/clk_rst.adoc §Clock and Reset-Based Power Management Integration (rev 2f40548ea787240680a1c45ab75b8729e9620778)
  record_sha256: bcaa33a7ad29c089da84eae522ef15ce70f71f85b5b1b5b32ac6734429b929bc
  scenarios:
  - key: SMC-CG-ARCH-PARAMS.S1
    intent: 'A 6-bit programmable hysteresis count delays re-gating after module activity ends, preventing
      clock-gating oscillation under varying load.

      '
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/clk_rst.adoc §Clock and Reset-Based Power Management Integration, row "Hysteresis
      Control" (rev 2f40548ea787240680a1c45ab75b8729e9620778)
    coverage:
      method: RANDOMIZED
      required_cells:
      - hysteresis_delay_min
      - hysteresis_delay_mid
      - hysteresis_delay_max
      random_knobs:
      - programmed_hysteresis_count
      coverage_artifact: null
  - key: SMC-CG-ARCH-PARAMS.S2
    intent: 'Activity detection is evaluated on a per-module basis: an active module''s clock stays running
      while an idle module''s clock is independently gated.

      '
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/clk_rst.adoc §Clock and Reset-Based Power Management Integration, row "Activity Detection"
      (rev 2f40548ea787240680a1c45ab75b8729e9620778)
    coverage:
      method: DIRECTED
      required_cells:
      - module_active_clock_running
      - module_idle_clock_gated
      random_knobs: []
      coverage_artifact: null
  - key: SMC-CG-ARCH-PARAMS.S3
    intent: 'A configurable enable-threshold delay balances gating responsiveness against power savings,
      independent of the hysteresis count.

      '
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/clk_rst.adoc §Clock and Reset-Based Power Management Integration, row "Enable Threshold"
      (rev 2f40548ea787240680a1c45ab75b8729e9620778)
    coverage:
      method: RANDOMIZED
      required_cells:
      - enable_threshold_delay_min
      - enable_threshold_delay_max
      random_knobs:
      - programmed_enable_threshold
      coverage_artifact: null
  - key: SMC-CG-ARCH-PARAMS.S4
    intent: 'Each functional block''s clock gating can be individually enabled or disabled, independent
      of every other block''s gating state.

      '
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/clk_rst.adoc §Clock and Reset-Based Power Management Integration, row "Module Gating"
      (rev 2f40548ea787240680a1c45ab75b8729e9620778)
    coverage:
      method: DIRECTED
      required_cells:
      - module_gating_enabled
      - module_gating_disabled
      random_knobs: []
      coverage_artifact: null
- key: DMA-CG-CTRL
  title: DMA controller activity-based clock gating
  intent: 'A single hysteresis clock gater gates the shared DMA clock domain off when neither the frontend
    nor the backend is active, and holds it enabled otherwise, under software enable control.

    '
  triad:
    producer: 'cg_enable_i configuration input plus DMA activity signals (idma_frontend_wrapper wakeup
      event, idma_backend_wrapper busy status)

      '
    transport: 'the single prim_clk_gater_hysteresis instance gating the shared DMA clock domain (CG_HYSTERESIS_W=6
      hysteresis width)

      '
    consumer: 'the gated clock feeding idma_frontend_wrapper, idma_request_manager_wrapper, and idma_backend_wrapper
      together as one clock domain

      '
  spec_refs:
  - hw/sys/smc/doc/dma.adoc §Performance Optimization and Power Management, table "Clock Gating Configuration"
    (rev e2aae39953bb8001c7c20e3afd3956e68c22440c)
  record_sha256: 8b5713de168e6574bb864a6a276fa8686308593372360e958489db609c66bba1
  scenarios:
  - key: DMA-CG-CTRL.S1
    intent: 'With gating enabled and neither frontend wakeup nor backend busy asserted for the programmed
      hysteresis window, the DMA clock gates off.

      '
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/dma.adoc §Performance Optimization and Power Management, table "Clock Gating Configuration",
      rows "Clock Gating Implementation"/"Hysteresis Width" (rev e2aae39953bb8001c7c20e3afd3956e68c22440c)
    coverage:
      method: DIRECTED
      required_cells:
      - dma_clock_gated_off_after_idle
      random_knobs: []
      coverage_artifact: null
  - key: DMA-CG-CTRL.S2
    intent: With gating enabled, a frontend wakeup event keeps/returns the DMA clock enabled.
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/dma.adoc §Performance Optimization and Power Management, table "Clock Gating Configuration",
      row "Activity Detection" (rev e2aae39953bb8001c7c20e3afd3956e68c22440c)
    coverage:
      method: DIRECTED
      required_cells:
      - dma_clock_enabled_on_frontend_wakeup
      random_knobs: []
      coverage_artifact: null
  - key: DMA-CG-CTRL.S3
    intent: With gating enabled, a backend busy indication keeps/returns the DMA clock enabled.
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/dma.adoc §Performance Optimization and Power Management, table "Clock Gating Configuration",
      row "Activity Detection" (rev e2aae39953bb8001c7c20e3afd3956e68c22440c)
    coverage:
      method: DIRECTED
      required_cells:
      - dma_clock_enabled_on_backend_busy
      random_knobs: []
      coverage_artifact: null
  - key: DMA-CG-CTRL.S4
    intent: 'Deasserting cg_enable_i disables clock gating entirely; the DMA clock stays continuously
      enabled regardless of activity.

      '
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/dma.adoc §Performance Optimization and Power Management, table "Clock Gating Configuration",
      row "Gating Control" (rev e2aae39953bb8001c7c20e3afd3956e68c22440c)
    coverage:
      method: DIRECTED
      required_cells:
      - dma_cg_disabled_clock_always_on
      random_knobs: []
      coverage_artifact: null
  - key: DMA-CG-CTRL.S5
    intent: 'The 6-bit programmed hysteresis count is exercised across its legal range and the measured
      re-gate delay matches the programmed count.

      '
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/dma.adoc §Configuration Parameters, row "CG_HYSTERESIS_W" (rev e2aae39953bb8001c7c20e3afd3956e68c22440c)
    coverage:
      method: RANDOMIZED
      required_cells:
      - dma_hysteresis_0
      - dma_hysteresis_mid
      - dma_hysteresis_63
      random_knobs:
      - dma_hysteresis_count
      coverage_artifact: functional-coverage cross of programmed hysteresis count vs. measured re-gate
        delay
  - key: DMA-CG-CTRL.S6
    intent: '[BOUNDED-LIVENESS] A frontend wakeup or backend-busy event arriving while a prior hysteresis
      idle countdown is still running does not leave the DMA clock gated or deadlocked; the clock resumes
      (or was never gated) within a bounded time.

      '
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/dma.adoc §Performance Optimization and Power Management, table "Clock Gating Configuration",
      rows "Activity Detection"/"Hysteresis Width" (rev e2aae39953bb8001c7c20e3afd3956e68c22440c)
    coverage:
      method: DIRECTED
      required_cells:
      - activity_during_hysteresis_countdown_resumes_without_gating
      random_knobs: []
      coverage_artifact: null
- key: CG-DFT-TEST-BYPASS
  title: DFT test-mode bypass of clock gating
  intent: 'Asserting the SMC-wide DFT/scan test-enable input forces every instantiated clock-gating cell''s
    output clock continuously enabled, bypassing its normal gating decision, for manufacturing test.

    '
  triad:
    producer: test_en_i DFT/scan test-enable input
    transport: the clock-gater test ports each instantiated clock-gating cell exposes
    consumer: 'the gated consumer clock forced continuously enabled, overriding whatever the normal gating
      decision would otherwise produce

      '
  spec_refs:
  - hw/sys/smc/doc/port_table.adoc §SMC Port Declaration, row "test_en_i" (rev 2ecc7b227e3926b253c65b5aac21239eec24ba5f)
  record_sha256: 6d49e64f8a437e8b31d0365cd3972cb56cb0f98cc2087d93c8c05c47818a6d30
  scenarios:
  - key: CG-DFT-TEST-BYPASS.S1
    intent: 'With test_en_i asserted, the DMA clock stays continuously enabled even when cg_enable_i and
      activity would otherwise gate it off.

      '
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/dma.adoc §Performance Optimization and Power Management, table "Clock Gating Configuration",
      row "Test Mode" (rev e2aae39953bb8001c7c20e3afd3956e68c22440c)
    - hw/sys/smc/doc/port_table.adoc §SMC Port Declaration, row "test_en_i" (rev 2ecc7b227e3926b253c65b5aac21239eec24ba5f)
    coverage:
      method: DIRECTED
      required_cells:
      - dma_gate_bypassed_in_test_mode
      random_knobs: []
      coverage_artifact: null
  - key: CG-DFT-TEST-BYPASS.S2
    intent: 'With test_en_i asserted, both the Memory Zeroer''s axi_clk and reg_clk stay continuously
      enabled even when their respective gating conditions would otherwise gate them off.

      '
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/zeroer.adoc §Clock Gating, table "Clock Gating Control", row "Test Support" (rev
      2f40548ea787240680a1c45ab75b8729e9620778)
    - hw/sys/smc/doc/port_table.adoc §SMC Port Declaration, row "test_en_i" (rev 2ecc7b227e3926b253c65b5aac21239eec24ba5f)
    coverage:
      method: DIRECTED
      required_cells:
      - zeroer_axiclk_bypassed_in_test_mode
      - zeroer_regclk_bypassed_in_test_mode
      random_knobs: []
      coverage_artifact: null
- key: ZEROER-AXICLK-CG
  title: Memory Zeroer AXI-clock gating
  intent: 'The Memory Zeroer''s AXI master-datapath clock (axi_clk) is gated off when the zeroer is idle,
    and held enabled by busy status, a software disable, or reset, per axi_clk_enable = disable_cg | zeroer_busy_o
    | ~rst_ni.

    '
  triad:
    producer: 'zeroer_busy_o busy status, the disable_cg configuration bit, and rst_ni reset, combined
      per the formula axi_clk_enable = disable_cg | zeroer_busy_o | ~rst_ni

      '
    transport: a prim_clkgater instance on the axi_clk domain
    consumer: the gated axi_clk feeding the Memory Zeroer's AXI4 master datapath
  spec_refs:
  - hw/sys/smc/doc/zeroer.adoc §Clock Gating, table "Clock Gating Control" (rev 2f40548ea787240680a1c45ab75b8729e9620778)
  record_sha256: 654d3d577196982077cab536e02697f29b1655f0dfb6f240fdb8c9fbe5f71819
  scenarios:
  - key: ZEROER-AXICLK-CG.S1
    intent: With disable_cg=0, zeroer_busy_o=0, and out of reset, axi_clk gates off.
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/zeroer.adoc §Clock Gating, table "Clock Gating Control", row "AXI Clock" (rev 2f40548ea787240680a1c45ab75b8729e9620778)
    coverage:
      method: DIRECTED
      required_cells:
      - axiclk_gated_off_idle
      random_knobs: []
      coverage_artifact: null
  - key: ZEROER-AXICLK-CG.S2
    intent: zeroer_busy_o=1 keeps axi_clk enabled regardless of disable_cg.
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/zeroer.adoc §Clock Gating, table "Clock Gating Control", row "AXI Clock" (rev 2f40548ea787240680a1c45ab75b8729e9620778)
    coverage:
      method: DIRECTED
      required_cells:
      - axiclk_enabled_on_busy
      random_knobs: []
      coverage_artifact: null
  - key: ZEROER-AXICLK-CG.S3
    intent: disable_cg=1 holds axi_clk continuously enabled, bypassing gating by configuration.
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/zeroer.adoc §Clock Gating, table "Clock Gating Control", row "AXI Clock" (rev 2f40548ea787240680a1c45ab75b8729e9620778)
    coverage:
      method: DIRECTED
      required_cells:
      - axiclk_enabled_disable_cg_set
      random_knobs: []
      coverage_artifact: null
  - key: ZEROER-AXICLK-CG.S4
    intent: Asserting reset (~rst_ni) forces axi_clk enabled per the reset-override term.
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/zeroer.adoc §Clock Gating, table "Clock Gating Control", row "Reset Override" (rev
      2f40548ea787240680a1c45ab75b8729e9620778)
    coverage:
      method: DIRECTED
      required_cells:
      - axiclk_enabled_during_reset
      random_knobs: []
      coverage_artifact: null
  - key: ZEROER-AXICLK-CG.S5
    intent: '[BOUNDED-LIVENESS] zeroer_busy_o deasserting as a new zeroing operation is triggered back-to-back
      does not gate axi_clk mid-sequence; the second operation''s data phase completes without a clock
      interruption.

      '
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/zeroer.adoc §Outstanding Transaction Management (rev 2f40548ea787240680a1c45ab75b8729e9620778)
    - hw/sys/smc/doc/zeroer.adoc §Clock Gating, table "Clock Gating Control", row "AXI Clock" (rev 2f40548ea787240680a1c45ab75b8729e9620778)
    coverage:
      method: DIRECTED
      required_cells:
      - axiclk_no_glitch_back_to_back_ops
      random_knobs: []
      coverage_artifact: null
- key: ZEROER-REGCLK-CG
  title: Memory Zeroer register-clock gating
  intent: 'The Memory Zeroer''s register-interface clock (reg_clk) is gated off when no register activity
    is occurring, and held enabled by register activity, a software disable, or reset, per reg_clk_enable
    = disable_cg | register_activity | ~rst_ni, independent of AXI activity.

    '
  triad:
    producer: 'register_activity signal, the disable_cg configuration bit, and rst_ni reset, combined
      per the formula reg_clk_enable = disable_cg | register_activity | ~rst_ni

      '
    transport: a prim_clkgater instance on the reg_clk domain
    consumer: the gated reg_clk feeding the Memory Zeroer's register interface
  spec_refs:
  - hw/sys/smc/doc/zeroer.adoc §Clock Gating, table "Clock Gating Control" (rev 2f40548ea787240680a1c45ab75b8729e9620778)
  record_sha256: 00ede8279af6a298f7eea41d3c0cdebb8787f9eb283e23db854a56795769ec90
  scenarios:
  - key: ZEROER-REGCLK-CG.S1
    intent: With disable_cg=0, register_activity=0, and out of reset, reg_clk gates off.
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/zeroer.adoc §Clock Gating, table "Clock Gating Control", row "Register Clock" (rev
      2f40548ea787240680a1c45ab75b8729e9620778)
    coverage:
      method: DIRECTED
      required_cells:
      - regclk_gated_off_idle
      random_knobs: []
      coverage_artifact: null
  - key: ZEROER-REGCLK-CG.S2
    intent: register_activity=1 keeps reg_clk enabled regardless of disable_cg.
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/zeroer.adoc §Clock Gating, table "Clock Gating Control", row "Register Clock" (rev
      2f40548ea787240680a1c45ab75b8729e9620778)
    coverage:
      method: DIRECTED
      required_cells:
      - regclk_enabled_on_register_activity
      random_knobs: []
      coverage_artifact: null
  - key: ZEROER-REGCLK-CG.S3
    intent: disable_cg=1 holds reg_clk continuously enabled, bypassing gating by configuration.
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/zeroer.adoc §Clock Gating, table "Clock Gating Control", row "Register Clock" (rev
      2f40548ea787240680a1c45ab75b8729e9620778)
    coverage:
      method: DIRECTED
      required_cells:
      - regclk_enabled_disable_cg_set
      random_knobs: []
      coverage_artifact: null
  - key: ZEROER-REGCLK-CG.S4
    intent: Asserting reset (~rst_ni) forces reg_clk enabled per the reset-override term.
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/zeroer.adoc §Clock Gating, table "Clock Gating Control", row "Reset Override" (rev
      2f40548ea787240680a1c45ab75b8729e9620778)
    coverage:
      method: DIRECTED
      required_cells:
      - regclk_enabled_during_reset
      random_knobs: []
      coverage_artifact: null
  - key: ZEROER-REGCLK-CG.S5
    intent: '[BOUNDED-LIVENESS] A new register access beginning while reg_clk is transitioning to gated-off
      from a prior idle period does not leave the access dropped or corrupted; reg_clk resumes within
      a bounded time.

      '
    requires: LIVE
    spec_refs:
    - hw/sys/smc/doc/zeroer.adoc §Clock Gating, table "Clock Gating Control", row "Register Clock" (rev
      2f40548ea787240680a1c45ab75b8729e9620778)
    coverage:
      method: DIRECTED
      required_cells:
      - regclk_no_glitch_pending_access
      random_knobs: []
      coverage_artifact: null
interactions:
- key: INT-ZEROER-CG-INDEP
  features:
  - ZEROER-AXICLK-CG
  - ZEROER-REGCLK-CG
  intent: 'zeroer.adoc states the Register Clock is "independent of AXI activity"; this interaction proves
    the two gating decisions are decoupled under asymmetric activity: axi-active + register-idle keeps
    axi_clk enabled while reg_clk gates off, and register-active + axi-idle keeps reg_clk enabled while
    axi_clk gates off (disable_cg=0, out of reset, per the domain formulas).'
  spec_refs:
  - hw/sys/smc/doc/zeroer.adoc §Clock Domains, table "Clock Domain Characteristics", row "Register Clock
    (reg_clk)" — "independent of AXI activity" (rev 2f40548ea787240680a1c45ab75b8729e9620778)
  - hw/sys/smc/doc/zeroer.adoc §Clock Gating, table "Clock Gating Control", rows "AXI Clock" and "Register
    Clock" (rev 2f40548ea787240680a1c45ab75b8729e9620778)
  requires: LIVE
  coverage:
    method: DIRECTED
    required_cells:
    - axi-active-reg-idle-decoupled
    - reg-active-axi-idle-decoupled
    random_knobs: []
    coverage_artifact: null
  record_sha256: 30602cffd560a5de3757e27775af4e0c902e995d1e46a4c0b58cb2f4b32afd94
---

# SMC_CLOCK_GATING — Spec Feature List (candidate amendment, artifact_revision 2)

**Milestone (pin field):** P1 — nominal function. **Boundary free text on the same pin also says**
"This pin closes P0–P2 scenarios (milestone P2)" — see the pin-inconsistency note at the end of
this document; this artifact's scope is `boundary` alone (§per DV_SKILL1_SPEC.md §4.1) and is
**not** trimmed by either milestone reading. Milestone bounds only the testcase plan (§4.2), one
layer down.

**Seal caveat — read first.** `derivation_provenance.sealed_derivation: false`. This run's Step 0
context-gathering read the full confirmed pin file, including the sealed `anchors` /
`anchor_name_prefix` / `owns_notes` fields, before feature derivation began. See the YAML block
above and the feature-semantics packet for the full caveat. The inventory below was still built by
walking the 9 pinned SPEC documents directly; no feature/scenario was shaped to match a known
anchor name, but the reviewer should treat the independence claim as weaker than a true seal.

## Clock Gating (5 features, 22 scenarios, 1 interaction)

**SMC-CG-ARCH-PARAMS — SMC architecture-level per-module clock-gating control parameters:**
Firmware/CSR-programmable per-module hysteresis, activity-detection, enable-threshold, and
individual enable/disable parameters hold each named functional block's gated clock stable
against oscillation.                                                          [ATOMIC-FEATURE]
  - Spec: `hw/sys/smc/doc/clk_rst.adoc` §Clock and Reset-Based Power Management Integration
    (table "Clock Gating Control Parameters")                                  [SPEC-CITATION]
  - Triad: producer per-module programmable CG fields | transport per-module CG cell (generic,
    unnamed beyond DMA/Zeroer) | consumer gated clock to the named block      [ATOMIC-FEATURE]
  - Required scenarios:                                                    [REQUIRED-SCENARIOS]
    - SMC-CG-ARCH-PARAMS.S1 [REQUIRES: LIVE]: 6-bit programmable hysteresis delays re-gating
      SPEC: clk_rst.adoc, row "Hysteresis Control"                             [SPEC-CITATION]
      COVERAGE: {method: RANDOMIZED, required_cells: [hysteresis_delay_min, hysteresis_delay_mid,
                 hysteresis_delay_max], random_knobs: [programmed_hysteresis_count],
                 coverage_artifact: null}
    - SMC-CG-ARCH-PARAMS.S2 [REQUIRES: LIVE]: per-module activity detection gates only idle modules
      SPEC: clk_rst.adoc, row "Activity Detection"
      COVERAGE: {method: DIRECTED, required_cells: [module_active_clock_running,
                 module_idle_clock_gated], random_knobs: [], coverage_artifact: null}
    - SMC-CG-ARCH-PARAMS.S3 [REQUIRES: LIVE]: configurable enable-threshold delay
      SPEC: clk_rst.adoc, row "Enable Threshold"
      COVERAGE: {method: RANDOMIZED, required_cells: [enable_threshold_delay_min,
                 enable_threshold_delay_max], random_knobs: [programmed_enable_threshold],
                 coverage_artifact: null}
    - SMC-CG-ARCH-PARAMS.S4 [REQUIRES: LIVE]: individual per-module gating enable/disable
      SPEC: clk_rst.adoc, row "Module Gating"
      COVERAGE: {method: DIRECTED, required_cells: [module_gating_enabled,
                 module_gating_disabled], random_knobs: [], coverage_artifact: null}

**DMA-CG-CTRL — DMA controller activity-based clock gating:** A single hysteresis clock gater
gates the shared DMA clock domain off when frontend and backend are both idle, and holds it
enabled by activity or by software.                                           [ATOMIC-FEATURE]
  - Spec: `hw/sys/smc/doc/dma.adoc` §Performance Optimization and Power Management, table
    "Clock Gating Configuration" (and §Configuration Parameters, CG_HYSTERESIS_W)  [SPEC-CITATION]
  - Triad: producer cg_enable_i + frontend wakeup/backend busy | transport
    prim_clk_gater_hysteresis (CG_HYSTERESIS_W=6) | consumer gated clock to
    frontend+request-manager+backend                                          [ATOMIC-FEATURE]
  - Required scenarios:                                                    [REQUIRED-SCENARIOS]
    - DMA-CG-CTRL.S1 [REQUIRES: LIVE]: idle for the hysteresis window gates the clock off
      SPEC: dma.adoc, "Clock Gating Implementation"/"Hysteresis Width" rows
      COVERAGE: {method: DIRECTED, required_cells: [dma_clock_gated_off_after_idle],
                 random_knobs: [], coverage_artifact: null}
    - DMA-CG-CTRL.S2 [REQUIRES: LIVE]: frontend wakeup keeps the clock enabled
      SPEC: dma.adoc, "Activity Detection" row
      COVERAGE: {method: DIRECTED, required_cells: [dma_clock_enabled_on_frontend_wakeup],
                 random_knobs: [], coverage_artifact: null}
    - DMA-CG-CTRL.S3 [REQUIRES: LIVE]: backend busy keeps the clock enabled
      SPEC: dma.adoc, "Activity Detection" row
      COVERAGE: {method: DIRECTED, required_cells: [dma_clock_enabled_on_backend_busy],
                 random_knobs: [], coverage_artifact: null}
    - DMA-CG-CTRL.S4 [REQUIRES: LIVE]: cg_enable_i=0 disables gating entirely
      SPEC: dma.adoc, "Gating Control" row
      COVERAGE: {method: DIRECTED, required_cells: [dma_cg_disabled_clock_always_on],
                 random_knobs: [], coverage_artifact: null}
    - DMA-CG-CTRL.S5 [REQUIRES: LIVE]: 6-bit hysteresis count swept across its legal range
      SPEC: dma.adoc, §Configuration Parameters, "CG_HYSTERESIS_W" row
      COVERAGE: {method: RANDOMIZED, required_cells: [dma_hysteresis_0, dma_hysteresis_mid,
                 dma_hysteresis_63], random_knobs: [dma_hysteresis_count],
                 coverage_artifact: "functional-coverage cross of programmed hysteresis count vs. measured re-gate delay"}
    - DMA-CG-CTRL.S6 [BOUNDED-LIVENESS][REQUIRES: LIVE]: activity arriving mid-hysteresis-countdown
      resumes/keeps the clock without deadlock, within bounded time
      SPEC: dma.adoc, "Activity Detection"/"Hysteresis Width" rows (combined boundary condition)
      COVERAGE: {method: DIRECTED,
                 required_cells: [activity_during_hysteresis_countdown_resumes_without_gating],
                 random_knobs: [], coverage_artifact: null}

**CG-DFT-TEST-BYPASS — DFT test-mode bypass of clock gating:** Asserting the SMC-wide DFT/scan
test-enable input forces every instantiated clock-gating cell's output clock continuously
enabled, for manufacturing test.                                              [ATOMIC-FEATURE]
  - Spec: `hw/sys/smc/doc/port_table.adoc` §SMC Port Declaration, row "test_en_i"; corroborated
    by `dma.adoc`'s "Test Mode" row and `zeroer.adoc`'s "Test Support" row     [SPEC-CITATION]
  - Triad: producer test_en_i | transport per-instance clock-gater test port | consumer gated
    clock forced continuously enabled                                        [ATOMIC-FEATURE]
  - Required scenarios:                                                    [REQUIRED-SCENARIOS]
    - CG-DFT-TEST-BYPASS.S1 [REQUIRES: LIVE]: test_en_i bypasses the DMA clock gater
      SPEC: dma.adoc, "Test Mode" row; port_table.adoc, "test_en_i" row
      COVERAGE: {method: DIRECTED, required_cells: [dma_gate_bypassed_in_test_mode],
                 random_knobs: [], coverage_artifact: null}
    - CG-DFT-TEST-BYPASS.S2 [REQUIRES: LIVE]: test_en_i bypasses both Zeroer clock gaters
      SPEC: zeroer.adoc, "Test Support" row; port_table.adoc, "test_en_i" row
      COVERAGE: {method: DIRECTED, required_cells: [zeroer_axiclk_bypassed_in_test_mode,
                 zeroer_regclk_bypassed_in_test_mode], random_knobs: [],
                 coverage_artifact: null}

**ZEROER-AXICLK-CG — Memory Zeroer AXI-clock gating:** `axi_clk_enable = disable_cg |
zeroer_busy_o | ~rst_ni` gates the Zeroer's AXI master-datapath clock.        [ATOMIC-FEATURE]
  - Spec: `hw/sys/smc/doc/zeroer.adoc` §Clock Gating, table "Clock Gating Control"
                                                                                 [SPEC-CITATION]
  - Triad: producer zeroer_busy_o/disable_cg/rst_ni | transport prim_clkgater (axi_clk) |
    consumer gated axi_clk to the Zeroer's AXI master datapath                [ATOMIC-FEATURE]
  - Required scenarios:                                                    [REQUIRED-SCENARIOS]
    - ZEROER-AXICLK-CG.S1 [REQUIRES: LIVE]: idle + enabled CG + out of reset gates axi_clk off
      SPEC: zeroer.adoc, "AXI Clock" row
      COVERAGE: {method: DIRECTED, required_cells: [axiclk_gated_off_idle], random_knobs: [],
                 coverage_artifact: null}
    - ZEROER-AXICLK-CG.S2 [REQUIRES: LIVE]: busy keeps axi_clk enabled regardless of disable_cg
      SPEC: zeroer.adoc, "AXI Clock" row
      COVERAGE: {method: DIRECTED, required_cells: [axiclk_enabled_on_busy], random_knobs: [],
                 coverage_artifact: null}
    - ZEROER-AXICLK-CG.S3 [REQUIRES: LIVE]: disable_cg=1 holds axi_clk always enabled
      SPEC: zeroer.adoc, "AXI Clock" row
      COVERAGE: {method: DIRECTED, required_cells: [axiclk_enabled_disable_cg_set],
                 random_knobs: [], coverage_artifact: null}
    - ZEROER-AXICLK-CG.S4 [REQUIRES: LIVE]: reset forces axi_clk enabled (reset override)
      SPEC: zeroer.adoc, "Reset Override" row
      COVERAGE: {method: DIRECTED, required_cells: [axiclk_enabled_during_reset],
                 random_knobs: [], coverage_artifact: null}
    - ZEROER-AXICLK-CG.S5 [BOUNDED-LIVENESS][REQUIRES: LIVE]: back-to-back triggering across a
      busy-deassert does not glitch-gate axi_clk mid-sequence
      SPEC: zeroer.adoc, §Outstanding Transaction Management; "AXI Clock" row
      COVERAGE: {method: DIRECTED, required_cells: [axiclk_no_glitch_back_to_back_ops],
                 random_knobs: [], coverage_artifact: null}

**ZEROER-REGCLK-CG — Memory Zeroer register-clock gating:** `reg_clk_enable = disable_cg |
register_activity | ~rst_ni` gates the Zeroer's register-interface clock, independent of AXI
activity.                                                                     [ATOMIC-FEATURE]
  - Spec: `hw/sys/smc/doc/zeroer.adoc` §Clock Gating, table "Clock Gating Control"
                                                                                 [SPEC-CITATION]
  - Triad: producer register_activity/disable_cg/rst_ni | transport prim_clkgater (reg_clk) |
    consumer gated reg_clk to the Zeroer's register interface                 [ATOMIC-FEATURE]
  - Required scenarios:                                                    [REQUIRED-SCENARIOS]
    - ZEROER-REGCLK-CG.S1 [REQUIRES: LIVE]: idle + enabled CG + out of reset gates reg_clk off
      SPEC: zeroer.adoc, "Register Clock" row
      COVERAGE: {method: DIRECTED, required_cells: [regclk_gated_off_idle], random_knobs: [],
                 coverage_artifact: null}
    - ZEROER-REGCLK-CG.S2 [REQUIRES: LIVE]: register_activity keeps reg_clk enabled regardless
      of disable_cg
      SPEC: zeroer.adoc, "Register Clock" row
      COVERAGE: {method: DIRECTED, required_cells: [regclk_enabled_on_register_activity],
                 random_knobs: [], coverage_artifact: null}
    - ZEROER-REGCLK-CG.S3 [REQUIRES: LIVE]: disable_cg=1 holds reg_clk always enabled
      SPEC: zeroer.adoc, "Register Clock" row
      COVERAGE: {method: DIRECTED, required_cells: [regclk_enabled_disable_cg_set],
                 random_knobs: [], coverage_artifact: null}
    - ZEROER-REGCLK-CG.S4 [REQUIRES: LIVE]: reset forces reg_clk enabled (reset override)
      SPEC: zeroer.adoc, "Reset Override" row
      COVERAGE: {method: DIRECTED, required_cells: [regclk_enabled_during_reset],
                 random_knobs: [], coverage_artifact: null}
    - ZEROER-REGCLK-CG.S5 [BOUNDED-LIVENESS][REQUIRES: LIVE]: a new register access beginning
      mid-gate-transition is not dropped or corrupted; reg_clk resumes in bounded time
      SPEC: zeroer.adoc, "Register Clock" row
      COVERAGE: {method: DIRECTED, required_cells: [regclk_no_glitch_pending_access],
                 random_knobs: [], coverage_artifact: null}

**Required interactions — 1 (amendment candidate):**

- **INT-ZEROER-CG-INDEP** [ZEROER-AXICLK-CG × ZEROER-REGCLK-CG][REQUIRES: LIVE]: Register Clock is independent of AXI activity — prove decoupling under asymmetric load: axi-active+reg-idle → axi_clk enabled / reg_clk gated; reg-active+axi-idle → reg_clk enabled / axi_clk gated.
  SPEC: zeroer.adoc §Clock Domains ("independent of AXI activity") + §Clock Gating formulas
  COVERAGE: {method: DIRECTED, required_cells: [axi-active-reg-idle-decoupled, reg-active-axi-idle-decoupled], random_knobs: [], coverage_artifact: null}

Prior empty `interactions: []` is superseded by this amendment (artifact_revision 2); feature records themselves are unchanged.

## Spec-visible but underspecified / incomplete (see `SMC_CLOCK_GATING_SPEC_REVIEW.md` for the
full, severity-ranked findings; summarized here for the feature-list reader)

- The pin's boundary names "module/per-IP clock-gate enable" as in-scope, but of the 8+
  peripherals `periphs.adoc` names (Mailbox, System Timer OCTS, eFuse, UART 16550, Log Engine,
  I2C, AVSBus Controller, GPIO, Telemetry Receiver), **none** has any clock-gating producer/
  transport/consumer behavior stated anywhere in the 9 pinned sources — only the DMA controller
  and the Memory Zeroer are concretely specified. (SF-001)
- `clk_rst.adoc`'s "Hysteresis Control" and "Enable Threshold" rows may name the same underlying
  counter or two independent fields; the pinned text does not say which. (SF-002)
- The pin's boundary names `clk_ref_i` and `clk_telemetry_i` as in-scope multi-domain clocks, but
  no pinned source states any clock-gating behavior for either domain. (SF-003)
- `zeroer.adoc`'s `register_activity` gating input is never defined (which register operations
  count as "activity"?). (SF-004)
- `dma.adoc` gives no reset-interaction statement for its clock gater, unlike `zeroer.adoc`'s
  explicit `~rst_ni` term — it is unspecified whether the DMA gater behaves the same way during
  reset. (SF-005)
- `port_table.adoc`'s `test_en_i` description says it drives clock-gater test ports for "All
  modules," but only DMA and the Zeroer have any documented clock-gating cell to bypass; the
  claim cannot be verified complete against the pinned set. (SF-006)

## Pin inconsistency observed (fact only, not corrected here)

The pin's `milestone:` field is `P1` (confirmed value returned by `pin_file.py validate`), but the
pin's `boundary:` free text states "This pin closes P0–P2 scenarios (milestone P2)." This
artifact does not resolve the conflict; it scopes the feature_list by `boundary` alone
(unaffected either way) and reports the milestone field, `P1`, as the value that bounds the
downstream testcase plan per DV_SKILL1_SPEC.md §3. See the closing report to the parent for the
same observation.
