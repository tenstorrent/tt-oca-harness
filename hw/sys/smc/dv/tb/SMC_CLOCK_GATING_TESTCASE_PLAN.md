---
schema: dv-quality/v1
artifact: testcase-plan
artifact_revision: 1
content_sha256: 23856412227c96ff9b0ac8e23dc49901183c598bad8b9e5e3d9a49914686edcd
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
  note: 'AMENDMENT 2026-08-05: allocate new interaction INT-ZEROER-CG-INDEP to derived anchor smc_zeroer_cg_indep_test
    (plan_revision kept at 1 so unchanged approved records and their Skill-2 card hashes stay byte-stable).
    Parent feature_list now artifact_revision 2 / sha a22b78b4…. Scoped staleness: only the new testcase
    record is candidate; existing seven current records retain approval. Whole-plan [SCENARIO-ALLOCATION]
    re-run includes the new interaction key. Prior seal caveat retained.'
approved_by: minshaoho
approved_at: '2026-08-05T09:20:00+08:00'
plan_revision: 1
anchor_mode: augment
derived_from:
  feature_list_revision: 2
  feature_list_sha256: a22b78b40765efe57912f03934312f6b07a8582c351fa97c4ff0169d49bcca20
testcases:
- id: SMC_CLK_MULTI_WINDOW_TEST
  anchor: smc_clk_multi_window_test
  origin: given
  revision: 1
  supersedes_revision: null
  current: true
  status: approved
  record_sha256: 4c7bf76fa91c76e37339db6bfed59f067c146c72a7c9576d0b361ad71211d550
  approved_by: minshaoho
  approved_at: '2026-08-05T09:20:00+08:00'
  intent: 'Exercise the SMC-level generic programmable hysteresis-window claim across multiple gating
    windows/delays.

    '
  category: SMC clock-gating architecture (generic hysteresis)
  owns: 'SMC-level generic hysteresis-window timing claim only (clk_rst.adoc architecture table); not
    the DMA/Zeroer instance-specific timing owned by SMC_DMA_CG_ACTIVITY_TEST / SMC_ZEROER_AXICLK_CG_TEST
    / SMC_ZEROER_REGCLK_CG_TEST.

    '
  evidence_class: frontdoor-func
  closure_tier: B
  allocated:
    features:
    - SMC-CG-ARCH-PARAMS
    scenarios:
    - SMC-CG-ARCH-PARAMS.S1
  rationale: 'One producer/transport/consumer path: program the SMC-level per-module hysteresis field,
    drive a module through idle/active transitions across multiple windows, and observe the gated clock''s
    re-gating delay each time. One setup (hysteresis-window sweep).

    '
  size_justification: null
  reuse: pinned pre-existing anchor smc_clk_multi_window_test (name/reuse only; rewritten in place per
    augment mode)
  blockers: []
- id: SMC_CLK_RUNNING_TEST
  anchor: smc_clk_running_test
  origin: given
  revision: 1
  supersedes_revision: null
  current: true
  status: approved
  record_sha256: c91b2feb06e2c2e916109dce085fddfea9c7b7dbb65d87e33775ac08caba6e32
  approved_by: minshaoho
  approved_at: '2026-08-05T09:20:00+08:00'
  intent: 'Exercise the SMC-level generic per-module activity-detection claim that an active module''s
    clock keeps running.

    '
  category: SMC clock-gating architecture (generic activity detection)
  owns: SMC-level generic activity-detection-keeps-clock-running claim only.
  evidence_class: frontdoor-func
  closure_tier: B
  allocated:
    features:
    - SMC-CG-ARCH-PARAMS
    scenarios:
    - SMC-CG-ARCH-PARAMS.S2
  rationale: 'One producer/transport/consumer path: drive per-module activity and observe that the gated
    clock stays running while active. One setup (activity-held-clock-running check).

    '
  size_justification: null
  reuse: pinned pre-existing anchor smc_clk_running_test (name/reuse only; rewritten in place per augment
    mode)
  blockers: []
