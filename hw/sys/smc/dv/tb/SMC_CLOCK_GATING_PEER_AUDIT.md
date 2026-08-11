---
schema: dv-quality/v1
artifact: ip-peer-audit
ip: SMC_CLOCK_GATING
milestone: P1
mode: CHECKBOX-MAPPING
repository_revision: 2ecc7b227e3926b253c65b5aac21239eec24ba5f
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
pin_revision: 1
feature_list_sha256: a22b78b40765efe57912f03934312f6b07a8582c351fa97c4ff0169d49bcca20
feature_list_revision: 2
testcase_plan_sha256: 23856412227c96ff9b0ac8e23dc49901183c598bad8b9e5e3d9a49914686edcd
testcase_plan_revision: 1
cards_sha256: c097f008eb7eb94183188970bf1c95c21977bc6c721f0b9bc65d735324834f69
derivation_provenance:
  sealed_derivation: false
  anchor_seal_mechanism: ordered-single-context
  fresh_context_route: fresh-subagent
  feature_list_frozen_at: '2026-08-05T08:20:00+08:00'
evidence_policy_sha256: 51a3357d9c31a018d69451b055bc956c089af26e1051368e25ce396c84ac2a75
quality_policy_sha256: 51a3357d9c31a018d69451b055bc956c089af26e1051368e25ce396c84ac2a75
grade_report_sha256:
- a57b8155beb259e7235a2b7acf7ee8ba609fec640e4663a196ccd09e279c6b2b   # smc_cg_test_mode_bypass_test (file sha256)
- a99a7baf65fda9ae01394a5923d4ad8437ed559cf52fc208b980b5bd91596b10   # smc_clk_multi_window_test (file sha256)
- e530a0145b71ae4c0cbe43697778f2fc5f42e19de6367ff71964f7da39d08275   # smc_clk_running_test (file sha256)
- 643323ffd6a2209f16ec2826e84e4b2e1b0b9fe3840f01903be0e3e1fc1bcbf4   # smc_dma_cg_activity_test (file sha256)
- 0299550393e0df6901406bb6c5e3cb5d77a24f2ad8e786c8b69e82a75133e493   # smc_static_cg_sanity_test (file sha256)
- 09a08a95e33716c19a8a0ec0fed163b436fc8b85fe68829540cae208e01839d6   # smc_zeroer_axiclk_cg_test (file sha256)
- 0d39f6ea64d7e18a641837f80c7b4e83f5bafcafb0fee704a4a2d5ec76a3c22d   # smc_zeroer_cg_indep_test (file sha256)
- 81cff1e014adfa756cc0dd41741e162a93dcf7e2e0b6543604c15531306936e7   # smc_zeroer_regclk_cg_test (file sha256)
reviewer:
  human_id: brucehsu
  run_id: dv_peer_audit-SMC_CLOCK_GATING-P1-5aa9c629a618-fresh-opus5-rereview
  model: {provider: anthropic, family: claude, version: opus-5}
prior_participants:
- role: feature-list-generator
  human_id: minshaoho
  run_id: dv_vplan_gen-smc_clock_gating-fresh_subagent-20260805T080404+0800
  model: {provider: anthropic, family: claude, version: sonnet-5}
- role: feature-list-generator
  human_id: minshaoho
  run_id: dv_vplan_gen-SMC_CLOCK_GATING-P1-20260805T132000+0800-amend-int-zeroer-cg-indep
  model: {provider: cursor, family: grok, version: '4.5'}
- role: test-author
  human_id: minshaoho
  run_id: dv_test_impl-SMC_DMA_CG_ACTIVITY_TEST-cfed1faa-1b63-498e-81d5-885bfc9fe47b
  model: {provider: cursor, family: grok, version: '4.5'}
- role: test-author
  human_id: minshaoho
  run_id: dv_test_impl-SMC_CG_TEST_MODE_BYPASS_TEST-916949e4-ce77-48fb-9e77-730455010537
  model: {provider: cursor, family: grok, version: '4.5'}
- role: test-author
  human_id: minshaoho
  run_id: dv_test_impl-SMC_ZEROER_CG_INDEP_TEST-7731943f-dcb5-4dae-a13c-7e3ea0301648
  model: {provider: cursor, family: grok, version: '4.5'}
- role: test-author
  human_id: minshaoho
  run_id: dv_test_impl-SMC_CLK_MULTI_WINDOW_TEST-95afef5e-2325-4e52-878d-d6236ae7bfa7
  model: {provider: cursor, family: grok, version: '4.5'}
- role: skill2-auditor
  human_id: minshaoho
  run_id: dv_test_audit-SMC_DMA_CG_ACTIVITY_TEST-8d57b4e6-2d89-4119-af45-91ca33dc3245
  model: {provider: cursor, family: grok, version: '4.5'}
- role: skill2-auditor
  human_id: minshaoho
  run_id: dv_test_audit-SMC_ZEROER_AXICLK_CG_TEST-a3f529c4-02ac-43fb-a1d8-907e6147b65a
  model: {provider: cursor, family: grok, version: '4.5'}
- role: skill2-auditor
  human_id: minshaoho
  run_id: dv_test_audit-SMC_ZEROER_REGCLK_CG_TEST-b7e506bf-b720-4295-82e9-dca594294dbf
  model: {provider: cursor, family: grok, version: '4.5'}
- role: skill2-auditor
  human_id: minshaoho
  run_id: dv_test_audit-SMC_ZEROER_CG_INDEP_TEST-24e034821e5542e98d84f70c280bbd56
  model: {provider: cursor, family: grok, version: '4.5'}
- role: skill2-auditor
  human_id: minshaoho
  run_id: dv_test_audit-SMC_STATIC_CG_SANITY_TEST-493b545b-2608-47f6-8c06-eb04fad4ad0e
  model: {provider: cursor, family: grok, version: '4.5'}
- role: skill2-auditor
  human_id: minshaoho
  run_id: dv_test_audit-SMC_CLK_MULTI_WINDOW_TEST-df05f6072436480d82eb71249e3a5c17
  model: {provider: cursor, family: grok, version: '4.5'}
- role: skill2-auditor
  human_id: minshaoho
  run_id: dv_test_audit-SMC_CLK_RUNNING_TEST-75e9d256c2bd40a8837f1aa4258bb201
  model: {provider: cursor, family: grok, version: '4.5'}
- role: skill2-auditor
  human_id: minshaoho
  run_id: dv_test_audit-SMC_CG_TEST_MODE_BYPASS_TEST-6ec5b8e65cd54fdeb374526fcc7ba25a
  model: {provider: cursor, family: grok, version: '4.5'}
- role: prior-peer-auditor
  human_id: dv-peer-fresh-smc-cg-final
  run_id: dv_peer_audit-SMC_CLOCK_GATING-P1-20260805T141900+0800-fresh-grok45-final
  model: {provider: cursor, family: grok, version: '4.5'}
denominator:
  inventory_keys: 23
  excluded_keys: 4
  milestone_required_keys: 19
  covered_keys: 17
coverage:
- key: SMC-CG-ARCH-PARAMS.S1
  required_proof_class: LIVE
  status: COVERED
  allocated_to: SMC_CLK_MULTI_WINDOW_TEST
  closed_by_allocated: true
  proven_by:
  - checker_ref: smc_clk_multi_window_test/CHK-HYST-WINDOW/a99a7baf65fda9ae01394a5923d4ad8437ed559cf52fc208b980b5bd91596b10
    independent_evidence:
      required: false          # closure_tier B
      method: NOT-REQUIRED
      source_run_id: dv_test_audit-SMC_CLK_MULTI_WINDOW_TEST-df05f6072436480d82eb71249e3a5c17
      source_log_sha256: 557f7d0f739f7fb0d81f68137db11e4b8b414b20eddc896e41cb7c42e809349c
      run_id: null
      build_fingerprint: null
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model: {provider: null, family: null, version: null}
      gate_satisfied: false
  required_cells: [hysteresis_delay_min, hysteresis_delay_mid, hysteresis_delay_max]
  achieved_cells: [hysteresis_delay_min, hysteresis_delay_mid, hysteresis_delay_max]
- key: SMC-CG-ARCH-PARAMS.S2
  required_proof_class: LIVE
  status: COVERED
  allocated_to: SMC_CLK_RUNNING_TEST
  closed_by_allocated: true
  proven_by:
  - checker_ref: smc_clk_running_test/CHK-ACTIVE-RUNNING/e530a0145b71ae4c0cbe43697778f2fc5f42e19de6367ff71964f7da39d08275
    independent_evidence:
      required: false          # closure_tier B
      method: NOT-REQUIRED
      source_run_id: dv_test_audit-SMC_CLK_RUNNING_TEST-75e9d256c2bd40a8837f1aa4258bb201
      source_log_sha256: 807b1266708bd851f04e28c5cb0a6075dd88f11bb3fc27265225321a45d5f945
      run_id: null
      build_fingerprint: null
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model: {provider: null, family: null, version: null}
      gate_satisfied: false
  required_cells: [module_active_clock_running, module_idle_clock_gated]
  achieved_cells: [module_active_clock_running, module_idle_clock_gated]
- key: SMC-CG-ARCH-PARAMS.S3
  required_proof_class: LIVE
  status: REAL-GAP
  allocated_to: SMC_STATIC_CG_SANITY_TEST
  closed_by_allocated: false
  proven_by:
  - checker_ref: smc_static_cg_sanity_test/CHK-ENABLE-THRESHOLD/0299550393e0df6901406bb6c5e3cb5d77a24f2ad8e786c8b69e82a75133e493
    independent_evidence:
      required: false          # closure_tier B
      method: NOT-REQUIRED
      source_run_id: dv_test_audit-SMC_STATIC_CG_SANITY_TEST-493b545b-2608-47f6-8c06-eb04fad4ad0e
      source_log_sha256: 3d21022c1749bc3d0ae9252fad6f8b0059c53198d93050e0f4ba55a240c1d806
      run_id: null
      build_fingerprint: null
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model: {provider: null, family: null, version: null}
      gate_satisfied: false
  required_cells: [enable_threshold_delay_min, enable_threshold_delay_max]
  achieved_cells: []
- key: SMC-CG-ARCH-PARAMS.S4
  required_proof_class: LIVE
  status: COVERED
  allocated_to: SMC_STATIC_CG_SANITY_TEST
  closed_by_allocated: true
  proven_by:
  - checker_ref: smc_static_cg_sanity_test/CHK-MODULE-GATING/0299550393e0df6901406bb6c5e3cb5d77a24f2ad8e786c8b69e82a75133e493
    independent_evidence:
      required: false          # closure_tier B
      method: NOT-REQUIRED
      source_run_id: dv_test_audit-SMC_STATIC_CG_SANITY_TEST-493b545b-2608-47f6-8c06-eb04fad4ad0e
      source_log_sha256: 3d21022c1749bc3d0ae9252fad6f8b0059c53198d93050e0f4ba55a240c1d806
      run_id: null
      build_fingerprint: null
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model: {provider: null, family: null, version: null}
      gate_satisfied: false
  required_cells: [module_gating_enabled, module_gating_disabled]
  achieved_cells: [module_gating_enabled, module_gating_disabled]
