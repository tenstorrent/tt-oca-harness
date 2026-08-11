---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_canonical_smoke_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094547__verilator__smc_canonical_smoke_test/smc_canonical_smoke_test/logs/smc_canonical_smoke_test.log
  sha256: eb171c869f6a927a26ee0432e0803c1ad92d3cd5732f28c1b4c4bc5105f48cfa
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
  tag: '[CHECKER-NONVACUITY]'
  severity: Blocking
  artifact_ref: hw/sys/smc/dv/cocotb/env/smc_scoreboard.py:86-103
  observed: >-
    Canonical smoke embeds the reset-recovery matrix: mid-window RAW_SAMPLE items
    only update FUNC_COV bins and return without asserting that powergood / cold /
    cool stimulus cleared powergood_stable or asserted primary resets. The only
    FAIL-ON reset compares are SAMPLE post-stable all-1s (baseline + three
    recoveries) plus sequence counters (`multi_agent_samples == 4`,
    `raw_reset_samples >= 7`). A DUT that ignores powergood_i / rst_cold_ni /
    rst_cool_ni still yields SAMPLE all-1s after the fixed recover delay, so
    cocotb PASS does not prove any transition leg ran. Kept log (sha256 eb171c86…):
    mid-window reset_state includes (0,0,0,0) after POWERGOOD_LO and (1,0,0,0)
    after cold release, but those values are never FAIL-ON compared; cool-window
    RAW samples stay (1,1,1,1) @ 17040/17744 ns while the test still passes.
  closure_condition: >-
    On each matrix leg (powergood glitch, cold reassert, cool pulse), assert at
    least one mid-window sample that fails unless the expected effect is observed
    (e.g. powergood_stable cleared and/or primary resets asserted), then keep the
    post-recovery SAMPLE all-1s compare; do not treat FUNC_COV or RAW count alone
    as proof.
  waived_by: null
- id: FIND-002
  tag: '[NO-BLIND-DELAY-SYNC]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_canonical_smoke_test_seq.py:82-84
  observed: >-
    `_recover_and_sample_all` always waits a fixed `RECOVER_REF_CYCLES=700` on
    `clk_ref_i` then issues `_sample_all`. Kept log: last powergood-window RAW @
    4736 ns → SAMPLE #2 @ 10336 ns; post-cold RAW @ 11176 ns → SAMPLE #3 @
    16776 ns; post-cool RAW @ 17744 ns → SAMPLE #4 @ 23344 ns — each recover gap
    is exactly 700 ref cycles × 8 ns. There is no bounded predicate wait on
    powergood_stable_o / primary-reset release that fails on expiry with
    last-state diagnostics; the magic cycle count stands in for recovery
    completion on every matrix leg.
  closure_condition: >-
    Replace `_recover_and_sample_all` with a bounded wait on the recovery outputs
    (released / stable levels) that raises on timeout with last-state diagnostics,
    then SAMPLE / scoreboard-compare.
  waived_by: null
- id: FIND-003
  tag: '[NO-DUMMY-DEAD-CODE]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/env/smc_scoreboard.py:139-141
  observed: >-
    After `assert item.resolvable`, `_check_gpio` asserts `core2pad_any` /
    `core2pad_en_any` / `pad2core_en_any` `in (0, 1)`. The GPIO driver only sets
    those fields to `int(sig)` when resolvable, else `-1`, so once `resolvable`
    is True the three range asserts cannot fail on any RTL. They read as active
    level checks while the scoreboard comment admits aggregate levels are not
    GPIO-diagnostic; the real fail path is only resolvability. This smoke's GPIO
    SAMPLE #1–#4 in the kept log exercise that path (`1/1/1`).
  closure_condition: >-
    Remove the tautological `in (0, 1)` asserts (keep `resolvable`), or replace
    them with an independently derived exact expectation that can fail on wrong
    levels when a future card requires pad-level proof.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_canonical_smoke_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🔴 1 Blocking · 🟠 2 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect** in the test by itself. Kept log is a sim PASS (seed 1); Layer 2 was not entered.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `89777e50…`)

