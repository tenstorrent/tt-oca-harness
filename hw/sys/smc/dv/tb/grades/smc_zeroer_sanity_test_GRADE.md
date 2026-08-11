---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_zeroer_sanity_test
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
- path: hw/sys/smc/dv/build/runs/20260806_163858__verilator__smc_zeroer_sanity_test/smc_zeroer_sanity_test/logs/smc_zeroer_sanity_test.log
  sha256: 9dce5557740d98994502ea6886f48dd5266fb8a4227026fe932d8278d6d4c822
test_author:
  human_id: unknown
  run_id: unknown
  model:
    provider: unknown
    family: unknown
    version: unknown
auditor:
  human_id: minshaoho
  run_id: cursor/grok/4.5-fixloop-20260806
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

# Grade Report — smc_zeroer_sanity_test (standalone Layer 1 re-audit)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | none | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST`). Layer 1 findings are the entire scope of this report.
> `NOT-READY` records the **absence of a closure claim, not a defect**. Kept
> log is a sim **PASS** (seed 1, verilator 5.050): post-preload write-count
> baseline, post-trigger +1 gate, JTAG zero/neighbour readback — Layer 2 entry
> is still not evaluated in this mode.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `5007601d…`)

| Item | Prior (log `5007601d…`, PASS) | This audit (log `9dce5557…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🔴 2 Blocking | **cleared** — none open (`findings: []`) |
| Prior FIND-001 `[NO-ALWAYS-PASS-CHECKER]` (write-count baseline before preload; +2) | open Blocking — `start_writes` before JTAG preload; wait/assert `+2`; log `0->2` same ns as trigger | **CLOSED** — baseline after preload+readback (`:207`); wait/assert `start_writes+1` (`:234`, `:254`); log L365 baseline=`2`, L390 `2->3` at 5190ns (after STATUS @ 5166ns) |
| Prior FIND-002 `[NO-ALWAYS-PASS-CHECKER]` (memory_model write→expect + VIP model claim) | open Blocking — post-trigger `write(ZEROER_EXPECTED)`+`expect`; VIP "matched memory model" | **CLOSED** — self-compare removed (`:255-258`); VIP details name JTAG AXI readback (test `:27-30`; log L407–L408); `model_checks=0` |
| Kept log | PASS seed=1 (`20260806_094625…`) sha256 `5007601d…` | PASS seed=1 (`20260806_163858…`) sha256 `9dce5557…` (content sha256 verified) |
| Repo / model | `c10b6d63…` / `2c815fa08277` | `c10b6d63…` / `2c815fa08277` |
| Auditor run_id | `cursor/grok/4.5-reaudit-20260806` | `cursor/grok/4.5-fixloop-20260806` |
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
| F1 fabricated verdict / backdoor write | ✅ clean — SEP_IN CSR + JTAG AXI preload/readback; `tb_output_axi_write_count` is passive observe; poison tracked in TB model for bookkeeping only (no post-trigger rewrite/expect); no force/deposit on proof path; ROM/efuse trailer is time-0 image load only |
| F2 can't-fail checker | ✅ clean — prior always-pass paths closed; `_wait_for_zeroer_write` / `write_count >= baseline+1` / JTAG `assert actual == ZEROER_EXPECTED` / neighbour poison assert are reachable FAIL-ON paths against RTL activity and payload |
| E1 skip-to-pass | ✅ clean — no missing-handle skip-to-pass; wait/mismatch paths raise |
| E2 empty phase | ✅ clean — filter program, poison preload+readback, DEST/SIZE program, trigger, post-trigger wait, zero/neighbour asserts all execute in the kept log |
| S1 silent fail | ✅ clean — mismatch/timeout raise `AssertionError`; scoreboard SYS AXI / VIP consistency asserts present |
| O1 checker disabled | ✅ clean — `auto_protocol_vip=False` with explicit VIP record; SYS AXI scoreboard checks #1–#15 + protocol VIP #1 active |
| Phase-S obligations — L1 | ✅ clean — ZEROER/filter CSRs from PeakRDL `smc_reg`; post-preload baseline+1 write gate; timeout converts to fail; JTAG payload/neighbour asserts remain real FAIL-ON; VIP details match proof path; seed logged; X-aware `is_resolvable` on TB counter; enrolled in `vplan_triplets.toml` |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_zeroer_sanity_test.py`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_zeroer_dma_timeout_test_seq.py`
  (discovered: test instantiates `smc_zeroer_dma_timeout_test_seq`)
- Scoreboard (proof path): `hw/sys/smc/dv/cocotb/env/smc_scoreboard.py`
- Log: `hw/sys/smc/dv/build/runs/20260806_163858__verilator__smc_zeroer_sanity_test/smc_zeroer_sanity_test/logs/smc_zeroer_sanity_test.log`
  sha256 `9dce5557740d98994502ea6886f48dd5266fb8a4227026fe932d8278d6d4c822`
  (content sha256 verified)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- Repo rev: `c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7`
- Policy: `51a3357d9c31a018d69451b055bc956c089af26e1051368e25ce396c84ac2a75`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary L412–L418:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Stimulus: pass-all filters → JTAG poison@`0x2000000` + neighbour@`0x2000008`
  → ZEROER DEST/SIZE → CTRL_STATUS start → wait `tb_output_axi_write_count`
  post-preload baseline+1 → JTAG readback zeros + neighbour intact
- Observed tokens: `CHK-NONVAC` (baseline after preload=2),
  `CHK-ZEROER-REGION-DECODE`, `CHK-ZEROER-TRIGGER-STARTS` (`2->3`),
  `CHK-ZEROER-REGION-ZEROED`, `SMC_006 scenario PASS`
- Addressing: `ZEROER_*` / filter CSRs imported from generated `smc_reg`
  (`ZEROER_CTRL_*_REG_ADDR`, `SMC_*_FILTER_CTRL_0__*`)
- Driver FAIL-ON: `_wait_for_zeroer_write` raises after `ZEROER_WAIT_CYCLES`;
  JTAG `assert actual == ZEROER_EXPECTED` / neighbour asserts raise on mismatch;
  `assert write_count >= start_writes + 1`
- Closed vacuous paths (this re-audit): baseline after preload (`:206-207`);
  no `memory_model.write(ZEROER_EXPECTED)`+`expect`; VIP details =
  JTAG AXI readback (not model self-compare)
- Enrollment: `hw/sys/smc/dv/testlists/vplan_triplets.toml`
- Bring-up trailer (post-PASS flush): efuse hex + ROM `$readmemh` — time-0 image
  load; not used as zeroer payload golden substitution
- No unexplained `ERROR`/`FATAL`/`Traceback` in the kept log
- Provenance: legacy (`test_author.run_id: unknown`); auditor
  `run_id: cursor/grok/4.5-fixloop-20260806`
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>9dce5557…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| filter pass-all | 268–329 | SEP_IN writes inbound/outbound windows | seq `:139-149` |
| preload + NONVAC | 336–365 | JTAG poison/neighbour write+read; baseline after preload=`2` | seq `:198-213` |
| DEST/SIZE | 366–381 | writes `0xc0038200`/`0xc0038208`; decode token | seq `:219-226` |
| trigger + wait | 382–390 | STATUS=`0x1` @ 5166ns; write_count `2->3` @ 5190ns | seq `:232-241` |
| zero + neighbour | 391–406 | region `00…00`; neighbour poison intact; COV cells | seq `:243-269` |
| VIP / monitors | 407–411 | protocol VIP JTAG AXI readback `checked_bytes=8`; SYS_OUT `4 R / 3 B` | test `:21-31` |
| cocotb result | 412–418 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | — |

</details>

## Not concluded

- Whether this zeroer path proves the SPEC properties a future card would
  require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
