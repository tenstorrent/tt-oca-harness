# SMC_CLOCK_GATING_P0 — Feature Semantics Review — P0 (candidate v1)

**Your task:** confirm each feature's intent matches the SPEC's meaning.

## Open questions — 3 (full detail in `SMC_CLOCK_GATING_P0_SPEC_REVIEW.md`)

| SF | Severity | Feature(s) | Question |
|---|---|---|---|
| SF-001 | Medium | SMC-CG-DMA, SMC-CG-ZEROER | do the DMA gated clock branch and the Zeroer axi_clk/reg_clk domains derive from `clk_smc_i`, and if so where is that binding documented? |
| SF-002 | High | SMC-CG-ENABLE-CTRL | which SMC register (and bit) is `cg_enable_i` wired from, and in which pinned doc should that mapping be stated? |
| SF-003 | High | SMC-CG-ENABLE-CTRL | which SMC register (and bit) is `disable_cg` wired from, and in which pinned doc should that mapping be stated? |

## Features — 3

| Approve | Feature | Intent | Spec | Scenarios |
|---|---|---|---|---|
| [x] | SMC-CG-DMA | the DMA frontend/request-manager/backend share one hysteresis-gated clock branch, gated by activity and by `cg_enable_i`, bypassed under DFT test mode | hw/sys/smc/doc/dma.adoc "Clock Gating Configuration" | 4 |
| [x] | SMC-CG-ZEROER | the Zeroer's AXI-clock and register-clock domains are each independently gated by their own activity signal, overridden free-running during reset or manufacturing test, and forced free-running by `disable_cg` | hw/sys/smc/doc/zeroer.adoc "Clock Gating" | 7 |
| [x] | SMC-CG-ENABLE-CTRL | firmware can reach the per-module clock-gating enable/disable control (DMA `cg_enable_i`, Zeroer `disable_cg`) that the clock-gating parameter table names generically as "Module Gating" | hw/sys/smc/doc/clk_rst.adoc "Clock and Reset-Based Power Management Integration" | 2 |

## Required interactions — 0

No interaction is required by the pinned docs within this boundary — DMA gating and Zeroer
gating are each self-contained bring-up behaviors with no SPEC-mandated joint observation
between them. `interactions: []` is authoritative, not an omission.

---
*Appendix: rendered from SMC_CLOCK_GATING_P0_SPEC_FEATURE_LIST.md @ candidate v1, pin rev 1,
spec rev 2ecc7b227e3926b253c65b5aac21239eec24ba5f (index.adoc). Derivation:
sealed_derivation=true, anchor_seal_mechanism=ordered-single-context,
fresh_context_route=fresh-subagent.*


---
**SIGN-OFF:** approved by `minshaoho` at `2026-08-05T15:52:00+08:00` (owner blanket approval).
