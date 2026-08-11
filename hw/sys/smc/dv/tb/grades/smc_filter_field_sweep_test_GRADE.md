---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_filter_field_sweep_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094643__verilator__smc_filter_field_sweep_test/smc_filter_field_sweep_test/logs/smc_filter_field_sweep_test.log
  sha256: e4b5ec5de91a28fd623b18eeefb640b1c9f1d03ba1b6e96b762747a3e2209b35
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

# Grade Report — smc_filter_field_sweep_test (standalone Layer 1 re-audit)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | none | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect**. Kept log is a sim **PASS** (seed 1, verilator 5.050): 24/24 SYS AXI filter
> field reset reads matched PeakRDL defaults — Layer 2 entry is still not evaluated in
> this mode.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `de7e7b9b…`)

| Item | Prior (log `de7e7b9b…`, PASS) | This audit (log `e4b5ec5d…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | none | none |
| Layer 1 structural / Phase-S L1 | all ✅ clean | unchanged — all ✅ clean |
| Kept log | `de7e7b9bdea8c1bf223e828651aa5c57be7d1166e2a9832ade7c141bddeff99d` | `e4b5ec5de91a28fd623b18eeefb640b1c9f1d03ba1b6e96b762747a3e2209b35` |
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
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN SYS AXI via `SmcSysAxiItem`; scoreboard compares DUT `rdata` to PeakRDL `*_REG_DEFAULT`; no force/deposit on CSR path |
| F2 can't-fail checker | ✅ clean — scoreboard `got == exp` / `resp_ok`, driver timeout `AssertionError`, and final `assert self.accesses == 24` are reachable FAIL-ON paths |
| E1 skip-to-pass | ✅ clean — no missing-handle skip-to-pass; strict `csr_read` (not bounded/allow_timeout) |
| E2 empty phase | ✅ clean — 2 dirs × 4 entries × 3 fields = 24 real SYS AXI reads with distinct expecteds (`0x3000` / `0x0` / `0x7`) |
| S1 silent fail | ✅ clean — mismatch/timeout/`resp_ok` raise; no swallow-to-pass |
| O1 checker disabled | ✅ clean — SYS AXI scoreboard path active (log checks #1–#24) |
| Phase-S obligations — L1 | ✅ clean — addresses via generated `smc_reg` symbols; exact PeakRDL reset expecteds; timeouts fail; seed=1 logged; enrolled in `p1_coverage_gap_r3.toml`; no unconditional CHK token; ROM/efuse preload is post-PASS bring-up trailer not CSR golden |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_filter_field_sweep_test.py`
  sha256 `7cbcb02f77d801882814704751cf8571ef3a76f41d0dbc459fdd03fb316c242f`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_filter_field_sweep_test_seq.py`
  sha256 `38bbda6fd3f96c0c1b0b828f8a6dcb23f511c879a429fc36e633eb364da19a2c`
- Scoreboard / driver (proof path): `smc_scoreboard._check_sys_axi`,
  `smc_sys_axi_agent._drive` / `_timed_event`
- Authoritative map: generated `hw/sys/smc/regs/gen/py/smc_reg.py`
  (`SMC_{INBOUND,OUTBOUND}_FILTER_CTRL_{n}__{field}_REG_ADDR`,
  `FILTER_CTRL_*_REG_DEFAULT`)
- Log: `hw/sys/smc/dv/build/runs/20260806_094643__verilator__smc_filter_field_sweep_test/smc_filter_field_sweep_test/logs/smc_filter_field_sweep_test.log`
  sha256 `e4b5ec5de91a28fd623b18eeefb640b1c9f1d03ba1b6e96b762747a3e2209b35`
  (verified via content sha256; matches invoker-kept log)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- Repo rev: `c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7`
- Policy: `51a3357d9c31a018d69451b055bc956c089af26e1051368e25ce396c84ac2a75`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary L465–L467:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Final assertion gate: seq `assert self.accesses == expected` (24) reached; protocol VIP
  records `csr_accesses=24 timeouts=0` (completion marker only; value proof is SYS AXI
  scoreboard)
- Test starts `smc_filter_field_sweep_test_seq` on `sys_axi_agent.sequencer`, then records
  protocol VIP
- Seq body (`smc_filter_field_sweep_test_seq.py:49-61`): nested loops over
  `INBOUND`/`OUTBOUND` × entries 0–3 × `{FILTER_CONFIG, START_ADDR, END_ADDR}` with
  `csr_read(..., expected=exp, length=8)`
- Addressing: `_filter_reg_addr` →
  `getattr(_smc_reg, f"SMC_{direction}_FILTER_CTRL_{entry}__{field}_REG_ADDR")`
  (e.g. inbound0 FILTER_CONFIG `0xc0015000`, outbound0 FILTER_CONFIG `0xc0016000`)
- Expecteds: `FILTER_CTRL_*_REG_DEFAULT` from the same PeakRDL map
  (`0x3000` / `0x0` / `0x7`)
- Driver FAIL-ON: `smc_sys_axi_agent.py:160-163` raises on unexpected AXI timeout
  (`[TIMEOUT-MUST-FAIL]` satisfied)
- Scoreboard value check: `smc_scoreboard.py:188-194` asserts `rdata` vs `expected`
  (all 24 reads set expected)
- Enrollment: `hw/sys/smc/dv/testlists/p1_coverage_gap_r3.toml`
- Bring-up trailer (post-PASS flush): efuse hex + ROM `$readmemh` — time-0 image load; not
  used as CSR golden substitution on this proof path (policy §6 standing preload)
- No unexplained `ERROR`/`FATAL`/`Traceback` in the kept log
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`); auditor
  `run_id: cursor/grok/4.5-reaudit-20260806`

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>e4b5ec5d…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| INBOUND_0 FILTER_CONFIG | 293 | `rdata=0x3000 exp=0x3000 ok=True` | seq field loop |
| INBOUND_0 START_ADDR | 300 | `rdata=0x0 exp=0x0 ok=True` | seq |
| INBOUND_0 END_ADDR | 307 | `rdata=0x7 exp=0x7 ok=True` | seq |
| INBOUND entries 1–3 | 313–370 | same triad at `0xc0015020`…`0xc0015070` | seq |
| OUTBOUND_0 FILTER_CONFIG | 377 | `0xc0016000` → `0x3000` | seq dir loop |
| OUTBOUND entries 0–3 | through 454 | checks #13–#24 match PeakRDL defaults | seq |
| protocol VIP | 456–457 | `csr_accesses=24 timeouts=0 passed=True` | `record_protocol_vip` |
| AXI monitor | 459 | `24 R beats, 0 B; OKAY=24; 0 errors` | monitor |
| cocotb result | 465–467 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | — |

</details>

## Not concluded

- Whether reset-value field decode proves the SPEC filter properties (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
