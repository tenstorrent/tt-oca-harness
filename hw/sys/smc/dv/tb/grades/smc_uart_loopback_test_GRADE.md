---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_uart_loopback_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094608__verilator__smc_uart_loopback_test/smc_uart_loopback_test/logs/smc_uart_loopback_test.log
  sha256: 19fb9f10cedadbcd367f736d3f36aa093d823b4cdb7619b1d4fe9dd761d829d6
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
  tag: '[NO-BLIND-DELAY-SYNC]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_uart_loopback_test_seq.py:73-74
  observed: >-
    After DLAB baud programming the sequence still waits
    `ClockCycles(cocotb.top.clk_smc_i, max(64, self.divisor * 16))` with only a
    legacy-TB comment ("Allow divisor reload to settle"). That fixed cycle count
    is not an event/handshake tied to a SPEC-bound completion. Kept log shows the
    settle gap from LCR clear complete (~5328 ns) to VIP bind (~11856 ns) equal
    to exactly 1088 smc cycles at 6 ns (max(64, 68*16)), then THR write and pad12
    capture. TX completion correctly uses `vip.capture_frame(timeout_us=5000)`
    later, but this settle step remains a bare delay on the programming path.
  closure_condition: >-
    Replace the fixed `ClockCycles` settle with a bounded, fail-on-timeout
    handshake or status poll derived from the 16550/SPEC (e.g. wait LSR THRE /
    TEMT after divisor reload — `UART0_LSR` is already imported from the map —
    or document a SPEC latency bound and assert it), keeping
    `[TIMEOUT-MUST-FAIL]` diagnostics on expiry.
  waived_by: null
- id: FIND-002
  tag: '[NO-DUMMY-DEAD-CODE]'
  severity: Minor
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_uart_loopback_test_seq.py:27-29
  observed: >-
    `UART0_LSR` is resolved from PeakRDL
    (`SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR`,
    `0xC0006114`) but never read or polled in `body()`. It is dead map-side
    scaffolding beside the live THR/LCR/IER path; a reader may assume LSR-based
    settle/completion is already implemented when it is not (the settle uses
    bare `ClockCycles` instead — FIND-001).
  closure_condition: >-
    Either use `UART0_LSR` in the post-divisor bounded status wait that closes
    FIND-001, or remove the unused `UART0_LSR` binding so the sequence does not
    advertise an unused LSR address on the proof path.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_uart_loopback_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🟠 1 Major · 🟡 1 Minor | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect** in the test by itself. Kept log is a sim **PASS** (seed 1, verilator 5.050):
> UART0 THR→pad12 capture completed with golden=a5 obs=a5 — Layer 2 entry is still
> not evaluated in this mode.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `2efbe42e…`)

