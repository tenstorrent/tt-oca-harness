---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_6agent_observability_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094547__verilator__smc_6agent_observability_test/smc_6agent_observability_test/logs/smc_6agent_observability_test.log
  sha256: de53fcf9e76f6dc8d66dc00cb6ce4050768adafc7c0bbb1e4dd77815266035c1
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
  tag: '[NO-DUMMY-DEAD-CODE]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/env/smc_scoreboard.py:139-141
  observed: >-
    After `assert item.resolvable`, `_check_gpio` asserts
    `core2pad_any` / `core2pad_en_any` / `pad2core_en_any` `in (0, 1)`.
    The GPIO driver only sets those fields to `int(sig)` when resolvable, else
    `-1`, so once `resolvable` is True the three range asserts cannot fail on
    any RTL. They read as active level checks while the scoreboard comment
    admits aggregate levels are not GPIO-diagnostic; the real fail path is only
    resolvability. This test's GPIO SAMPLE (#1 in the kept log) exercises that
    path.
  closure_condition: >-
    Remove the tautological `in (0, 1)` asserts (keep `resolvable`), or replace
    them with an independently derived exact expectation that can fail on wrong
    levels when a future card requires pad-level proof.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_6agent_observability_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🟠 1 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect** in the test by itself.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `b04fb2ee…`)

| Item | Prior (log `b04fb2ee…`, PASS) | This audit (log `de53fcf9…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🟠 1 Major | 🟠 1 Major |
| FIND-001 `[NO-DUMMY-DEAD-CODE]` | open — GPIO `in (0, 1)` after resolvable | still open — scoreboard sha / lines 139–141 unchanged |
| Kept log | `b04fb2ee3390f0acfa56e20ad7677c95d2f312022718be36ab6e5e7789ecbd39` | `de53fcf9e76f6dc8d66dc00cb6ce4050768adafc7c0bbb1e4dd77815266035c1` |
| Repo rev | `2ecc7b227e3926b253c65b5aac21239eec24ba5f` | `c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7` |
| Waivers carried | none signed (`waivers: []`) | none (nothing to drop; no signed entries) |

## Your to-do — 1 items (🟠 1 Major)

| # | Kind | Id | Severity / grade | Where |
|---|---|---|---|---|
| 1 | finding | FIND-001 | 🟠 Major | `smc_scoreboard.py:139-141` |

<details>
<summary>1. FIND-001 — 🟠 Major <code>[NO-DUMMY-DEAD-CODE]</code> — GPIO range asserts can't fail after resolvable</summary>

- **Where:** `hw/sys/smc/dv/cocotb/env/smc_scoreboard.py:139-141` (proof-path helper used by this 6-agent sweep)
- **Observed:** `_check_gpio` asserts each aggregate `in (0, 1)` only after `assert item.resolvable`. Driver sets `0`/`1` when resolvable and `-1` otherwise, so the range guards never fire once resolvable passes; they resemble value checks the comment says are intentionally not proven. Log SAMPLE: `core2pad_any=1, core2pad_en_any=1, pad2core_en_any=1`.
- **Closure:** Drop the tautological range asserts, or replace with a fail-capable exact expectation when a card requires pad-level proof (today's observability only needs X-free sampling).

</details>

**Then:** owner may leave this as enrolled smoke under STANDALONE-REQUEST, or allocate a real IP pin + card via `/dv_vplan_gen` before any closure claim; re-invoke `/dv_test_audit smc_6agent_observability_test` after scoreboard hygiene if FIND-001 is fixed.

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — passive SAMPLE / COUNT_EDGES on top-level pins; bring-up drives `powergood_i` / `rst_cold_ni` / `rst_cool_ni` only; no Force/deposit on proof path |
| F2 can't-fail checker | ✅ clean — scoreboard reset/i2c/clk/irq/axil asserts can fail; GPIO fail path is resolvable (see FIND-001 for dead range guards) |
| E1 skip-to-pass | ✅ clean — unsupported ops raise; no missing-path skip-to-pass |
| E2 empty phase | ✅ clean — body dispatches six agent ops (reset/i2c/irq/gpio/axil SAMPLE + clk COUNT_EDGES) |
| S1 silent fail | ✅ clean — scoreboard `assert` on each SAMPLE/COUNT_EDGES; `check_phase` fails if zero SAMPLE items |
| O1 checker disabled | ✅ clean — all six agent APs connected; log shows sample #1 per agent |
| Phase-S obligations — L1 | 🟠 Major — FIND-001; else X-aware `resolvable`, seed logged, enrolled in `combined.toml`/`all.toml`, COUNT_EDGES window is the measured quantity (not a blind delay substitute), ROM/efuse preload is post-PASS bring-up trailer |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_6agent_observability_test.py`
  sha256 `0c79da5c140dd23fc392f63cdb577d8492a280130ab40cae8e45544aa5ed2eb2`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_6agent_observability_test_seq.py`
  sha256 `cd5d3d67cd24cea15f0d0f44830cd8f8e6a02ed2b6b04ebb807ec47e620a9113`
- Scoreboard (proof path): `hw/sys/smc/dv/cocotb/env/smc_scoreboard.py`
- Log: `hw/sys/smc/dv/build/runs/20260806_094547__verilator__smc_6agent_observability_test/smc_6agent_observability_test/logs/smc_6agent_observability_test.log`
  sha256 `de53fcf9e76f6dc8d66dc00cb6ce4050768adafc7c0bbb1e4dd77815266035c1` (matches claimed)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `return_code: 0`, cocotb summary: `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Stimulus: one SAMPLE each on reset / i2c / irq / gpio / axil, then COUNT_EDGES (`window_ref_cycles=25`)
- Observed in log: reset SAMPLE stable-1 invariants; I2C `cg_en=0` `debug_lo=0x4`; IRQ zeros; GPIO aggregates `1/1/1`; AXIL idle `any=0`; clk edges `ref=25 smc=33 periph=24`
- Fail path (static): per-agent scoreboard asserts + `check_phase` `total > 0`; no `CHK-*` tokens (none required without a card)
- Enrollment: `hw/sys/smc/dv/testlists/combined.toml`, `all.toml`
- Bring-up trailer: efuse/ROM hex preload lines after cocotb PASS; not used by pin-sample proof path
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`)

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>de53fcf9…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| bring-up | 256–267 | clocks + powergood + cold release | `smc_base_test` |
| reset SAMPLE #1 | 279–282 | stable-1 invariants; FUNC_COV reset | seq `:32–33` / `_check_reset` |
| I2C SAMPLE #1 | 283–285 | `cg_en=0`, `debug_lo=0x4` | seq `:34–35` / `_check_i2c` |
| IRQ SAMPLE #1 | 286–288 | sync/gpio/uart = 0 | seq `:36–37` / `_check_irq` |
| GPIO SAMPLE #1 | 289–291 | aggregates `1/1/1` (resolvable) | seq `:38–39` / `_check_gpio` |
| AXIL SAMPLE #1 | 292–294 | `any=0` idle | seq `:40–41` / `_check_axil` |
| COUNT_EDGES | 297–299 | `ref=25 smc=33 periph=24` | seq `:42–43` / `_check_clk` |
| cocotb result | 302–308 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | — |

</details>

## Not concluded

- Whether one idle six-agent SAMPLE/COUNT_EDGES sweep proves the SPEC properties a future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
