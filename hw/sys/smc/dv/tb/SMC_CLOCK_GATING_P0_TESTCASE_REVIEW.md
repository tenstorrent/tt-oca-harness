# SMC_CLOCK_GATING_P0 — Testcase Set Review — P0 (candidate plan v1, augment mode)

**Your two decisions:** (a) is this the right set of testcases, (b) is the OWNS split right.

## NEW testcases I am asking you to approve — 2

Agreeing to write a new test is a bigger commitment than agreeing to rewrite an existing card;
these two are additions to the pinned anchor pair.

| Approve | Proposed name | Exists to prove | OWNS | Scenarios | Tier |
|---|---|---|---|---|---|
| [x] | SMCCGP0_003 `smc_cg_dft_reset_bringup_test` | the top-level DFT test_en_i override bypasses gating on DMA and Zeroer, and the Zeroer reset-override term holds its clocks free-running during reset | DFT test_en_i bypass for DMA and Zeroer gating, and Zeroer reset-override free-running | 3 | B |
| [x] | SMCCGP0_004 `smc_cg_zeroer_activity_bringup_test` | one Zeroer zero operation ungates axi_clk (via busy) and reg_clk (via register access) from their own idle-gated baselines | Zeroer axi_clk and reg_clk activity-driven idle-gate/ungate behavior triggered by one zero operation | 3 | A |

## Existing testcases, re-scoped — 2

| Approve | Testcase | Exists to prove | OWNS | Scenarios | Tier |
|---|---|---|---|---|---|
| [x] | SMCCGP0_001 `smc_clk_running_test` | DMA activity ungates its clock while Zeroer stays idle-gated, concurrently, and both modules' CG-enable CSR bits are reachable/readback-consistent | DMA activity-driven ungate/idle-gate behavior, concurrent Zeroer idle-gate reinforcement, and DMA/Zeroer clock-gate-enable register reachability | 5 | A |
| [x] | SMCCGP0_002 `smc_static_cg_sanity_test` | with gating disabled per module, each module's gated clock free-runs regardless of activity | DMA gate-disabled free-running and Zeroer gate-disabled free-running (module-level enable/disable boundary) | 2 | A |

## Scenarios NO testcase claims — 0

Every one of the thirteen frozen scenarios is allocated; there is no unallocated row for you to
accept. This is not the inventory being trimmed to the tests — the feature list
(`SMC_CLOCK_GATING_P0_SPEC_FEATURE_LIST.md`) was frozen anchor-blind, before any anchor name was
read, and the pin's own P0 boundary is narrow enough (a single bring-up smoke per mechanism)
that it turned out to be fully closable once two new testcases were proposed.

## Carried spec-audit note (no action needed here)

`SMCCGP0_001` closes `SMC-CG-ENABLE-CTRL.S1`/`.S2` by reusing the existing anchor's frontdoor
writes, even though the pinned docs never state the exact register/bit driving `cg_enable_i` /
`disable_cg` (`SF-002`/`SF-003`, open on the spec owner's queue in
`SMC_CLOCK_GATING_P0_SPEC_REVIEW.md`). That documentation gap does not block this allocation.

---
*Appendix: rendered from SMC_CLOCK_GATING_P0_TESTCASE_PLAN.md @ candidate plan v1, pin rev 1,
anchor_mode augment.*


---
**SIGN-OFF:** approved by `minshaoho` at `2026-08-05T15:52:00+08:00` (owner blanket approval).