- id: SMC_STATIC_CG_SANITY_TEST
  anchor: smc_static_cg_sanity_test
  origin: given
  revision: 1
  supersedes_revision: null
  current: true
  status: approved
  record_sha256: bd3ff0d4488f120d7b6b9e08981e7d9570a8aaa947582e08951b40df609f6ff8
  approved_by: minshaoho
  approved_at: '2026-08-05T09:20:00+08:00'
  intent: 'Exercise the SMC-level generic static per-module gating enable/disable and its configurable
    enable-threshold delay.

    '
  category: SMC clock-gating architecture (generic static module gating)
  owns: SMC-level generic static module-gating enable/disable and enable-threshold delay claims only.
  evidence_class: frontdoor-func
  closure_tier: B
  allocated:
    features:
    - SMC-CG-ARCH-PARAMS
    scenarios:
    - SMC-CG-ARCH-PARAMS.S3
    - SMC-CG-ARCH-PARAMS.S4
  rationale: 'One producer/transport/consumer path: statically program a module''s gating enable/disable
    bit and its enable-threshold delay, and observe the gated clock''s static response. One setup (static
    configuration sanity, as distinct from the dynamic activity/hysteresis path covered by SMC_CLK_RUNNING_TEST
    / SMC_CLK_MULTI_WINDOW_TEST).

    '
  size_justification: null
  reuse: pinned pre-existing anchor smc_static_cg_sanity_test (name/reuse only; rewritten in place per
    augment mode)
  blockers: []
- id: SMC_DMA_CG_ACTIVITY_TEST
  anchor: smc_dma_cg_activity_test
  origin: derived
  revision: 1
  supersedes_revision: null
  current: true
  status: approved
  record_sha256: 392d53ae853d76a3fdfbc7f31a4099290100b25a06fbbd51f47fbd7a09a12469
  approved_by: minshaoho
  approved_at: '2026-08-05T09:20:00+08:00'
  intent: 'Prove the DMA controller''s single prim_clk_gater_hysteresis clock-gating decision: cg_enable_i,
    frontend wakeup, and backend busy all drive the one shared DMA gated clock.

    '
  category: DMA controller clock gating
  owns: 'The DMA controller''s own activity/enable clock-gating decision (frontend wakeup, backend busy,
    cg_enable_i) for the shared frontend+request-manager+backend clock domain, at P1 nominal function.

    '
  evidence_class: strict-e2e
  closure_tier: A
  allocated:
    features:
    - DMA-CG-CTRL
    scenarios:
    - DMA-CG-CTRL.S1
    - DMA-CG-CTRL.S2
    - DMA-CG-CTRL.S3
    - DMA-CG-CTRL.S4
  rationale: 'One producer/transport/consumer path: cg_enable_i and DMA activity signals drive the one
    prim_clk_gater_hysteresis instance gating the shared DMA clock domain. One setup (program cg_enable_i,
    drive frontend/backend activity, observe the shared gated clock).

    '
  size_justification: null
  reuse: null
  blockers: []
- id: SMC_ZEROER_AXICLK_CG_TEST
  anchor: smc_zeroer_axiclk_cg_test
  origin: derived
  revision: 1
  supersedes_revision: null
  current: true
  status: approved
  record_sha256: 5b2f4fe439dc4b09edbcad1945ca1abc3a2e3aa354c37a9000e8c4dd6f7b0ed3
  approved_by: minshaoho
  approved_at: '2026-08-05T09:20:00+08:00'
  intent: 'Prove the Memory Zeroer''s axi_clk gating decision end-to-end: axi_clk_enable = disable_cg
    | zeroer_busy_o | ~rst_ni.

    '
  category: Memory Zeroer clock gating (AXI clock)
  owns: 'The Memory Zeroer''s axi_clk gating decision (zeroer_busy_o, disable_cg, rst_ni) at P1 nominal
    function.

    '
  evidence_class: strict-e2e
  closure_tier: A
  allocated:
    features:
    - ZEROER-AXICLK-CG
    scenarios:
    - ZEROER-AXICLK-CG.S1
    - ZEROER-AXICLK-CG.S2
    - ZEROER-AXICLK-CG.S3
    - ZEROER-AXICLK-CG.S4
  rationale: 'One producer/transport/consumer path: zeroer_busy_o, disable_cg, and rst_ni drive the one
    prim_clkgater instance on the axi_clk domain. One setup (configure disable_cg, trigger a zeroing operation,
    exercise reset, observe axi_clk).

    '
  size_justification: null
  reuse: null
  blockers: []
