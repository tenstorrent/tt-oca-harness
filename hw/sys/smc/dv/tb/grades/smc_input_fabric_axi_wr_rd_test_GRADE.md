---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_input_fabric_axi_wr_rd_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094605__verilator__smc_input_fabric_axi_wr_rd_test/smc_input_fabric_axi_wr_rd_test/logs/smc_input_fabric_axi_wr_rd_test.log
  sha256: 013f5d4ce8be55d30443cc351d50ea56ffeed16096eb32afcb094cf1de5c1e6e
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

# Grade Report — smc_input_fabric_axi_wr_rd_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | none | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase. Layer 1 findings
> are the entire scope of this report. `NOT-READY` records the **absence of a closure
> claim, not a defect**. Kept log is a sim **PASS** (seed 1, verilator 5.050): 9/9 SEP_IN
> SYS AXI remap/filter CSR reset reads match PeakRDL defaults — Layer 2 entry is still not
> evaluated in this mode.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `bc28f572…`)

| Item | Prior (log `bc28f572…`, PASS) | This audit (log `013f5d4c…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | none | none |
| Layer 1 matrix | all structural rows clean; L2 not evaluated | unchanged — still clean / L2 not evaluated |
| Kept log | `bc28f572c45fddea549978eb2fe0091fd6678dfdc2831d4aed2ebb12e4277b84` | `013f5d4ce8be55d30443cc351d50ea56ffeed16096eb32afcb094cf1de5c1e6e` |
| repository_revision | `2ecc7b227e3926b253c65b5aac21239eec24ba5f` | `c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7` |
| auditor.run_id | `cursor/grok/4.5` | `cursor/grok/4.5-reaudit-20260806` |
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
| F2 can't-fail checker | ✅ clean — scoreboard `got == exp` / `resp_ok`, driver timeout `AssertionError`, and final `assert self.accesses == 9` are reachable FAIL-ON paths |
| E1 skip-to-pass | ✅ clean — no missing-handle skip-to-pass; every FILTER_REMAP_REGS entry issues a real AXI read |
| E2 empty phase | ✅ clean — 9 real SYS AXI CSR reads (ALIAS0 START/END/ATTRS + inbound/outbound FILTER_CONFIG/START/END) |
| S1 silent fail | ✅ clean — mismatch/timeout/`resp_ok` raise; no swallow-to-pass |
| O1 checker disabled | ✅ clean — SYS AXI scoreboard path active (log checks #1–#9) |
| Phase-S obligations — L1 | ✅ clean — addresses/defaults from generated PeakRDL `smc_reg.py`; CHK addresses from generated C map via `smc_indexed_addr` (values match PeakRDL); exact expected on every read; timeouts fail; seed logged; enrolled in `batch_d.toml` / `all.toml`; CHK tokens emit only after `accesses==9` gate; ROM/efuse preload is post-PASS bring-up trailer not CSR golden |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_input_fabric_axi_wr_rd_test.py`
  sha256 `8609604dbc532361267e315da44ef3b65d089aee6902e04ad39b3460851d8f70`
  (alias wrapper; starts `smc_input_output_fabric_wr_rd_test_seq` on `sys_axi_agent.sequencer`)
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_input_output_fabric_wr_rd_test_seq.py`
  sha256 `274322e42d951f299a8054bcb47a70a4dad12a2b227018961307ada703b1f9f3`
- Helper / scoreboard (proof path): `smc_csr_seq_utils.SmcCsrSeq.csr_read` →
  `smc_sys_axi_agent` → `smc_scoreboard._check_sys_axi`
- Log: `hw/sys/smc/dv/build/runs/20260806_094605__verilator__smc_input_fabric_axi_wr_rd_test/smc_input_fabric_axi_wr_rd_test/logs/smc_input_fabric_axi_wr_rd_test.log`
  sha256 `013f5d4ce8be55d30443cc351d50ea56ffeed16096eb32afcb094cf1de5c1e6e`
  (verified via `sha256sum`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Stimulus: loop `FILTER_REMAP_REGS` (9 entries) with
  `csr_read(..., expected=<PeakRDL *_REG_DEFAULT>, length=8)` — reset-content CSR
  precheck over SEP_IN (no AXI write in this sequence; name `wr_rd` is historical alias)
- Addressing: seq imports PeakRDL symbols from `hw/sys/smc/regs/gen/py/smc_reg.py`
  (ALIAS0 `0xC0012000`/`2008`/`2010`; inbound `0xC0015000`/`5008`/`5010`; outbound
  `0xC0016000`/`6008`/`6010`); defaults include FILTER_CONFIG `0x3000`, END_ADDR `0x7`
- Driver FAIL-ON: `smc_sys_axi_agent.py` raises on unexpected AXI timeout
- Scoreboard value check: `smc_scoreboard.py` asserts `rdata` vs `expected` when set
  (all 9 reads set expected; log SYS AXI checks #1–#9)
- Final seq gate: `assert self.accesses == 9`; then
  `CHK-ALIAS-REMAP-RESET-DEFAULT` / `CHK-NONVAC` / `SMC_004 scenario PASS`
- AXI monitor: `9 R beats … OKAY=9; 0 errors`
- Enrollment: `hw/sys/smc/dv/testlists/batch_d.toml`, `all.toml`
- Bring-up trailer (post-PASS flush): efuse/ROM sense message — not used as CSR golden
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`); auditor `run_id: cursor/grok/4.5-reaudit-20260806`
- Note: test file carries a DV-CARD provenance header; this audit is
  `STANDALONE-REQUEST` and does not grade or invent checkbox closure from that header

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>013f5d4c…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| STEP S1/S2 | 268–269 | SETUP log + ALIAS remap reset-read step | seq `:71-72` |
| ALIAS0_START RD | 294–295 | `addr=0xc0012000 rdata=0x0 exp=0x0 ok=True` | FILTER_REMAP_REGS |
| ALIAS0_ATTRS RD | 308–309 | `addr=0xc0012010 rdata=0x0 exp=0x0 ok=True` | seq |
| INBOUND0_FILTER_CONFIG | 315–316 | `addr=0xc0015000 rdata=0x3000 exp=0x3000 ok=True` | seq |
| INBOUND0_END | 329–330 | `addr=0xc0015010 rdata=0x7 exp=0x7 ok=True` | seq |
| OUTBOUND0_FILTER_CONFIG | 336–337 | `addr=0xc0016000 rdata=0x3000 exp=0x3000 ok=True` | seq |
| OUTBOUND0_END | 350–351 | `addr=0xc0016010 rdata=0x7 exp=0x7 ok=True` | seq |
| CHK + NONVAC | 353–355 | ALIAS0 token + `accesses==9` + scenario PASS | seq `:78-100` |
| AXI monitor | 356 | `9 R beats … OKAY=9; 0 errors` | monitor |
| cocotb result | 358–364 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | — |

</details>

## Not concluded

- Whether remap/filter CSR reset-read precheck proves the SPEC input-fabric WR/RD or
  fabric-proxy properties a future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
