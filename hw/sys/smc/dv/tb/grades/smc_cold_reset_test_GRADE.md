---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_cold_reset_test
ip: SMC_ACTIVE_REGRESSION
anchor: null
mode: NO-CHECKBOX
no_contract_reason: STANDALONE-REQUEST
entry_status: NOT-EVALUATED
repository_revision: c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7
spec: []
card_sha256: null
card_revision: null
card_path: null
testcase_plan:
  path: null
  plan_revision: null
  testcase_revision: null
  testcase_record_sha256: null
  parent_approved: null
evidence_class: null
closure_tier: null
quality_policy:
  path: /home/minshaoho/.claude/skills/dv_common/DV_QUALITY_POLICY.md
  revision: 51a3357d9c31a018d69451b055bc956c089af26e1051368e25ce396c84ac2a75
build_config: default
simulator: verilator
simulator_version: 5.050 2026-07-01
compile_target: default
model_fingerprint: 2c815fa08277
compile_inputs_sha256: null
seeds:
- 1
logs:
- path: hw/sys/smc/dv/build/runs/20260806_094523__verilator__smc_cold_reset_test/smc_cold_reset_test/logs/smc_cold_reset_test.log
  sha256: 9af9e3ebc20b6e93928b808cbc19cd9a6a1d6a819890748ea4d4bad97146e4d1
test_author:
  human_id: unknown
  run_id: unknown
  model:
    provider: unknown
    family: unknown
    version: unknown
auditor:
  human_id: minshaoho
  run_id: cursor/grok/4.5-reaudit-20260806
  model:
    provider: cursor
    family: grok
    version: '4.5'
exceptions: []
checkers: []
findings:
- id: FIND-001
  tag: '[NO-ALWAYS-PASS-CHECKER]'
  severity: Blocking
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_cold_reset_test_seq.py:99-108
  observed: >
    S2 / CHK-CLK-EDGES asserts `clk_smc_i` / `clk_ref_i` / `clk_periph_i` rising-edge
    counts `>= 1` over a fixed window. Those three nets are TB-driven by
    `cocotb.clock.Clock` in `smc_base_test._bring_up` and are not DUT outputs; RTL
    cannot suppress the edges. Scoreboard ratio asserts on the same item are likewise
    period-geometry of the TB clocks, not DUT behavior.
  closure_condition: >
    Drop or re-scope the clock-edge proof so it observes a DUT-controlled clock (gated
    / derived / exported) with a FAIL-ON path reachable from RTL, or remove the token
    from any future card so it is not treated as DUT evidence.
  waived_by: null
- id: FIND-002
  tag: '[NO-ALWAYS-PASS-CHECKER]'
  severity: Blocking
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_cold_reset_test_seq.py:229-244
  observed: >
    S7 INT_POR_COLD_WHILE_PG0 uses `_wait_raw` that returns on the first sample where
    primary matches the pre-COLD gated levels. Kept log: POWERGOOD_LO at 22048 ns →
    state (0,0,0,0) at 22056 ns → COLD_RST_LO → same (0,0,0,0) at 22064 ns and the
    wait completes (one ref cycle). Cold→primary assert latency on the same run is
    ~33 ref cycles (S4: 4664→4928 ns). A DUT that releases primary after cold while
    PG is gated would still pass this wait. The follow-on
    `assert not (both primary == 1)` is then dead when gated levels are already 0,0.
  closure_condition: >
    After COLD_RST_LO under powergood_stable_o==0, poll for a bounded window and fail
    if primary ever leaves the gated levels (or require N consecutive matching samples
    after a cold-propagation lower bound), and keep the positive-control cold assert
    under PG=1 as a separate ordered step.
  waived_by: null