- id: SMC_ZEROER_REGCLK_CG_TEST
  anchor: smc_zeroer_regclk_cg_test
  origin: derived
  revision: 1
  supersedes_revision: null
  current: true
  status: approved
  record_sha256: 69210848a8214010c3e43e43a032d700ee9d0061b6bb8512de2c73b83db44b42
  approved_by: minshaoho
  approved_at: '2026-08-05T09:20:00+08:00'
  intent: 'Prove the Memory Zeroer''s reg_clk gating decision end-to-end: reg_clk_enable = disable_cg
    | register_activity | ~rst_ni.

    '
  category: Memory Zeroer clock gating (register clock)
  owns: 'The Memory Zeroer''s reg_clk gating decision (register_activity, disable_cg, rst_ni) at P1 nominal
    function.

    '
  evidence_class: strict-e2e
  closure_tier: A
  allocated:
    features:
    - ZEROER-REGCLK-CG
    scenarios:
    - ZEROER-REGCLK-CG.S1
    - ZEROER-REGCLK-CG.S2
    - ZEROER-REGCLK-CG.S3
    - ZEROER-REGCLK-CG.S4
  rationale: 'One producer/transport/consumer path: register_activity, disable_cg, and rst_ni drive the
    one prim_clkgater instance on the reg_clk domain. One setup (configure disable_cg, drive register
    accesses, exercise reset, observe reg_clk).

    '
  size_justification: null
  reuse: null
  blockers: []
- id: SMC_ZEROER_CG_INDEP_TEST
  anchor: smc_zeroer_cg_indep_test
  origin: derived
  revision: 1
  supersedes_revision: null
  current: true
  status: approved
  record_sha256: af246ccaaec1265a4b108f970b90726c58b7506ea70db7292939077909a69da0
  approved_by: minshaoho
  approved_at: '2026-08-05T13:50:00+08:00'
  intent: 'Prove Memory Zeroer axi_clk and reg_clk gating decisions are independent: under asymmetric
    activity (disable_cg=0, out of reset), each domain follows its own formula without the other domain''s
    activity forcing it enabled.'
  category: Memory Zeroer clock gating (AXI/REG independence)
  owns: The cross-domain independence of Memory Zeroer axi_clk vs reg_clk gating (INT-ZEROER-CG-INDEP)
    only; not the single-domain formula cells owned by SMC_ZEROER_AXICLK_CG_TEST / SMC_ZEROER_REGCLK_CG_TEST.
  evidence_class: strict-e2e
  closure_tier: A
  allocated:
    features:
    - ZEROER-AXICLK-CG
    - ZEROER-REGCLK-CG
    scenarios:
    - INT-ZEROER-CG-INDEP
  rationale: 'One producer/transport/consumer path: simultaneous observation of both Zeroer prim_clkgater
    outputs under one setup (disable_cg=0, out of reset) while driving asymmetric activity on the two
    domains. Exists to close the SPEC-required cross, not to re-own single-domain formula cells.'
  size_justification: null
  reuse: null
  blockers: []
