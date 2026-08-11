---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_gpio_multi_sample_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094544__verilator__smc_gpio_multi_sample_test/smc_gpio_multi_sample_test/logs/smc_gpio_multi_sample_test.log
  sha256: ba38124dd3177ffeb352a9e04dd0cdca2947f1e02f3507378f9edf1b01768737
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
  severity: Minor
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_gpio_multi_sample_test_seq.py:19-28
  observed: >-
    Sequence body appends each completed SAMPLE into `self.samples`, but nothing
    reads the list, compares samples across the 80-cycle gaps, or asserts
    stability of `core2pad_any` / `core2pad_en_any` / `pad2core_en_any`. The live
    fail path is only the scoreboard per-sample `resolvable` plus `in (0, 1)`
    range guards. The list therefore stores evidence that is never checked and
    resembles an unfinished cross-sample compare.
  closure_condition: >-
    Either assert on the collected samples (e.g. length == 3 and any
    cross-sample equality a future card requires) or drop the unused list so the
    sequence body matches the scoreboard's actual per-sample resolvability check.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_gpio_multi_sample_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🟡 1 Minor | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect** in the test by itself.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `b5daea41…`)

| Item | Prior (log `b5daea41…`, PASS) | This audit (log `ba38124d…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🟡 1 Minor | 🟡 1 Minor |
| FIND-001 `[NO-DUMMY-DEAD-CODE]` | open — unused `self.samples` | still open — seq sha256 `53849549…` unchanged; list still append-only |
| Kept log | `b5daea410959b459cf0d50784577c1bda26cb2499569d0ba2907f570114b5d7a` | `ba38124dd3177ffeb352a9e04dd0cdca2947f1e02f3507378f9edf1b01768737` |
| Repo / model | `2ecc7b22…` / `2c815fa08277` | `c10b6d63…` / `2c815fa08277` |
| Waivers carried | none signed (`waivers: []`) | none (nothing to drop; no signed entries) |

## Your to-do — 1 items (🟡 1 Minor)

| # | Kind | Id | Severity / grade | Where |
|---|---|---|---|---|
| 1 | finding | FIND-001 | 🟡 Minor | `smc_gpio_multi_sample_test_seq.py:19-28` |

<details>
<summary>1. FIND-001 — 🟡 Minor <code>[NO-DUMMY-DEAD-CODE]</code> — unused <code>self.samples</code> looks like a stability compare</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_gpio_multi_sample_test_seq.py:19-28`
- **Observed:** Three SAMPLE items are appended to `self.samples`; neither the list nor cross-sample field equality is asserted. Scoreboard only fails on unresolvable pins or out-of-range aggregate bits (log: three samples `resolvable=True`, aggregates `(1,1,1)`).
- **Closure:** Wire a real compare on the collected samples, or remove the dead list and keep only the per-sample scoreboard path.

</details>

**Then:** owner may leave this as enrolled smoke under STANDALONE-REQUEST, or allocate a real IP pin + card via `/dv_vplan_gen` before any closure claim; re-invoke `/dv_test_audit smc_gpio_multi_sample_test` after FIND-001 hygiene if fixed.

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — passive top-level SAMPLE of `tb_gpio_*_any`; no Force/deposit on proof path |
| F2 can't-fail checker | ✅ clean — scoreboard `assert item.resolvable` fails on X; `in (0, 1)` guards fail on out-of-range |
| E1 skip-to-pass | ✅ clean — unsupported op raises; no missing-path skip-to-pass |
| E2 empty phase | ✅ clean — body dispatches three SAMPLE items with 80-cycle gaps |
| S1 silent fail | ✅ clean — scoreboard asserts raise; `check_phase` fails if zero SAMPLE items |
| O1 checker disabled | ✅ clean — GPIO analysis path active (log sample #1–#3) |
| Phase-S obligations — L1 | 🟡 Minor — FIND-001; else X-aware `resolvable`, seed logged, enrolled in `gpio.toml`/`all.toml`, `ClockCycles` gaps are stimulus spacing (not handshake substitutes), ROM/efuse preload is post-PASS bring-up trailer; aggregate values intentionally not golden-locked (agent/scoreboard document OR-of-pad bus) |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_gpio_multi_sample_test.py`
  sha256 `0a7207ff776a241d37d1f694cabaec45ffb186d8ec5a752fbb62b3275493fe45`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_gpio_multi_sample_test_seq.py`
  sha256 `538495491a478f6d261a896b2dfa883acddce158a94e74bf90429925a4d39012`
- Agent / scoreboard (proof path): `smc_gpio_agent.py` (`24ee9592…`) → `SmcScoreboard._check_gpio` (`d0508fd1…`)
- Log: `hw/sys/smc/dv/build/runs/20260806_094544__verilator__smc_gpio_multi_sample_test/smc_gpio_multi_sample_test/logs/smc_gpio_multi_sample_test.log`
  sha256 `ba38124dd3177ffeb352a9e04dd0cdca2947f1e02f3507378f9edf1b01768737` (matches claimed)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `return_code: 0`, cocotb summary: `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Stimulus: 3× `SmcGpioOp.SAMPLE` separated by `GAP_REF_CYCLES=80` on `clk_ref_i`
- Observed in log: GPIO SAMPLE #1–#3 at 4152 / 4792 / 5432 ns, each `resolvable=True`, aggregates `(1,1,1)`; `FUNC_COV_VALUE bin=gpio_state value=(1, 1, 1)` ×3
- Fail path (static): non-resolvable pins → AssertionError; no `CHK-*` tokens (none required without a card)
- Enrollment: `hw/sys/smc/dv/testlists/gpio.toml`, `all.toml`
- Bring-up trailer: efuse/ROM hex preload lines after cocotb PASS; not used by pin-sample proof path
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`)
- Auditor: `cursor/grok/4.5-reaudit-20260806` (re-audit; prior auditor `cursor/grok/4.5`)

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>ba38124d…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| bring-up | 257–267 | clocks + powergood + cold release | `smc_base_test` |
| SAMPLE #1 | 280–282 | aggregates `(1,1,1)`, scoreboard #1 | seq loop `i=0` / `_check_gpio` |
| gap 80 ref cycles | 283 | next sample at +640 ns (80×8 ns) | `ClockCycles(..., 80)` |
| SAMPLE #2 | 283–285 | same aggregates `(1,1,1)` | seq `i=1` |
| SAMPLE #3 | 286–288 | same values; PASS follows | seq `i=2` |
| cocotb result | 291–297 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | — |

</details>

## Not concluded

- Whether three idle GPIO OR-aggregate observation samples prove the SPEC properties a future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
