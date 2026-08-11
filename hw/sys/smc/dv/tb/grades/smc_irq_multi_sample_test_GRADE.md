---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_irq_multi_sample_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094544__verilator__smc_irq_multi_sample_test/smc_irq_multi_sample_test/logs/smc_irq_multi_sample_test.log
  sha256: da00b26175f0ac66ad1526841ed8cfb4da25d243319b9dcac1e4092d0bc493e3
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
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_irq_multi_sample_test_seq.py:19-28
  observed: >-
    Sequence body appends each completed SAMPLE into `self.samples`, but nothing
    reads `self.samples`, compares samples, or asserts cross-sample equality of
    `sync_irq` / `gpio_irq_any` / `uart_irq_any`. The live fail path is only
    scoreboard per-sample `resolvable` plus idle-zero on the three IRQ
    aggregates. The list therefore stores evidence that is never checked and
    resembles an unfinished cross-sample stability compare.
  closure_condition: >-
    Either assert on the collected samples (e.g. length == 3 and cross-sample
    equality for fields a future card requires) or drop the unused list.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_irq_multi_sample_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🟡 1 Minor | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect** in the test by itself.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `097fcf14…`)

| Item | Prior (log `097fcf14…`, PASS) | This audit (log `da00b261…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🟡 1 Minor | 🟡 1 Minor |
| FIND-001 `[NO-DUMMY-DEAD-CODE]` | open — unused `self.samples` | still open — seq sha256 unchanged; list still append-only |
| Kept log | `097fcf14f30e864056d398ce684f336cfdf9f339501675361b032ac23e9c85bf` | `da00b26175f0ac66ad1526841ed8cfb4da25d243319b9dcac1e4092d0bc493e3` |
| Repo rev | `2ecc7b227e3926b253c65b5aac21239eec24ba5f` | `c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7` |
| Waivers carried | none signed (`waivers: []`) | none (nothing to drop; no signed entries) |

## Your to-do — 1 items (🟡 1 Minor)

| # | Kind | Id | Severity / grade | Where |
|---|---|---|---|---|
| 1 | finding | FIND-001 | 🟡 Minor | `smc_irq_multi_sample_test_seq.py:19-28` |

<details>
<summary>1. FIND-001 — 🟡 Minor <code>[NO-DUMMY-DEAD-CODE]</code> — unused <code>self.samples</code> looks like a stability compare</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_irq_multi_sample_test_seq.py:19-28`
- **Observed:** Three SAMPLE items are appended to `self.samples`; neither the list nor a cross-sample compare is asserted. Scoreboard only fails on unresolvable samples or non-zero idle IRQ aggregates (log: three samples `sync=0`, `gpio_any=0`, `uart_any=0`).
- **Closure:** Wire a real compare on the collected samples, or remove the dead list.

</details>

**Then:** owner may leave this as enrolled smoke under STANDALONE-REQUEST, or allocate a real IP pin + card via `/dv_vplan_gen` before any closure claim; re-invoke `/dv_test_audit smc_irq_multi_sample_test` after FIND-001 hygiene if fixed.

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — passive top-level SAMPLE of `tb_sync_irq` / `tb_gpio_irq_any` / `tb_uart_irq_any`; no Force/deposit on proof path |
| F2 can't-fail checker | ✅ clean — scoreboard `assert item.resolvable` and idle-zero asserts on `sync_irq` / `gpio_irq_any` / `uart_irq_any` can fail on X or non-idle IRQ |
| E1 skip-to-pass | ✅ clean — unsupported op raises; no missing-path skip-to-pass |
| E2 empty phase | ✅ clean — body dispatches three SAMPLE items with 100-cycle gaps |
| S1 silent fail | ✅ clean — scoreboard asserts raise; `check_phase` fails if zero SAMPLE items |
| O1 checker disabled | ✅ clean — IRQ analysis path active (log sample #1–#3) |
| Phase-S obligations — L1 | 🟡 Minor — FIND-001; else X-aware `resolvable`, seed logged, enrolled in `irq.toml`/`all.toml`, `ClockCycles` gaps are stimulus spacing (not handshake substitutes), ROM/efuse preload is post-PASS bring-up trailer |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_irq_multi_sample_test.py`
  sha256 `9c1a77de80ce72068f8fe625db4021fbab50c53bb3ec8cff2f0548f876b2bbc0`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_irq_multi_sample_test_seq.py`
  sha256 `ab1c9f798b6fbaca5e3a91ae87fcac75f43190d4029972af3e0d608d688c2261`
- Agent / scoreboard (proof path): `smc_irq_agent.py` → `SmcScoreboard._check_irq`
- Log: `hw/sys/smc/dv/build/runs/20260806_094544__verilator__smc_irq_multi_sample_test/smc_irq_multi_sample_test/logs/smc_irq_multi_sample_test.log`
  sha256 `da00b26175f0ac66ad1526841ed8cfb4da25d243319b9dcac1e4092d0bc493e3` (matches claimed)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `return_code: 0`, cocotb summary: `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Stimulus: 3× `SmcIrqOp.SAMPLE` separated by `GAP_REF_CYCLES=100` on `clk_ref_i`
- Observed in log: IRQ SAMPLE #1–#3 at 4152 / 4952 / 5752 ns, each `resolvable=True`, `sync=0`, `gpio_any=0`, `uart_any=0`; `FUNC_COV_VALUE bin=irq_state value=(0, 0, 0)` ×3
- Fail path (static): non-resolvable pins or any idle IRQ aggregate != 0 → AssertionError; no `CHK-*` tokens (none required without a card)
- Enrollment: `hw/sys/smc/dv/testlists/irq.toml`, `all.toml`
- Bring-up trailer: efuse/ROM hex preload lines after cocotb PASS; not used by pin-sample proof path
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`)

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>da00b261…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| bring-up | 267–268 | clocks + powergood + cold release | `smc_base_test` |
| SAMPLE #1 | 280–282 | `sync=0`, `gpio_any=0`, `uart_any=0`, scoreboard #1 | seq loop `i=0` / `_check_irq` |
| gap 100 ref cycles | 283 | next sample at +800 ns (100×8 ns) | `ClockCycles(..., 100)` |
| SAMPLE #2 | 283–285 | same idle-zero IRQ aggregates | seq `i=1` |
| SAMPLE #3 | 286–288 | same values; PASS follows | seq `i=2` |
| cocotb result | 291–297 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | — |

</details>

## Not concluded

- Whether three idle IRQ observation samples prove the SPEC properties a future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
