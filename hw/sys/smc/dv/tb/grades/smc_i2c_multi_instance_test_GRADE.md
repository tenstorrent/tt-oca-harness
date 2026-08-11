---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_i2c_multi_instance_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094635__verilator__smc_i2c_multi_instance_test/smc_i2c_multi_instance_test/logs/smc_i2c_multi_instance_test.log
  sha256: 29d0f2da97471d52f7ef7208b75544f55ed962a9e07843b6d997f8ce2ecaed6c
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
findings: []
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_i2c_multi_instance_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | none | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect** in the test by itself. Kept log is a sim **PASS** (seed 1, verilator 5.050):
> three frontdoor SEP_IN SYS AXI CSR reads at PeakRDL I2C_1 / I2C_2 INTR_STATE and
> I2C_CTRL completed OKAY with scoreboard `rdata == 0` — Layer 2 entry is still not
> evaluated in this mode.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `b32b48b3…`)

| Item | Prior (log `b32b48b3…`, FAIL) | This audit (log `29d0f2da…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🔴 1 Blocking | none |
| Prior FIND-001 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` | open Blocking — hand `0xC0009200/9400/9E00` (false identity / unmapped; sim FAIL on #2) | **closed** — `I2C_INSTANCE_READS` uses `smc_indexed_addr` PeakRDL symbols; kept log hits `0xc0005200` / `5400` / `5e00` OKAY + reset-0 |
| Kept log | `b32b48b37900245926063c55c34387cfef1b4114e0183b0d28a0cf6165100a77` (FAIL) | `29d0f2da97471d52f7ef7208b75544f55ed962a9e07843b6d997f8ce2ecaed6c` (PASS) |
| Repo rev | `2ecc7b227e3926b253c65b5aac21239eec24ba5f` | `c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7` |
| Waivers carried | none signed (`waivers: []`) | none (nothing to drop; no signed entries) |

## Your to-do — 0 items (none)

| # | Sev | Item |
|---|---|---|
| — | — | none open |

**Then:** leave enrolled under `STANDALONE-REQUEST`, or allocate a real IP pin + card via
`/dv_vplan_gen` before any closure claim. Re-invoke `/dv_test_audit` only after material
test/log changes. Do not invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN SYS AXI via `SmcSysAxiItem` / `SmcCsrSeq.csr_read`; no force/deposit on CSR proof path; scoreboard compares DUT `rdata`/`resp_ok`; ROM/efuse preload is post-PASS trailer not CSR golden |
| F2 can't-fail checker | ✅ clean — scoreboard `resp_ok` / `got == exp` and final `assert self.accesses == len(I2C_INSTANCE_READS)` are reachable FAIL-ON paths; prior wrong-address FAIL proved `resp_ok` sensitivity |
| E1 skip-to-pass | ✅ clean — strict `csr_read` (no `allow_timeout` / skip-on-missing-handle); sequence issues three real AXI reads |
| E2 empty phase | ✅ clean — body issues three CSR reads; scoreboard SYS AXI checks #1–#3 present |
| S1 silent fail | ✅ clean — non-OKAY / value mismatch / unexpected timeout raise `AssertionError` in scoreboard/driver; no swallow-to-pass |
| O1 checker disabled | ✅ clean — SYS AXI scoreboard path active (checks #1–#3); AXI monitor OKAY=3; protocol VIP `passed` is a non-asserted completion marker only |
| Phase-S obligations — L1 | ✅ clean — addresses from `smc_addr_map.smc_indexed_addr` / PeakRDL `smc_addr.h`; exact expected `0x0` on every read (matches `I2C_INTR_STATE_REG_DEFAULT` / `I2C_CTRL_I2C_CTRL_REG_DEFAULT`); timeouts fail; seed logged; enrolled in `p1_coverage_gap.toml`; no unconditional CHK token; ROM/efuse preload is post-PASS bring-up trailer not CSR golden |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_i2c_multi_instance_test.py`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_i2c_multi_instance_test_seq.py`
- CSR helper: `hw/sys/smc/dv/cocotb/seq_lib/smc_csr_seq_utils.py` `SmcCsrSeq.csr_read`
- Scoreboard (proof path): `hw/sys/smc/dv/cocotb/env/smc_scoreboard.py` `_check_sys_axi`
- Authoritative map: `hw/sys/smc/regs/gen/c/smc_addr.h` via `smc_addr_map.smc_indexed_addr` —
  `SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR(1)=0xC0005200`,
  `(2)=0xC0005400`,
  `SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR(0)=0xC0005E00`
- Log: `hw/sys/smc/dv/build/runs/20260806_094635__verilator__smc_i2c_multi_instance_test/smc_i2c_multi_instance_test/logs/smc_i2c_multi_instance_test.log`
  sha256 `29d0f2da97471d52f7ef7208b75544f55ed962a9e07843b6d997f8ce2ecaed6c`
  (verified via `manifest.py hash-file` / `sha256sum`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary L318–L320:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Final assertion gate: seq `assert self.accesses == len(I2C_INSTANCE_READS)` (3) reached;
  value proof is SYS AXI scoreboard `got == exp` on every read (3/3 logged)
- AXI monitor: `3 R beats, 0 B resps; R-resp tally OKAY=3; 0 errors`
- Address / value cites (kept log):
  - I2C_1_BASE `0xc0005200` → `0x0` exp match (L280–L293)
  - I2C_2_BASE `0xc0005400` → `0x0` exp match (L295–L300)
  - I2C_CTRL `0xc0005e00` → `0x0` exp match (L302–L307)
- Enrollment: `hw/sys/smc/dv/testlists/p1_coverage_gap.toml`
- Bring-up trailer (post-PASS flush): efuse hex + ROM `$readmemh` — time-0 image load;
  not used as CSR golden on this proof path (policy §6 standing preload)
- No unexplained `ERROR`/`FATAL`/`Traceback` in the kept log
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`); auditor
  `run_id: cursor/grok/4.5-reaudit-20260806`

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>29d0f2da…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| I2C_1_BASE RD | 280–293 | read `0xc0005200` OKAY `rdata=0x0` scoreboard #1 ok | seq `smc_indexed_addr(...INTR_STATE..., 1)` |
| I2C_2_BASE RD | 295–300 | read `0xc0005400` OKAY `rdata=0x0` scoreboard #2 ok | seq `…INTR_STATE…, 2` |
| I2C_CTRL RD | 302–307 | read `0xc0005e00` OKAY `rdata=0x0` scoreboard #3 ok | seq `…I2C_CTRL…, 0` |
| VIP / monitor | 309–312 | `csr_accesses=3` · `OKAY=3` | test + monitor |
| cocotb result | 314–320 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | — |

</details>

## Not concluded

- Whether a corrected I2C multi-instance CSR sweep proves the SPEC properties (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