- key: DMA-CG-CTRL.S1
  required_proof_class: LIVE
  status: COVERED
  allocated_to: SMC_DMA_CG_ACTIVITY_TEST
  closed_by_allocated: true
  proven_by:
  - checker_ref: smc_dma_cg_activity_test/CHK-DMA-GATE-OFF/643323ffd6a2209f16ec2826e84e4b2e1b0b9fe3840f01903be0e3e1fc1bcbf4
    independent_evidence:
      required: true          # closure_tier A
      method: REPRODUCE-FROM-SEED
      source_run_id: dv_test_audit-SMC_DMA_CG_ACTIVITY_TEST-8d57b4e6-2d89-4119-af45-91ca33dc3245
      source_log_sha256: c448f12feaa5d2a7098e95531fd1ecfb5ca937adc2ba894f21ea97c06b0a1ab1
      run_id: null
      build_fingerprint: null
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model: {provider: null, family: null, version: null}
      gate_satisfied: false
  required_cells: [dma_clock_gated_off_after_idle]
  achieved_cells: [dma_clock_gated_off_after_idle]
- key: DMA-CG-CTRL.S2
  required_proof_class: LIVE
  status: COVERED
  allocated_to: SMC_DMA_CG_ACTIVITY_TEST
  closed_by_allocated: true
  proven_by:
  - checker_ref: smc_dma_cg_activity_test/CHK-DMA-WAKEUP-FRONTEND/643323ffd6a2209f16ec2826e84e4b2e1b0b9fe3840f01903be0e3e1fc1bcbf4
    independent_evidence:
      required: true          # closure_tier A
      method: REPRODUCE-FROM-SEED
      source_run_id: dv_test_audit-SMC_DMA_CG_ACTIVITY_TEST-8d57b4e6-2d89-4119-af45-91ca33dc3245
      source_log_sha256: c448f12feaa5d2a7098e95531fd1ecfb5ca937adc2ba894f21ea97c06b0a1ab1
      run_id: null
      build_fingerprint: null
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model: {provider: null, family: null, version: null}
      gate_satisfied: false
  required_cells: [dma_clock_enabled_on_frontend_wakeup]
  achieved_cells: [dma_clock_enabled_on_frontend_wakeup]
- key: DMA-CG-CTRL.S3
  required_proof_class: LIVE
  status: COVERED
  allocated_to: SMC_DMA_CG_ACTIVITY_TEST
  closed_by_allocated: true
  proven_by:
  - checker_ref: smc_dma_cg_activity_test/CHK-DMA-WAKEUP-BACKEND/643323ffd6a2209f16ec2826e84e4b2e1b0b9fe3840f01903be0e3e1fc1bcbf4
    independent_evidence:
      required: true          # closure_tier A
      method: REPRODUCE-FROM-SEED
      source_run_id: dv_test_audit-SMC_DMA_CG_ACTIVITY_TEST-8d57b4e6-2d89-4119-af45-91ca33dc3245
      source_log_sha256: c448f12feaa5d2a7098e95531fd1ecfb5ca937adc2ba894f21ea97c06b0a1ab1
      run_id: null
      build_fingerprint: null
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model: {provider: null, family: null, version: null}
      gate_satisfied: false
  required_cells: [dma_clock_enabled_on_backend_busy]
  achieved_cells: [dma_clock_enabled_on_backend_busy]
- key: DMA-CG-CTRL.S4
  required_proof_class: LIVE
  status: COVERED
  allocated_to: SMC_DMA_CG_ACTIVITY_TEST
  closed_by_allocated: true
  proven_by:
  - checker_ref: smc_dma_cg_activity_test/CHK-DMA-GATING-DISABLED/643323ffd6a2209f16ec2826e84e4b2e1b0b9fe3840f01903be0e3e1fc1bcbf4
    independent_evidence:
      required: true          # closure_tier A
      method: REPRODUCE-FROM-SEED
      source_run_id: dv_test_audit-SMC_DMA_CG_ACTIVITY_TEST-8d57b4e6-2d89-4119-af45-91ca33dc3245
      source_log_sha256: c448f12feaa5d2a7098e95531fd1ecfb5ca937adc2ba894f21ea97c06b0a1ab1
      run_id: null
      build_fingerprint: null
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model: {provider: null, family: null, version: null}
      gate_satisfied: false
  required_cells: [dma_cg_disabled_clock_always_on]
  achieved_cells: [dma_cg_disabled_clock_always_on]
- key: DMA-CG-CTRL.S5
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells: [dma_hysteresis_0, dma_hysteresis_mid, dma_hysteresis_63]
  achieved_cells: []
- key: DMA-CG-CTRL.S6
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells: [activity_during_hysteresis_countdown_resumes_without_gating]
  achieved_cells: []
- key: CG-DFT-TEST-BYPASS.S1
  required_proof_class: LIVE
  status: COVERED
  allocated_to: SMC_CG_TEST_MODE_BYPASS_TEST
  closed_by_allocated: true
  proven_by:
  - checker_ref: smc_cg_test_mode_bypass_test/CHK-DFT-BYPASS-DMA/a57b8155beb259e7235a2b7acf7ee8ba609fec640e4663a196ccd09e279c6b2b
    independent_evidence:
      required: false          # closure_tier B
      method: NOT-REQUIRED
      source_run_id: dv_test_audit-SMC_CG_TEST_MODE_BYPASS_TEST-6ec5b8e65cd54fdeb374526fcc7ba25a
      source_log_sha256: 15806e516ec4238ba7ecc30a30a506af1967f51ca57f28e72efacc07e99c2dd8
      run_id: null
      build_fingerprint: null
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model: {provider: null, family: null, version: null}
      gate_satisfied: false
  required_cells: [dma_gate_bypassed_in_test_mode]
  achieved_cells: [dma_gate_bypassed_in_test_mode]
- key: CG-DFT-TEST-BYPASS.S2
  required_proof_class: LIVE
  status: REAL-GAP
  allocated_to: SMC_CG_TEST_MODE_BYPASS_TEST
  closed_by_allocated: false
  proven_by:
  - checker_ref: smc_cg_test_mode_bypass_test/CHK-DFT-BYPASS-ZEROER/a57b8155beb259e7235a2b7acf7ee8ba609fec640e4663a196ccd09e279c6b2b
    independent_evidence:
      required: false          # closure_tier B
      method: NOT-REQUIRED
      source_run_id: dv_test_audit-SMC_CG_TEST_MODE_BYPASS_TEST-6ec5b8e65cd54fdeb374526fcc7ba25a
      source_log_sha256: 15806e516ec4238ba7ecc30a30a506af1967f51ca57f28e72efacc07e99c2dd8
      run_id: null
      build_fingerprint: null
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model: {provider: null, family: null, version: null}
      gate_satisfied: false
  required_cells: [zeroer_axiclk_bypassed_in_test_mode, zeroer_regclk_bypassed_in_test_mode]
  achieved_cells: []
- key: ZEROER-AXICLK-CG.S1
  required_proof_class: LIVE
  status: COVERED
  allocated_to: SMC_ZEROER_AXICLK_CG_TEST
  closed_by_allocated: true
  proven_by:
  - checker_ref: smc_zeroer_axiclk_cg_test/CHK-ZAXI-GATE-OFF-IDLE/09a08a95e33716c19a8a0ec0fed163b436fc8b85fe68829540cae208e01839d6
    independent_evidence:
      required: true          # closure_tier A
      method: REPRODUCE-FROM-SEED
      source_run_id: dv_test_audit-SMC_ZEROER_AXICLK_CG_TEST-a3f529c4-02ac-43fb-a1d8-907e6147b65a
      source_log_sha256: d32840f62eaba3585678e27560c396fdfaafd797a0d227b9dd1722aeba25222e
      run_id: null
      build_fingerprint: null
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model: {provider: null, family: null, version: null}
      gate_satisfied: false
  required_cells: [axiclk_gated_off_idle]
  achieved_cells: [axiclk_gated_off_idle]
- key: ZEROER-AXICLK-CG.S2
  required_proof_class: LIVE
  status: COVERED
  allocated_to: SMC_ZEROER_AXICLK_CG_TEST
  closed_by_allocated: true
  proven_by:
  - checker_ref: smc_zeroer_axiclk_cg_test/CHK-ZAXI-BUSY-ENABLE/09a08a95e33716c19a8a0ec0fed163b436fc8b85fe68829540cae208e01839d6
    independent_evidence:
      required: true          # closure_tier A
      method: REPRODUCE-FROM-SEED
      source_run_id: dv_test_audit-SMC_ZEROER_AXICLK_CG_TEST-a3f529c4-02ac-43fb-a1d8-907e6147b65a
      source_log_sha256: d32840f62eaba3585678e27560c396fdfaafd797a0d227b9dd1722aeba25222e
      run_id: null
      build_fingerprint: null
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model: {provider: null, family: null, version: null}
      gate_satisfied: false
  required_cells: [axiclk_enabled_on_busy]
  achieved_cells: [axiclk_enabled_on_busy]
- key: ZEROER-AXICLK-CG.S3
  required_proof_class: LIVE
  status: COVERED
  allocated_to: SMC_ZEROER_AXICLK_CG_TEST
  closed_by_allocated: true
  proven_by:
  - checker_ref: smc_zeroer_axiclk_cg_test/CHK-ZAXI-DISABLE-CG/09a08a95e33716c19a8a0ec0fed163b436fc8b85fe68829540cae208e01839d6
    independent_evidence:
      required: true          # closure_tier A
      method: REPRODUCE-FROM-SEED
      source_run_id: dv_test_audit-SMC_ZEROER_AXICLK_CG_TEST-a3f529c4-02ac-43fb-a1d8-907e6147b65a
      source_log_sha256: d32840f62eaba3585678e27560c396fdfaafd797a0d227b9dd1722aeba25222e
      run_id: null
      build_fingerprint: null
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model: {provider: null, family: null, version: null}
      gate_satisfied: false
  required_cells: [axiclk_enabled_disable_cg_set]
  achieved_cells: [axiclk_enabled_disable_cg_set]
- key: ZEROER-AXICLK-CG.S4
  required_proof_class: LIVE
  status: COVERED
  allocated_to: SMC_ZEROER_AXICLK_CG_TEST
  closed_by_allocated: true
  proven_by:
  - checker_ref: smc_zeroer_axiclk_cg_test/CHK-ZAXI-RESET-OVERRIDE/09a08a95e33716c19a8a0ec0fed163b436fc8b85fe68829540cae208e01839d6
    independent_evidence:
      required: true          # closure_tier A
      method: REPRODUCE-FROM-SEED
      source_run_id: dv_test_audit-SMC_ZEROER_AXICLK_CG_TEST-a3f529c4-02ac-43fb-a1d8-907e6147b65a
      source_log_sha256: d32840f62eaba3585678e27560c396fdfaafd797a0d227b9dd1722aeba25222e
      run_id: null
      build_fingerprint: null
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model: {provider: null, family: null, version: null}
      gate_satisfied: false
  required_cells: [axiclk_enabled_during_reset]
  achieved_cells: [axiclk_enabled_during_reset]
- key: ZEROER-AXICLK-CG.S5
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells: [axiclk_no_glitch_back_to_back_ops]
  achieved_cells: []
- key: ZEROER-REGCLK-CG.S1
  required_proof_class: LIVE
  status: COVERED
  allocated_to: SMC_ZEROER_REGCLK_CG_TEST
  closed_by_allocated: true
  proven_by:
  - checker_ref: smc_zeroer_regclk_cg_test/CHK-ZREG-GATE-OFF-IDLE/81cff1e014adfa756cc0dd41741e162a93dcf7e2e0b6543604c15531306936e7
    independent_evidence:
      required: true          # closure_tier A
      method: REPRODUCE-FROM-SEED
      source_run_id: dv_test_audit-SMC_ZEROER_REGCLK_CG_TEST-b7e506bf-b720-4295-82e9-dca594294dbf
      source_log_sha256: 9ae9ce78cb840329b87af06f2af9463aab869def1c155b779d3b87d3e7882a27
      run_id: null
      build_fingerprint: null
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model: {provider: null, family: null, version: null}
      gate_satisfied: false
  required_cells: [regclk_gated_off_idle]
  achieved_cells: [regclk_gated_off_idle]
