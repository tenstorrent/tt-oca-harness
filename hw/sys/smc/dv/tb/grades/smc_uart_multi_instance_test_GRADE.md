---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_uart_multi_instance_test
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
- path: hw/sys/smc/dv/build/runs/20260806_095338__verilator__smc_uart_multi_instance_test/smc_uart_multi_instance_test/logs/smc_uart_multi_instance_test.log
  sha256: 91d1b9b78eaa6edecdcf3c9c7927c5bd9b80ca339c2dceeb9adfc001e7240d1c
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

# Grade Report — smc_uart_multi_instance_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | none | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect** in the test by itself. Kept log is a sim **PASS** (seed 1, verilator 5.050):
> nine frontdoor SEP_IN SYS AXI CSR reads at PeakRDL UART_LOG_ENGINE wrap 1/2/3
> CTRL/UART/LOG_ENGINE bases completed OKAY with scoreboard `rdata == 0` — Layer 2
> entry is still not evaluated in this mode.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `94bb8862…`)

| Item | Prior (log `94bb8862…`, PASS wrong window) | This audit (log `91d1b9b7…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🔴 1 Blocking | none |
| Prior FIND-001 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` | open Blocking — hand `0xC000A400`…`0xC000AE00` (OCTS→DTP hole; false identity OKAY+0) | **closed** — `UART_WRAP_READS` uses `smc_indexed_addr` PeakRDL symbols; kept log hits `0xc0006400`…`0xc0006e00` OKAY + reset-0 |
| Kept log | `94bb88622df5fa11a6e57021406a8d5eae808d22aaeadf7bb95458baac7aff88` (PASS, wrong window) | `91d1b9b78eaa6edecdcf3c9c7927c5bd9b80ca339c2dceeb9adfc001e7240d1c` (PASS, UART window) |
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
| F2 can't-fail checker | ✅ clean — scoreboard `resp_ok` / `got == exp` and final `assert self.accesses == len(UART_WRAP_READS)` are reachable FAIL-ON paths |
| E1 skip-to-pass | ✅ clean — strict `csr_read` (no `allow_timeout` / skip-on-missing-handle); sequence issues nine real AXI reads |
| E2 empty phase | ✅ clean — body issues nine CSR reads with expected reset values; scoreboard SYS AXI checks #1–#9 present |
| S1 silent fail | ✅ clean — non-OKAY / value mismatch raise `AssertionError` in scoreboard; access-count gate asserts; no swallow-to-pass |
| O1 checker disabled | ✅ clean — SYS AXI scoreboard path active (checks #1–#9); AXI monitor OKAY=9; protocol VIP `passed` is a non-asserted completion marker only |
| Phase-S obligations — L1 | ✅ clean — addresses from `smc_addr_map.smc_indexed_addr` / PeakRDL `smc_addr.h`; exact expected `0x0` on every read (RDL-anchored wrap base reset); timeouts fail via driver; seed logged; enrolled in `p1_coverage_gap.toml`; no unconditional CHK token; ROM/efuse preload is post-PASS bring-up trailer not CSR golden |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_uart_multi_instance_test.py`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_uart_multi_instance_test_seq.py`
- CSR helper: `hw/sys/smc/dv/cocotb/seq_lib/smc_csr_seq_utils.py` `SmcCsrSeq.csr_read`
- Scoreboard (proof path): `hw/sys/smc/dv/cocotb/env/smc_scoreboard.py` `_check_sys_axi`
- Authoritative map: `hw/sys/smc/regs/gen/c/smc_addr.h` via `smc_addr_map.smc_indexed_addr` —
  `SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_*_BASE_ADDR(idx)`:
  idx1 `0xC0006400/6500/6600`, idx2 `0xC0006800/6900/6A00`,
  idx3 `0xC0006C00/6D00/6E00`
- Log: `hw/sys/smc/dv/build/runs/20260806_095338__verilator__smc_uart_multi_instance_test/smc_uart_multi_instance_test/logs/smc_uart_multi_instance_test.log`
  sha256 `91d1b9b78eaa6edecdcf3c9c7927c5bd9b80ca339c2dceeb9adfc001e7240d1c`
  (verified via `hashlib.sha256` / `sha256sum`; run id `20260806_095338`)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary L360–L362:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Final assertion gate: seq `assert self.accesses == len(UART_WRAP_READS)` (9) reached;
  value proof is SYS AXI scoreboard `got == exp` on every read (9/9 logged)
- AXI monitor: `9 R beats, 0 B resps; R-resp tally OKAY=9; 0 errors`
- Address / value cites (kept log):
  - WRAP_1 CTRL/UART/LOG `0xc0006400/6500/6600` → `0x0` (L280–L307)
  - WRAP_2 CTRL/UART/LOG `0xc0006800/6900/6a00` → `0x0` (L309–L328)
  - WRAP_3 CTRL/UART/LOG `0xc0006c00/6d00/6e00` → `0x0` (L330–L349)
- Enrollment: `hw/sys/smc/dv/testlists/p1_coverage_gap.toml`
- Bring-up trailer (post-PASS flush): efuse hex + ROM `$readmemh` — time-0 image load;
  not used as CSR golden on this proof path (policy §6 standing preload)
- No unexplained `ERROR`/`FATAL`/`Traceback` in the kept log
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`); auditor
  `run_id: cursor/grok/4.5-reaudit-20260806`

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>91d1b9b7…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| WRAP_1_CTRL RD | 280–293 | read `0xc0006400` OKAY `rdata=0x0` scoreboard #1 ok | seq `smc_indexed_addr(...CTRL..., 1)` |
| WRAP_1_UART RD | 295–300 | read `0xc0006500` OKAY `rdata=0x0` #2 ok | seq `…UART…, 1` |
| WRAP_1_LOG_ENGINE RD | 302–307 | read `0xc0006600` OKAY `rdata=0x0` #3 ok | seq `…LOG_ENGINE…, 1` |
| WRAP_2_* RD | 309–328 | `0xc0006800/6900/6a00` OKAY `0x0` #4–#6 | seq idx 2 |
| WRAP_3_* RD | 330–349 | `0xc0006c00/6d00/6e00` OKAY `0x0` #7–#9 | seq idx 3 |
| VIP / monitor | 351–354 | `csr_accesses=9` · `OKAY=9` | test + monitor |
| cocotb result | 356–362 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | — |

</details>

## Not concluded

- Whether a corrected UART multi-instance CSR sweep proves the SPEC properties (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
