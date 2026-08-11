# SMC_CLOCK_GATING_P2 Testcase Set Review — P2 (candidate plan v1, augment mode)

**Your two decisions:** (a) is this the right set of testcases for this milestone, (b) is the
OWNS split right — no two testcases claiming the same behavior. Rows: 3 of 40 · cards: 3 of 8
(well within budget).

**Headline: no NEW testcase is proposed this round.** All 4 in-scope scenarios (across 3
features) are closed by **extending** the 3 pinned anchors `owns_notes` already named as the
preferred target — `smc_dma_cg_activity_test`, `smc_zeroer_axiclk_cg_test`,
`smc_zeroer_regclk_cg_test`. Because `augment` mode still requires the newly-proposed population
to be called out first when one exists, and none exists here, that population is stated as empty
rather than omitted.

## NEW testcases I am asking you to approve — 0

None. Every scenario in this boundary-scoped feature_list is reachable at `LIVE` proof class by
extending an existing pinned anchor.

## Existing testcases, re-scoped (extended) — 3 (3 features / 4 scenarios total)

| Approve | Name | Exists to prove | OWNS | Scenarios | Tier |
|---|---|---|---|---|---|
| [x] | `smc_dma_cg_activity_test` (id `SMC_CG_P2_001`) | DMA clock-gating hysteresis resolves correctly across its full 0-63 cycle range and when activity re-asserts mid-countdown | `prim_clk_gater_hysteresis` full-range sweep + activity-during-hysteresis race only (excludes nominal single-point hysteresis and the axi_cg_snoop area — no feature exists for it) | 2 | A |
| [x] | `smc_zeroer_axiclk_cg_test` (id `SMC_CG_P2_002`) | The Zeroer `axi_clk` gate does not glitch, and a follow-on operation starts/completes correctly, when a trigger races the prior operation's busy-to-idle edge | `axi_clk_enable` gate behavior across the busy-to-idle back-to-back race only (excludes `reg_clk`, owned by `SMC_CG_P2_003`) | 1 | A |
| [x] | `smc_zeroer_regclk_cg_test` (id `SMC_CG_P2_003`) | A register access arriving while `reg_clk` is gated ungates the clock and completes within a bounded time | `reg_clk_enable` gate behavior across the pending-access-while-gated race only (excludes `axi_clk`, owned by `SMC_CG_P2_002`) | 1 | A |

Two of the three (`SMC_CG_P2_002`, `SMC_CG_P2_003`) carry an open-finding `blockers` entry
(`SF-005`, `SF-004` respectively): the race is fully locatable and stimulable today, but one
checker on each card deliberately does not score the exact sub-behavior the open finding leaves
undefined, rather than guessing it. See `SMC_CLOCK_GATING_P2_CARD_REVIEW.md` for exactly which
checker and why.

## Pinned anchor not allocated in this plan — 1 decision needed

| Accept | Anchor | Why it owns nothing here | Your call |
|---|---|---|---|
| [x] | `smc_clk_multi_window_test` | This pinned `augment`-mode anchor owns no scenario in the frozen P2 feature_list: none of the 4 allocated scenarios requires joint multi-window observation across the DMA and Zeroer domains, and the feature_list's `interactions` array is empty (no SPEC-required cross exists within this boundary). | Confirm this anchor's existing scope is out of this P2 boundary (likely already-closed nominal/cross-domain formula cells from a prior milestone), or tell us what P2-in-scope behavior you expected it to close so we can re-derive. |

## Scenarios NO testcase claims — you must accept each (0)

**`unallocated` is empty.** Naming this out loud per the workflow's own instruction: an empty
list is a claim worth a second look, because it usually means the inventory was trimmed to the
tests. It is not a trim here — the feature_list was derived by a subagent that never saw these
anchor names, and it independently converged on exactly the three named races the pin's boundary
describes, plus a fourth boundary-named area (`axi_cg_snoop`) that produced **zero features**
(raised as `SF-001`, not silently dropped — see the feature-review packet). The empty
`unallocated` list is a direct consequence of this pin's boundary being scoped narrowly to three
explicit P1-deferred races rather than the whole SMC clock-gating surface; it is not evidence
that every scenario this boundary could ever contain has been found and closed.

## Not asking you to review

Step text and checker mechanics → `SMC_CLOCK_GATING_P2_CARD_REVIEW.md`, after this set is
approved. Feature semantics → `SMC_CLOCK_GATING_P2_FEATURE_REVIEW.md`.

---
*Appendix: rendered from `SMC_CLOCK_GATING_P2_TESTCASE_PLAN.md` @ candidate plan_revision 1
(content_sha256 33a2949f9b2995cfb3c59b4c165586f70b5e796f017dee8721d35292caf1912f), derived_from
feature_list_revision 1 (sha 98edfcaf…), pin_revision 1, anchor_mode augment, generated_by
dv_vplan_gen-SMC_CLOCK_GATING_P2-step3-2026-08-05T15:40:00+08:00 (cursor/claude/sonnet-5).*


---
**SIGN-OFF:** approved by `minshaoho` at `2026-08-05T15:52:00+08:00` (owner blanket approval).
