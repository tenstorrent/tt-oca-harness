# SMC_CLOCK_GATING_P2 Card Mechanics Review — P2 (candidate cards v1)

**Your task:** review step/checker mechanics for the 3 cards below, once (and only once) their
parent testcase records are approved in `SMC_CLOCK_GATING_P2_TESTCASE_REVIEW.md`. Cards: 3 of 8
(within budget). All three are first-draft candidates — **REVIEW-FOCUS: everything is new**.

---

## Card `SMC_CG_P2_001` — anchor `smc_dma_cg_activity_test`

**REVIEW-FOCUS:** new card. Extends the existing anchor with a full 0-63 cycle hysteresis sweep
(previously untested range per the pin's boundary) and an activity-reassertion race case.

**OWNS:** `prim_clk_gater_hysteresis` full-range 0-63 cycle sweep and the activity-during-
hysteresis race for the DMA frontend/request-manager/backend clock only; excludes nominal
single-point hysteresis and the axi_cg_snoop area (no feature exists for it).

**Description:** producer = combined DMA activity (frontend wakeup OR backend busy) | transport
= the single `prim_clk_gater_hysteresis` 6-bit counter | consumer = the gated clock reaching
`idma_frontend_wrapper` / `idma_request_manager_wrapper` / `idma_backend_wrapper`.

| Step | From scenario | Text |
|---|---|---|
| S1 (setup) | — (scaffolding) | Reset DMA, `disable_cg=0`, confirm idle baseline (no activity, counter=0, clock gated) |
| S2 | `SMC-CG-DMA-HYST.S1` | Sweep inter-activity gap across {0,1,32,63,64} cycles; record exact deassertion cycle at each |
| S3 | `SMC-CG-DMA-HYST.S2` | Reassert activity early-in / at-last-cycle-of an in-progress countdown; confirm no premature gate and correct countdown restart |
| S4 (TIMEOUT) | — (scaffolding) | Bounded wait on deassertion / post-clear completion fails with last state on expiry |

| Checker | Proves / how it can fail |
|---|---|
| `CHK-DMA-HYST-SWEEP` | **Proves:** clock-enable deasserts exactly at the swept gap cycle for {0,1,32,63}, and by cycle 63 at the latest for gap=64. **Fails on:** early/late deassertion at any swept cell, X/Z, or a missing required cell. |
| `CHK-DMA-HYST-RACE` | **Proves:** clock-enable never deasserts during a reassertion window, and the post-clear countdown restarts from the full window. **Fails on:** any deassert pulse during the interrupted window, or a countdown that doesn't restart correctly. |
| `CHK-NONVAC` | Ordered fence `SETUP < ACTIVITY-BASELINE < SWEEP-COMPLETE < RACE-REASSERT-EARLY < RACE-REASSERT-LAST < PASS`. Integrity only — no feature/scenario credit. |
| `CHK-TIMEOUT-PATHS` | Every bounded wait has a finite logged bound, a static fail-on-expiry path, and a last-state diagnostic. |

**Guardrails (non-runtime):** no force/deposit on any DMA/CG internal signal; expected
deassertion cycles are computed from the applied stimulus timing, never copied from the DUT's own
trace. **Blockers:** none.

---

## Card `SMC_CG_P2_002` — anchor `smc_zeroer_axiclk_cg_test` (revision 2, supersedes revision 1)

**REVIEW-FOCUS: amended.** Skill 1.5's implementation of the real trigger protocol (3 sequential
AXI-Lite writes DEST_ADDR→SIZE→CTRL_STATUS) found that `axi_clk_enable` necessarily deasserts for
~26–28 `clk_smc_i` cycles between the op1 busy-fall and op2 busy-rise at **all three** swept
timings — revision 1's `CHK-ZEROER-AXICLK-NOGLITCH` required zero deassert across the *whole*
busy-to-idle boundary including that protocol turnaround, which is physically unreachable via
frontdoor. **Diff vs. revision 1 (owner decision minshaoho, standing order "都簽署繼續", amend
choice ii — everything else on the card is byte-identical):**
  - `CHK-ZEROER-AXICLK-NOGLITCH.proof`/`fail_on` narrowed: now requires `axi_clk_enable` stay
    asserted only *while `zeroer_busy_o`==1* for either operation (no mid-busy glitch); a deassert
    gap strictly between busy pulses, caused by the multi-write trigger latency, is now **allowed
    and logged** (start/end cycle + duration), not scored as a NOGLITCH failure.
  - `expect_source` for that checker gains a citation to zeroer.adoc §Operation Flow
    (Configuration/Trigger), backing why the gap is protocol-caused rather than spurious.
  - One new `guardrails` entry documents the `BY-DESIGN-EXCEPTION` for this gap.
  - `observation` gains one sentence: the inter-busy deassert window, if any, is logged with its
    start/end cycle and duration at each swept timing.
  - `CHK-ZEROER-AXICLK-COMPLETION` is **unchanged**: same-cycle/1-after still scored; 1-cycle-before
    stays evidence-only pending `SF-005`.
  - `owns`, `allocated_scenarios`, `description`, steps S1–S3, `CHK-NONVAC`, `CHK-TIMEOUT-PATHS`
    are unchanged from revision 1.
  - No feature_list or testcase-plan amendment was needed — `owns`/`allocated.scenarios`/
    `allocated.features` are byte-identical to plan revision 1; this is a Step-4
    checker-exactness narrowing, not an allocation change.

