---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_irq_observe_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094544__verilator__smc_irq_observe_test/smc_irq_observe_test/logs/smc_irq_observe_test.log
  sha256: 635613a4daccb5c355eb48ad832ca2cff0f1b4766b1afee8fda9f92cc777904a
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
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_irq_observe_test_seq.py:15-29
  observed: >
    Sequence stores the completed SAMPLE in `self.sample`, but nothing reads
    `self.sample` or asserts on it. The live fail paths are `assert item.resolvable`
    in the sequence body and scoreboard idle-zero asserts on
    `sync_irq` / `gpio_irq_any` / `uart_irq_any`. The field therefore stores
    evidence that is never checked and resembles an unfinished post-SAMPLE compare.
  closure_condition: >
    Drop unused `self.sample`, or assert on the stored item (fields a future card
    requires) so the storage participates in a fail-capable check.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_irq_observe_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🟡 1 Minor | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase. Layer 1 findings
> are the entire scope of this report. `NOT-READY` records the **absence of a closure
> claim, not a defect**. Kept log is a sim PASS (seed 1); Layer 2 was not entered.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `450daa21…`)

| Prior id | Tag / grade | Status this round | Notes |
|---|---|---|---|
| (none) | findings: [] | — | Prior round reported zero findings |
| FIND-001 | 🟡 `[NO-DUMMY-DEAD-CODE]` | NEW | Unused `self.sample` on seq proof path (same class as `smc_irq_multi_sample` FIND-001) |
| waivers: [] | — | unchanged | Prior ledger empty; no signed `approved_by` to carry; none dropped |
| Kept log | `450daa21…` | replaced | `635613a4…` (seed=1 PASS; model `2c815fa08277`) |
| repository_revision | `2ecc7b22…` | updated | `c10b6d63…` |

## Your to-do — 1 items (🟡 1 Minor)

| # | Sev | Item |
|---|---|---|
| 1 | 🟡 Minor | FIND-001 `[NO-DUMMY-DEAD-CODE]` — unused `self.sample` |

<details>
<summary>1. 🟡 Minor — FIND-001 `[NO-DUMMY-DEAD-CODE]` at seq `self.sample`</summary>

Sequence assigns `self.sample = item` after SAMPLE and never reads it. Fail paths are
`assert item.resolvable` plus scoreboard idle-zero checks on the analysis port; the stored
field does not participate.

**Close when:** drop `self.sample`, or assert on the stored item so storage is on a
fail-capable path.

</details>

**Then:** owner may drop/wire `self.sample`, leave enrolled under `STANDALONE-REQUEST`, or
allocate a real IP pin + card via `/dv_vplan_gen` before any closure claim. Re-invoke
`/dv_test_audit smc_irq_observe_test` after material test/log changes. Do not invent a card
here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — passive SAMPLE of `tb_sync_irq` / `tb_gpio_irq_any` / `tb_uart_irq_any` (DUT wrapper outputs / OR-reductions); no force/deposit on proof path |
| F2 can't-fail checker | ✅ clean — scoreboard `assert item.resolvable` and idle `sync_irq` / `gpio_irq_any` / `uart_irq_any` `== 0` can fail on X/Z or spuriously asserted IRQ; `check_phase` fails if zero SAMPLE items |
| E1 skip-to-pass | ✅ clean — unsupported `SmcIrqOp` raises; missing HDL handles raise; no skip-to-pass branch |
| E2 empty phase | ✅ clean — S2 dispatches one SAMPLE + scoreboard asserts; S1 is SETUP restatement of base bring-up only |
| S1 silent fail | ✅ clean — scoreboard / seq resolvable mismatches raise `AssertionError` |
| O1 checker disabled | ✅ clean — `irq_agent.ap` connected to scoreboard; log shows Scoreboard IRQ sample #1 |
| Phase-S obligations — L1 | 🟡 Minor — FIND-001; else X-aware `resolvable`; force-free pin observe; CHK-NONVAC after assert; seed logged; enrolled in `irq.toml` / `all.toml`; no blind-delay sync on this path |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Log: `hw/sys/smc/dv/build/runs/20260806_094544__verilator__smc_irq_observe_test/smc_irq_observe_test/logs/smc_irq_observe_test.log`
  sha256 `635613a4daccb5c355eb48ad832ca2cff0f1b4766b1afee8fda9f92cc777904a`
  (verified via `sha256sum`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `return_code: 0`, cocotb summary L294:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Test: `hw/sys/smc/dv/cocotb/tests/smc_irq_observe_test.py` starts
  `smc_irq_observe_test_seq` on `irq_agent.sequencer` after `smc_base_test` bring-up
- Seq: one `SmcIrqOp.SAMPLE` (`smc_irq_observe_test_seq.py:17-36`); asserts
  `item.resolvable`; emits `CHK-NONVAC` then `SMC_007 scenario PASS`; stores unused
  `self.sample` (FIND-001)
- Driver: `smc_irq_agent.py:42-58` samples `tb_sync_irq` / `tb_gpio_irq_any` /
  `tb_uart_irq_any` with X/Z → `resolvable=False`
- Scoreboard: `smc_scoreboard.py:115-123` asserts resolvable + idle zeros; `check_phase`
  requires `total > 0`
- TB ports: `tb_top.sv` assigns `tb_sync_irq = sync_irq`,
  `tb_gpio_irq_any = |gpio_interrupt`, `tb_uart_irq_any = |uart_interrupt` from
  `smc_wrapper` outputs
- Kept-log cites: SAMPLE L281 (`sync=0, gpio_any=0, uart_any=0`); scoreboard L282–L283;
  CHK-NONVAC L284; scenario PASS L285; cocotb PASS L288–L294
- Enrollment: `hw/sys/smc/dv/testlists/irq.toml`, `all.toml`
- Bring-up trailer: efuse hex + ROM `$readmemh` — time-0 image load; not used as golden
  for these pin samples (policy §6 standing preload; off this proof path)
- No unexplained `ERROR`/`FATAL`/`Traceback`; only cocotb/library `DeprecationWarning`s
  and fuse-sense INFO
- Provenance: legacy (`test_author.run_id: unknown`)
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)

</details>

## Not concluded

- Whether post-reset idle IRQ observability matches SPEC interrupt properties (O2) —
  Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers from
  the passing log.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
