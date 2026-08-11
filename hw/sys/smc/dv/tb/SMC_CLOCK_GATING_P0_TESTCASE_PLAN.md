---
schema: dv-quality/v1
artifact: testcase-plan
artifact_revision: 1
content_sha256: a0693deada1cf76a6dee1065ebffad8d390167af5fdfd3e86fcc2d552832c28e
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
plan_revision: 1
anchor_mode: augment
derived_from:
  feature_list_revision: 1
  feature_list_sha256: a5d5f6f1f55a8d4de7436f84c1729ec544c123251bf3338d4f49bff48df2fe90
testcases:
- id: SMCCGP0_001
  anchor: smc_clk_running_test
  origin: given
  revision: 1
  supersedes_revision: null
  current: true
  status: approved
  record_sha256: 0d033ae30973d5d21f601d2782614dbdaad3d7fa560ff3cd922534e826ce3ca9
  approved_by: minshaoho
  approved_at: '2026-08-05T15:52:00+08:00'
  intent: with clock gating enabled on both modules, DMA activity ungates its clock while Zeroer stays
    idle-gated, concurrently, and both modules' CSR gating-enable bits are shown reachable and readback-consistent
  category: DMA activity-driven gating + concurrent Zeroer idle-gate + CG-enable CSR reachability
  owns: DMA activity-driven ungate/idle-gate behavior, concurrent Zeroer idle-gate reinforcement, and
    DMA/Zeroer clock-gate-enable register reachability
  evidence_class: frontdoor-func
  closure_tier: A
  allocated:
    features:
    - SMC-CG-DMA
    - SMC-CG-ZEROER
    - SMC-CG-ENABLE-CTRL
    scenarios:
    - SMC-CG-DMA.S2
    - SMC-CG-DMA.S3
    - SMC-CG-ZEROER.S3
    - SMC-CG-ENABLE-CTRL.S1
    - SMC-CG-ENABLE-CTRL.S2
  rationale: one producer/transport/consumer path — a single CLOCK_GATE_CONTROL frontdoor write enables
    gating on both modules, then one DMA transfer exercises the shared activity-detection mechanism (idle-gate
    baseline, then activity ungates DMA while Zeroer stays gated) — and one setup (program the gate-enable
    CSR, program one DMA descriptor)
  size_justification: null
  reuse: 'smc_clk_running_test: existing Skill 1.5 implementation (dv/smc/dv/cocotb/tests/smc_clk_running_test.py);
    reallocate under the P0 feature/scenario keys above, no rewrite required'
  blockers: []
- id: SMCCGP0_002
  anchor: smc_static_cg_sanity_test
  origin: given
  revision: 1
  supersedes_revision: null
  current: true
  status: approved
  record_sha256: 1f5b76cb4385fb6652f42dce64b040c578e5722f373560b5a6143f493b19060c
  approved_by: minshaoho
  approved_at: '2026-08-05T15:52:00+08:00'
  intent: with clock gating disabled (per module) on DMA and, independently, on Zeroer, each module's
    gated clock stays free-running regardless of activity — the module-level enable/disable boundary named
    "Module Gating" in the clock-gating parameter table
  category: DMA and Zeroer gate-disabled free-running (module-level enable/disable boundary)
  owns: DMA gate-disabled free-running and Zeroer gate-disabled free-running (module-level enable/disable
    boundary)
  evidence_class: frontdoor-func
  closure_tier: A
  allocated:
    features:
    - SMC-CG-DMA
    - SMC-CG-ZEROER
    scenarios:
    - SMC-CG-DMA.S4
    - SMC-CG-ZEROER.S7
  rationale: one producer/transport/consumer path — the same CLOCK_GATE_CONTROL frontdoor write, this
    time clearing each module's enable bit in turn, showing the gated clock free-runs independent of that
    module's own activity — and one setup (program the gate-enable CSR with one module disabled at a time)
  size_justification: null
  reuse: 'smc_static_cg_sanity_test: existing Skill 1.5 implementation (dv/smc/dv/cocotb/tests/smc_static_cg_sanity_test.py);
    reallocate the module-gating scenarios under the P0 keys above (the same test also measures enable-threshold/hysteresis
    delay, which is OUT for P0 per the pin boundary and is not claimed by this record)'
  blockers: []
