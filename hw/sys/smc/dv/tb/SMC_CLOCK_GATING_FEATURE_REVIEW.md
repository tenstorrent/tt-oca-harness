# SMC_CLOCK_GATING — Feature Semantics Review (DIFF-ONLY amendment, artifact_revision 2)

**⚠ Independence caveat (read first):** this inventory's `sealed_derivation` is **false**
(retained from the original generation). This amendment does not re-seal or re-derive the
feature set; it only inserts the SPEC-required interaction omitted by FIND-001.

**Your task (this amendment):** approve the **new** interaction below. The five existing
features are unchanged (keys and per-feature record hashes stable) — prior feature-semantics
approval is not re-opened.

## DELTA — new required interaction (approve)

| Approve | Interaction | Features | Intent | Spec |
|---|---|---|---|---|
| [x] approved by minshaoho @ 2026-08-05T13:50:00+08:00 | INT-ZEROER-CG-INDEP | ZEROER-AXICLK-CG × ZEROER-REGCLK-CG | Register Clock independent of AXI activity — prove decoupling: axi-active+reg-idle → axi enabled / reg gated; reg-active+axi-idle → reg enabled / axi gated | `hw/sys/smc/doc/zeroer.adoc` §Clock Domains + §Clock Gating |

Coverage cells (authoritative on the interaction record): `axi-active-reg-idle-decoupled`,
`reg-active-axi-idle-decoupled`.

## Unchanged features — prior approval retained (not re-opened)

| Feature | Intent | Spec | Scenarios |
|---|---|---|---|
| SMC-CG-ARCH-PARAMS | firmware/CSR-programmable per-module hysteresis, activity detection, enable-threshold delay, and module enable/disable hold each block's gated clock stable while idle | `hw/sys/smc/doc/clk_rst.adoc` | 4 |
| DMA-CG-CTRL | a single hysteresis clock gater gates the shared DMA clock off when frontend+backend are both idle, held enabled by activity or software disable | `hw/sys/smc/doc/dma.adoc` | 6 |
| CG-DFT-TEST-BYPASS | asserting the SMC-wide DFT/scan test-enable forces every instantiated clock-gating cell's output continuously enabled | `hw/sys/smc/doc/port_table.adoc` | 2 |
| ZEROER-AXICLK-CG | axi_clk gated off when idle, held enabled by busy/disable_cg/reset per `axi_clk_enable = disable_cg \| zeroer_busy_o \| ~rst_ni` | `hw/sys/smc/doc/zeroer.adoc` | 5 |
| ZEROER-REGCLK-CG | reg_clk gated off when idle, held enabled by register activity/disable_cg/reset per `reg_clk_enable = disable_cg \| register_activity \| ~rst_ni` | `hw/sys/smc/doc/zeroer.adoc` | 5 |

## Required interactions — 1 (was 0)

See DELTA above. Prior empty `interactions: []` is superseded by this amendment.

## Open questions (unchanged; full text in `SMC_CLOCK_GATING_SPEC_REVIEW.md`)

| ID | Severity | Feature(s) affected | Question (one line) |
|---|---|---|---|
| SF-001 | High | SMC-CG-ARCH-PARAMS | which peripherals (if any) actually implement per-module clock gating beyond DMA/Zeroer? |
| SF-002 | Medium | SMC-CG-ARCH-PARAMS | are "Hysteresis Control" and "Enable Threshold" the same field or two independent fields? |
| SF-003 | High | *(no feature — nothing to name)* | is clk_ref_i or clk_telemetry_i ever clock-gated? |
| SF-004 | High | ZEROER-REGCLK-CG | what exact condition asserts `register_activity`? *(answered: any AXI4-Lite access — used by INT cells)* |
| SF-005 | Medium | DMA-CG-CTRL | does the DMA clock gater force-enable during reset like the Zeroer's gaters do? |
| SF-006 | Low | CG-DFT-TEST-BYPASS | which other modules besides DMA/Zeroer have a test_en_i-bypassable gater? |

---
*Appendix: rendered from `SMC_CLOCK_GATING_SPEC_FEATURE_LIST.md` @ candidate amendment
artifact_revision 2 (sha a22b78b40765efe57912f03934312f6b07a8582c351fa97c4ff0169d49bcca20),
interaction INT-ZEROER-CG-INDEP record_sha256
30602cffd560a5de3757e27775af4e0c902e995d1e46a4c0b58cb2f4b32afd94,
pin revision 1, run_id
dv_vplan_gen-SMC_CLOCK_GATING-P1-20260805T132000+0800-amend-int-zeroer-cg-indep,
model cursor/grok/4.5, fresh_context_route fresh-subagent.*