| Item | Prior (log `89777e50…`) | This audit (log `eb171c86…`) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🟠 1 Major (GPIO dead range as FIND-001) | 🔴 1 Blocking · 🟠 2 Major (FIND-001/002 newly opened; prior GPIO retained as FIND-003) |
| FIND-001 | open — `[NO-DUMMY-DEAD-CODE]` GPIO `in (0,1)` | **reclassified id** — now `[CHECKER-NONVACUITY]` on RAW_SAMPLE / transition vacuity (shared with reset-recovery matrix) |
| FIND-002 | — | **new** — `[NO-BLIND-DELAY-SYNC]` fixed 700-cycle `_recover_and_sample_all` |
| FIND-003 | — (was prior FIND-001) | still open — GPIO tautological range asserts |
| Kept log | `89777e508f218a0cf76a13c024cace2fa56887025b35f0b1057990af8ea2469c` PASS seed=1 | `eb171c869f6a927a26ee0432e0803c1ad92d3cd5732f28c1b4c4bc5105f48cfa` PASS seed=1 |
| Waivers carried | none signed (`waivers: []`; nothing to drop) | none |

## Your to-do — 3 items (🔴 1 Blocking · 🟠 2 Major)

| # | Kind | Id | Severity / grade | Where |
|---|---|---|---|---|
| 1 | finding | FIND-001 | 🔴 Blocking | `smc_scoreboard.py:86-103` |
| 2 | finding | FIND-002 | 🟠 Major | `smc_canonical_smoke_test_seq.py:82-84` |
| 3 | finding | FIND-003 | 🟠 Major | `smc_scoreboard.py:139-141` |

<details>
<summary>1. FIND-001 — 🔴 Blocking <code>[CHECKER-NONVACUITY]</code> — mid-window RAW_SAMPLE never FAIL-ON</summary>

- **Where:** `hw/sys/smc/dv/cocotb/env/smc_scoreboard.py:86-103` (proof-path helper; RAW_SAMPLE early-return)
- **Observed:** `_check_reset` returns on `RAW_SAMPLE` after coverage only. Sequence end-gates only require four six-agent sweeps and `raw_reset_samples >= 7`. Kept-log mid-window `reset_state` tuples are never compared for FAIL-ON; a no-effect DUT still passes the post-recover all-1s SAMPLE path. Cool-window RAW stays `(1,1,1,1)`.
- **Closure:** each matrix leg needs at least one checked mid-window sample that fails unless the glitch/cold/cool effect is observed, then keep post-recovery SAMPLE all-1s.

</details>