- key: ZEROER-REGCLK-CG.S2
  required_proof_class: LIVE
  status: COVERED
  allocated_to: SMC_ZEROER_REGCLK_CG_TEST
  closed_by_allocated: true
  proven_by:
  - checker_ref: smc_zeroer_regclk_cg_test/CHK-ZREG-ACTIVITY-ENABLE/81cff1e014adfa756cc0dd41741e162a93dcf7e2e0b6543604c15531306936e7
    independent_evidence:
      required: true          # closure_tier A
      method: REPRODUCE-FROM-SEED
      source_run_id: dv_test_audit-SMC_ZEROER_REGCLK_CG_TEST-b7e506bf-b720-4295-82e9-dca594294dbf
      source_log_sha256: 9ae9ce78cb840329b87af06f2af9463aab869def1c155b779d3b87d3e7882a27
      run_id: null
      build_fingerprint: null
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model: {provider: null, family: null, version: null}
      gate_satisfied: false
  required_cells: [regclk_enabled_on_register_activity]
  achieved_cells: [regclk_enabled_on_register_activity]
- key: ZEROER-REGCLK-CG.S3
  required_proof_class: LIVE
  status: COVERED
  allocated_to: SMC_ZEROER_REGCLK_CG_TEST
  closed_by_allocated: true
  proven_by:
  - checker_ref: smc_zeroer_regclk_cg_test/CHK-ZREG-DISABLE-CG/81cff1e014adfa756cc0dd41741e162a93dcf7e2e0b6543604c15531306936e7
    independent_evidence:
      required: true          # closure_tier A
      method: REPRODUCE-FROM-SEED
      source_run_id: dv_test_audit-SMC_ZEROER_REGCLK_CG_TEST-b7e506bf-b720-4295-82e9-dca594294dbf
      source_log_sha256: 9ae9ce78cb840329b87af06f2af9463aab869def1c155b779d3b87d3e7882a27
      run_id: null
      build_fingerprint: null
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model: {provider: null, family: null, version: null}
      gate_satisfied: false
  required_cells: [regclk_enabled_disable_cg_set]
  achieved_cells: [regclk_enabled_disable_cg_set]
- key: ZEROER-REGCLK-CG.S4
  required_proof_class: LIVE
  status: COVERED
  allocated_to: SMC_ZEROER_REGCLK_CG_TEST
  closed_by_allocated: true
  proven_by:
  - checker_ref: smc_zeroer_regclk_cg_test/CHK-ZREG-RESET-OVERRIDE/81cff1e014adfa756cc0dd41741e162a93dcf7e2e0b6543604c15531306936e7
    independent_evidence:
      required: true          # closure_tier A
      method: REPRODUCE-FROM-SEED
      source_run_id: dv_test_audit-SMC_ZEROER_REGCLK_CG_TEST-b7e506bf-b720-4295-82e9-dca594294dbf
      source_log_sha256: 9ae9ce78cb840329b87af06f2af9463aab869def1c155b779d3b87d3e7882a27
      run_id: null
      build_fingerprint: null
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model: {provider: null, family: null, version: null}
      gate_satisfied: false
  required_cells: [regclk_enabled_during_reset]
  achieved_cells: [regclk_enabled_during_reset]
- key: ZEROER-REGCLK-CG.S5
  required_proof_class: LIVE
  status: MILESTONE-DEFERRED
  allocated_to: null
  closed_by_allocated: null
  proven_by: []
  required_cells: [regclk_no_glitch_pending_access]
  achieved_cells: []
- key: INT-ZEROER-CG-INDEP
  required_proof_class: LIVE
  status: COVERED
  allocated_to: SMC_ZEROER_CG_INDEP_TEST
  closed_by_allocated: true
  proven_by:
  - checker_ref: smc_zeroer_cg_indep_test/CHK-ZINDEP-DECOUPLE/0d39f6ea64d7e18a641837f80c7b4e83f5bafcafb0fee704a4a2d5ec76a3c22d
    independent_evidence:
      required: true          # closure_tier A
      method: REPRODUCE-FROM-SEED
      source_run_id: dv_test_audit-SMC_ZEROER_CG_INDEP_TEST-24e034821e5542e98d84f70c280bbd56
      source_log_sha256: 1c39f29a1c81d83950d23ab4e38423bf62b9dfeceb8b1fd19b0cba178fc8f56a
      run_id: null
      build_fingerprint: null
      log_or_artifact_sha256: null
      observer:
        human_id: null
        model: {provider: null, family: null, version: null}
      gate_satisfied: false
  required_cells: [axi-active-reg-idle-decoupled, reg-active-axi-idle-decoupled]
  achieved_cells: [axi-active-reg-idle-decoupled, reg-active-axi-idle-decoupled]
residuals:
- key: DMA-CG-CTRL.S5
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: 'SMC_CLOCK_GATING_TESTCASE_PLAN.md unallocated row DMA-CG-CTRL.S5 reason OUT-OF-MILESTONE / downstream_class out-of-scope; accepted_by minshaoho accepted_at 2026-08-05T09:20:00+08:00 (full-range (0/mid/63) randomized hysteresis-boundary sweep)'
  closes_at_milestone: P2
  review_or_expiry: pin_revision 1 / plan_revision 1 / feature_list_revision 2
- key: DMA-CG-CTRL.S6
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: 'SMC_CLOCK_GATING_TESTCASE_PLAN.md unallocated row DMA-CG-CTRL.S6 reason OUT-OF-MILESTONE / downstream_class out-of-scope; accepted_by minshaoho accepted_at 2026-08-05T09:20:00+08:00 (contested activity-during-hysteresis-countdown race)'
  closes_at_milestone: P2
  review_or_expiry: pin_revision 1 / plan_revision 1 / feature_list_revision 2
- key: ZEROER-AXICLK-CG.S5
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: 'SMC_CLOCK_GATING_TESTCASE_PLAN.md unallocated row ZEROER-AXICLK-CG.S5 reason OUT-OF-MILESTONE / downstream_class out-of-scope; accepted_by minshaoho accepted_at 2026-08-05T09:20:00+08:00 (contested back-to-back-operation/busy-deassert race on axi_clk)'
  closes_at_milestone: P2
  review_or_expiry: pin_revision 1 / plan_revision 1 / feature_list_revision 2
- key: ZEROER-REGCLK-CG.S5
  class: MILESTONE-DEFERRED
  counts_against_closure: false
  authority_kind: PLAN-ROW
  authority_ref: 'SMC_CLOCK_GATING_TESTCASE_PLAN.md unallocated row ZEROER-REGCLK-CG.S5 reason OUT-OF-MILESTONE / downstream_class out-of-scope; accepted_by minshaoho accepted_at 2026-08-05T09:20:00+08:00 (contested pending-register-access-during-gate-transition race on reg_clk)'
  closes_at_milestone: P2
  review_or_expiry: pin_revision 1 / plan_revision 1 / feature_list_revision 2
- key: SMC-CG-ARCH-PARAMS.S3
  class: REAL-GAP
  counts_against_closure: true
  authority_kind: NONE
  authority_ref: null          # a real gap claims no exemption
  closes_at_milestone: null
  review_or_expiry: 'no checker proves an enable-threshold delay independent of the hysteresis count (F3)'
- key: CG-DFT-TEST-BYPASS.S2
  class: REAL-GAP
  counts_against_closure: true
  authority_kind: NONE
  authority_ref: null          # a real gap claims no exemption
  closes_at_milestone: null
  review_or_expiry: 'no in-run otherwise-gating precondition for the two Zeroer clocks (F2)'
findings:
- id: F1
  tag: '[BUILD-MODEL-IDENTITY]'
  severity: Blocking
  affected_keys: [CG-DFT-TEST-BYPASS.S1, CG-DFT-TEST-BYPASS.S2, ZEROER-AXICLK-CG.S1,
    ZEROER-AXICLK-CG.S2, ZEROER-AXICLK-CG.S3, ZEROER-AXICLK-CG.S4, ZEROER-REGCLK-CG.S1,
    ZEROER-REGCLK-CG.S2, ZEROER-REGCLK-CG.S3, ZEROER-REGCLK-CG.S4, INT-ZEROER-CG-INDEP,
    DMA-CG-CTRL.S1, DMA-CG-CTRL.S2, DMA-CG-CTRL.S3, DMA-CG-CTRL.S4,
    SMC-CG-ARCH-PARAMS.S1, SMC-CG-ARCH-PARAMS.S2, SMC-CG-ARCH-PARAMS.S4]
  artifact_ref: hw/common/och_prim_generic/rtl/prim_clkgater.sv:20 (uncommitted working-tree
    change) vs every grade report's repository_revision 2ecc7b227e3926b253c65b5aac21239eec24ba5f
  observed: 'Shared DUT RTL was modified in the working tree to implement the very DFT
    behavior under test: prim_clkgater.sv:20 now reads `latched_en = i_en | i_te;` where the
    committed revision reads `latched_en = i_en;`. prim_clkgater is the cell the Memory Zeroer
    instantiates for both gated clocks, so at the recorded revision test_en_i could not have
    bypassed those gates at all and CG-DFT-TEST-BYPASS.S2 could not have passed. The change is
    itself owner-decided and recorded as such in hw/sys/smc/dv/docs/smc_cg_skill3.md 1 item 4
    ("SMC_CG_TEST_MODE_BYPASS_TEST after the prim_clkgater i_te fix"), so it is not a silent
    edit - the defect is that nothing in the evidence chain reflects it. All 8 grade reports
    record repository_revision 2ecc7b227e39 (a commit that does not contain the change),
    compile_inputs_sha256 null, and exceptions []. hw/sys/smc/dv/tb/tb_top.sv is likewise
    modified (+44 lines of observation lifts and the test_en_i pin) and all 13 cocotb
    sequence/test sources for this milestone are untracked. So every grade report in this
    milestone misidentifies the elaborated model, no recorded hash pins the code that actually
    ran, and a change to shared common RTL that is outside DV scope to approve has not been
    reviewed or committed by its design owner.'
  owner: DV owner + SMC design owner (prim_clkgater is shared common RTL outside DV scope)
  closure_condition: The prim_clkgater change is reviewed and either committed or reverted
    by the design owner; tb_top.sv and all cocotb sources are committed; every grade report
    re-records a repository_revision and a non-null compile_inputs_sha256 that contain the
    reviewed state, and the 8 runs are repeated at that identity.
- id: F2
  tag: '[NEGATIVE-NEEDS-POSITIVE-CONTROL]'
  severity: Blocking
  affected_keys: [CG-DFT-TEST-BYPASS.S2]
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_cg_test_mode_bypass_test_seq.py:42-53,108-122
  observed: 'CG-DFT-TEST-BYPASS.S2 requires both Zeroer clocks to stay enabled "even when
    their respective gating conditions would otherwise gate them off". The sequence never
    establishes that precondition in-run: test_en_i is already 1 from line 81, the two clocks
    are sampled after a bare ClockCycles(HYST+4) wait, and there is no positive control on
    either handle. Worse, this file''s _program_cg (42-53) is the only one in the slate with
    no CSR readback assertion, and the sequence never checks tb_zeroer_cg_en == 1 or
    tb_zeroer_busy == 0. The observation "axi_edges=16 reg_edges=16" is therefore equally
    consistent with gating never having been enabled, disable_cg being set, or the Zeroer
    being busy. The DMA leg (S1) does carry the control (wait_gated_off at 72-79 with
    test_en_i=0), which is what makes the asymmetry objective. The code comment at line 109
    outsources the precondition to the ZEROER_* tests, but those ran in different simulations
    at test_en_i=0.'
  owner: DV owner
  closure_condition: The sequence proves in the same run, on the same two handles, that both
    Zeroer clocks gate off with test_en_i=0 under the programmed gating conditions (with CSR
    readback of ZEROER_CG_EN), then that both stay enabled every cycle with test_en_i=1;
    Skill 2 re-grades CHK-DFT-BYPASS-ZEROER.
