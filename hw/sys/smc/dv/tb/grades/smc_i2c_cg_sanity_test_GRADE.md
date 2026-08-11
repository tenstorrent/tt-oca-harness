---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_i2c_cg_sanity_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094529__verilator__smc_i2c_cg_sanity_test/smc_i2c_cg_sanity_test/logs/smc_i2c_cg_sanity_test.log
  sha256: e9545dae79d4c873cd01a62218f295fe620962d38b2c2ba34cabe76d76fab571
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
  artifact_ref: hw/sys/smc/dv/cocotb/env/smc_scoreboard.py:78-84
  observed: >
    SmcI2cDriver always samples `tb_i2c_debug_lo` into `item.debug_lo` (kept log
    L280–L281 shows `debug_lo=0x4` on the scoreboard sample line), but `_check_i2c`
    only asserts `resolvable` and `cg_en == 0`. The debug nibble is never compared
    to any expectation on this proof path; the logged item string makes it look
    like part of the checked sample.
  closure_condition: >
    Either assert an independently derived expectation on `debug_lo` after SAMPLE,
    or stop sampling/logging it on this agent's SAMPLE path so the scoreboard line
    only carries fields that are actually FAIL-ON checked.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_i2c_cg_sanity_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🟡 1 Minor | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase. Layer 1 findings
> are the entire scope of this report. `NOT-READY` records the **absence of a closure
> claim, not a defect**. Kept log is a sim PASS (seed 1); Layer 2 was not entered.

## DELTA (re-audit vs prior grade)

| Item | Prior (`2a7b71964df7`, log `cc0f8247…`) | This audit (`cursor/grok/4.5-reaudit-20260806`, log `e9545dae…`) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| `no_contract_reason` | STANDALONE-REQUEST | STANDALONE-REQUEST |
| Repository | `2ecc7b227e39…` | `c10b6d63e0b3…` |
| Findings | 🟡 1 Minor (FIND-001) | 🟡 1 Minor (FIND-001) — still open |
| FIND-001 `[NO-DUMMY-DEAD-CODE]` | open — `debug_lo` sampled/logged, never value-checked | open — unchanged on `_check_i2c` (`smc_scoreboard.py:78-84`); new log L280–L281 still shows `debug_lo=0x4` |
| Waivers carried | none signed (`approved_by` null / empty) | none — dropped nothing; nothing to carry |
| Kept log | `cc0f824796c850665fcc2fc45ccebb8635cbaad601151a0e3e3d2eb278eb431c` | `e9545dae79d4c873cd01a62218f295fe620962d38b2c2ba34cabe76d76fab571` (sha256sum verified) |

## Your to-do — 1 item (🟡 1 Minor)

| # | Sev | Item |
|---|---|---|
| 1 | 🟡 Minor | FIND-001 `[NO-DUMMY-DEAD-CODE]` — `debug_lo` sampled/logged, never checked |

<details>
<summary>1. 🟡 Minor — FIND-001 `[NO-DUMMY-DEAD-CODE]` at scoreboard `_check_i2c`</summary>

Driver fills `item.debug_lo` from `tb_i2c_debug_lo` and the scoreboard logs the full item
(`debug_lo=0x4` in kept log L281), but the only FAIL-ON compares are `resolvable` and
`cg_en == 0`.

**Close when:** add a real expectation for `debug_lo`, or drop it from the SAMPLE/log path
so unchecked fields do not appear as scoreboard evidence.

</details>

**Then:** owner may remediate FIND-001 for hygiene, or leave enrolled smoke under
`STANDALONE-REQUEST`; allocate a real IP pin + card via `/dv_vplan_gen` before any closure
claim. Re-invoke `/dv_test_audit smc_i2c_cg_sanity_test` after changes. Do not invent a card
here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — passive reads of `tb_i2c_cg_en` / `tb_i2c_debug_lo` only; no force/deposit on proof path |
| F2 can't-fail checker | ✅ clean — `assert item.resolvable` and `assert item.cg_en == 0` can fail on X/Z or non-zero enable; `check_phase` fails if zero SAMPLE items |
| E1 skip-to-pass | ✅ clean — missing HDL handles raise; no skip-to-pass branch |
| E2 empty phase | ✅ clean — one SAMPLE dispatched, scoreboard asserts, check_phase requires activity |
| S1 silent fail | ✅ clean — scoreboard mismatches raise `AssertionError` |
| O1 checker disabled | ✅ clean — i2c analysis port connected; log shows Scoreboard I2C sample #1 |
| Phase-S obligations — L1 | 🟡 Minor — FIND-001; else X-aware `resolvable`, force-free, enrolled in `i2c.toml` / `all.toml`, seed logged, no blind-delay sync on this path |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Log: `hw/sys/smc/dv/build/runs/20260806_094529__verilator__smc_i2c_cg_sanity_test/smc_i2c_cg_sanity_test/logs/smc_i2c_cg_sanity_test.log`
  sha256 `e9545dae79d4c873cd01a62218f295fe620962d38b2c2ba34cabe76d76fab571`
  (verified via `sha256sum`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `return_code: 0`, cocotb summary L291:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Test: `hw/sys/smc/dv/cocotb/tests/smc_i2c_cg_sanity_test.py` →
  `smc_i2c_cg_sanity_test_seq` on default `i2c_agent.sequencer` after `smc_base_test` bring-up
- Seq: one `SmcI2cOp.SAMPLE` (`smc_i2c_cg_sanity_test_seq.py:23-28`)
- Driver: `smc_i2c_agent.py:43-51` samples `tb_i2c_cg_en` / `tb_i2c_debug_lo`
- Scoreboard: `smc_scoreboard.py:78-84` asserts resolvable + `cg_en == 0`; `check_phase`
  requires `total > 0`
- TB ports: `tb_top.sv` assigns `tb_i2c_cg_en = u_dut.u_smc.cg_ctrl_i2c_cg_en`,
  `tb_i2c_debug_lo = u_dut.u_smc.i2c_debug[0]`
- Kept-log cites: SAMPLE L280 (`cg_en=0, debug_lo=0x4`); scoreboard L281–L282;
  PASS L285–L291
- Enrollment: `hw/sys/smc/dv/testlists/i2c.toml`, `all.toml`
- Bring-up trailer: efuse hex + ROM `$readmemh` — time-0 image load; not used as golden
  for these pin samples (policy §6 standing preload; off this proof path)
- No unexplained `ERROR`/`FATAL`/`Traceback`; only cocotb/library `DeprecationWarning`s
- Provenance: legacy (`test_author.run_id: unknown`)
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)

</details>

## Not concluded

- Whether post-reset `cg_en==0` observability matches SPEC I2C clock-gating properties (O2) —
  Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