<details>
<summary>2. FIND-002 — 🟠 Major <code>[NO-BLIND-DELAY-SYNC]</code> — fixed 700-cycle recover settle</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_canonical_smoke_test_seq.py:82-84` (`_recover_and_sample_all`)
- **Observed:** All three recovery SAMPLE legs synchronize with a fixed 700-cycle `ClockCycles` then `_sample_all` (log gaps match 700×8 ns after last RAW). No bounded handshake wait with fail-on-expiry.
- **Closure:** recovery proof uses predicate waits with fail-on-expiry and last-state diagnostics, not a blind cycle count.

</details>

<details>
<summary>3. FIND-003 — 🟠 Major <code>[NO-DUMMY-DEAD-CODE]</code> — GPIO range asserts can't fail after resolvable</summary>

- **Where:** `hw/sys/smc/dv/cocotb/env/smc_scoreboard.py:139-141` (proof-path helper used by this smoke)
- **Observed:** `_check_gpio` asserts each aggregate `in (0, 1)` only after `assert item.resolvable`. Driver sets `0`/`1` when resolvable and `-1` otherwise, so the range guards never fire once resolvable passes; they resemble value checks the comment says are intentionally not proven. Log SAMPLE: `core2pad_any=1, core2pad_en_any=1, pad2core_en_any=1`.
- **Closure:** Drop the tautological range asserts, or replace with a fail-capable exact expectation when a card requires pad-level proof (today's smoke only needs X-free observability).

</details>

**Then:** owner remediates FIND-001/002/003 in the scoreboard and/or sequence, re-keeps a PASS log, and re-invokes `/dv_test_audit smc_canonical_smoke_test`. Do not invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — top-level pin drive (`powergood_i` / `rst_cold_ni` / `rst_cool_ni`) + passive SAMPLE / COUNT_EDGES; no Force/deposit on proof path |
| F2 can't-fail checker | ✅ clean — scoreboard reset/i2c/clk/irq/axil SAMPLE asserts and seq sample-count gates can fail; GPIO fail path is resolvable (see FIND-003 for dead range guards); RAW vacuity filed under Phase-S not F2 |
| E1 skip-to-pass | ✅ clean — no missing-path skip branch; agents must dispatch; unsupported ops raise |
| E2 empty phase | ✅ clean — baseline + powergood/cold/cool recoveries each run `_sample_all` / RAW_SAMPLE matrix |
| S1 silent fail | ✅ clean — scoreboard `assert` + seq `assert multi_agent_samples == 4` / `raw_reset_samples >= 7` |
| O1 checker disabled | ✅ clean — scoreboard analysis path active (log shows sample #1–#4 per agent); RAW_SAMPLE intentionally skips post-stable invariants (vacuity filed under Phase-S, not O1) |
| Phase-S obligations — L1 | 🔴 Blocking — FIND-001 · 🟠 Major — FIND-002 · FIND-003; else X-aware `resolvable`, seed logged, enrolled in `combined.toml`/`all.toml`, ROM/efuse preload is bring-up trailer not proof path |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_canonical_smoke_test.py`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_canonical_smoke_test_seq.py`
- Scoreboard (proof path): `hw/sys/smc/dv/cocotb/env/smc_scoreboard.py`
- Log: `hw/sys/smc/dv/build/runs/20260806_094547__verilator__smc_canonical_smoke_test/smc_canonical_smoke_test/logs/smc_canonical_smoke_test.log`
  sha256 `eb171c869f6a927a26ee0432e0803c1ad92d3cd5732f28c1b4c4bc5105f48cfa` (verified via `sha256sum`; matches claimed)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `exit_code: 0`, cocotb summary: `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Stimulus: POWERGOOD glitch + COLD + COOL assert/release with RAW_SAMPLE windows; 4× six-agent sweeps
- Observed in log: reset SAMPLE #1–#4 with stable-1 invariants; I2C `cg_en=0`; IRQ zeros; AXIL idle; clk edges `ref=25 smc=33/34 periph=24` (window 25); RAW_SAMPLE count ≥ 7 (9 logged)
- Mid-window cov cites (never FAIL-ON): POWERGOOD RAW `(0,0,0,0)` @ 4368/4416/4480 ns; cold post-release RAW `(1,0,0,0)` @ 10920/11176 ns; cool RAW stays `(1,1,1,1)` @ 17040/17744 ns
- Blind recover cite: powergood last RAW 4736→SAMPLE 10336; cold 11176→16776; cool 17744→23344 (=700 ref cycles × 8 ns each)
- Final seq gates: `multi_agent_samples == 4`, `raw_reset_samples >= 7` (counters + scoreboard asserts; no `CHK-*` tokens — none required without a card)
- Enrollment: `hw/sys/smc/dv/testlists/combined.toml`, `all.toml`
- Bring-up trailer: efuse/ROM hex preload present; not used by pin-sample / reset-drive proof path
- No unexplained `ERROR`/`FATAL`/`Traceback`; only cocotb deprecation warnings
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`); auditor `run_id: cursor/grok/4.5-reaudit-20260806`

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>eb171c86…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| baseline `_sample_all` | 280–299 | reset/i2c/irq/gpio/axil SAMPLE #1 + clk COUNT_EDGES | seq `:89` / agents |
| POWERGOOD_LO/HI + RAW | 301–347 | drive glitch/recover; RAW_SAMPLE windows | seq `:91–97` |
| after_powergood | 369–386 | SAMPLE #2 six-agent sweep | seq `:97` |
| COLD_RST_LO/HI + RAW | 388–421 | cold assert/release | seq `:99–105` |
| after_cold | 443–460 | SAMPLE #3 recovery sweep | seq `:105` |
| COOL_RST_LO/HI + RAW | 462–513 | cool assert/release; RAW stays `(1,1,1,1)` | seq `:107–112` |
| after_cool | 514–531 | SAMPLE #4 + clk edges; PASS | seq `:112–115` |
| cocotb result | 539–541 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | — |

</details>

## Not concluded

- Whether six-agent idle observability plus reset-recovery sampling proves the SPEC properties a future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