- id: FIND-003
  tag: '[NO-BLIND-DELAY-SYNC]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_cold_reset_test_seq.py:77-81
  observed: >
    `_recover_sample` always waits a fixed `RECOVER_REF_CYCLES=700` on `clk_ref_i`
    then issues SAMPLE. S4 checked_cleared and S5 checked_cleared use that helper
    immediately before asserting recovered levels (log: COLD_RST_HI @ 4928 ns →
    SAMPLE @ 10528 ns = exactly 700×8 ns; POWERGOOD_HI @ 10536 ns → SAMPLE @
    16136 ns). Completion is synchronized by magic cycle count, not by a predicate
    wait with fail-on-expiry (contrast S6 cool release, which correctly uses
    `_wait_raw`).
  closure_condition: >
    Replace `_recover_sample` callers on proof paths with `_wait_raw` (or equivalent)
    predicates for the cleared levels, bounded with last-state TIMEOUT failure — same
    pattern already used for cool release.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_cold_reset_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🔴 2 Blocking · 🟠 1 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase. Layer 1 findings
> are the entire scope of this report. `NOT-READY` records the **absence of a closure
> claim, not a defect**. Kept log is a sim PASS (seed 1); Layer 2 was not entered.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `db445b17…`)

| Prior id | Tag / grade | Status this round | Notes |
|---|---|---|---|
| FIND-001 | 🔴 `[NO-ALWAYS-PASS-CHECKER]` | OPEN — unchanged | Same TB-driven clock-edge proof; new log still emits CHK-CLK-EDGES |
| FIND-002 | 🔴 `[NO-ALWAYS-PASS-CHECKER]` | OPEN — unchanged | Same first-sample wait; new log POWERGOOD_LO@22048 → match@22064 |
| FIND-003 | 🟠 `[NO-BLIND-DELAY-SYNC]` | OPEN — unchanged | Same 700-cycle `_recover_sample`; 4928→10528 ns cite reproduces |
| waivers: [] | — | unchanged | Prior ledger empty; no signed `approved_by` to carry; none dropped |
| Kept log | `db445b17…` | replaced | `9af9e3eb…` (seed=1 PASS; model `2c815fa08277`) |
| repository_revision | `2ecc7b22…` | updated | `c10b6d63…` |

## Your to-do — 3 items (🔴 2 Blocking · 🟠 1 Major)

| # | Sev | Item |
|---|---|---|
| 1 | 🔴 Blocking | FIND-001 `[NO-ALWAYS-PASS-CHECKER]` — CLK edges observe TB-driven inputs |
| 2 | 🔴 Blocking | FIND-002 `[NO-ALWAYS-PASS-CHECKER]` — INT_POR cold-while-PG0 wait exits on first sample |
| 3 | 🟠 Major | FIND-003 `[NO-BLIND-DELAY-SYNC]` — `_recover_sample` fixed 700-cycle settle |

<details>
<summary>1. 🔴 Blocking — FIND-001 `[NO-ALWAYS-PASS-CHECKER]` at seq S2 / CHK-CLK-EDGES</summary>

`COUNT_EDGES` on `clk_smc_i` / `clk_ref_i` / `clk_periph_i` measures clocks the TB itself
starts in `_bring_up`. Asserts `>= 1` and scoreboard ratio checks cannot fail because of
RTL; they only fail if the TB clock tasks stop.

**Close when:** the clock proof targets a DUT-controlled clock with a real FAIL-ON path, or
the token is removed from any future contract so it is not DUT evidence.

</details>

<details>
<summary>2. 🔴 Blocking — FIND-002 `[NO-ALWAYS-PASS-CHECKER]` at seq S7 INT_POR_COLD_WHILE_PG0</summary>

`_wait_raw` returns on the first sample matching pre-COLD gated levels. Kept log completes
that wait one ref cycle after `COLD_RST_LO`, while cold→primary assert elsewhere takes ~33
ref cycles — so a delayed illegal release while PG-gated still passes. The
`assert not (both == 1)` after a successful wait with gated=(0,0) cannot fire.

**Close when:** hold a bounded post-COLD observation window (or N consecutive samples past
a cold-propagation lower bound) and fail if primary leaves gated levels; keep PG=1 cold
assert as the positive control.

</details>

