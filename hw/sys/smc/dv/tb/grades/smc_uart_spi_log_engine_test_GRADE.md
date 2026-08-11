---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_uart_spi_log_engine_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094608__verilator__smc_uart_spi_log_engine_test/smc_uart_spi_log_engine_test/logs/smc_uart_spi_log_engine_test.log
  sha256: 51be9c6743e5f75a4a6e5d8ccded340b023e31768b7c45eb2eddfe897cbfb909
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

# Grade Report — smc_uart_spi_log_engine_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | none | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect** in the test by itself. Kept log is a sim **PASS** (seed 1); Layer 2 entry
> is not evaluated in this mode.

## DELTA (re-audit vs prior grade)

| Item | Prior (log `e2ebcb62…`, FAIL) | This audit (log `51be9c67…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🔴 1 Blocking `FIND-001` `[ADDRESS-FROM-AUTHORITATIVE-MAP]` (hand-copied `0xC000Axxx` = OCTS window) | none (addresses now via `smc_indexed_addr` → UART wrap-0 `0xC0006xxx`) |
| Kept log | `e2ebcb6250e5179e1382a14a2143df8b5de591007a58130af6b39859e5b8233d` FAIL seed=1; check #2 `0xc000a108` exp IIR `0x1` got `0x0` | `51be9c6743e5f75a4a6e5d8ccded340b023e31768b7c45eb2eddfe897cbfb909` PASS seed=1; 6/6 SYS AXI value checks OKAY on `0xc0006xxx` |
| Seq sha256 | `480f99070aacc74d4c6188ca1cb9cdf127024d1f3a5edb2430abe2a0b7877235` | `4b3374693c07d57da0ea430f141a1accd2aa84f8e10d3092c6afa58e3a2295e3` |
| `repository_revision` | `2ecc7b227e3926b253c65b5aac21239eec24ba5f` | `c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7` |
| `auditor.run_id` | `cursor/grok/4.5` | `cursor/grok/4.5-reaudit-20260806` |
| Waivers carried | none signed (`waivers: []`; nothing to drop) | none |

## Your to-do — 0 items (none)

| # | Kind | Id | Severity / grade | Where |
|---|---|---|---|---|
| — | — | — | — | none open |

**Then:** leave enrolled under `STANDALONE-REQUEST`, or allocate a real IP pin + card via
`/dv_vplan_gen` before any closure claim. Re-invoke `/dv_test_audit smc_uart_spi_log_engine_test`
only after material test/log changes. Do not invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN SYS AXI via `SmcSysAxiItem`; scoreboard compares DUT `rdata` to sequence `expected`; no force/deposit on CSR path |
| F2 can't-fail checker | ✅ clean — scoreboard `got == exp` / `resp_ok` and final `assert accesses == len(UART_LOG_READS)` are reachable FAIL-ON paths (prior FAIL log proved check #2 assert fires) |
| E1 skip-to-pass | ✅ clean — no missing-handle skip-to-pass; AXI path must complete or raise |
| E2 empty phase | ✅ clean — six real SYS AXI CSR reads with exact expecteds (not a no-op stub) |
| S1 silent fail | ✅ clean — mismatch raises `AssertionError` in `smc_scoreboard._check_sys_axi` |
| O1 checker disabled | ✅ clean — SYS AXI scoreboard path active (checks #1–#6); protocol VIP is completion marker only (`csr_accesses=0`), not the value-proof path |
| Phase-S obligations — L1 | ✅ clean — addresses from generated PeakRDL map via `smc_indexed_addr`; exact expecteds on every read (MSR `0x11` documented as tied-modem HW regression-lock, not RDL reset); timeouts fail; seed logged; enrolled in `batch_d.toml` / `all.toml` / `vplan_triplets.toml`; no unconditional CHK token; ROM/efuse preload is post-PASS bring-up trailer not CSR golden |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_uart_spi_log_engine_test.py`
  sha256 `491fe3161ecdb1e21dcdab2d06f76ae789d1f97bc0050969fdda00a91acc8fc7`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_uart_spi_log_engine_test_seq.py`
  sha256 `4b3374693c07d57da0ea430f141a1accd2aa84f8e10d3092c6afa58e3a2295e3`
- Helpers on proof path: `smc_addr_map.smc_indexed_addr` →
  `smc_csr_seq_utils.SmcCsrSeq.csr_read_many` → `smc_sys_axi_agent` /
  `smc_scoreboard._check_sys_axi`
- Log: `hw/sys/smc/dv/build/runs/20260806_094608__verilator__smc_uart_spi_log_engine_test/smc_uart_spi_log_engine_test/logs/smc_uart_spi_log_engine_test.log`
  sha256 `51be9c6743e5f75a4a6e5d8ccded340b023e31768b7c45eb2eddfe897cbfb909`
  (verified via `manifest.py hash-file`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Final assertion gate: seq `assert self.accesses == len(UART_LOG_READS)` (6) reached
  after scoreboard value checks #1–#6
- Addressing (idx 0, resolved): `UART_LOG_ENGINE_CTRL=0xC0006000`, `UART_IIR=0xC0006108`,
  `UART_LSR=0xC0006114`, `UART_MSR=0xC0006118`, `LOG_ENGINE_CTRL=0xC0006200`,
  `LOG_ENGINE_INTR_STATUS=0xC0006214` from `hw/sys/smc/regs/gen/c/smc_addr.h`
- Expecteds: CTRL/INTR_STATUS `0x0`, IIR `0x1`, LSR `0x60`, MSR `0x11` (tied modem HW
  lock; RDL field resets are 0 — documented in sequence header)
- Name note (not a Layer-1 finding): testcase name includes `spi` but sequence only
  sweeps UART/log-engine CSRs (docstring: "UART/log-engine representative CSR precheck")
- Enrollment: `hw/sys/smc/dv/testlists/batch_d.toml`, `all.toml`, `vplan_triplets.toml`
- Bring-up trailer after PASS: efuse/ROM hex preload (log L343–L347); not used as CSR golden
- No unexplained `ERROR`/`FATAL`/`Traceback` in the kept log
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`); auditor
  `run_id: cursor/grok/4.5-reaudit-20260806`

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>51be9c67…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| bring-up | 258–278 | clocks / cold reset / agents ready | `smc_base_test` |
| check #1 | 280–293 | read `0xc0006000` → `0x0`, `exp=0x0`, OKAY | `UART_LOG_ENGINE_CTRL` |
| check #2 | 295–300 | read `0xc0006108` → `0x1`, `exp=0x1`, OKAY | `UART_IIR` |
| check #3 | 302–307 | read `0xc0006114` → `0x60`, `exp=0x60`, OKAY | `UART_LSR` |
| check #4 | 309–314 | read `0xc0006118` → `0x11`, `exp=0x11`, OKAY | `UART_MSR` |
| check #5 | 316–321 | read `0xc0006200` → `0x0`, `exp=0x0`, OKAY | `LOG_ENGINE_CTRL` |
| check #6 | 323–328 | read `0xc0006214` → `0x0`, `exp=0x0`, OKAY | `LOG_ENGINE_INTR_STATUS` |
| protocol VIP | 330–331 | `uart_log:… mode=proxy csr_accesses=0 … passed=True` | completion marker only |
| AXI monitor | 333 | `6 R beats; OKAY=6; 0 errors` | monitor |
| cocotb result | 335–341 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | — |

</details>

## Not concluded

- Whether a UART/log CSR reset precheck proves the SPEC properties a future card would
  require (O2), or whether SPI belongs in this testcase's intent — Skill 3 / plan ownership.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