- id: SMCCGP0_003
  anchor: smc_cg_dft_reset_bringup_test
  origin: derived
  revision: 1
  supersedes_revision: null
  current: true
  status: approved
  record_sha256: 1c1053289e15ccfa6dd29d0e1711bcfd540f51ab071234d456097e9669600b2b
  approved_by: minshaoho
  approved_at: '2026-08-05T15:52:00+08:00'
  intent: the top-level DFT test-enable override bypasses clock gating on both DMA and Zeroer, and the
    Zeroer reset-override term holds its clocks free-running while reset is asserted
  category: DFT test_en_i bypass (DMA + Zeroer) and Zeroer reset override
  owns: DFT test_en_i bypass for DMA and Zeroer gating, and Zeroer reset-override free-running
  evidence_class: frontdoor-func
  closure_tier: B
  allocated:
    features:
    - SMC-CG-DMA
    - SMC-CG-ZEROER
    scenarios:
    - SMC-CG-DMA.S1
    - SMC-CG-ZEROER.S1
    - SMC-CG-ZEROER.S2
  rationale: one producer/transport/consumer path — the top-level test_en_i / rst_ni override muxes sit
    ahead of every per-module clock gater and force free-running independent of activity or the gate-enable
    CSR — and one setup (assert the override, sample each gated clock for continuous toggling, then release
    and confirm normal gating resumes)
  size_justification: null
  reuse: null
  blockers: []
- id: SMCCGP0_004
  anchor: smc_cg_zeroer_activity_bringup_test
  origin: derived
  revision: 1
  supersedes_revision: null
  current: true
  status: approved
  record_sha256: ad90a6ffe25462797477d28fbc5ef3d6bf3c5ab3b38f384757cd94872e3e23f7
  approved_by: minshaoho
  approved_at: '2026-08-05T15:52:00+08:00'
  intent: one Zeroer zero operation produces both a register access (which ungates reg_clk from its idle-gated
    baseline) and a busy interval (which ungates axi_clk from its idle-gated baseline), closing the Zeroer
    register-clock scenarios and the axi-clock activity smoke that SMCCGP0_001 does not exercise
  category: Zeroer axi_clk + reg_clk activity-driven gate/ungate, single zero operation
  owns: Zeroer axi_clk and reg_clk activity-driven idle-gate/ungate behavior triggered by one zero operation
  evidence_class: frontdoor-func
  closure_tier: A
  allocated:
    features:
    - SMC-CG-ZEROER
    scenarios:
    - SMC-CG-ZEROER.S4
    - SMC-CG-ZEROER.S5
    - SMC-CG-ZEROER.S6
  rationale: one producer/transport/consumer path — a single triggered zero operation (DEST_ADDR/SIZE/CTRL_STATUS
    register writes, then the busy interval until completion) drives both Zeroer clock domains through
    their own idle-to-active transition — and one setup (program and trigger one zero operation over a
    small region)
  size_justification: null
  reuse: null
  blockers: []
unallocated: []
---

# SMC_CLOCK_GATING_P0 — Testcase Plan (candidate plan v1, augment mode)

Four testcases close all thirteen frozen scenarios: two pinned anchors
reallocated under the new P0 keys (`SMCCGP0_001`/`smc_clk_running_test`,
`SMCCGP0_002`/`smc_static_cg_sanity_test`), and two newly proposed testcases
(`SMCCGP0_003`/`smc_cg_dft_reset_bringup_test`,
`SMCCGP0_004`/`smc_cg_zeroer_activity_bringup_test`) for the DFT/reset
override and the Zeroer register-clock-domain scenarios that neither pinned
anchor exercises.

`unallocated: []` — every scenario is allocated. This is not the inventory
being trimmed to the tests: the feature list was derived anchor-blind (see
`SMC_CLOCK_GATING_P0_SPEC_FEATURE_LIST.md` provenance) before these anchors
were read, and the pin's own boundary already scopes P0 tightly to a single
bring-up smoke per mechanism — a scope narrow enough that, once discovered,
turned out to be fully closable at this milestone with two new testcases.
`SF-002`/`SF-003` (unresolved CSR identity in the pinned docs) stay open on
the spec audit as documentation gaps for the spec owner, but do not block
`SMC-CG-ENABLE-CTRL.S1`/`.S2` here because `SMCCGP0_001` already closes them
through the register the existing anchor's own frontdoor writes target.
