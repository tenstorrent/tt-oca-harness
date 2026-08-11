---
schema: dv-quality/v1
artifact: testcase-plan
artifact_revision: 1
plan_revision: 1
content_sha256: 8ec020019d780b5f0e6c25e870c49b7d2c06d0a2e6a0074dd1e0dd678869ddd8
ip: SMC_CLOCK_GATING_P2
milestone: P2
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
  run_id: dv_vplan_gen-SMC_CLOCK_GATING_P2-step3-2026-08-05T15:40:00+08:00
  model:
    provider: cursor
    family: claude
    version: sonnet-5
derivation_provenance:
  sealed_derivation: true
  anchor_seal_mechanism: fresh-subagent
  fresh_context_route: fresh-subagent
  feature_list_frozen_at: '2026-08-05T15:09:00+08:00'
approved_by: minshaoho
approved_at: '2026-08-05T15:52:00+08:00'
anchor_mode: augment
derived_from:
  feature_list_revision: 1
  feature_list_sha256: 98edfcafc4474d142fa0a6ad9ef0f619826ceeedaf5eea953d0b7399bd56df9b
testcases:
- id: SMC_CG_P2_001
  anchor: smc_dma_cg_activity_test
  origin: given
  revision: 1
  supersedes_revision: null
  current: true
  status: approved
  record_sha256: 98e628cd4183ce05c02517f1828a9ed5ee18b3a0849be5c14b4c2d8a71dbd316
  approved_by: minshaoho
  approved_at: '2026-08-05T15:52:00+08:00'
  intent: Prove the DMA clock-gating hysteresis controller resolves correctly across its full 0-63 cycle
    window and when activity re-asserts mid-countdown.
  category: DMA clock-gating hysteresis breadth (P2)
  owns: prim_clk_gater_hysteresis full-range 0-63 cycle sweep and the activity-during-hysteresis race
    for the DMA frontend/request-manager/backend clock only; excludes nominal single-point hysteresis
    assert/deassert already closed under the prior milestone, and excludes the axi_cg_snoop/fabric-capacity
    area (blocked entirely by SF-001 -- no feature exists to own).
  evidence_class: frontdoor-func
  closure_tier: A
  allocated:
    features:
    - SMC-CG-DMA-HYST
    scenarios:
    - SMC-CG-DMA-HYST.S1
    - SMC-CG-DMA-HYST.S2
  rationale: Both scenarios share one producer (the combined DMA frontend-wakeup/backend-busy activity
    signal), one transport (the single prim_clk_gater_hysteresis instance and its 6-bit counter), and
    one consumer (the gated DMA frontend/request-manager/backend clock) -- one setup extending the existing
    DMA activity test's stimulus/observation.
  size_justification: null
  reuse: smc_dma_cg_activity_test (extend with a swept-gap stimulus loop and a mid-countdown reactivation
    case per owns_notes)
  blockers: []
- id: SMC_CG_P2_002
  anchor: smc_zeroer_axiclk_cg_test
  origin: given
  revision: 1
  supersedes_revision: null
  current: true
  status: approved
  record_sha256: 53791893d0c2043a2cb1d773b4736eb35027ab47038d3b039c5053a239393681
  approved_by: minshaoho
  approved_at: '2026-08-05T15:52:00+08:00'
  intent: Prove the Zeroer axi_clk gate does not spuriously close, and the follow-on operation starts
    and completes correctly, when a new trigger arrives back-to-back with the prior operation's busy-to-idle
    transition.
  category: Zeroer axi_clk clock-gating breadth (P2)
  owns: axi_clk_enable = disable_cg | zeroer_busy_o | ~rst_ni gate behavior across the busy-to-idle back-to-back
    trigger race only; excludes reg_clk gating (owned by SMC_CG_P2_003) and excludes nominal single-operation
    axi_clk gate/ungate already closed under the prior milestone.
  evidence_class: frontdoor-func
  closure_tier: A
  allocated:
    features:
    - SMC-CG-ZEROER-AXICLK
    scenarios:
    - SMC-CG-ZEROER-AXICLK.S1
  rationale: One producer (zeroer_busy_o falling edge racing a new trigger write), one transport (the
    axi_clk prim_clkgater), one consumer (the zeroer AXI4 master interface) -- one setup extending the
    existing axi_clk CG test's trigger timing.
  size_justification: null
  reuse: smc_zeroer_axiclk_cg_test (extend with a swept trigger-vs-busy-deassert timing loop per owns_notes)
  blockers:
  - SF-005
