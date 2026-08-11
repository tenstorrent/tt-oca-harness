---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_filter_multi_entry_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094641__verilator__smc_filter_multi_entry_test/smc_filter_multi_entry_test/logs/smc_filter_multi_entry_test.log
  sha256: b6f42812f83311f53eae14fb52987d6de924056117bbed97ac91df6f1dfa0186
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

# Grade Report — smc_filter_multi_entry_test (standalone Layer 1 re-audit)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | none | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST`). Layer 1 findings are the entire scope of this report.
> `NOT-READY` records the **absence of a closure claim, not a defect**. Kept log
> is a sim **PASS** (seed 1, verilator 5.050): 32/32 SYS AXI FILTER_CONFIG reset
> reads (16 inbound + 16 outbound) match PeakRDL default `0x3000` — Layer 2
> entry is still not evaluated in this mode.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `c9a1ad34…`)

| Item | Prior (log `c9a1ad34…`, PASS) | This audit (log `b6f42812…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | none | none |
| Layer 1 matrix | all F/E/S/O1 + Phase-S L1 ✅ clean; L2 — not evaluated | unchanged — reconfirmed clean on new kept log |
| Kept log | `c9a1ad346cd5d5c9d5aad70d840f97c8198dc40e91acf53dca91abdf419cfc29` | `b6f42812f83311f53eae14fb52987d6de924056117bbed97ac91df6f1dfa0186` |
| Repo rev | `2ecc7b227e3926b253c65b5aac21239eec24ba5f` | `c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7` |
| Auditor run_id | `cursor/grok/4.5` | `cursor/grok/4.5-reaudit-20260806` |
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
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN SYS AXI via `SmcSysAxiItem`; scoreboard compares DUT `rdata` to PeakRDL `FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT`; no force/deposit on CSR path |
| F2 can't-fail checker | ✅ clean — scoreboard `got == exp` / `resp_ok`, driver timeout `AssertionError`, and final `assert self.accesses == 32` are reachable FAIL-ON paths |
| E1 skip-to-pass | ✅ clean — no missing-handle skip-to-pass; every slot issues a real AXI read |
| E2 empty phase | ✅ clean — 16 inbound + 16 outbound FILTER_CONFIG reads (32 real SYS AXI accesses) |
| S1 silent fail | ✅ clean — mismatch/timeout/`resp_ok` raise; no swallow-to-pass |
| O1 checker disabled | ✅ clean — SYS AXI scoreboard path active (log checks #1–#32) |
| Phase-S obligations — L1 | ✅ clean — addresses from generated PeakRDL `smc_reg.py`; exact expected on every read; timeouts fail; seed logged; enrolled in `p1_coverage_gap_r2.toml`; no unconditional CHK token; ROM/efuse preload is post-PASS bring-up trailer not CSR golden |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Log: `hw/sys/smc/dv/build/runs/20260806_094641__verilator__smc_filter_multi_entry_test/smc_filter_multi_entry_test/logs/smc_filter_multi_entry_test.log`
  sha256 `b6f42812f83311f53eae14fb52987d6de924056117bbed97ac91df6f1dfa0186`
  (verified via `manifest.py hash-file`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Final assertion gate: seq `assert self.accesses == 32` reached; protocol VIP records
  `csr_accesses=32 timeouts=0` (completion marker only; value proof is SYS AXI scoreboard)
- Test: `hw/sys/smc/dv/cocotb/tests/smc_filter_multi_entry_test.py` starts
  `smc_filter_multi_entry_test_seq` on `sys_axi_agent.sequencer`, then records protocol VIP CSR
- Seq body: loop `_INBOUND_FILTER_CONFIG` then `_OUTBOUND_FILTER_CONFIG`, each
  `csr_read(..., expected=FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT, length=8)`
- Addressing: `smc_filter_multi_entry_test_seq.py:22-96` imports PeakRDL symbols from
  `hw/sys/smc/regs/gen/py/smc_reg.py` — inbound `0xC0015000`…`0xC00151E0`, outbound
  `0xC0016000`…`0xC00161E0`; expected `FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT = 0x3000`
- Driver FAIL-ON: `smc_sys_axi_agent.py:160-163` raises on unexpected AXI timeout
  (`[TIMEOUT-MUST-FAIL]` satisfied)
- Scoreboard value check: `smc_scoreboard.py:188-194` asserts `rdata` vs `expected` when set
  (all 32 reads in this seq set expected)
- Enrollment: `hw/sys/smc/dv/testlists/p1_coverage_gap_r2.toml`
- Bring-up trailer (post-PASS flush): efuse hex + ROM `$readmemh` — time-0 image load; not
  used as CSR golden substitution on this proof path (policy §6 standing preload)
- No unexplained `ERROR`/`FATAL`/`Traceback` in the kept log
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`); auditor `run_id: cursor/grok/4.5-reaudit-20260806`

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>b6f42812…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| INBOUND_0 CONFIG RD | 292–293 | `addr=0xc0015000 rdata=0x3000 exp=0x3000 ok=True` | seq inbound loop |
| INBOUND_15 CONFIG RD | 397–398 | `addr=0xc00151e0 rdata=0x3000 exp=0x3000 ok=True` | seq |
| OUTBOUND_0 CONFIG RD | 404–405 | `addr=0xc0016000 rdata=0x3000 exp=0x3000 ok=True` | seq outbound loop |
| OUTBOUND_15 CONFIG RD | 509–510 | `addr=0xc00161e0 rdata=0x3000 exp=0x3000 ok=True` | seq |
| scoreboard tally | 293…510 | SYS AXI checks #1–#32 all `exp=0x3000 ok=True` | `smc_scoreboard` |
| protocol VIP | 512–513 | `csr_accesses=32 timeouts=0` | `record_protocol_vip` |
| AXI monitor | 515 | `32 R beats, 0 B resps; OKAY=32; 0 errors` | monitor |
| cocotb result | 521–523 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | — |

</details>

## Not concluded

- Whether FILTER_CONFIG reset-read sweep proves the SPEC filter multi-entry / filter-control
  properties (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
