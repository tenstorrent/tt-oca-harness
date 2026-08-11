# SMC_CLOCK_GATING_P0 — Card Mechanics Review — P0 (candidate v1)

**Your task:** confirm each card's steps and checkers actually exercise its OWNS, and that no
checker claims more than its steps produce. No card forces or deposits into RTL state.

## SMCCGP0_001 — `smc_clk_running_test`

**REVIEW-FOCUS:** first revision — reallocates the existing anchor under the P0
feature/scenario keys above; no test-code change implied, VPLAN bookkeeping only.

**OWNS:** DMA activity-driven ungate/idle-gate behavior, concurrent Zeroer idle-gate
reinforcement, and DMA/Zeroer clock-gate-enable register reachability

**Description:** producer = firmware/frontdoor `CLOCK_GATE_CONTROL` write plus a DMA descriptor
driving frontend wakeup/backend busy; transport = the CSR write path into `cg_enable_i`/
`disable_cg`, and the DMA activity-detection path into its hysteresis-gated clock branch;
consumer = DMA gated clock branch and Zeroer `axi_clk` domain.

| Step | Text | Derives from |
|---|---|---|
| S1 | frontdoor-write `CLOCK_GATE_CONTROL` (`DMA_CG_EN=1`, `ZEROER_CG_EN=1`), read back and compare | SMC-CG-ENABLE-CTRL.S1, SMC-CG-ENABLE-CTRL.S2 |
| S2 | sample `dma_gated_clk` / `zeroer_axi_gated_clk` before any DMA activity | SMC-CG-DMA.S2, SMC-CG-ZEROER.S3 |
| S3 | trigger one DMA descriptor; sample `dma_gated_clk` through the transfer, `zeroer_axi_gated_clk` concurrently | SMC-CG-DMA.S3 |
| S4 | bounded wait for DMA completion (TIMEOUT) | — |

| Checker | Proves / how it can fail |
|---|---|
| `CHK-CG-ENABLE-READBACK` | proves SMC-CG-ENABLE-CTRL.S1/.S2 reachable — fails on readback mismatch, X, or write not observed |
| `CHK-IDLE-GATED-BASELINE` | proves SMC-CG-DMA.S2, SMC-CG-ZEROER.S3 — fails on any toggle before activity, X, or wrong sample count |
| `CHK-DMA-ACTIVITY-UNGATE` | proves SMC-CG-DMA.S3 — fails on toggle gap during the activity window, toggle_count below expected, or X |
| `CHK-NONVAC` | ordering fence over S1–S3 — fails if the testcase passes with any term missing or out of order |
| `CHK-TIMEOUT-PATHS` | S4's bounded wait — fails on unbounded wait, ignored timeout, or expiry without testcase failure |

## SMCCGP0_002 — `smc_static_cg_sanity_test`

**REVIEW-FOCUS:** first revision — reallocates the existing anchor's module-gating scenarios
under the P0 keys; the anchor's hysteresis/enable-threshold measurement is out of this card's
OWNS and P0 boundary, and is not claimed here.

**OWNS:** DMA gate-disabled free-running and Zeroer gate-disabled free-running (module-level
enable/disable boundary)

**Description:** producer = the same `CLOCK_GATE_CONTROL` frontdoor write, clearing one
module's enable bit at a time; transport = the CSR write path into `cg_enable_i`/`disable_cg`;
consumer = DMA gated clock branch and Zeroer `axi_clk`/`reg_clk` domains.

| Step | Text | Derives from |
|---|---|---|
| S1 | frontdoor-write `CLOCK_GATE_CONTROL` (`DMA_CG_EN=0`, `ZEROER_CG_EN=1`), no DMA activity | — |
| S2 | sample `dma_gated_clk` with no DMA activity | SMC-CG-DMA.S4 |
| S3 | frontdoor-write `CLOCK_GATE_CONTROL` (`ZEROER_CG_EN=0`, `DMA_CG_EN=1`), no Zeroer activity | — |
| S4 | sample `zeroer_axi_gated_clk` / `zeroer_reg_gated_clk` with no Zeroer activity | SMC-CG-ZEROER.S7 |

| Checker | Proves / how it can fail |
|---|---|
| `CHK-DMA-GATE-DISABLED-FREE-RUN` | proves SMC-CG-DMA.S4 — fails on any gated interval, toggle_count below expected, or X |
| `CHK-ZEROER-GATE-DISABLED-FREE-RUN` | proves SMC-CG-ZEROER.S7 — fails on any gated interval on either clock, toggle_count below expected, or X |
| `CHK-NONVAC` | ordering fence over S1–S4 — fails if the testcase passes with any term missing or out of order |

## SMCCGP0_003 — `smc_cg_dft_reset_bringup_test` (NEW)