**OWNS:** `axi_clk_enable` gate behavior across the busy-to-idle back-to-back trigger race only;
excludes `reg_clk` gating (owned by `SMC_CG_P2_003`) and nominal single-operation gating.

**Description:** producer = `zeroer_busy_o` racing a new trigger write | transport =
`prim_clkgater` on `axi_clk` | consumer = the zeroer AXI4 master interface.

| Step | From scenario | Text |
|---|---|---|
| S1 (setup) | — (scaffolding) | Reset zeroer, `disable_cg=0`, confirm idle baseline |
| S2 | `SMC-CG-ZEROER-AXICLK.S1` | Run a first zero-fill op to near completion; issue a follow-on trigger at 1-before / same-cycle / 1-after the `zeroer_busy_o` falling edge (3 sequential AXI-Lite writes DEST_ADDR→SIZE→CTRL_STATUS); observe `axi_clk_enable` and the follow-on op's execution |
| S3 (TIMEOUT) | — (scaffolding) | Bounded wait on the follow-on write-address phase fails with last state on expiry |

| Checker | Proves / how it can fail |
|---|---|
| `CHK-ZEROER-AXICLK-NOGLITCH` (amended) | **Proves:** `axi_clk_enable` stays asserted with zero deassert pulses *while `zeroer_busy_o`==1* for either operation, at all 3 swept timings; a between-busy deassert gap from trigger-write latency is permitted and logged. **Fails on:** any deassert pulse while busy, X/Z while busy, a missing cell, or an unlogged inter-busy gap. |
| `CHK-ZEROER-AXICLK-COMPLETION` (unchanged) | **Proves:** at same-cycle/1-after, the follow-on op begins within the bound and completes with a status update. **At 1-before (genuine busy overlap), logs the DUT's response as evidence-only and asserts no pass/fail verdict on it — `SF-005` is open.** **Fails on:** missing/late completion at the two defined cells, or silently dropping / prematurely scoring the 1-before response. |
| `CHK-NONVAC` | Ordered fence `SETUP < FIRST-OP-BUSY < BOUNDARY-SWEEP(3-cells) < FOLLOWON-OBSERVED < PASS`. |
| `CHK-TIMEOUT-PATHS` | Finite logged bound + fail-on-expiry path + last-state diagnostic. |

