# SMC_CLOCK_GATING — Testcase Set Review (DIFF-ONLY amendment, plan_revision 1, augment mode)

**Your two decisions for this amendment:** (a) approve the **one NEW** derived testcase that
closes `INT-ZEROER-CG-INDEP`; (b) confirm its OWNS does not collide with the existing Zeroer
axi/reg cards. The other seven current records and the four already-accepted OUT-OF-MILESTONE
gaps are **not re-opened**.

**Milestone-scope note (unchanged):** pin `milestone: P1`; four contested/sweep scenarios remain
deferred to P2.

## NEW testcase I am asking you to approve — 1 addition

| Approve | Proposed name | Exists to prove | OWNS | Scenarios | Tier |
|---|---|---|---|---|---|
| [x] approved by minshaoho @ 2026-08-05T13:50:00+08:00 | SMC_ZEROER_CG_INDEP_TEST `smc_zeroer_cg_indep_test` | Zeroer axi_clk / reg_clk gating independence under asymmetric activity | cross-domain independence (INT-ZEROER-CG-INDEP) only; not single-domain formula cells owned by the axi/reg cards | 1 (`INT-ZEROER-CG-INDEP`) | A |

Why a new derived anchor (not an extend of axi/reg): the interaction's rationale is joint
observation of both prim_clkgaters under one asymmetric-activity setup — a different path from
either single-domain formula card. Extending either would merge unrelated paths into one
`rationale` and force superseding an already Skill-2-closed approved record.

## Existing testcases — prior approval retained (not re-opened)

### Previously approved derived (4)

| ID | Anchor | Exists to prove | OWNS | Scenarios | Tier |
|---|---|---|---|---|---|
| SMC_DMA_CG_ACTIVITY_TEST | smc_dma_cg_activity_test | DMA activity/enable gates the shared DMA clock | DMA CG decision | 4 | A |
| SMC_ZEROER_AXICLK_CG_TEST | smc_zeroer_axiclk_cg_test | Zeroer axi_clk gating formula | Zeroer axi_clk CG | 4 | A |
| SMC_ZEROER_REGCLK_CG_TEST | smc_zeroer_regclk_cg_test | Zeroer reg_clk gating formula | Zeroer reg_clk CG | 4 | A |
| SMC_CG_TEST_MODE_BYPASS_TEST | smc_cg_test_mode_bypass_test | test_en_i bypasses DMA/Zeroer gaters | DFT bypass only | 2 | B |

### Previously approved given / re-scoped (3)

| ID | Anchor | Exists to prove | OWNS | Scenarios | Tier |
|---|---|---|---|---|---|
| SMC_CLK_MULTI_WINDOW_TEST | smc_clk_multi_window_test | SMC-level generic hysteresis-window timing | generic hysteresis window | 1 | B |
| SMC_CLK_RUNNING_TEST | smc_clk_running_test | SMC-level generic activity keeps clock running | generic activity detection | 1 | B |
| SMC_STATIC_CG_SANITY_TEST | smc_static_cg_sanity_test | SMC-level generic static module-gating/threshold | generic static gating | 2 | B |

## Pinned anchors NOT represented (unchanged decision)

| Anchor | Why not allocated |
|---|---|
| `smc_pll_cgm_awm_config_test` | out of pin boundary (PLL CGM/AWM) |
| `smc_i2c_cg_sanity_test` | no SPEC-stated I2C CG behavior (SF-001) |

## Scenarios NO testcase claims — prior Accept retained (4)

| Accept | Scenario | Reason | Evidence | Counts as |
|---|---|---|---|---|
| Accept retained | DMA-CG-CTRL.S5 | OUT-OF-MILESTONE | full-range hysteresis-boundary sweep deferred to P2 | out-of-scope |
| Accept retained | DMA-CG-CTRL.S6 | OUT-OF-MILESTONE | contested activity-during-hysteresis race deferred to P2 | out-of-scope |
| Accept retained | ZEROER-AXICLK-CG.S5 | OUT-OF-MILESTONE | contested back-to-back race deferred to P2 | out-of-scope |
| Accept retained | ZEROER-REGCLK-CG.S5 | OUT-OF-MILESTONE | contested pending-access race deferred to P2 | out-of-scope |

`[SCENARIO-ALLOCATION]` re-run: every feature_list key is allocated or unallocated; the new
interaction is allocated to `SMC_ZEROER_CG_INDEP_TEST` only.

---
*Appendix: rendered from `SMC_CLOCK_GATING_TESTCASE_PLAN.md` @ mixed amendment
plan_revision 1 (sha e8247360028a6fa8ab304621bbff2e2df380d99e60900e4182ccc41b27eda250),
derived from feature_list artifact_revision 2 (sha
a22b78b40765efe57912f03934312f6b07a8582c351fa97c4ff0169d49bcca20),
new testcase record_sha256
af246ccaaec1265a4b108f970b90726c58b7506ea70db7292939077909a69da0,
pin revision 1, run_id
dv_vplan_gen-SMC_CLOCK_GATING-P1-20260805T132000+0800-amend-int-zeroer-cg-indep,
model cursor/grok/4.5.*
