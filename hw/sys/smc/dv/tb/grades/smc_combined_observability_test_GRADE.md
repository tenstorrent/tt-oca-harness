---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_combined_observability_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094547__verilator__smc_combined_observability_test/smc_combined_observability_test/logs/smc_combined_observability_test.log
  sha256: c77a6bc6d5e2dad22f1ae29967003b0a4fd8a1c603bfdb593f02209fd8e9d403
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
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_combined_observability_test_seq.py:27-47
  observed: >-
    Sequence body stores completed SAMPLE items into `self.reset_sample` and
    `self.i2c_sample`, but nothing reads those fields or compares them. The live
    fail path is only the scoreboard analysis path (`_check_reset` /
    `_check_i2c`). Kept-log scoreboard lines also show `rst_wdt_smc=1` and
    `debug_lo=0x4`, yet neither field is FAIL-ON asserted (reset checks four
    other rails; I2C checks only `resolvable` and `cg_en == 0`). The stored
    handles and logged extra fields therefore look like unfinished dual-agent
    evidence that is never checked in-sequence.
  closure_condition: >-
    Either assert on the stored samples (and any fields a future card requires,
    including `debug_lo` / `rst_wdt_smc_clk_n` if claimed) or drop the unused
    sequence fields and stop presenting unchecked fields as scoreboard evidence.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_combined_observability_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🟡 1 Minor | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect** in the test by itself.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `17567cc4…`)

| Item | Prior (log `17567cc4…`, PASS) | This audit (log `c77a6bc6…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🟡 1 Minor | 🟡 1 Minor |
| FIND-001 `[NO-DUMMY-DEAD-CODE]` | open — unused `reset_sample` / `i2c_sample` + unchecked logged fields | still open — seq sha256 unchanged (`15c53fb9…`); same dead stores |
| Kept log | `17567cc4834dcda469d8125f2d3d77ef7cb1331545641206a2e9fe76c4dc3f44` | `c77a6bc6d5e2dad22f1ae29967003b0a4fd8a1c603bfdb593f02209fd8e9d403` |
| repository_revision | `2ecc7b22…` | `c10b6d63…` |
| auditor.run_id | `dv_test_audit-SMC_COMBINED_OBS-20260806-4b9963772986` | `cursor/grok/4.5-reaudit-20260806` |
| Waivers carried | none signed (`waivers: []`) | none (nothing to drop; no signed entries) |

## Your to-do — 1 items (🟡 1 Minor)

| # | Kind | Id | Severity / grade | Where |
|---|---|---|---|---|
| 1 | finding | FIND-001 | 🟡 Minor | `smc_combined_observability_test_seq.py:27-47` |

<details>
<summary>1. FIND-001 — 🟡 Minor <code>[NO-DUMMY-DEAD-CODE]</code> — unused sample fields look like dual-agent evidence</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_combined_observability_test_seq.py:27-47`
- **Observed:** `self.reset_sample` / `self.i2c_sample` are assigned after dispatch and never read. Scoreboard only fails on unresolvable samples, reset rails ≠ 1, or `cg_en != 0` (log: reset sample rails all 1 including unchecked `rst_wdt_smc=1`; I2C `cg_en=0`, `debug_lo=0x4` unchecked).
- **Closure:** Wire real compares on the stored samples / claimed fields, or remove the dead handles and align logged evidence with FAIL-ON checks.

</details>

**Then:** owner may leave this as enrolled smoke under STANDALONE-REQUEST, or allocate a real IP pin + card via `/dv_vplan_gen` before any closure claim; re-invoke `/dv_test_audit smc_combined_observability_test` after FIND-001 hygiene if fixed.

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — passive top-level SAMPLE of reset status outs + `tb_i2c_cg_en` / `tb_i2c_debug_lo`; no Force/deposit on proof path |
| F2 can't-fail checker | ✅ clean — scoreboard `assert item.resolvable` and reset-rail / `cg_en == 0` asserts can fail on X or wrong levels |
| E1 skip-to-pass | ✅ clean — unsupported op raises; missing dispatch hooks throw; no missing-path skip-to-pass |
| E2 empty phase | ✅ clean — body dispatches one reset SAMPLE then one I2C SAMPLE with a 50-cycle gap |
| S1 silent fail | ✅ clean — scoreboard asserts raise; `check_phase` fails if zero SAMPLE items |
| O1 checker disabled | ✅ clean — reset + I2C analysis paths active (log reset sample #1 and I2C sample #1) |
| Phase-S obligations — L1 | 🟡 Minor — FIND-001; else X-aware `resolvable`, seed logged, enrolled in `combined.toml`/`all.toml`, `ClockCycles` gap is stimulus spacing (not a handshake substitute), ROM/efuse preload is post-PASS bring-up trailer |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_combined_observability_test.py`
  sha256 `4a3c347b06d8d2e2b644ed54777e52184eeccdc48d4afac47007d24e830da95f`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_combined_observability_test_seq.py`
  sha256 `15c53fb9249b7ef29947e0c99ecc462eb1e157f33602878d9dea9763918d95f2`
- Agent / scoreboard (proof path): `smc_reset_agent.py` + `smc_i2c_agent.py` → `SmcScoreboard._check_reset` / `_check_i2c`
  (scoreboard sha256 `d0508fd1e52db630eb7b85de60872460d8bf969ae4fcb67cd5a172bd85a15495`)
- Log: `hw/sys/smc/dv/build/runs/20260806_094547__verilator__smc_combined_observability_test/smc_combined_observability_test/logs/smc_combined_observability_test.log`
  sha256 `c77a6bc6d5e2dad22f1ae29967003b0a4fd8a1c603bfdb593f02209fd8e9d403` (matches claimed)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `return_code: 0`, cocotb summary: `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Stimulus: 1× `SmcResetOp.SAMPLE` then `GAP_REF_CYCLES=50` then 1× `SmcI2cOp.SAMPLE` via dual one-shot dispatchers
- Observed in log: reset SAMPLE at 4152 ns (`resolvable=True`, rails 1); I2C SAMPLE at 4552 ns (`cg_en=0`, `debug_lo=0x4`); `FUNC_COV_VALUE bin=reset_op/reset_state` then `i2c_state`
- Fail path (static): non-resolvable pins, reset rails ≠ 1, or `cg_en != 0` → AssertionError; no `CHK-*` tokens (none required without a card)
- Enrollment: `hw/sys/smc/dv/testlists/combined.toml`, `all.toml`
- Bring-up trailer: efuse/ROM hex preload lines after cocotb PASS; not used by pin-sample proof path
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`)

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>c77a6bc6…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| bring-up | 256–266 | clocks + powergood + cold release | `smc_base_test` |
| reset SAMPLE | 279–282 | rails all 1; scoreboard reset #1 | seq + `_check_reset` |
| gap 50 ref cycles | 283 | I2C sample at +400 ns (50×8 ns) | `ClockCycles(..., 50)` |
| I2C SAMPLE | 283–285 | `cg_en=0`, `debug_lo=0x4`; scoreboard I2C #1 | seq + `_check_i2c` |
| cocotb result | 288–294 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | — |

</details>

## Not concluded

- Whether one reset SAMPLE plus one I2C SAMPLE prove the SPEC properties a future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
