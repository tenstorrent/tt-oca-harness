# SMC_CLOCK_GATING — Card Mechanics Review (DIFF-ONLY, artifact_revision 3) — 8 current cards

**REVIEW-FOCUS (amendment 2026-08-05 FIND-001):** new candidate card
`SMC_ZEROER_CG_INDEP_TEST` only — interaction checker `CHK-ZINDEP-DECOUPLE` for
`INT-ZEROER-CG-INDEP` plus `CHK-NONVAC`. Other seven cards unchanged; their prior card
mechanics approval is not re-opened. `[MERGED-EVIDENCE]`: single-feature checkers for
`ZEROER-AXICLK-CG` / `ZEROER-REGCLK-CG` remain on their dedicated cards.

**Your task:** approve the new card's steps/checkers. Confirm no force/deposit in stimulus
and that the interaction checker can fail independently of an aggregate PASS.

---

## DELTA — SMC_ZEROER_CG_INDEP_TEST — `smc_zeroer_cg_indep_test` (APPROVED by minshaoho @ 2026-08-05T13:50:00+08:00)

**OWNS:** The cross-domain independence of Memory Zeroer axi_clk vs reg_clk gating
(INT-ZEROER-CG-INDEP) only; not the single-domain formula cells owned by
SMC_ZEROER_AXICLK_CG_TEST / SMC_ZEROER_REGCLK_CG_TEST.

**Description:** producer = asymmetric Zeroer activity (zeroer_busy_o vs register_activity /
AXI4-Lite access) with disable_cg=0 and out of reset · transport = both prim_clkgater
instances observed jointly · consumer = gated axi_clk and gated reg_clk following their own
formulas without coupling.

**Steps:**
- S1 — axi-active + register-idle → axi_clk enabled / reg_clk gated *(from INT-ZEROER-CG-INDEP,
  cell axi-active-reg-idle-decoupled)*
- S2 — register-active + axi-idle → reg_clk enabled / axi_clk gated *(from INT-ZEROER-CG-INDEP,
  cell reg-active-axi-idle-decoupled)*

**Checkers:**
| Checker | Proves | How it can fail |
|---|---|---|
| CHK-ZINDEP-DECOUPLE | ZEROER-AXICLK-CG + ZEROER-REGCLK-CG jointly via INT-ZEROER-CG-INDEP | either asymmetric cell couples (both enabled or both gated), wrong domain gated/enabled, X/Z, missing sample |
| CHK-NONVAC | axi-active-reg-idle then reg-active-axi-idle observed in order before PASS | fence missing/out of order, or progress substituted for PASS |

**Guardrails:** no force/deposit; no aggregate PASS standing in for CHK-ZINDEP-DECOUPLE.

| Approve card |
|---|
| [x] approved by minshaoho @ 2026-08-05T13:50:00+08:00 |

---

## Unchanged cards — prior approval retained (IDs + checkers listed for lint)

### SMC_CLK_MULTI_WINDOW_TEST — `smc_clk_multi_window_test`
Checkers: CHK-HYST-WINDOW, CHK-NONVAC — unchanged.

### SMC_CLK_RUNNING_TEST — `smc_clk_running_test`
Checkers: CHK-ACTIVE-RUNNING, CHK-NONVAC — unchanged.

### SMC_STATIC_CG_SANITY_TEST — `smc_static_cg_sanity_test`
Checkers: CHK-MODULE-GATING, CHK-ENABLE-THRESHOLD, CHK-NONVAC — unchanged.

### SMC_DMA_CG_ACTIVITY_TEST — `smc_dma_cg_activity_test` (r2)
Checkers: CHK-DMA-GATE-OFF, CHK-DMA-WAKEUP-FRONTEND, CHK-DMA-WAKEUP-BACKEND,
CHK-DMA-GATING-DISABLED, CHK-NONVAC — unchanged since DMA S3 amend.

### SMC_ZEROER_AXICLK_CG_TEST — `smc_zeroer_axiclk_cg_test`
Checkers: CHK-ZAXI-GATE-OFF-IDLE, CHK-ZAXI-BUSY-ENABLE, CHK-ZAXI-DISABLE-CG,
CHK-ZAXI-RESET-OVERRIDE, CHK-NONVAC — unchanged (single-feature proofs for ZEROER-AXICLK-CG).

### SMC_ZEROER_REGCLK_CG_TEST — `smc_zeroer_regclk_cg_test`
Checkers: CHK-ZREG-GATE-OFF-IDLE, CHK-ZREG-ACTIVITY-ENABLE, CHK-ZREG-DISABLE-CG,
CHK-ZREG-RESET-OVERRIDE, CHK-NONVAC — unchanged (single-feature proofs for ZEROER-REGCLK-CG).

### SMC_CG_TEST_MODE_BYPASS_TEST — `smc_cg_test_mode_bypass_test`
Checkers: CHK-DFT-BYPASS-DMA, CHK-DFT-BYPASS-ZEROER, CHK-NONVAC — unchanged.

---
*Appendix: rendered from `SMC_CLOCK_GATING_VPLAN_DETAIL.md` @ mixed artifact_revision 3 (sha
a3e1694a7430ace1056c6c9f9d549bdf33124caf19b1998df91fb3dec7876ace),
new card SMC_ZEROER_CG_INDEP_TEST record_sha256
46ad998bc85c45be9ff0180d25267976c65047f0d983dec945caf0e9eebee833,
derived from plan_revision 1 / testcase_revision 1 / testcase_record_sha256
af246ccaaec1265a4b108f970b90726c58b7506ea70db7292939077909a69da0,
pin revision 1, run_id
dv_vplan_gen-SMC_CLOCK_GATING-P1-20260805T132000+0800-amend-int-zeroer-cg-indep,
model cursor/grok/4.5.*
