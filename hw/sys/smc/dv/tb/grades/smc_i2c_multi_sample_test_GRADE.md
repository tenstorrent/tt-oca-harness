---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_i2c_multi_sample_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094529__verilator__smc_i2c_multi_sample_test/smc_i2c_multi_sample_test/logs/smc_i2c_multi_sample_test.log
  sha256: adf12c3c870f06764e8167894e94f8b539037e81e266f47f0545023cc5094660
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
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_i2c_multi_sample_test_seq.py:25-34
  observed: >-
    Sequence body appends each completed SAMPLE into `self.samples` and the
    module docstring claims clock-gate enable and `i2c_debug` stay stable over
    the spaced samples, but nothing reads `self.samples`, compares samples, or
    asserts `debug_lo`. The live fail path is only scoreboard per-sample
    `resolvable` + `cg_en == 0`. The list therefore stores evidence that is never
    checked and resembles an unfinished cross-sample stability compare.
  closure_condition: >-
    Either assert on the collected samples (e.g. length == 3 and cross-sample
    equality for fields a future card requires) or drop the unused list and
    narrow the docstring to the scoreboard's actual per-sample `cg_en` check.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_i2c_multi_sample_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🟡 1 Minor | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect** in the test by itself.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `18bf9412…`)

| Item | Prior (log `18bf9412…`, PASS) | This audit (log `adf12c3c…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🟡 1 Minor | 🟡 1 Minor |
| FIND-001 `[NO-DUMMY-DEAD-CODE]` | open — unused `self.samples`; docstring claims enable/`i2c_debug` stability | still open — seq `25-34` and scoreboard `_check_i2c` unchanged; three samples still only assert `resolvable` + `cg_en==0` |
| Kept log | `18bf941253997a4aa09dae2d30b5ab790987eaebbc41c99cff85dc083836750b` | `adf12c3c870f06764e8167894e94f8b539037e81e266f47f0545023cc5094660` |
| Repo / auditor | rev `2ecc7b22…` · run_id `dv_test_audit-SMC_I2C_MULTI_SAMPLE-20260806-a61916779cdb` | rev `c10b6d63…` · run_id `cursor/grok/4.5-reaudit-20260806` |
| Waivers carried | none signed (`waivers: []`) | none (nothing to drop; no signed entries) |

## Your to-do — 1 items (🟡 1 Minor)

| # | Kind | Id | Severity / grade | Where |
|---|---|---|---|---|
| 1 | finding | FIND-001 | 🟡 Minor | `smc_i2c_multi_sample_test_seq.py:25-34` |

<details>
<summary>1. FIND-001 — 🟡 Minor <code>[NO-DUMMY-DEAD-CODE]</code> — unused <code>self.samples</code> looks like a stability compare</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_i2c_multi_sample_test_seq.py:25-34`
- **Observed:** Three SAMPLE items are appended to `self.samples`; docstring mentions enable/`i2c_debug` stability; neither the list nor `debug_lo` is asserted. Scoreboard only fails on unresolvable samples or `cg_en != 0` (log: three samples `cg_en=0`, `debug_lo=0x4`).
- **Closure:** Wire a real compare on the collected samples, or remove the dead list and align prose with the per-sample scoreboard check.

</details>

**Then:** owner may leave this as enrolled smoke under STANDALONE-REQUEST, or allocate a real IP pin + card via `/dv_vplan_gen` before any closure claim; re-invoke `/dv_test_audit smc_i2c_multi_sample_test` after FIND-001 hygiene if fixed.

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — passive top-level SAMPLE of `tb_i2c_cg_en` / `tb_i2c_debug_lo`; no Force/deposit on proof path |
| F2 can't-fail checker | ✅ clean — scoreboard `assert item.resolvable` and `assert item.cg_en == 0` can fail on X or non-zero gate enable |
| E1 skip-to-pass | ✅ clean — unsupported op raises; no missing-path skip-to-pass |
| E2 empty phase | ✅ clean — body dispatches three SAMPLE items with 100-cycle gaps |
| S1 silent fail | ✅ clean — scoreboard asserts raise; `check_phase` fails if zero SAMPLE items |
| O1 checker disabled | ✅ clean — I2C analysis path active (log sample #1–#3) |
| Phase-S obligations — L1 | 🟡 Minor — FIND-001; else X-aware `resolvable`, seed logged, enrolled in `i2c.toml`/`all.toml`, `ClockCycles` gaps are stimulus spacing (not handshake substitutes), ROM/efuse preload is post-PASS bring-up trailer |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_i2c_multi_sample_test.py`
  sha256 `48b5bffc528257a7ac1de75be4206e11aa9dc488603c7da74b4fb1fc11002ff9`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_i2c_multi_sample_test_seq.py`
  sha256 `2ce18344a32b720332177f08fbe7fded6f34b3b63aa81fa469e6078eb8c5dd68`
- Agent / scoreboard (proof path): `smc_i2c_agent.py` → `SmcScoreboard._check_i2c`
- Log: `hw/sys/smc/dv/build/runs/20260806_094529__verilator__smc_i2c_multi_sample_test/smc_i2c_multi_sample_test/logs/smc_i2c_multi_sample_test.log`
  sha256 `adf12c3c870f06764e8167894e94f8b539037e81e266f47f0545023cc5094660` (matches claimed)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `return_code: 0`, cocotb summary: `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Stimulus: 3× `SmcI2cOp.SAMPLE` separated by `GAP_REF_CYCLES=100` on `clk_ref_i`
- Observed in log: I2C SAMPLE #1–#3 at 4152 / 4952 / 5752 ns, each `resolvable=True`, `cg_en=0`, `debug_lo=0x4`; `FUNC_COV_VALUE bin=i2c_state value=(1, 0)` ×3
- Fail path (static): non-resolvable pins or `cg_en != 0` → AssertionError; no `CHK-*` tokens (none required without a card)
- Enrollment: `hw/sys/smc/dv/testlists/i2c.toml`, `all.toml`
- Bring-up trailer: efuse/ROM hex preload lines after cocotb PASS; not used by pin-sample proof path
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`)

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>adf12c3c…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| bring-up | 257–267 | clocks + powergood + cold release | `smc_base_test` |
| SAMPLE #1 | 280–282 | `cg_en=0`, `debug_lo=0x4`, scoreboard #1 | seq loop `i=0` / `_check_i2c` |
| gap 100 ref cycles | 283 | next sample at +800 ns (100×8 ns) | `ClockCycles(..., 100)` |
| SAMPLE #2 | 283–285 | same `cg_en=0` / `debug_lo=0x4` | seq `i=1` |
| SAMPLE #3 | 286–288 | same values; PASS follows | seq `i=2` |
| cocotb result | 291–297 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | — |

</details>

## Not concluded

- Whether three idle I2C observation samples prove the SPEC properties a future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