- id: SMC_CG_TEST_MODE_BYPASS_TEST
  anchor: smc_cg_test_mode_bypass_test
  origin: derived
  revision: 1
  supersedes_revision: null
  current: true
  status: approved
  record_sha256: 3168d8b18d1afd7b31f6d5ae4780534e509da9dd543115098f4847f9df5355a0
  approved_by: minshaoho
  approved_at: '2026-08-05T09:20:00+08:00'
  intent: 'Prove that test_en_i bypasses the DMA and Memory Zeroer clock-gating cells, forcing their gated
    clocks continuously enabled for manufacturing test.

    '
  category: DFT test-mode clock-gating bypass
  owns: The test_en_i DFT bypass of the DMA and Zeroer clock gaters only.
  evidence_class: strict-e2e
  closure_tier: B
  allocated:
    features:
    - CG-DFT-TEST-BYPASS
    scenarios:
    - CG-DFT-TEST-BYPASS.S1
    - CG-DFT-TEST-BYPASS.S2
  rationale: 'One producer/transport/consumer path: test_en_i drives every instantiated clock-gater''s
    test port. One setup (assert test_en_i under conditions that would otherwise gate the DMA and Zeroer
    clocks off, observe all stay enabled).

    '
  size_justification: null
  reuse: null
  blockers: []
unallocated:
- key: DMA-CG-CTRL.S5
  reason: OUT-OF-MILESTONE
  detail: 'Full-range (0/mid/63-cycle) randomized hysteresis-boundary sweep is feature/error breadth,
    deferred to milestone P2; this run''s milestone is P1 (nominal function).

    '
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T09:20:00+08:00'
- key: DMA-CG-CTRL.S6
  reason: OUT-OF-MILESTONE
  detail: 'The contested activity-during-hysteresis-countdown race is feature/error breadth, deferred
    to milestone P2; this run''s milestone is P1 (nominal function).

    '
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T09:20:00+08:00'
- key: ZEROER-AXICLK-CG.S5
  reason: OUT-OF-MILESTONE
  detail: 'The contested back-to-back-operation/busy-deassert race on axi_clk is feature/error breadth,
    deferred to milestone P2; this run''s milestone is P1 (nominal function).

    '
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T09:20:00+08:00'
- key: ZEROER-REGCLK-CG.S5
  reason: OUT-OF-MILESTONE
  detail: 'The contested pending-register-access-during-gate-transition race on reg_clk is feature/error
    breadth, deferred to milestone P2; this run''s milestone is P1 (nominal function).

    '
  downstream_class: out-of-scope
  accepted_by: minshaoho
  accepted_at: '2026-08-05T09:20:00+08:00'
---

# SMC_CLOCK_GATING — Testcase Plan (mixed — amendment candidate for INT-ZEROER-CG-INDEP, plan_revision 1, augment mode)


**Amendment 2026-08-05 (FIND-001):** added `SMC_ZEROER_CG_INDEP_TEST` / `smc_zeroer_cg_indep_test` allocating `INT-ZEROER-CG-INDEP`. Existing seven records unchanged and still approved; plan artifact status is `approved` after owner approval of SMC_ZEROER_CG_INDEP_TEST @ 2026-08-05T13:50:00+08:00.

**Milestone note:** the pin's `milestone:` field is `P1` (confirmed); this plan closes only
`LIVE` nominal-function scenarios at P1 and defers the four full-range/contested-race scenarios
below to `P2` as explicit `OUT-OF-MILESTONE` rows, per DV_SKILL1_SPEC.md §4.2 `[MILESTONE-SCOPE]`.
The pin's `boundary:` free text separately says "This pin closes P0–P2 scenarios (milestone P2)" —
this is the pin inconsistency reported to the parent; this plan follows the `milestone:` field
value (`P1`), not the boundary prose, because §3 is explicit that the field is the normative
scope input.

## Testcase set (8: 3 pinned given, 5 derived — 1 amendment addition)

### Newly proposed (origin: derived) — 5, listed first per augment-mode convention