- id: SMC_CG_P2_003
  anchor: smc_zeroer_regclk_cg_test
  origin: given
  revision: 1
  supersedes_revision: null
  current: true
  status: approved
  record_sha256: 49c886a759cc50a15a1dfbc1bc3e0e51ad3cfa62eb333bbc7b397b689df7f484
  approved_by: minshaoho
  approved_at: '2026-08-05T15:52:00+08:00'
  intent: Prove a register access arriving while reg_clk is gated (no recent register_activity) ungates
    the clock and completes within a bounded time rather than being dropped, corrupted, or hung.
  category: Zeroer reg_clk clock-gating breadth (P2)
  owns: reg_clk_enable = disable_cg | register_activity | ~rst_ni gate behavior across the pending-access-while-gated
    race only; excludes axi_clk gating (owned by SMC_CG_P2_002) and excludes nominal single-access reg_clk
    gate/ungate already closed under the prior milestone.
  evidence_class: frontdoor-func
  closure_tier: A
  allocated:
    features:
    - SMC-CG-ZEROER-REGCLK
    scenarios:
    - SMC-CG-ZEROER-REGCLK.S1
  rationale: One producer (a register access arriving while reg_clk is currently gated), one transport
    (the reg_clk prim_clkgater), one consumer (the zeroer register interface) -- one setup extending the
    existing reg_clk CG test's access timing.
  size_justification: null
  reuse: smc_zeroer_regclk_cg_test (extend with a gated-then-access timing sweep per owns_notes)
  blockers:
  - SF-004
unallocated: []
---

## Testcase set (candidate, augment mode)

Three testcases are proposed, all `origin: given` -- every scenario the frozen feature_list
admits within this pin's boundary is closed by **extending** one of the three pinned anchors
`owns_notes` already named as the preferred extension target. No brand-new (`origin: derived`)
testcase is proposed this round: the boundary's in-scope surface, once anchor-blind-derived, was
narrow enough (three features, four scenarios total, one area blocked entirely by SF-001) that
the pinned extension targets can genuinely reach every scenario at LIVE proof class without a new
setup/producer/transport path.

| ID | Anchor | Origin | Owns | Scenarios | Tier |
|---|---|---|---|---|---|
| SMC_CG_P2_001 | `smc_dma_cg_activity_test` | given (extend) | DMA hysteresis full-range sweep + reassertion race | 2 | A |
| SMC_CG_P2_002 | `smc_zeroer_axiclk_cg_test` | given (extend) | Zeroer axi_clk gate vs back-to-back trigger race | 1 | A |
| SMC_CG_P2_003 | `smc_zeroer_regclk_cg_test` | given (extend) | Zeroer reg_clk gate vs pending-access race | 1 | A |

## Scenario allocation `[SCENARIO-ALLOCATION]`

The frozen feature_list contains exactly 4 scenario keys and 0 interaction keys within this
boundary. All 4 are allocated above; `unallocated` is **empty**.

**Naming this out loud, per the workflow's own instruction:** an empty `unallocated` list is a
claim worth a second look, because it usually means the inventory was trimmed to the tests. Here
it is not a trim -- the feature_list was derived anchor-blind by a sealed subagent that could not
see these anchor names, and it independently arrived at exactly the three named-race areas the
pin's boundary describes, one of which (`axi_cg_snoop`/fabric-capacity) turned out to admit **no
feature at all** (raised as `SF-001`, not silently dropped). The apparent full allocation is a
consequence of this pin's boundary being narrowly and explicitly scoped to three named P1-deferred
races rather than the whole SMC clock-gating surface -- a broader boundary would very likely
produce real `unallocated` rows. The reviewer should independently judge whether the boundary
itself was scoped correctly (that is a Skill 1 pin-confirmation decision already made by the
owner, not something this plan can re-open) rather than trusting the empty list at face value.

## Pinned anchor not allocated in this plan

`smc_clk_multi_window_test` is a pinned `anchor_mode: augment` anchor (via the confirmed pin) but
owns **no scenario in this P2-boundary feature_list**. Nothing in the 4 allocated scenarios
requires joint multi-window observation across the DMA and Zeroer clock domains (the frozen
feature_list's `interactions` array is empty -- no SPEC-required cross exists within this
boundary), so there is no scenario left for it to close here. This is surfaced as an explicit
decision for the DV owner in `SMC_CLOCK_GATING_P2_TESTCASE_REVIEW.md`, not silently omitted.

## Spec findings blocking exact allocation

`SMC_CG_P2_002` and `SMC_CG_P2_003` carry `blockers: [SF-005]` / `blockers: [SF-004]`
respectively: both testcases can be allocated their scenario now (the contested race itself is
locatable and directed stimulus can be built), but the **open** Critical spec finding means the
exact pass/fail expectation for the race's outcome (what "correct" means when a trigger/access
races the gate) cannot yet be written into a checker `PROOF` without guessing. `SMC_CG_P2_001`
is allocated without a blocker despite `SF-002`/`SF-003` (High, not Critical) affecting its
scenarios -- those findings narrow the exact hysteresis-value/wakeup-signal semantics but do not
prevent a bounded-completion checker from being written today; per policy §3 a High finding
narrows but does not block, unlike SF-004/SF-005's Critical severity.
