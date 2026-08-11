---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_register_sanity_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094548__verilator__smc_register_sanity_test/smc_register_sanity_test/logs/smc_register_sanity_test.log
  sha256: b13196e5f51affa93ad243cd6201a489f2ea0065de58cee407fcd8e318a62bd7
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

# Grade Report — smc_register_sanity_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | none | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase. Layer 1 findings
> are the entire scope of this report. `NOT-READY` records the **absence of a closure
> claim, not a defect**. Kept log is a sim **PASS** (seed 1, verilator 5.050): all 15
> SYS AXI scratch reset/write/readback/restore accesses completed OKAY — Layer 2 entry is
> still not evaluated in this mode.

## DELTA (re-audit vs prior grade)

| Item | Prior (log `b81477fd…`, PASS) | This audit (log `b13196e5…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | none | none |
| Kept log | `b81477fde715fbd1fd5aa2a8211f5d7ef2f9a4ed0fe608023e0a1c71f4f8e978` PASS seed=1; 15/15 SYS AXI + `assert accesses == 15` | `b13196e5f51affa93ad243cd6201a489f2ea0065de58cee407fcd8e318a62bd7` PASS seed=1; same 15/15 proof shape on rev `c10b6d63…` |
| Waivers carried | none signed (`waivers: []`; nothing to drop) | none |

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
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN SYS AXI via `SmcSysAxiItem`; scoreboard compares DUT `rdata` to independently supplied `expected`; no force/deposit on CSR path |
| F2 can't-fail checker | ✅ clean — scoreboard `got == exp` / `resp_ok`, driver timeout `AssertionError`, and final `assert self.accesses == 15` are reachable FAIL-ON paths |
| E1 skip-to-pass | ✅ clean — no missing-handle skip-to-pass; `wait_fuse_sense_done` raises on miss |
| E2 empty phase | ✅ clean — 3× reset read + 3× write/readback + 3× restore write/read (15 real SYS AXI accesses) |
| S1 silent fail | ✅ clean — mismatch/timeout/`resp_ok` raise; no swallow-to-pass |
| O1 checker disabled | ✅ clean — SYS AXI scoreboard path active (log checks #1–#15) |
| Phase-S obligations — L1 | ✅ clean — addresses from generated map; exact expecteds on every read; timeouts fail; seed logged; enrolled in `batch_b.toml` / `all.toml` / `vplan_triplets.toml`; no unconditional CHK token; ROM/efuse preload is post-PASS bring-up trailer not CSR golden |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Log: `hw/sys/smc/dv/build/runs/20260806_094548__verilator__smc_register_sanity_test/smc_register_sanity_test/logs/smc_register_sanity_test.log`
  sha256 `b13196e5f51affa93ad243cd6201a489f2ea0065de58cee407fcd8e318a62bd7`
  (verified via `manifest.py hash-file`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Final assertion gate: seq `assert self.accesses == 15` reached; protocol VIP records
  `csr_accesses=15 timeouts=0` (completion marker only; value proof is SYS AXI scoreboard)
- Warm CSR: `SCRATCH_COLD_WARM_0` @ `0xc0002880` completed OKAY for reset read, pattern
  write/readback (`0xc0de0003`), and restore-to-0
- Test: `hw/sys/smc/dv/cocotb/tests/smc_register_sanity_test.py` starts
  `smc_register_sanity_test_seq` on `sys_axi_agent.sequencer`, then records protocol VIP CSR
- Seq body: `wait_fuse_sense_done` → catalog validate → 3× reset read (`expected=0`) →
  write/readback patterns → restore-to-0 with expected `0`
- Addressing: `smc_register_sanity_test_seq.py:18-26` via
  `smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD{,_WARM}_SCRATCH_BASE_ADDR", idx)`
  resolving to `0xc0002800` / `0xc0002804` / `0xc0002880` from
  `hw/sys/smc/regs/gen/c/smc_addr.h`; `catalog_entry` is consistency-only
- Driver FAIL-ON: `smc_sys_axi_agent.py:160-163` raises on unexpected AXI timeout
  (`[TIMEOUT-MUST-FAIL]` satisfied)
- Scoreboard value check: `smc_scoreboard.py:188-194` asserts `rdata` vs `expected` when set
  (all nine reads in this seq set expected)
- Enrollment: `hw/sys/smc/dv/testlists/batch_b.toml`, `all.toml`, `vplan_triplets.toml`
- Bring-up trailer (post-PASS flush): efuse hex + ROM `$readmemh` — time-0 image load; not
  used as CSR golden substitution on this proof path (policy §6 standing preload)
- No unexplained `ERROR`/`FATAL`/`Traceback` in the kept log
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`); auditor `run_id: cursor/grok/4.5-reaudit-20260806`

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>b13196e5…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| SCRATCH_COLD_0 reset RD | 293 | `rdata=0x0 exp=0x0 ok=True` | seq reset loop |
| SCRATCH_COLD_1 reset RD | 300 | `rdata=0x0 exp=0x0 ok=True` | seq |
| SCRATCH_COLD_WARM_0 reset RD | 307 | `rdata=0x0 exp=0x0 ok=True` | seq |
| COLD_0 WR/RD pattern | 319–327 | write `0xa5a50001`, readback match | `WRITE_READBACK` |
| COLD_1 WR/RD pattern | 333–341 | write `0x5a5a0002`, readback match | seq |
| WARM_0 WR/RD pattern | 347–355 | write `0xc0de0003`, readback match | seq |
| restore-to-0 ×3 | 361–397 | write `0`, readback `0` for all three | seq restore loop |
| protocol VIP | 399–400 | `csr_accesses=15 timeouts=0` | `record_protocol_vip` |
| AXI monitor | 402 | `9 R beats, 6 B resps; OKAY=9; 0 errors` | monitor |
| cocotb result | 404–410 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | — |

</details>

## Not concluded

- Whether scratch RW reset/write/readback proves the SPEC register properties (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