**REVIEW-FOCUS:** newly proposed testcase — no existing test exercises `test_en_i` bypass or the
Zeroer reset override; this card is new code, not a rewrite.

**OWNS:** DFT test_en_i bypass for DMA and Zeroer gating, and Zeroer reset-override
free-running

**Description:** producer = the top-level `test_en_i` DFT override input and `rst_ni` reset
input; transport = the override mux ahead of each per-module clock gater; consumer = DMA gated
clock branch and Zeroer `axi_clk`/`reg_clk` domains.

| Step | Text | Derives from |
|---|---|---|
| S1 | assert `test_en_i`; frontdoor-write `CLOCK_GATE_CONTROL` (`DMA_CG_EN=1`, `ZEROER_CG_EN=1`); no module activity | — |
| S2 | sample `dma_gated_clk`, `zeroer_axi_gated_clk`, `zeroer_reg_gated_clk` with `test_en_i` asserted | SMC-CG-DMA.S1, SMC-CG-ZEROER.S2 |
| S3 | deassert `test_en_i`; assert `rst_ni` (reset held); gating still enabled | — |
| S4 | sample `zeroer_axi_gated_clk` / `zeroer_reg_gated_clk` with `rst_ni` asserted | SMC-CG-ZEROER.S1 |

| Checker | Proves / how it can fail |
|---|---|
| `CHK-DFT-BYPASS-FREE-RUN` | proves SMC-CG-DMA.S1, SMC-CG-ZEROER.S2 — fails on any gated interval on any of the three clocks, toggle_count below expected, or X |
| `CHK-RESET-OVERRIDE-FREE-RUN` | proves SMC-CG-ZEROER.S1 — fails on any gated interval on either Zeroer clock, toggle_count below expected, or X |
| `CHK-NONVAC` | ordering fence over S1–S4 — fails if the testcase passes with any term missing or out of order |

## SMCCGP0_004 — `smc_cg_zeroer_activity_bringup_test` (NEW)

**REVIEW-FOCUS:** newly proposed testcase — no existing test exercises the Zeroer
register-clock domain or the axi_clk busy-triggered smoke; this card is new code, not a
rewrite.

**OWNS:** Zeroer axi_clk and reg_clk activity-driven idle-gate/ungate behavior triggered by
one zero operation

**Description:** producer = one firmware-triggered zero operation (`DEST_ADDR`/`SIZE`
programming, then a `CTRL_STATUS` start write) producing `register_activity` and
`zeroer_busy_o`; transport = two `prim_clkgater` instances, one per clock domain (`axi_clk`,
`reg_clk`); consumer = Zeroer AXI master datapath (`axi_clk`) and Zeroer register interface
(`reg_clk`).

| Step | Text | Derives from |
|---|---|---|
| S1 | frontdoor-write `CLOCK_GATE_CONTROL` (`ZEROER_CG_EN=1`); sample `zeroer_reg_gated_clk` with no register activity, `zeroer_busy_o=0` | SMC-CG-ZEROER.S5 |
| S2 | program `DEST_ADDR`/`SIZE`, write `CTRL_STATUS` to start one zero operation; sample `zeroer_reg_gated_clk` across the register writes | SMC-CG-ZEROER.S6 |
| S3 | sample `zeroer_axi_gated_clk` and `zeroer_busy_o` from operation start through completion | SMC-CG-ZEROER.S4 |
| S4 | bounded wait for zero-operation completion (TIMEOUT) | — |

| Checker | Proves / how it can fail |
|---|---|
| `CHK-REG-CLK-IDLE-GATED` | proves SMC-CG-ZEROER.S5 — fails on any toggle observed, X, or wrong sample count |
| `CHK-REG-ACCESS-UNGATES-REG-CLK` | proves SMC-CG-ZEROER.S6 — fails on no toggle during the register-write window, X, or toggle starting before the first write |
| `CHK-BUSY-UNGATES-AXI-CLK` | proves SMC-CG-ZEROER.S4 — fails on a toggle gap while `zeroer_busy_o=1`, toggle_count below expected, or X |
| `CHK-NONVAC` | ordering fence over S1–S3 — fails if the testcase passes with any term missing or out of order |
| `CHK-TIMEOUT-PATHS` | S4's bounded wait — fails on unbounded wait, ignored timeout, or expiry without testcase failure |

---
*Appendix: rendered from SMC_CLOCK_GATING_P0_VPLAN_DETAIL.md @ candidate v1, pin rev 1, parent
plan @ candidate plan v1. Guardrails on every card: no internal write/force/deposit; passive
hierarchical reads allowed (tb_* observation ports); frontdoor CSR access only.*


---
**SIGN-OFF:** approved by `minshaoho` at `2026-08-05T15:52:00+08:00` (owner blanket approval).