<details>
<summary>3. 🟠 Major — FIND-003 `[NO-BLIND-DELAY-SYNC]` at `_recover_sample`</summary>

S4/S5 `checked_cleared` use a fixed 700-cycle delay then SAMPLE/assert. S6 cool release
already shows the correct pattern (`_wait_raw` + TIMEOUT).

**Close when:** recovery proof uses predicate waits with fail-on-expiry and last-state
diagnostics, not a blind cycle count.

</details>

**Then:** owner remediates FIND-001/002/003 in the sequence, re-keeps a PASS log, and
re-invokes `/dv_test_audit`. Do not invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — pin drive via `SmcResetDriver` on top-level `powergood_i` / `rst_cold_ni` / `rst_cool_ni`; samples top-level status outputs; no force/deposit on proof path |
| F2 can't-fail checker | 🔴 Blocking — FIND-001, FIND-002 |
| E1 skip-to-pass | ✅ clean — missing ops raise; no HDL-path skip-to-pass |
| E2 empty phase | ✅ clean — S2–S8 drive/sample/assert; S1 is SETUP restatement only |
| S1 silent fail | ✅ clean — `_wait_raw` TIMEOUT and level asserts raise `AssertionError` with last state |
| O1 checker disabled | ✅ clean — scoreboard reset/clk checks remain enabled; RAW_SAMPLE intentionally skips post-release invariants |
| Phase-S obligations — L1 | 🟠 Major — FIND-003 `[NO-BLIND-DELAY-SYNC]`; bounded waits otherwise fail-on-expiry; X/Z via `resolvable`; enrolled in `reset.toml` / `all.toml`; CHK tokens after asserts |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Log: `hw/sys/smc/dv/build/runs/20260806_094523__verilator__smc_cold_reset_test/smc_cold_reset_test/logs/smc_cold_reset_test.log`
  sha256 `9af9e3ebc20b6e93928b808cbc19cd9a6a1d6a819890748ea4d4bad97146e4d1`
  (verified via `sha256sum`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `return_code: 0`, cocotb summary:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Test: `hw/sys/smc/dv/cocotb/tests/smc_cold_reset_test.py` starts
  `smc_cold_reset_test_seq` on `reset_agent.sequencer` after `smc_base_test` bring-up
- Seq proof path: `smc_cold_reset_test_seq.py` → `_OneShot` → `SmcResetAgent` /
  `SmcClkAgent` → `SmcScoreboard` reset/clk writers
- Token cites (kept log): CHK-CLK-EDGES L287; CHK-BRINGUP-LEVELS L293;
  CHK-COLD-ASSERT-PRIMARY L429; CHK-POWERGOOD-GATES L488; CHK-COOL-PRIMARY L687;
  CHK-INT-POR-COLD L874; CHK-INT-COOL-SEQ L1066; CHK-NONVAC L1072; scenario PASS L1083
- INT_POR timing cite: POWERGOOD_LO @ 22048 ns; gated (0,0,0,0) @ 22056 ns;
  COLD_RST_LO then matching sample @ 22064 ns (wait done)
- Cold assert latency cite (S4): COLD_RST_LO @ 4664 ns → primary asserted @ 4928 ns
- Blind recover cite: COLD_RST_HI @ 4928 ns → SAMPLE @ 10528 ns; POWERGOOD_HI @ 10536 ns
  → SAMPLE @ 16136 ns
- Enrollment: `hw/sys/smc/dv/testlists/reset.toml`, `all.toml`
- Bring-up trailer: efuse hex + ROM `$readmemh` — time-0 image load; not used as golden
  for these pin-level checks (policy §6 standing preload exception; off this proof path)
- No unexplained `ERROR`/`FATAL`/`Traceback`; only cocotb deprecation warnings / fuse-sense INFO
- Prior waivers: `[]` — nothing with non-null `approved_by` to carry forward

</details>

## Not concluded

- Whether cold/POR/cool pin behavior matches SPEC reset properties (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers from
  the passing log.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