**Guardrails (non-runtime):** no force/deposit; `BY-DESIGN-EXCEPTION` note that the 1-before
cell's protocol verdict is deliberately unscored pending `SF-005` — re-examine once answered;
**new** `BY-DESIGN-EXCEPTION` note that an inter-busy `axi_clk_enable` deassert gap caused by the
multi-write trigger protocol is expected and logged, not a NOGLITCH failure.
**Blockers:** `SF-005` (open, Critical — trigger-during-busy outcome undefined in the pinned
SPEC).

---

## Card `SMC_CG_P2_003` — anchor `smc_zeroer_regclk_cg_test`

**REVIEW-FOCUS:** new card. Extends the existing anchor with a 3-cell gated-access timing sweep.

**OWNS:** `reg_clk_enable` gate behavior across the pending-access-while-gated race only;
excludes `axi_clk` gating (owned by `SMC_CG_P2_002`) and nominal single-access gating.

**Description:** producer = a register access racing the currently-gated `reg_clk` | transport =
`prim_clkgater` on `reg_clk` | consumer = the zeroer register interface.

| Step | From scenario | Text |
|---|---|---|
| S1 (setup) | — (scaffolding) | Reset zeroer, `disable_cg=0`, idle the register interface until `reg_clk` gates |
| S2 | `SMC-CG-ZEROER-REGCLK.S1` | Issue a register access immediately-after / long-after gating, and back-to-back across the gate boundary; observe `reg_clk_enable`'s rise and the access's result |
| S3 (TIMEOUT) | — (scaffolding) | Bounded wait on ungate + service fails with last state on expiry |

| Checker | Proves / how it can fail |
|---|---|
| `CHK-ZEROER-REGCLK-UNGATE` | **Proves:** `reg_clk_enable` rises within the declared bound at all 3 swept cells. **Fails on:** no rise within bound, X/Z, or a missing cell. |
| `CHK-ZEROER-REGCLK-ACCESS-COMPLETE` | **Proves:** the pending access is serviced correctly (correct read data / write reflected) at every cell, with the maximum service latency recorded pending `SF-004`. **Fails on:** stale/incorrect/X data, a write not reflected, or a hang beyond the bound. |
| `CHK-NONVAC` | Ordered fence `SETUP < REG_CLK-GATED-BASELINE < ACCESS-SWEEP(3-cells) < PASS`. |
| `CHK-TIMEOUT-PATHS` | Finite logged bound + fail-on-expiry path + last-state diagnostic. |

**Guardrails (non-runtime):** no force/deposit; expected read-back values come from the
testbench's own applied stimulus / documented reset value, never the DUT's own read path.
**Blockers:** `SF-004` (open, Critical — `register_activity` generation/duration semantics
undefined in the pinned SPEC).

---
*Appendix: rendered from `SMC_CLOCK_GATING_P2_VPLAN_DETAIL.md` @ artifact_revision 1
(content_sha256 6a10cab30c73449a6968b1803148bf19d5de8f91f2dcfea40f2d4886f0afa69b, after amending
`SMC_CG_P2_002` to revision 2, record_sha256
7716914f5e4c5adb60a4a2ebb6c58c271518148cdabc04a7796f561b5743fc7f), derived_from testcase-plan
plan_revision 1, pin_revision 1, generated_by
dv_vplan_gen-SMC_CLOCK_GATING_P2-amend-SMC_CG_P2_002-2026-08-05T17:25:00+08:00
(cursor/claude/sonnet-5). `schema_check.py` (`--plan` + `--feature-list`): `valid`.*


---
**SIGN-OFF:** `SMC_CG_P2_001`/`SMC_CG_P2_003` approved by `minshaoho` at
`2026-08-05T15:52:00+08:00` (owner blanket approval, unchanged by this amendment).
`SMC_CG_P2_002` revision 2 approved by `minshaoho` at `2026-08-05T17:25:00+08:00` (owner decision,
standing order "都簽署繼續" — amend choice ii).