| ID | Proposed anchor | Exists to prove | OWNS | Scenarios | Tier |
|---|---|---|---|---|---|
| SMC_DMA_CG_ACTIVITY_TEST | smc_dma_cg_activity_test | DMA activity/enable gates the shared DMA clock | DMA CG decision | 4 | A |
| SMC_ZEROER_AXICLK_CG_TEST | smc_zeroer_axiclk_cg_test | Zeroer axi_clk gating formula | Zeroer axi_clk CG | 4 | A |
| SMC_ZEROER_REGCLK_CG_TEST | smc_zeroer_regclk_cg_test | Zeroer reg_clk gating formula | Zeroer reg_clk CG | 4 | A |
| SMC_ZEROER_CG_INDEP_TEST *(amend)* | smc_zeroer_cg_indep_test | Zeroer AXI/REG CG independence | INT-ZEROER-CG-INDEP only | 1 | A |
| SMC_CG_TEST_MODE_BYPASS_TEST | smc_cg_test_mode_bypass_test | test_en_i bypasses DMA/Zeroer gaters | DFT bypass only | 2 | B |

### Pinned anchors, re-scoped (origin: given) — 3

| ID | Anchor | Exists to prove | OWNS | Scenarios | Tier |
|---|---|---|---|---|---|
| SMC_CLK_MULTI_WINDOW_TEST | smc_clk_multi_window_test | SMC-level generic hysteresis-window timing | generic hysteresis window | 1 | B |
| SMC_CLK_RUNNING_TEST | smc_clk_running_test | SMC-level generic activity keeps clock running | generic activity detection | 1 | B |
| SMC_STATIC_CG_SANITY_TEST | smc_static_cg_sanity_test | SMC-level generic static module-gating/threshold | generic static gating | 2 | B |

## Pinned anchors NOT represented in this plan (2) — reported, not silently dropped

Two of the pin's five pinned anchors could not be given a testcase record in this plan:

- **`smc_pll_cgm_awm_config_test`** — targets PLL CGM/AWM configuration, which the pin's own
  `boundary` text places explicitly **out of scope** ("PLL frequency synthesis / DVFS / CGM-AWM
  programming beyond what clk_rst names as clock-gating control"), and clk_rst.adoc's only PLL
  mention is as the reference-clock source for PLL control/frequency synthesis — never as
  clock-gating control. This is consistent with the pin's own `owns_notes` conditional ("PLL
  CGM/AWM anchors remain only if the frozen feature_list still places them inside boundary") —
  it does not.
- **`smc_i2c_cg_sanity_test`** — targets I2C peripheral clock gating, which is nominally inside
  the pin's IN-boundary by name ("module/per-IP clock-gate enable... controls"), but no pinned
  SPEC source states any I2C-specific clock-gating behavior (see **SF-001**, open, High). No
  feature/scenario exists in the frozen feature_list for this anchor to close; per the Direction
  Rule (§6.3), this plan does not invent one to justify the anchor's existence. This is a spec
  gap, not a testcase-allocation gap — it does not appear as an `unallocated` scenario row because
  no scenario for it exists to be allocated or deferred.

## Scenarios deferred to P2 (4) — you must accept each

| Scenario | Reason | Evidence | Counts as |
|---|---|---|---|
| DMA-CG-CTRL.S5 | OUT-OF-MILESTONE | full-range hysteresis sweep deferred to P2 | out-of-scope for P1 |
| DMA-CG-CTRL.S6 | OUT-OF-MILESTONE | contested activity/hysteresis race deferred to P2 | out-of-scope for P1 |
| ZEROER-AXICLK-CG.S5 | OUT-OF-MILESTONE | contested back-to-back race deferred to P2 | out-of-scope for P1 |
| ZEROER-REGCLK-CG.S5 | OUT-OF-MILESTONE | contested pending-access race deferred to P2 | out-of-scope for P1 |

**Every scenario is accounted for:** 18 allocated + 4 unallocated = 22, the complete
`SMC_CLOCK_GATING_SPEC_FEATURE_LIST.md` scenario-key set. No key is allocated twice.

---
*Appendix: rendered from `SMC_CLOCK_GATING_TESTCASE_PLAN.md` @ candidate plan revision 1, derived
from feature_list revision 1 (sha 97216e3d227e4a7a7f7caa6e62bd59d7c24881779fd2b0c7f20eecd5e7c22579),
pin revision 1, spec source revision 2ecc7b227e3926b253c65b5aac21239eec24ba5f.*