- id: F3
  tag: '[CONTRACT-MATCH]'
  severity: Blocking
  affected_keys: [SMC-CG-ARCH-PARAMS.S3, SMC-CG-ARCH-PARAMS.S1]
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_static_cg_sanity_test_seq.py:22-24,175-178,243-245,324-329
  observed: 'Intent mode O2 (checks the wrong thing), confirmed by objective diff against the
    card. SMC-CG-ARCH-PARAMS.S3''s approved intent is "A configurable enable-threshold delay
    ... independent of the hysteresis count", and the approved card SMC_STATIC_CG_SANITY_TEST
    steps S3/S4 say "program the enable-threshold delay field". The implementation programs
    CLOCK_GATE_CONTROL.CG_HYSTERESIS - the same single field smc_clk_multi_window_test
    programs for S1 - and asserts the measured re-gate delay against that programmed
    hysteresis value (`assert abs(delay - hyst) <= 1`, line 243, message "threshold delay
    {delay} != programmed {hyst}"). The source states it outright at line 22: "SF-002:
    Enable Threshold == Hysteresis Control (same programmable field)", and the approved spec
    audit SF-002 resolution agrees ("No independent Enable Threshold field is claimed in this
    milestone"). S3''s exercised values {8, 63} are a strict subset of S1''s {8, 31, 63}, so
    one measurement of one field is credited to two required inventory keys and S3 receives no
    independent proof. The declared random knob programmed_enable_threshold does not exist
    ([RANDOMIZATION-CONTRACT]). Three approved artifacts disagree; per policy this routes to
    Skill 1 and must not be patched in the test.'
  owner: Skill 1 owner (contract), then DV owner
  closure_condition: 'Skill 1 amends the feature_list to resolve SF-002 in the inventory -
    either merge S3 into S1 as one mechanism, or restate S3 as a genuinely independent field
    with its own spec_refs - and regenerates the affected card; if merged, S3 leaves the
    inventory by an accepted plan row or waiver rather than by silent double-credit.'
- id: F4
  tag: '[REPRESENTATIVE-EVIDENCE]'
  severity: Blocking
  affected_keys: [DMA-CG-CTRL.S1, DMA-CG-CTRL.S2, DMA-CG-CTRL.S3, DMA-CG-CTRL.S4,
    ZEROER-AXICLK-CG.S1, ZEROER-AXICLK-CG.S2, ZEROER-AXICLK-CG.S3, ZEROER-AXICLK-CG.S4,
    ZEROER-REGCLK-CG.S1, ZEROER-REGCLK-CG.S2, ZEROER-REGCLK-CG.S3, ZEROER-REGCLK-CG.S4,
    INT-ZEROER-CG-INDEP]
  artifact_ref: hw/sys/smc/dv/tb/SMC_CLOCK_GATING_PEER_AUDIT.md (prior revision) coverage[].independent_evidence
    vs hw/sys/smc/dv/build/runs/ (39 run dirs, 153 result.json seed records)
  observed: 'The same-log common-mode gate is unsatisfied for all 17 closure_tier A checkers
    and the prior review asserted the gate instead of deriving it. Objectively: every grade
    report declares exactly one log and seeds [1]; every result.json under build/runs (153
    occurrences) records seed 1 and no other value; the multiple run directories per test are
    sequential same-seed re-runs whose earlier iterations carry status FAIL/ERROR, so the
    cited run is the only run of the final code state. No REPRODUCE-FROM-SEED artifact (a
    distinct run id + distinct log hash + build fingerprint) and no INDEPENDENT-OBSERVATION
    artifact exists anywhere. The prior peer audit nevertheless recorded, for tier-A checkers,
    required false / method NOT-REQUIRED / run_id null / build_fingerprint null /
    log_or_artifact_sha256 null / observer null with gate_satisfied true - precisely the
    self-asserted boolean DV_SKILL3_SPEC.md 6 forbids. Policy 4 designates closure_tier A as
    "required for milestone closure", so required must be true for these 17 checkers.'
  owner: DV owner
  closure_condition: Each of the 17 tier-A checkers gains either a reproduce-from-seed re-run
    of the reviewed build with a distinct run id, a distinct log hash and a non-null build
    fingerprint, or an independent observation artifact with observer provenance satisfying
    policy separation; gate_satisfied then derives true from the recorded fields.
- id: F5
  tag: '[NO-ALWAYS-PASS-CHECKER]'
  severity: Blocking
  affected_keys: [SMC-CG-ARCH-PARAMS.S1, SMC-CG-ARCH-PARAMS.S3, SMC-CG-ARCH-PARAMS.S4]
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_clk_multi_window_test_seq.py:284-289 and
    hw/sys/smc/dv/cocotb/seq_lib/smc_static_cg_sanity_test_seq.py:340-345
  observed: 'Both sequences emit a proof token CHK-TIMEOUT-PATHS whose every field is a
    compile-time constant - "timeout_smc={GATE_OFF_TIMEOUT_SMC} fail_on_expiry=1" - with no
    comparison of any kind executed before or after it. Both tests then list CHK-TIMEOUT-PATHS
    in their required-token final gate (smc_clk_multi_window_test.py:26,
    smc_static_cg_sanity_test.py:30), so a token that measures nothing contributes to the
    pass decision and appears in the kept log alongside real checker results. It is not a
    graded checker in either Skill 2 report, so it closes no key, but it is an always-pass
    proof line in the evidence record of two tests that close three required keys.'
  owner: DV owner
  closure_condition: CHK-TIMEOUT-PATHS is either removed from both sequences and from both
    required-token gates, or replaced by a token emitted only after an executed comparison
    (e.g. a deliberately expired wait proven to raise).
- id: F6
  tag: '[EXACT-EXPECTATION]'
  severity: Major
  affected_keys: [DMA-CG-CTRL.S1]
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_dma_cg_activity_test_seq.py:64-65,127-141,371-379
  observed: 'The tier-A CHK-DMA-GATE-OFF timing bound is looser than its approved card and
    coarser than the quantity it measures, and it is skippable. The card''s fail_on is "a
    toggle observed on the DMA clock beyond the programmed hysteresis window"; the code
    asserts last_toggle <= HYST_CYCLES + IDLE_OBSERVE = 8 + 16 = 24 for a programmed window
    of 8. _wait_gated_off advances cyc in IDLE_OBSERVE steps (line 130) and returns
    last_toggle_at = cyc + IDLE_OBSERVE (135), so the observable values are only -1, 16, 32,
    ... - a 16-cycle resolution for an 8-cycle window, which is what the card''s own
    [NO-BLIND-DELAY-SYNC] guardrail forbids. The assert is additionally guarded by
    `if last_toggle >= 0` (375) and the source notes -1 is an expected outcome ("already
    gated"), so on such a run the timing claim is never checked while the same PROVEN token
    still prints. In the graded run last_toggle was 16, so the assert did execute and the
    gate-off cell (dma_clock_gated_off_after_idle) is genuinely hit - which is why this key
    stays COVERED rather than becoming a gap.'
  owner: DV owner
  closure_condition: The gate-off latency is measured at cycle resolution against the actual
    tb_dma_gater_busy fall (as smc_clk_multi_window_test already does), the bound is the
    programmed hysteresis window +/- 1 rather than +IDLE_OBSERVE, and the timing assert runs
    unconditionally (the already-gated case is either excluded by construction or asserted
    separately).
- id: F7
  tag: '[CROSS-TESTCASE-CONSISTENCY]'
  severity: Major
  affected_keys: [DMA-CG-CTRL.S1, DMA-CG-CTRL.S3, SMC-CG-ARCH-PARAMS.S1, SMC-CG-ARCH-PARAMS.S3]
  artifact_ref: smc_clk_multi_window_test_seq.py:245 and smc_static_cg_sanity_test_seq.py:243
    vs smc_dma_cg_activity_test_seq.py:376; SMC_CLOCK_GATING_VPLAN_DETAIL.md card
    SMC_DMA_CG_ACTIVITY_TEST revision 1 vs revision 2
  observed: 'Two unexplained rigor asymmetries within one behaviour class. (a) The same
    re-gate-delay measurement is asserted to +/-1 cycle in smc_clk_multi_window_test (line
    245) and smc_static_cg_sanity_test (243), but with a +16-cycle / 2x-of-window bound in the
    tier-A smc_dma_cg_activity_test (376); the loosest of the three is the closure-critical
    one and no card cites a reason. (b) Of the four activity-source checkers, three prove
    resume-from-gated with an explicit latency (CHK-DMA-WAKEUP-FRONTEND resume_cyc=0,
    CHK-ZAXI-BUSY-ENABLE resume_cyc=1, CHK-ZREG-ACTIVITY-ENABLE resume_at=1) while
    CHK-DMA-WAKEUP-BACKEND was weakened at card revision 2 from "resumes toggling within one
    cycle of backend busy asserting" to "toggles every cycle during a backend-only window",
    and its evidence (edges_before_be=4 be_at=4) shows the clock was already running, so no
    resumption is exercised. DMA-CG-CTRL.S3''s intent permits "keeps/returns", so the key
    still closes, but the class is now checked two different ways with no stated rationale.'
  owner: DV owner
  closure_condition: Either the three measurements adopt one documented exactness bound and
    CHK-DMA-WAKEUP-BACKEND exercises a gated-to-enabled transition, or each deviation carries
    an explicit rationale on its approved card.
- id: F8
  tag: '[SHARED-INFRA-QUALITY]'
  severity: Major
  affected_keys: [DMA-CG-CTRL.S1, DMA-CG-CTRL.S2, DMA-CG-CTRL.S4]
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_dma_cg_activity_test_seq.py:104-125 vs
    hw/sys/smc/dv/cocotb/seq_lib/smc_cg_obs_utils.py:76-100,103-125
  observed: 'The tier-A DMA sequence carries a private fork of the shared count_gated_rising
    helper that is strictly weaker than the shared version: it omits the X/Z guard the shared
    level samplers carry (smc_cg_obs_utils.py:119-120) and it omits the same-timestep Timer
    the shared edge counter uses before setting stop["done"], which the shared docstring says
    exists to mitigate a free-running N-1 under-count. That under-count is then absorbed by
    loosening three tier-A checks to `edges >= 2` (429) and `edges >= IDLE_OBSERVE - 1` (473).
    The shared helper''s own docstring directs callers to prefer count_enabled_at_smc_rise for
    exact every-cycle proof, and the DFT-bypass test does exactly that - the tier-A DMA test
    does not. Shared infra reviewed once is otherwise sound: every sizing/threshold argument in
    smc_cg_obs_utils.py is keyword-only with no default, a wrong signal name raises
    AttributeError, and all addresses in smc_addr_map.py resolve through generated PeakRDL
    headers with fail-loud KeyError/RuntimeError paths.'
  owner: DV owner
  closure_condition: The DMA sequence uses the shared helpers (count_enabled_at_smc_rise for
    every-cycle claims), the private fork is deleted, and the three loosened bounds are
    restored to exact comparisons.
- id: F9
  tag: '[EVIDENCE-TOKEN-CONDITIONAL]'
  severity: Major
  affected_keys: [DMA-CG-CTRL.S1, DMA-CG-CTRL.S2, DMA-CG-CTRL.S4, ZEROER-AXICLK-CG.S1,
    ZEROER-REGCLK-CG.S1, CG-DFT-TEST-BYPASS.S1]
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_dma_cg_activity_test_seq.py:381-385,430-434,476-480;
    smc_zeroer_axiclk_cg_test_seq.py:233; smc_zeroer_regclk_cg_test_seq.py:148
  observed: 'Numeric fields in the kept-log proof tokens are not all measurements. Some are
    hard-coded literals (resume_within_1cyc=1 at dma seq 432, toggles_every_cycle=1 at 478);
    some are recomputed from a condition already asserted, so they can only ever print 1
    (within_1, resume_ok, every_ok, toggles_rst, dma_every, z_every, s1_ok, s2_ok,
    independent); and zero_toggles_idle prints the window constant IDLE_OBSERVE rather than
    the measured edges value that was actually compared. The proofs still hold because every
    sequence is fail-fast on real asserts, but the token a milestone reviewer reads is not
    self-evidencing, and each test''s final gate checks token presence only - a token
    carrying toggles_every_cycle=0 would still satisfy it.'
  owner: DV owner
  closure_condition: Each token field prints the measured quantity that was compared (edges,
    measured latency) rather than a constant or a restatement of the assert outcome.
- id: F10
  tag: '[IP-CHECKLIST-CONSISTENCY]'
  severity: Major
  affected_keys: [SMC-CG-ARCH-PARAMS.S3, SMC-CG-ARCH-PARAMS.S4]
  artifact_ref: hw/sys/smc/dv/testlists/clock.toml:28-34,74 vs hw/sys/smc/dv/testlists/deferred.toml:93
    and hw/sys/smc/dv/testlists/all.toml:13
  observed: 'smc_static_cg_sanity_test - the only test allocated SMC-CG-ARCH-PARAMS.S3 and .S4
    - is simultaneously an active entry in clock.toml (seed 1, run_modes ["smoke"], reachable
    from all.toml) and a member of deferred.toml''s deferred_tb_policy group, which all.toml''s
    own header declares "NOT included here". Two authoritative enrollment lists disagree about
    a test that closes two required P1 keys. All 8 anchors are otherwise properly enrolled via
    clock.toml, so there is no E3 orphan in this milestone.'
  owner: DV owner
  closure_condition: The stale deferred.toml entry for smc_static_cg_sanity_test is removed (or
    clock.toml''s entry is removed if the deferral is the intended state), so exactly one list
    governs enrollment.
- id: F11
  tag: '[EVIDENCE-FRESHNESS]'
  severity: Major
  affected_keys: [INT-ZEROER-CG-INDEP, DMA-CG-CTRL.S1, DMA-CG-CTRL.S2, DMA-CG-CTRL.S3, DMA-CG-CTRL.S4]
  artifact_ref: SMC_CLOCK_GATING_VPLAN_DETAIL.md front matter (artifact_revision 3, approved_at
    09:20) / SMC_CLOCK_GATING_TESTCASE_PLAN.md (approved_at 09:20, derived_from feature_list_revision
    2) / SMC_CLOCK_GATING_SPEC_FEATURE_LIST.md (approved_at 13:50) / SMC_CLOCK_GATING_PIN.yaml
    (confirmed_at 12:00)
  observed: 'Artifact-level approval timestamps predate the content they certify, so the frozen
    set cannot be ordered from its own records. The cards artifact is revision 3 with approved_at
    2026-08-05T09:20 while it contains a card approved at 13:50 (SMC_ZEROER_CG_INDEP_TEST) and a
    card revision approved at 11:20 (SMC_DMA_CG_ACTIVITY_TEST revision 2). The plan artifact is
    approved at 09:20 yet its derived_from names feature_list revision 2, which was approved at
    13:50. derivation_provenance.feature_list_frozen_at is still 08:20 after the revision-2
    amendment. And the pin''s confirmed_by/confirmed_at (12:00) postdates the feature-list freeze
    (08:20) and the plan, cards and spec-audit approvals (09:20), i.e. the scope input the whole
    derivation cites was confirmed hours after that derivation was approved. Every per-record
    approval and every declared content_sha256 does verify (feature_list a22b78b4, plan 23856412,
    cards c097f008, spec audit 8dbc9a1d all recompute exactly), and each of the 8 grade reports
    cites the correct current card record_sha256 - so this is a records-integrity defect, not a
    wrong-card defect.'
  owner: Skill 1 owner
  closure_condition: The cards and plan artifacts carry an approved_at no earlier than their
    newest approved record, feature_list_frozen_at reflects the revision-2 freeze, and the pin
    records a confirmed_at that precedes the derivation it scopes.
- id: F12
  tag: '[FEATURE-INVENTORY-COMPLETE]'
  severity: Major
  affected_keys: []
  artifact_ref: SMC_CLOCK_GATING_PIN.yaml:30 (boundary) vs SMC_CLOCK_GATING_SPEC_REVIEW.md SF-003
    vs SMC_CLOCK_GATING_REVERSE_FEATURE_INVENTORY.md SF-003
  observed: 'The pin''s boundary names clk_periph among the in-scope multi-domain clocks, but no
    approved artifact asks or answers whether it is clock-gated. The approved spec audit''s SF-003
    covers only clk_ref_i and clk_telemetry_i (answered "always-on by construction"); the
    independent anchor-blind reverse derivation''s SF-003 names the peripheral clock domain
    alongside them. The approved SF-001 waiver addresses per-peripheral module gating, not the
    clk_periph domain itself. No feature or scenario exists for it in either inventory, so this is
    an unasked spec question rather than an inventory omission - which is why the reverse-diff
    disposition is CLEAN - but it leaves one named in-boundary clock domain with no recorded
    answer at the P1 gate.'
  owner: Skill 1 owner + SMC design owner
  closure_condition: A spec-audit finding for clk_periph is raised and answered (gated, or
    always-on by construction) at the next pin revision.
- id: F13
  tag: '[NO-DUMMY-DEAD-CODE]'
  severity: Major
  affected_keys: [INT-ZEROER-CG-INDEP]
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_zeroer_cg_indep_test_seq.py:339-351,382-395
  observed: 'In the tier-A interaction sequence the explicit decoupling checks are tautologically
    unreachable. coupled_s1 = (axi1 == w1 and reg1 == w1) or (axi1 == 0 and reg1 == 0) is
    evaluated after assert w1 > 0 (339), assert axi1 == w1 (340) and assert reg1 == 0 (343), so
    both disjuncts require w1 == 0 and `assert not coupled_s1` can never fire; the same holds for
    coupled_s2 (391-395) after lines 382-387. The interaction key still closes, because the
    preceding per-domain asserts do prove both required cells, but the check that reads as the
    decoupling proof is dead code resembling an active check.'
  owner: DV owner
  closure_condition: The coupling check is rewritten to compare the two domains'' observations in
    a form that can fail, or removed so the per-domain asserts are visibly the whole proof.
- id: F14
  tag: '[NEGATIVE-NEEDS-POSITIVE-CONTROL]'
  severity: Major
  affected_keys: [SMC-CG-ARCH-PARAMS.S2]
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_clk_running_test_seq.py:262-264
  observed: 'The module_idle_clock_gated half of SMC-CG-ARCH-PARAMS.S2 rests on
    `zaxi_edges == 0` on tb_zeroer_gated_axi_clk, and this test never reads a 1 from that handle,
    so there is no same-handle positive control in the run. The pass value and the
    no-observation value are the same number. The risk is bounded - the shared pair sampler
    rejects X/Z (smc_cg_obs_utils.py:141-144), the handle is a continuous assign from the
    Zeroer''s axi_clk, and the DMA handle in the same window reads 16 - so the observation
    mechanism is proven live even though the specific handle is not. Every other gate-off claim
    in the slate does carry a same-handle control.'
  owner: DV owner
  closure_condition: The test reads a nonzero count from tb_zeroer_gated_axi_clk in the same run
    (e.g. under disable_cg) before asserting the gated-off count is zero.
- id: F15
  tag: '[QUALITY-OBLIGATION-GAP]'
  severity: Major
  affected_keys: []
  artifact_ref: SMC_CLOCK_GATING_PIN.yaml:38-40 (quality_policy path /home/minshaoho/.claude/skills/dv_common/DV_QUALITY_POLICY.md)
    and DV_QUALITY_POLICY.md 4-5
  observed: 'No authoritative evidence policy exists for this IP. The pin declares only a
    quality_policy; its PASS definition (5) is titled "pilot, SMU_SEP cocotb" and its
    frontdoor/stimulus policy (4) "SMU_SEP", and neither designates a required gating simulator
    or tool for the SMC P1 gate - so the verilator-only evidence cannot be checked against a
    tool requirement, and DV_QUALITY_POLICY.md 8 directs that a missing threshold be reported as
    INSUFFICIENT-EVIDENCE for the affected judgment. Separately the pinned policy path is not
    readable at the recorded location from a reviewer account (permission denied), which also
    makes schema_check.py report the plan and cards artifacts invalid on that single ground;
    policy identity was instead established by content hash - the reviewer''s local copy
    recomputes to the pinned revision 51a3357d exactly.'
  owner: Policy owner + pin owner
  closure_condition: An SMC-scoped authoritative evidence policy (required tool/version,
    accepted build-model identity, completion/error semantics) is pinned, and quality_policy.path
    points at a location readable by every reviewer.
- id: F16
  tag: '[TRACEABILITY]'
  severity: Major
  affected_keys: []
  artifact_ref: SMC_CLOCK_GATING_PEER_AUDIT.md (prior revision) grade_report_sha256 vs
    hw/sys/smc/dv/tb/grades/*.md
  observed: 'None of the 8 grade_report_sha256 values recorded by the prior peer audit
    (42b7251f, b89ff223, 0eb5b309, e603ee88, bc6725dd, 891482cd, e19a9e28, 2742d04f) matches
    either the file sha256 or the canonical content_sha256 of any grade report now on disk
    (files a57b8155.. / contents ad6d9195..). The prior PASS therefore cannot be tied to the
    artifacts it is recorded against, and the board entry that reads "Skill 2 all 8 grades
    EVIDENCE-CLOSED + owner signoff" rests on a frozen set that is not reconstructible. This
    review recomputed every hash from the current files rather than inheriting any.'
  owner: DV owner
  closure_condition: Grade-report hashes are recorded with a stated method (file or canonical
    content hash) that a reader can recompute from the artifacts on disk.
- id: F17
  tag: '[ALLOCATION-INTENT-DIFF]'
  severity: Major
  affected_keys: [SMC-CG-ARCH-PARAMS.S1, DMA-CG-CTRL.S5]
  artifact_ref: SMC_CLOCK_GATING_TESTCASE_PLAN.md:73-76 (SMC_CLK_MULTI_WINDOW_TEST owns) vs
    hw/sys/smc/dv/cocotb/seq_lib/smc_clk_multi_window_test_seq.py:22-28,53-62,155,197,269-271
  observed: 'Every plan allocation is met by the testcase it was allocated to and no key is
    credited twice, so there is no unmet or accidental allocation. The OWNS partition, however,
    is contradicted by the implementation: SMC_CLK_MULTI_WINDOW_TEST''s owns says "SMC-level
    generic hysteresis-window timing claim only ... not the DMA/Zeroer instance-specific timing",
    yet its only checker programs the shared CLOCK_GATE_CONTROL.CG_HYSTERESIS field and measures
    tb_dma_gated_clk - the DMA instance''s gated clock - at 8/31/63. That is the substance of
    DMA-CG-CTRL.S5, which the plan defers to P2 as "full-range hysteresis sweep ... feature/error
    breadth". The only part of S5 not already exercised is the cell dma_hysteresis_0, and the
    source records that this value does not work: "hyst=0 never runs under cg_enable; hyst=1
    loses the frontend to backend handoff (DMA accepts NEXT_ID but DONE never advances)"
    (lines 22-25). The P2 deferral may therefore be carrying an open design question rather than
    breadth, and the next gate should inherit it as such.'
  owner: Skill 1 owner (OWNS partition) + SMC design owner (hyst=0 behaviour)
  closure_condition: The plan''s owns text matches what the test measures (or the test measures
    an instance the card claims), and the DMA-CG-CTRL.S5 plan row records the hyst=0/hyst=1
    observation so the P2 gate treats it as a design question rather than a sweep.
- id: F18
  tag: '[NO-DUMMY-DEAD-CODE]'
  severity: Minor
  affected_keys: [ZEROER-AXICLK-CG.S1, ZEROER-AXICLK-CG.S2]
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_cg_obs_utils.py:206-232;
    smc_zeroer_axiclk_cg_test_seq.py:22,239,247-253,221-223; smc_zeroer_regclk_cg_test_seq.py:52-53;
    smc_zeroer_cg_indep_test_seq.py:71-72
  observed: 'Housekeeping items, none of which changes a proof: measure_regate_delay is defined
    in the shared helper and called by nothing; start_writes (axiclk 239) is sampled and never
    asserted on; three sequences (axiclk 69-70, regclk 52-53, indep 71-72) read back only the
    enable bit and never confirm the hysteresis value they wrote, while
    smc_cg_test_mode_bypass_test_seq performs no readback at all; axiclk programs HYST=8 but
    expects gate-off within 1 cycle (correct for the Zeroer, whose formula has no hysteresis
    term, but the two constants are never reconciled in that file); max(0, ...) clamps at dma
    seq 424, axiclk 179, regclk 103 and indep 288 would report an early resume as latency 0;
    measure_gate_off_latency''s docstring promises "then stays 0 once" but returns on the first
    zero sample; and the card packet holds 9 records against max_cards_per_packet 8 (the 9th is
    the superseded DMA revision 1, so exactly one current record per anchor is intact).'
  owner: DV owner
  closure_condition: Dead helper and unused measurements removed, hysteresis readback added to
    the three sequences, and the packet split or the superseded record excluded from the count.
- id: F19
  tag: '[MILESTONE-DENOMINATOR]'
  severity: Minor
  affected_keys: []
  artifact_ref: hw/sys/smc/dv/tb/SMC_CLOCK_GATING_PIN.yaml:10 (milestone) vs :30 (boundary prose)
  observed: 'The pin contradicts itself about the milestone it scopes. Its `milestone:` field is
    P1, while its `boundary:` free text states "This pin closes P0-P2 scenarios (milestone P2);
    P3 corner/stress remains OUT-OF-MILESTONE unless later re-pinned." Per DV_SKILL1_SPEC.md 3
    the `milestone:` field is the normative scope input and bounds only which scenarios the
    testcase set must close, so this gate is correctly reviewed at P1 and the four
    OUT-OF-MILESTONE deferrals to P2 are validly authorized - the plan states the same reading
    explicitly. The contradictory prose nevertheless remains in the frozen pin, and a reader who
    computed the denominator from the boundary text would score all four signed P2 deferrals as
    in-milestone and arrive at 23 required keys instead of 19. Recorded so the next re-pin fixes
    it rather than inheriting it.'
  owner: pin owner
  closure_condition: The pin's boundary prose is corrected to agree with its milestone field at
    the next pin revision, or the milestone field is changed and the plan re-scoped.
inventory_delta:
  status: CLEAN
  keys: []
reverse_diff:
  spec_sha256: f093bc4c0efec21b1307be0413b8bb7c167034babcfc2f4d8b2cd2ac5349cc82
  generated_inventory_sha256: 535b4a2d146baf5f1c822ecc0588516d0016b92fe18725e5d626558c711eef92
  run_id: dv_vplan_gen-SMC_CLOCK_GATING-reverse-inventory-20260805T121100+0800-fresh-claude-sonnet5
  actor:
    human_id: fresh-subagent-unattended
    model: {provider: cursor, family: claude, version: sonnet-5}
  compared_generator:
    run_id: dv_vplan_gen-SMC_CLOCK_GATING-P1-20260805T132000+0800-amend-int-zeroer-cg-indep
    model: {provider: cursor, family: grok, version: '4.5'}
  separation_gate_satisfied: true
  reviewed_by: brucehsu
  disposition: CLEAN
result: FAIL
---

# IP Peer Audit — SMC_CLOCK_GATING, P1 gate (MODE=CHECKBOX-MAPPING) — re-review

## Result: **FAIL** — 2 required real gaps; independent-evidence gate unsatisfied on all 17 tier-A checkers

Required at P1: **19 of 23** inventory keys (4 deferred to P2 by accepted plan rows) · Covered: **17 of 19**
Features: 3 of 5 covered · Interactions: 1 of 1 · Real gaps: **2** · Blocked: 0 · Deferred: 4 · Waived: 0
Findings: **5 🔴 Blocking, 12 🟠 Major, 2 🟡 Minor** · Reverse-diff: **CLEAN** · Derivation: **unsealed** (`ordered-single-context`)
Why: `SMC-CG-ARCH-PARAMS.S3` is proven by programming the *hysteresis* field its own intent says it is independent of, and
`CG-DFT-TEST-BYPASS.S2` never establishes the gating precondition it claims to bypass. Independently of those, no closure
certificate is available: the 17 `closure_tier: A` checkers have single-seed single-log evidence only, and the shared
clock-gater RTL was modified in the working tree to implement the DFT behaviour under test while every grade report cites a
committed revision that does not contain that change.

---

## DELTA vs the prior peer audit (`PASS`, 2026-08-05T14:19, grok-4.5)

| Item | Prior review | This review |
|---|---|---|
| Result | `PASS` | **`FAIL`** |
| Denominator | 23 inventory / 4 excluded / 19 required / **19 covered** | 23 / 4 / 19 / **17 covered** |
| Findings | **none recorded** | 5 Blocking · 12 Major · 2 Minor |
| Tier-A independent evidence | `gate_satisfied: true` with `required: false`, `method: NOT-REQUIRED`, all provenance fields `null` | **`gate_satisfied: false`** derived from the recorded fields (F4) |
| Reverse-diff | CLEAN | CLEAN — independently re-diffed, incl. cell granularity |

**Closed since the prior review:** nothing was open — the prior review recorded no findings and no residuals other than the
four P2 deferrals, which remain valid and unchanged.

**Still open:** the four `MILESTONE-DEFERRED` P2 rows (unchanged, correctly authorized).

**New in this review:** F1–F19. Five are closure-blocking. Three could only be found by reading the implementation against
the cards and the working tree rather than the grade reports (F1 RTL change, F2 missing precondition, F3 wrong target); one
is a derivation error in the prior report itself (F4); one shows the prior report's consumed-evidence hashes do not match any
artifact on disk (F16).

---

## Blocking items (must resolve before closure)

**1. REAL-GAP — `SMC-CG-ARCH-PARAMS.S3` (configurable enable-threshold delay)  ·  finding F3**
The scenario's approved intent is *"a configurable enable-threshold delay … **independent of the hysteresis count**"*, and the
approved card step says *"program the enable-threshold delay field"*. The implementation programs
`CLOCK_GATE_CONTROL.CG_HYSTERESIS` — the same single field `smc_clk_multi_window_test` programs for `.S1` — and asserts the
measured re-gate delay against that programmed hysteresis value. The source says so at
`smc_static_cg_sanity_test_seq.py:22`: `# SF-002: Enable Threshold == Hysteresis Control (same programmable field).` The
values exercised, {8, 63}, are a strict subset of `.S1`'s {8, 31, 63}. One measurement of one field is credited to two
required keys. This is intent mode `O2`, and it is a contract defect: the approved spec audit's SF-002 resolution already
says no independent Enable Threshold field is claimed, while the feature_list still carries a scenario whose intent asserts
independence.
Owner: **Skill 1 owner** (do not patch the test) · Closes when: Skill 1 amends the inventory so `.S3` is either merged into
`.S1` as one mechanism or restated as a genuinely independent field, and the affected card is regenerated.

**2. REAL-GAP — `CG-DFT-TEST-BYPASS.S2` (Zeroer axi_clk + reg_clk DFT bypass)  ·  finding F2**
The key requires both Zeroer clocks to stay enabled *"even when their respective gating conditions would otherwise gate them
off."* `smc_cg_test_mode_bypass_test_seq.py:108-122` samples both clocks with `test_en_i` already 1, after a bare
`ClockCycles(HYST+4)` wait, with no positive control on either handle — and this file's `_program_cg` (42-53) is the only one
in the slate with **no CSR readback**, so it is never confirmed that `ZEROER_CG_EN` was even set. `axi_edges=16 reg_edges=16`
is equally consistent with gating disabled or the Zeroer busy. The DMA leg of the same test does carry the control
(`wait_gated_off` at 72-79 with `test_en_i=0`), which is what makes the asymmetry objective rather than stylistic.
Owner: **DV owner** · Closes when: the same run proves both Zeroer clocks gate off at `test_en_i=0` under readback-confirmed
gating, then stay enabled every cycle at `test_en_i=1`; Skill 2 re-grades `CHK-DFT-BYPASS-ZEROER`.

**3. BUILD-MODEL IDENTITY — uncommitted DUT RTL change implements the feature under test  ·  finding F1**
`hw/common/och_prim_generic/rtl/prim_clkgater.sv:20` reads `latched_en = i_en | i_te;` in the working tree; the committed
revision reads `latched_en = i_en;`. That cell is the one the Memory Zeroer instantiates for both gated clocks, so at the
recorded revision `test_en_i` could not have bypassed those gates at all. The change is owner-decided and recorded as such in
`hw/sys/smc/dv/docs/smc_cg_skill3.md` §1 item 4 — it is not a silent edit. **The defect is that no part of the evidence chain
reflects it:** every grade report records `repository_revision: 2ecc7b227e39…` (a commit without the change),
`compile_inputs_sha256: null` and `exceptions: []`; `tb_top.sv` is modified (+44 lines) and all 13 cocotb sources are
untracked. So all 8 runs misidentify the elaborated model, no recorded hash pins the code that ran, and a change to shared
common RTL — outside DV's scope to approve — has not been reviewed or committed by its design owner. Reported for decision,
not patched.
Owner: **SMC design owner** (shared common RTL) **+ DV owner** · Closes when: the RTL change is reviewed and committed or
reverted, `tb_top.sv` and the cocotb sources are committed, and the 8 runs are repeated with a `repository_revision` and a
non-null `compile_inputs_sha256` that contain the reviewed state.

**4. SAME-LOG COMMON-MODE GATE — 17 `closure_tier: A` checkers, 13 required keys  ·  finding F4**
Policy §4 designates tier `A` as *"required for milestone closure"*, so `independent_evidence.required` is `true` for these
checkers. No qualifying evidence exists: every grade report declares one log and `seeds: [1]`; all 153 `seed` records under
`build/runs/` read `1`; the extra run directories per test are same-seed re-runs whose earlier iterations carry
`status=FAIL`/`ERROR`, so the cited run is the only run of the final code state. The prior review recorded
`gate_satisfied: true` alongside `required: false`, `method: NOT-REQUIRED` and every provenance field `null` — the
self-asserted boolean the spec forbids. Affected: `DMA-CG-CTRL.S1`–`.S4`, `ZEROER-AXICLK-CG.S1`–`.S4`,
`ZEROER-REGCLK-CG.S1`–`.S4`, `INT-ZEROER-CG-INDEP`.
Owner: **DV owner** · Closes when: each tier-A checker gains a reproduce-from-seed re-run with a distinct run id, a distinct
log hash and a non-null build fingerprint, or an independent observation artifact with policy-conformant observer provenance.

**5. ALWAYS-PASS PROOF LINE — `CHK-TIMEOUT-PATHS`  ·  finding F5**
`smc_clk_multi_window_test_seq.py:284-289` and `smc_static_cg_sanity_test_seq.py:340-345` emit a proof token whose every
field is a compile-time constant (`timeout_smc=512 fail_on_expiry=1`) with no comparison executed. Both tests list it in
their required-token final gate, so a token that measures nothing contributes to the pass decision and sits in the kept log
beside real checker results. It is not a graded checker, so it closes no key — but it is an always-pass proof line in the
evidence of two tests that close three required keys.
Owner: **DV owner** · Closes when: the token is removed from both sequences and both gates, or emitted only after a real
executed comparison.

---

## Coverage map

| Feature | Scenarios | Status |
|---|---|---|
| `SMC-CG-ARCH-PARAMS` — architecture-level CG control parameters | 3/4 required | ⚠️ **not covered** — `.S3` REAL-GAP |
| `DMA-CG-CTRL` — DMA activity-based clock gating | 4/4 required · 6 in inventory | covered (`smc_dma_cg_activity_test`); `.S5`,`.S6` deferred to P2 |
| `CG-DFT-TEST-BYPASS` — DFT test-mode bypass | 1/2 required | ⚠️ **not covered** — `.S2` REAL-GAP |
| `ZEROER-AXICLK-CG` — Zeroer AXI-clock gating | 4/4 required · 5 in inventory | covered (`smc_zeroer_axiclk_cg_test`); `.S5` deferred to P2 |
| `ZEROER-REGCLK-CG` — Zeroer register-clock gating | 4/4 required · 5 in inventory | covered (`smc_zeroer_regclk_cg_test`); `.S5` deferred to P2 |
| `INT-ZEROER-CG-INDEP` *(interaction)* | 1/1 required | covered (`smc_zeroer_cg_indep_test`) |

Scenario detail for the two features that are not fully covered:

| Scenario | Required class | Allocated to | Closed by allocated? | Status |
|---|---|---|---|---|
| `SMC-CG-ARCH-PARAMS.S1` hysteresis window | LIVE | SMC_CLK_MULTI_WINDOW_TEST | yes | COVERED (`CHK-HYST-WINDOW`, ±1 cyc at 8/31/63) |
| `SMC-CG-ARCH-PARAMS.S2` per-module activity detection | LIVE | SMC_CLK_RUNNING_TEST | yes | COVERED (`CHK-ACTIVE-RUNNING`) — see F14 |
| `SMC-CG-ARCH-PARAMS.S3` enable-threshold delay | LIVE | SMC_STATIC_CG_SANITY_TEST | **no** | **REAL-GAP** (F3) |
| `SMC-CG-ARCH-PARAMS.S4` per-module gating enable | LIVE | SMC_STATIC_CG_SANITY_TEST | yes | COVERED (`CHK-MODULE-GATING`) |
| `CG-DFT-TEST-BYPASS.S1` DMA gate bypassed | LIVE | SMC_CG_TEST_MODE_BYPASS_TEST | yes | COVERED (`CHK-DFT-BYPASS-DMA`, positive control present) |
| `CG-DFT-TEST-BYPASS.S2` Zeroer axi+reg bypassed | LIVE | SMC_CG_TEST_MODE_BYPASS_TEST | **no** | **REAL-GAP** (F2) |

**No closure statement is emitted.** Two required keys are real gaps, and the 13 required keys closed by tier-A checkers are
excluded from closure certification pending F4, so this milestone has neither 100% feature-mapped evidence closure nor the
independent evidence its own policy requires for the checkers that carry it.

**Denominator arithmetic** (§4.2 step 0, reconstructible): `inventory_keys 23` − `excluded_keys 4` = `milestone_required_keys 19`;
`covered_keys 17`. The four exclusions are the only keys that leave the denominator and each names an accepted plan row.

---

## Findings

### 🔴 Blocking

| # | Tag | What | Owner |
|---|---|---|---|
| F1 | `[BUILD-MODEL-IDENTITY]` | `prim_clkgater.sv:20` changed to `i_en \| i_te` in the working tree — the DFT bypass under test; grades cite a commit without it, `compile_inputs_sha256: null`, all cocotb sources untracked | design + DV owner |
| F2 | `[NEGATIVE-NEEDS-POSITIVE-CONTROL]` | `CG-DFT-TEST-BYPASS.S2`: no otherwise-gating precondition, no CSR readback, `tb_zeroer_cg_en` never checked | DV owner |
| F3 | `[CONTRACT-MATCH]` *(intent mode `O2`)* | `SMC-CG-ARCH-PARAMS.S3` proven by programming `CG_HYSTERESIS`, the field its intent says it is independent of; values a subset of `.S1`'s | Skill 1 owner |
| F4 | `[REPRESENTATIVE-EVIDENCE]` | 17 tier-A checkers have single-seed single-log evidence; prior report asserted `gate_satisfied: true` with all provenance `null` | DV owner |
| F5 | `[NO-ALWAYS-PASS-CHECKER]` | `CHK-TIMEOUT-PATHS` emits a constants-only proof token and gates two tests' PASS | DV owner |

### 🟠 Major

| # | Tag | What | Owner |
|---|---|---|---|
| F6 | `[EXACT-EXPECTATION]` | `CHK-DMA-GATE-OFF` (tier A) bound is `hyst+16` = 24 for a window of 8, at 16-cycle resolution, and the timing assert is skipped when `last_toggle == -1` | DV owner |
| F7 | `[CROSS-TESTCASE-CONSISTENCY]` | same re-gate measurement asserted ±1 cyc in two tests but +16 in the tier-A one; 3 of 4 activity checkers prove resume-from-gated, `CHK-DMA-WAKEUP-BACKEND` (card rev 2) proves only stays-enabled | DV owner |
| F8 | `[SHARED-INFRA-QUALITY]` | tier-A DMA sequence forks `count_gated_rising` without the shared X/Z guard or the ±1 mitigation, then loosens three checks to absorb the resulting undercount | DV owner |
| F9 | `[EVIDENCE-TOKEN-CONDITIONAL]` | token fields are constants or restatements of an already-asserted condition; `zero_toggles_idle` prints the window, not the measured `edges` | DV owner |
| F10 | `[IP-CHECKLIST-CONSISTENCY]` | `smc_static_cg_sanity_test` is both an active `clock.toml` smoke test and a member of `deferred.toml`'s excluded group | DV owner |
| F11 | `[EVIDENCE-FRESHNESS]` | artifact-level approvals predate their content: cards rev 3 approved 09:20 holds records approved 11:20/13:50; plan approved 09:20 derives from a feature_list approved 13:50; pin `confirmed_at` 12:00 postdates all of it | Skill 1 owner |
| F12 | `[FEATURE-INVENTORY-COMPLETE]` | pin boundary names `clk_periph` in scope; approved SF-003 answers only `clk_ref_i`/`clk_telemetry_i`; the independent reverse derivation named `clk_periph` too | Skill 1 + design owner |
| F13 | `[NO-DUMMY-DEAD-CODE]` | `coupled_s1`/`coupled_s2` in the tier-A interaction sequence are tautologically unreachable — dead code shaped like the decoupling proof | DV owner |
| F14 | `[NEGATIVE-NEEDS-POSITIVE-CONTROL]` | `module_idle_clock_gated` rests on `zaxi_edges == 0` with no same-handle positive control in that run (X/Z guard bounds the risk) | DV owner |
| F15 | `[QUALITY-OBLIGATION-GAP]` | no SMC-scoped authoritative evidence policy; the pinned policy's PASS and frontdoor sections are titled *SMU_SEP*, no gating tool designated; pinned policy path unreadable (identity established by content hash) | policy + pin owner |
| F16 | `[TRACEABILITY]` | none of the prior audit's 8 `grade_report_sha256` values matches any grade report on disk, by file hash or canonical content hash | DV owner |
| F17 | `[ALLOCATION-INTENT-DIFF]` | allocations all met and no double-credit, but `SMC_CLK_MULTI_WINDOW_TEST`'s `owns` disclaims DMA timing while measuring `tb_dma_gated_clk` at 8/31/63 — the substance of P2-deferred `DMA-CG-CTRL.S5`, whose remaining cell `dma_hysteresis_0` the source records as non-working | Skill 1 + design owner |

### 🟡 Minor

| # | Tag | What | Owner |
|---|---|---|---|
| F18 | `[NO-DUMMY-DEAD-CODE]` | unused `measure_regate_delay`; unasserted `start_writes`; hysteresis readback missing in 3 sequences; `max(0,…)` clamps hide early resume; 9 cards vs `max_cards_per_packet: 8` | DV owner |
| F19 | `[MILESTONE-DENOMINATOR]` | pin `boundary` prose says "This pin closes P0–P2 scenarios (milestone P2)" while its `milestone:` field — the normative one — says P1; reading the prose instead would score all four signed P2 deferrals as in-milestone (23 required, not 19) | pin owner |

### Verified clean (recorded because "checked and clean" is the information)

- **Evidence integrity.** All 8 kept logs exist and their sha256 matches the declaration exactly. All **27/27** evidence
  tokens appear verbatim at their declared line numbers; all 27 `implementation_path` refs resolve to the emitting call. Zero
  `ERROR`/`FATAL`/`Traceback`/UVM_ERROR records in any log; the only `FAIL` hit per log is inside `TESTS=1 PASS=1 FAIL=0`.
  All 19 `coverage_artifacts` hashes match. **No fabricated or misplaced evidence token was found.**
- **No cross-testcase conflict.** A claim matrix over `tb_dma_gated_clk`, `tb_zeroer_gated_axi_clk` and
  `tb_zeroer_gated_reg_clk` across all 8 tests contains no target with two disagreeing rows: gating-enabled + idle → gated,
  every other condition → toggling, consistently. `[CROSS-TESTCASE-CONFLICT]`: clean.
- **Force-free.** No `force`, `release`, `deposit` or `setimmediatevalue` anywhere in the slate; the only DUT writes are
  `dut.rst_cool_ni` and `dut.tb_test_en_i`, both declared `input wire logic` on `smc_uvm_top` and both real stimulus pins.
  All clock/busy observation is continuous-assign lifts read passively. `[NO-BACKDOOR-WRITE]`: clean.
- **Proof classes and cells.** Every scenario requires `LIVE` and every crediting checker is `LIVE`; no `DECODE`/
  `CONNECTIVITY` over-credit, and `INTEGRITY` (`CHK-NONVAC`) earns no scenario credit anywhere. All `achieved_cells` equal
  their `required_cells` for the 17 covered keys. `[PROOF-CLASS-HONESTY]`: clean.
- **Merged evidence.** `INT-ZEROER-CG-INDEP` is closed by a joint interaction line, and both participating features have
  independent single-feature proof in their own testcases — so the interaction keeps its credit and no feature is credited
  from the joint line alone. `[MERGED-EVIDENCE]`: clean.
- **Enrollment.** All 8 approved anchors appear in `clock.toml`, which `all.toml` includes. No `E3` orphan. (See F10 for the
  contradictory second listing.)
- **Card/grade matching.** Exactly one `current: true` card per anchor, each with its own approval; all 8 grade reports cite
  the correct current `record_sha256`, including the superseded-then-amended `SMC_DMA_CG_ACTIVITY_TEST` revision 2. No
  superseded approval was used and no unapproved candidate is current.
- **Timeouts fail closed.** Every bounded wait in the slate raises on expiry; no `except: pass`, no `skip`, no `xfail`.
- **Addresses.** All 30 register symbols resolve through generated PeakRDL headers with fail-loud parse errors; no
  hand-copied address literals. `[ADDRESS-FROM-AUTHORITATIVE-MAP]`: clean.
- **Exceptions.** `exceptions: []` in all 8 reports and no backdoor requiring one — so there is no expired or
  scope-exceeding exception. (F1 is the converse problem: an undeclared change that *should* have been recorded somewhere.)

---

## Residual ledger

| Key | Class | Counts against closure? | Authority | Closes at |
|---|---|---|---|---|
| `SMC-CG-ARCH-PARAMS.S3` | **REAL-GAP** | **yes** | `NONE` — claims no exemption | — |
| `CG-DFT-TEST-BYPASS.S2` | **REAL-GAP** | **yes** | `NONE` — claims no exemption | — |
| `DMA-CG-CTRL.S5` | MILESTONE-DEFERRED | no | PLAN-ROW, `OUT-OF-MILESTONE`, accepted by minshaoho 2026-08-05T09:20 | **P2** |
| `DMA-CG-CTRL.S6` | MILESTONE-DEFERRED | no | PLAN-ROW, `OUT-OF-MILESTONE`, accepted by minshaoho 2026-08-05T09:20 | **P2** |
| `ZEROER-AXICLK-CG.S5` | MILESTONE-DEFERRED | no | PLAN-ROW, `OUT-OF-MILESTONE`, accepted by minshaoho 2026-08-05T09:20 | **P2** |
| `ZEROER-REGCLK-CG.S5` | MILESTONE-DEFERRED | no | PLAN-ROW, `OUT-OF-MILESTONE`, accepted by minshaoho 2026-08-05T09:20 | **P2** |

All four deferrals were verified against the approved plan: `reason: OUT-OF-MILESTONE`, `downstream_class: out-of-scope`
(which maps to `MILESTONE-DEFERRED`, **not** to the closure-blocking `OUT-OF-SCOPE` class), each `accepted_by`-signed, each
naming P2. No separate waiver is needed or claimed. No `WAIVED`, `UNREACHABLE`, `BLOCKED` or `OUT-OF-SCOPE` residual exists
in this milestone. **Carry into P2:** F17 — `DMA-CG-CTRL.S5`'s remaining cell `dma_hysteresis_0` is the value the test source
records as non-working, so that row is not a pure breadth deferral.

---

## Questions routed to the designer

1. **`prim_clkgater`:** is `latched_en = i_en | i_te` the correct DFT bypass for shared common RTL, and is it approved for
   commit? At the committed revision `i_te` is unused, so `test_en_i` reaches no Zeroer gate — i.e. the DFT bypass the SPEC's
   `test_en_i` row describes was not implemented, and the DV flow's fix is currently the only implementation of it.
2. **Enable Threshold (SF-002):** is there an independent enable-threshold field, or is `CLOCK_GATE_CONTROL.CG_HYSTERESIS`
   the only programmable delay? The answer decides whether `SMC-CG-ARCH-PARAMS.S3` is a scenario or a duplicate.
3. **`CG_HYSTERESIS = 0`:** the test source records that `hyst=0` "never runs under `cg_enable`" and `hyst=1` "loses the
   frontend→backend handoff (DMA accepts `NEXT_ID` but `DONE` never advances)". Is that intended?
4. **`clk_periph`:** is the peripheral clock domain ever clock-gated? The pin puts it in scope; no approved artifact answers.

---

## Review limitations

- **Sampling.** Policy §7 floor is all tier-`A` checkers + 20% of the rest (min 5) = 22 of 27. This review mechanically
  re-verified **all 27** PROVEN checkers (token / declared line / log hash / coverage-artifact hash) and read the
  implementation of all 8 sequences, all 8 tests, both shared helpers and the base test.
- **No simulation was run.** This review is read-only and advisory; it did not re-execute any test, so F4 records the absence
  of independent reproduction rather than supplying it. No test, RTL, contract or tracker was modified.
- **Unsealed derivation.** The feature_list declares `sealed_derivation: false` / `anchor_seal_mechanism:
  ordered-single-context`, which per §4.5 is a reason to widen the reverse diff rather than a finding. The diff was widened
  to cell granularity accordingly (see appendix).
- **Policy gaps.** F15 records a judgment the pinned policy does not resolve: no SMC-scoped authoritative evidence policy
  and no designated gating tool for this milestone, which DV_QUALITY_POLICY.md §8 directs be reported rather than guessed. It
  is fed back to the policy owner rather than decided here.
- **Advisory only.** This report holds no signoff or tracker authority and makes no `Done` decision. The board entry
  `hw/sys/smc/dv/tb/audit_status_smc_clock_gating.md` currently reads "P1 Done" on the strength of the prior `PASS`; updating
  it is the owner's call, not this review's.

---
*Machinery appendix: full YAML coverage records, reverse-diff provenance, grade-report hashes and sampled-evidence detail —
for tooling and re-audit.*

## Machinery appendix

### Frozen input set (all hashes recomputed in this session)

| Artifact | Identity | Verified |
|---|---|---|
| Pin | `SMC_CLOCK_GATING_PIN.yaml`, `pin_revision: 1`, file `d6800e99…` | `milestone: P1` **equals** the plan's — gate confirmed |
| Feature list | `artifact_revision 2`, `content_sha256 a22b78b4…` | declared == recomputed |
| Testcase plan | `plan_revision 1`, `content_sha256 23856412…`, `status: approved` | declared == recomputed; `derived_from` → feature_list rev 2 / `a22b78b4…` ✓ |
| Cards | `artifact_revision 3`, `content_sha256 c097f008…` | declared == recomputed; 9 records, 8 `current: true`, one per anchor |
| Spec audit | `artifact_revision 1`, `content_sha256 8dbc9a1d…` | 6 findings, all `answered`/`waived`, **none open** |
| Grade reports | 8 files, file hashes listed in `grade_report_sha256` | all `mode: CHECKBOX`, all `EVIDENCE-CLOSED-AWAITING-SIGNOFF` |
| Quality policy | `51a3357d9c31a018d69451b055bc956c089af26e1051368e25ce396c84ac2a75` | pinned path unreadable; identity established by content hash against the reviewer's local copy |
| Pinned SPEC | 9 `.adoc` sources; combined `spec_sha256 f093bc4c…` | method: SHA-256 over canonical JSON of `[{path, file-sha256}]` sorted by path |

### Independence

Reviewer `brucehsu` / `dv_peer_audit-SMC_CLOCK_GATING-P1-5aa9c629a618-fresh-opus5-rereview` / anthropic·claude·opus-5, in a
fresh read-only context with no authoring, generation, self-audit or prior-discussion history for this IP. Distinct from
every `prior_participants` `run_id` and from `minshaoho`, who generated, implemented, Skill-2-audited and approved every
input artifact. Model separation is optional per policy §6 and is recorded, not enforced: the prior review and all Skill 2
grades ran on cursor·grok·4.5.

### Reverse inventory diff (Step 5 — delegated, not re-derived here)

Source: `SMC_CLOCK_GATING_REVERSE_FEATURE_INVENTORY.md`, `content_sha256 535b4a2d…` (declared == recomputed),
`reverse_inventory: true`, `pin_consulted: false`, `sealed_derivation: true`, generated anchor-blind by
`fresh-subagent-unattended` on cursor·claude·sonnet-5 — a different run and human from both feature-list generators, so
`separation_gate_satisfied` derives **true**.

Key-level diff: **CLEAN.** All 6 reverse features and 1 reverse interaction map onto the approved inventory (`CG-CTRL-PARAMS`
→ `SMC-CG-ARCH-PARAMS`; `DMA-CG` → `DMA-CG-CTRL`; `DMA-CG-TESTMODE` + `ZEROER-CG-TESTMODE` → `CG-DFT-TEST-BYPASS`;
`ZEROER-AXI-CG` → `ZEROER-AXICLK-CG`; `ZEROER-REG-CG` → `ZEROER-REGCLK-CG`; `INT-ZEROER-CG-INDEP` identical). The reverse
`DMA-CG.S4` (activity re-asserting before hysteresis expiry) maps to the P2-deferred `DMA-CG-CTRL.S6`; the approved inventory
is a superset at scenario level (it additionally carries `ZEROER-*.S5`). No reverse behaviour is absent from the approved
inventory, so the disposition is `CLEAN` and `inventory_delta.keys` is empty.

Cell-granularity diff (the widening required by the unsealed derivation): the reverse derivation asks for eight cells the
approved inventory does not require — `both-asserted`, `cg-disabled-with-activity`, `reset-asserted-busy`,
`reset-asserted-reg-active`, `disable_cg-1-busy`, `disable_cg-1-reg-activity`,
`test-mode-cg-would-have-been-enabled-anyway`, `activity-toggle-within-hysteresis-window`. Each is the non-discriminating
half of an OR term whose discriminating half the approved inventory already requires (e.g. proving the reset override while
*idle* is the case that isolates `~rst_ni`; proving it while *busy* is satisfied by the busy term alone), and the last maps
to deferred `DMA-CG-CTRL.S6`. They are therefore recorded as **advisory P2 candidates**, not as omitted requirements — which
is why this remains `CLEAN` rather than `UNRESOLVED`.

### Sampled-evidence detail

Re-verification covered 27/27 PROVEN checkers across 8 reports: log existence and sha256 (8/8 exact), token-at-declared-line
(27/27 exact, 0 wrong-line, 0 absent), `implementation_path` resolution (27/27), coverage-artifact hashes (19/19),
entry-PASS gates (8/8 `TESTS=1 PASS=1 FAIL=0 SKIP=0`, corroborated by `results.xml` with 0 `<failure>`/`<error>`), and
error-record scans (0 `ERROR`/`FATAL`/`Traceback`, 0 X/Z warnings; the only warnings are cocotb/pyuvm `DeprecationWarning`
boilerplate at 0 ns). Build identity: `verilator 5.050 2026-07-01`, `compile_target default`, `build_config default`,
`model_fingerprint 2c815fa08277` — identical across all 8 runs — with `compile_inputs_sha256: null` in all 8 (F1). Every
`coverage_artifacts` entry points at the run's own `.log`; no coverage database (`*.ucdb`/`*.vdb`/`*cov*`) exists in any cited
run directory, which is consistent with the feature_list declaring `coverage_artifact: null` for every required scenario.

**No false-PROVEN was found in the evidence layer** — every graded token is real and correctly located — so the escalation
path of §4.5 (full re-verify of a behaviour class, cap 20) was not triggered. The blocking findings are contract, precondition,
identity and independence defects, not fabricated evidence.
