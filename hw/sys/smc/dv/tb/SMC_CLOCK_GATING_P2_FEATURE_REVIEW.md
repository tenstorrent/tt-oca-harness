# SMC_CLOCK_GATING_P2 Feature Semantics Review — P2 (candidate v1)

**Your task:** confirm each feature's intent matches the SPEC's meaning. Mark approve / reject /
question. Rows: 3 of 40 (well within budget).

**Provenance note (read first):** this feature_list was derived by a fresh, anchor-sealed
subagent that saw only the 9 pinned SMC docs, the IP name/milestone, and the pin's `boundary`
text — it never saw the `anchors` list, `owns_notes`, or any existing test/plan file.
`sealed_derivation: true`, `anchor_seal_mechanism: fresh-subagent`, `fresh_context_route:
fresh-subagent`. No caveat is required on that basis.

## Needs your decision first (4 open questions affecting features)

| # | Question | Blocks |
|---|---|---|
| Q1 | **SF-001 (Critical)** — none of the 9 pinned docs names an `axi_cg_snoop` module, an "OutstandingTx" counter, or any mechanism tying `fabric.adoc`'s outstanding-transaction capacity numbers (MaxTrans=32, FABRIC_MAX_TRANS=32, MAX_INFLIGHT_IDS=4) to a clock-gating decision. The boundary names this as in-scope P2 breadth, but **no feature could be derived for it at all** — the producer/transport/consumer triad has no SPEC anchor to cite. Does this mechanism exist and is undocumented, or should this boundary item be withdrawn from P2? | No feature exists for this area (see the feature_list's "axi_cg_snoop / fabric outstanding-transaction capacity" subsection) |
| Q2 | **SF-002 (High)** — is the DMA hysteresis delay (`CG_HYSTERESIS_W`) a runtime-programmable register or a synthesis-time RTL parameter? `clk_rst.adoc` says "6-bit programmable"; `dma.adoc` frames it as a build-time parameter with no named register. | `SMC-CG-DMA-HYST.S1` |
| Q3 | **SF-003 (High)** — what exact signal/event is "frontend wakeup" (one of the two DMA activity-detection conditions), and for how long is it asserted? | `SMC-CG-DMA-HYST.S2` |
| Q4 | **SF-004 (Critical) / SF-005 (Critical)** — the Zeroer spec defines the `register_activity` (reg_clk) and busy-during-trigger (axi_clk) gate conditions but never states what generates/bounds `register_activity`, nor what happens to a trigger write arriving while `zeroer_busy_o` is still asserted. Both are needed to write an exact pass/fail contract for the two named Zeroer races. | `SMC-CG-ZEROER-REGCLK.S1`, `SMC-CG-ZEROER-AXICLK.S1` |

Full detail, severities, and exact spec citations for all 6 findings (including `SF-006`,
informational) are in `SMC_CLOCK_GATING_P2_SPEC_REVIEW.md`, routed separately to the spec owner.

## Features (Area: DMA hysteresis clock gating) — 1 feature, 2 scenarios

| Approve | Feature | Intent (one line) | Spec | Scenarios |
|---|---|---|---|---|
| [x] | `SMC-CG-DMA-HYST` | A single `prim_clk_gater_hysteresis` instance gates the DMA frontend/request-manager/backend clock on combined activity, holding it enabled for a 6-bit (0-63 cycle) hysteresis window that must resolve correctly across its full range and when activity re-asserts mid-countdown | `dma.adoc` §Performance Optimization and Power Management; §Configuration Parameters | 2 |

## Features (Area: Zeroer axi_clk / reg_clk clock gating) — 2 features, 2 scenarios

| Approve | Feature | Intent (one line) | Spec | Scenarios |
|---|---|---|---|---|
| [x] | `SMC-CG-ZEROER-AXICLK` | The zeroer's AXI master clock is gated on `zeroer_busy_o`; a follow-on trigger arriving back-to-back with the prior operation's busy-to-idle edge must not glitch the gate or drop the new request | `zeroer.adoc` §Clock Gating; §State Machine | 1 |
| [x] | `SMC-CG-ZEROER-REGCLK` | The zeroer's register-interface clock is gated on `register_activity`, independent of AXI activity; a register access arriving while gated must ungate the clock and complete within a bounded time | `zeroer.adoc` §Clock Gating; §Operation Control | 1 |

## Features (Area: axi_cg_snoop / fabric outstanding-transaction capacity) — 0 features

No feature is emitted for this boundary-named area — see Q1 / `SF-001` above. This is not an
omission: the area was walked against all 9 pinned docs and no producer/transport/consumer triad
could be constructed from the SPEC alone.

## Required interactions — 0

None. The SPEC states no cross-feature requirement within this boundary; `zeroer.adoc` §Clock
Domains explicitly states the register clock is "independent of AXI activity" (evidence against
an interaction, not for one).

## Not asking you to review

Checker mechanics, observation methods, card details → DV owner review
(`SMC_CLOCK_GATING_P2_CARD_REVIEW.md`). Which testcases close these scenarios and the OWNS split
→ `SMC_CLOCK_GATING_P2_TESTCASE_REVIEW.md`. Scenario keys/coverage records → the normative
`SMC_CLOCK_GATING_P2_SPEC_FEATURE_LIST.md`.

---
*Appendix: rendered from `SMC_CLOCK_GATING_P2_SPEC_FEATURE_LIST.md` @ candidate artifact_revision
1 (content_sha256 98edfcafc4474d142fa0a6ad9ef0f619826ceeedaf5eea953d0b7399bd56df9b), pin_revision
1, quality_policy rev 51a3357d…, source_revision 2ecc7b22…, generated_by
dv_vplan_gen-SMC_CLOCK_GATING_P2-step1-2026-08-05T15:09:00+08:00 (cursor/claude/sonnet-5).*


---
**SIGN-OFF:** approved by `minshaoho` at `2026-08-05T15:52:00+08:00` (owner blanket approval).