| Item | Prior (log `2efbe42e…`, FAIL) | This audit (log `19fb9f10…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🔴 1 Blocking · 🟠 1 Major | 🟠 1 Major · 🟡 1 Minor |
| Prior FIND-001 wrong UART literals / OCTS window | open Blocking `[ADDRESS-FROM-AUTHORITATIVE-MAP]` | **resolved** — sequence imports PeakRDL via `smc_addr_map` / `smc_indexed_addr`; log hits `0xc0006000` / `0xc0006100` / `6104` / `610c` (UART0), not `0xc000a000` |
| Prior FIND-002 fixed ClockCycles settle | open Major `[NO-BLIND-DELAY-SYNC]` | **still open** as FIND-001 Major — `smc_uart_loopback_test_seq.py:73-74` unchanged |
| New FIND-002 unused `UART0_LSR` | — | open Minor `[NO-DUMMY-DEAD-CODE]` — bound at `:27-29`, never used |
| VIP / sim result | `cocotbext-uart` missing → FAIL at bind; THR+capture never reached | VIP binds (cocotbext-uart 0.1.4); pad12 `Read byte 0xa5`; `TESTS=1 PASS=1 FAIL=0 SKIP=0` |
| Kept log | `2efbe42e5764d8e8e50163addae893962ede41cfefcfd97c13e604659f910264` | `19fb9f10cedadbcd367f736d3f36aa093d823b4cdb7619b1d4fe9dd761d829d6` |
| Repo rev | `2ecc7b227e3926b253c65b5aac21239eec24ba5f` | `c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7` |
| Auditor run_id | `cursor/grok/4.5` | `cursor/grok/4.5-reaudit-20260806` |
| Waivers carried | none signed (`waivers: []`) | none (nothing to drop; no signed entries) |

## Your to-do — 2 items (🟠 1 Major · 🟡 1 Minor)

| # | Kind | Id | Severity / grade | Where |
|---|---|---|---|---|
| 1 | finding | FIND-001 | 🟠 Major | `smc_uart_loopback_test_seq.py:73-74` |
| 2 | finding | FIND-002 | 🟡 Minor | `smc_uart_loopback_test_seq.py:27-29` |

<details>
<summary>1. FIND-001 — 🟠 Major <code>[NO-BLIND-DELAY-SYNC]</code> — fixed ClockCycles divisor settle</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_uart_loopback_test_seq.py:73-74`
- **Observed:** `await ClockCycles(..., max(64, divisor * 16))` bridges baud reload with a magic cycle count (legacy comment only). Log settle gap matches exactly 1088 × 6 ns. Capture later uses a timed VIP wait, but this settle step is still a bare delay on the proof path.
- **Closure:** Use a bounded LSR/status (or SPEC-bound) wait with fail-on-timeout instead of fixed `ClockCycles`.

</details>

<details>
<summary>2. FIND-002 — 🟡 Minor <code>[NO-DUMMY-DEAD-CODE]</code> — unused <code>UART0_LSR</code> binding</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_uart_loopback_test_seq.py:27-29`
- **Observed:** PeakRDL `UART_LSR` address is imported but never polled; settle uses `ClockCycles` instead.
- **Closure:** Wire LSR into the FIND-001 status wait, or delete the unused binding.

</details>

**Then:** owner remediates FIND-001 (and FIND-002 with it or by removing unused LSR), re-keeps a PASS log for `smc_uart_loopback_test`, and re-invokes `/dv_test_audit smc_uart_loopback_test`. Do not invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN SYS AXI CSR + pad-level `OcahUartConsole` / cocotbext-uart sink on `tb_uart0_tx_from_dut`; no force/deposit on UART proof path; ROM/efuse preload is post-PASS trailer |
| F2 can't-fail checker | ✅ clean — VIP bind raises; `assert captured == TX_BYTE` and `capture_frame` timeout (`SmcUartVipError`) are reachable FAIL-ON paths; protocol VIP golden/obs compare also fail-capable |
| E1 skip-to-pass | ✅ clean — missing VIP / bind failure raises `AssertionError`; sibling `uart_pin_wire_proof` skip path is not invoked |
| E2 empty phase | ✅ clean — CG ungate, UART_EN, DLAB baud, THR write, pad12 capture, CG restore all executed (9 CSR accesses + VIP byte) |
| S1 silent fail | ✅ clean — bind failure, capture timeout, and byte mismatch raise; success log only after assert |
| O1 checker disabled | ✅ clean — SYS AXI scoreboard checks #1–#9 + protocol VIP check #1 active; axi_monitor 0 errors |
| Phase-S obligations — L1 | 🟠 Major — FIND-001 (`[NO-BLIND-DELAY-SYNC]`); 🟡 Minor — FIND-002 (`[NO-DUMMY-DEAD-CODE]`); else addresses from `smc_addr_map`, seed logged, capture timeout fails, enrolled in `batch_d.toml`/`all.toml`, force-free, no unconditional CHK token |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_uart_loopback_test.py`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_uart_loopback_test_seq.py`
- UART VIP helper: `hw/sys/smc/dv/cocotb/seq_lib/smc_uart_protocol_vip.py` (`SmcUartVip` → `OcahUartConsole`)
- CSR helper: `hw/sys/smc/dv/cocotb/seq_lib/smc_csr_seq_utils.py` `SmcCsrSeq`
- Authoritative map: `hw/sys/smc/regs/gen/c/smc_addr.h` via `smc_addr_map.py`
- Log: `hw/sys/smc/dv/build/runs/20260806_094608__verilator__smc_uart_loopback_test/smc_uart_loopback_test/logs/smc_uart_loopback_test.log`
  sha256 `19fb9f10cedadbcd367f736d3f36aa093d823b4cdb7619b1d4fe9dd761d829d6`
  (verified via `sha256sum`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- Repo rev: `c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7`
- cocotb summary: `TESTS=1 PASS=1 FAIL=0 SKIP=0`; `result.json` status PASS, exit_code 0
- Final gates: seq `assert captured == TX_BYTE` + scoreboard protocol VIP `golden=a5 obs=a5` (no `CHK-*` tokens — none required without a card)
- Enrollment: `hw/sys/smc/dv/testlists/batch_d.toml`, `all.toml`
- Bring-up trailer (post-PASS flush): efuse hex + ROM `$readmemh` — time-0 image load; not used as UART golden (policy §6 standing preload)
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`); auditor `run_id: cursor/grok/4.5-reaudit-20260806`

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>19fb9f10…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| timing / bring-up | 25 | seed=1; periph=8ns; smc=6ns | base_test |
| divisor compute | 268 | `baud=115200 divisor=68` | seq `:50-61` |
| CLOCK_GATE save/ungate | 281–308 | RD/WR `0xc0010018` data `0x1f000000` OKAY | seq `:63-64` |
| UART_EN | 309–315 | WR `0xc0006000 <- 0x1` OKAY | seq `:65` |
| LCR/DLL/DLM/LCR | 316–343 | WR `0xc000610c`/`6100`/`6104`/`610c` OKAY | seq `:68-71` |
| blind settle | 343→344 | ~5328 ns → ~11856 ns (=1088×6 ns) | seq `:73-74` |
| VIP bind | 344–361 | cocotbext-uart 0.1.4 source/sink @ 115200 | seq `:76-79` / vip |
| THR write | 362–368 | WR `0xc0006100 <- 0xa5` OKAY | seq `:81` |
| pad12 capture | 369–370 | `Read byte 0xa5`; `UART DUT TX OK` | seq `:83-92` |
| CG restore + VIP record | 371–379 | WR `0xc0010018`; protocol VIP golden=a5 obs=a5 | seq `:94` / test |
| cocotb result | 387–389 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | — |

</details>

## Not concluded

- Whether a corrected UART0 THR→pad12 capture proves the SPEC properties a future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
