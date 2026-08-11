---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_uart_log_engine_reg_rw_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094608__verilator__smc_uart_log_engine_reg_rw_test/smc_uart_log_engine_reg_rw_test/logs/smc_uart_log_engine_reg_rw_test.log
  sha256: 53350c70ac8a32063257deba91d0b610e54e030b4c26afa3cae970813029d4e5
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
  tag: '[EXACT-EXPECTATION]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_uart_log_engine_reg_rw_test_seq.py:11-38
  observed: >-
    UART_LOG_READS still passes expected=None for every entry into
    csr_read_many, so the initial 10-register "read depth" sweep completes on
    AXI OKAY alone with no exact reset/value expectation. Kept log shows
    non-trivial rdata on UART0_IIR (0x1), UART0_LSR (0x60), UART0_MSR (0x11)
    while scoreboard records exp=None (checks #2–#4). Write/readback/restore
    asserts later enforce masked patterns for five RW regs, but the read-only
    sweep (including LOG_ENGINE_CTRL and LOG_ENGINE_LOG_CTRL_0) remains
    value-blind and is counted in the final accesses==35 gate.
  closure_condition: >-
    Bind each UART_LOG_READS entry that has an independent SPEC/PeakRDL reset
    or known readable value to that exact expected (via item.expected /
    csr_read expected=); keep expected=None only where no independent golden
    exists and document that limit — do not treat OKAY-only completion as
    register-content proof for the read sweep.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_uart_log_engine_reg_rw_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🟠 1 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST`). Layer 1 findings are the entire scope of this report.
> `NOT-READY` records the **absence of a closure claim, not a defect**. Kept
> log is a sim **PASS** (seed 1, verilator 5.050): 35 SYS AXI scoreboard checks
> + write/readback/restore asserts + `accesses == 35` — Layer 2 entry is still
> not evaluated in this mode.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `079e0cdd…`)

| Item | Prior (log `079e0cdd…`, FAIL) | This audit (log `53350c70…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🔴 1 Blocking · 🟠 1 Major | 🟠 1 Major |
| Prior FIND-001 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` | open Blocking — hand `0xC000_Axxx` literals hit SYSTEM_TIMER_OCTS | **closed** — addresses via `smc_indexed_addr` / `smc_bootrom_addr`; kept log hits PeakRDL UART/log window `0xC0006000`+ with successful masked readbacks |
| Prior FIND-002 `[EXACT-EXPECTATION]` | open Major — `UART_LOG_READS` all `expected=None` | **still open** as FIND-001 Major — read sweep still OKAY-only |
| Kept log | `079e0cddf90bb931e11ad7e54384ab2bd6807ed7b22326f8ce51b2f330bdfbb1` (FAIL) | `53350c70ac8a32063257deba91d0b610e54e030b4c26afa3cae970813029d4e5` (PASS) |
| Repo rev | `2ecc7b227e3926b253c65b5aac21239eec24ba5f` | `c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7` |
| Waivers carried | none signed (`waivers: []`) | none (nothing to drop; no signed entries) |

## Your to-do — 1 item (🟠 1 Major)

| # | Kind | Id | Severity / grade | Where |
|---|---|---|---|---|
| 1 | finding | FIND-001 | 🟠 Major | `smc_uart_log_engine_reg_rw_test_seq.py:11-38` |

<details>
<summary>1. FIND-001 — 🟠 Major <code>[EXACT-EXPECTATION]</code> — read sweep is value-blind</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_uart_log_engine_reg_rw_test_seq.py:11-38`
- **Observed:** Every `UART_LOG_READS` entry uses `expected=None`, so the initial sweep only proves AXI completion, not register content/identity. Kept log IIR/LSR/MSR return non-zero rdata with no compare.
- **Closure:** Attach exact PeakRDL/SPEC expected values where an independent golden exists (or document and drop those entries from the content-proof path); do not treat OKAY-only as register proof.

</details>

**Then:** owner remediates FIND-001 on the sequence, re-keeps a PASS log, and re-invokes `/dv_test_audit smc_uart_log_engine_reg_rw_test`. Do not invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN AXI CSR via `SmcCsrSeq`; no force/deposit on proof path; ROM/efuse `$readmemh` is time-0 bring-up trailer |
| F2 can't-fail checker | ✅ clean — write/readback and restore `(got & mask) == (pattern & mask)` and `accesses == expected` are real reachable `AssertionError` paths; prior FAIL proved readback sensitivity |
| E1 skip-to-pass | ✅ clean — no missing-handle skip-to-pass; AXI path raises on unexpected timeout |
| E2 empty phase | ✅ clean — body issues 10 AXI reads then 5× save/write/readback + 5× restore/readback (scoreboard checks #1–#35) |
| S1 silent fail | ✅ clean — mismatch raises `AssertionError` with register name / got / expected / mask |
| O1 checker disabled | ✅ clean — SYS AXI scoreboard active (checks #1–#35 in kept log); protocol VIP `passed` is a non-asserted completion marker only |
| Phase-S obligations — L1 | 🟠 Major — FIND-001 `[EXACT-EXPECTATION]`; addresses sourced from PeakRDL/`smc_addr.h` (+ bootrom flatten for LOG_CTRL_0); seed logged; enrolled in `batch_d.toml` / `vplan_triplets.toml`; no unconditional CHK token; timeouts fail on driver path |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_uart_log_engine_reg_rw_test.py`
  sha256 `badb1309f34265cfb60bcfed384e15e25cc421dcb4e67b4c1fd656252d0db499`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_uart_log_engine_reg_rw_test_seq.py`
  sha256 `31cab12d38e5cf9455eb9e775562894791e4d4cb9ed9f53ccd78c5dd1b0ef3d0`
- Helper (proof path): `hw/sys/smc/dv/cocotb/seq_lib/smc_csr_seq_utils.py` (`SmcCsrSeq`)
- Authoritative map: `hw/sys/smc/dv/cocotb/seq_lib/smc_addr_map.py` →
  `hw/sys/smc/regs/gen/c/smc_addr.h` (`smc_indexed_addr`); LOG_ENGINE_LOG_CTRL_0 via
  bootrom `smc_top_regs.h` (`smc_bootrom_addr`) — resolves to PeakRDL `0xC0006240`
- Log: `hw/sys/smc/dv/build/runs/20260806_094608__verilator__smc_uart_log_engine_reg_rw_test/smc_uart_log_engine_reg_rw_test/logs/smc_uart_log_engine_reg_rw_test.log`
  sha256 `53350c70ac8a32063257deba91d0b610e54e030b4c26afa3cae970813029d4e5`
  (verified via `manifest.py hash-file`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary L550:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Stimulus: read-many UART/log CSRs → save/write/readback/restore sweep on five
  RW registers → `accesses == 35` gate (reached)
- Observed PASS cites: CTRL write `0x1` @ `0xc0006000` → readback `0x1` (L365–L383);
  SCR `0x5a` (L392–L404); REGION_SIZE `0x1000` (L413–L425); REGION_ADDR `0x2000`
  (L434–L446); INTR_ENABLE `0x11` (L455–L467); restores complete through check #35
- Enrollment: `hw/sys/smc/dv/testlists/batch_d.toml`, `vplan_triplets.toml`
- Auto protocol VIP records `csr_accesses=0` / `passed=True` (completion marker;
  scoreboard does not assert `passed`); real activity gate is seq `accesses == 35`
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`); auditor
  `run_id: cursor/grok/4.5-reaudit-20260806`

</details>

<details>
<summary>Stimulus / PASS cites (kept log <code>53350c70…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| read sweep | 280–356 | SEP_IN reads `0xc0006000`…`0xc0006240` OKAY (`exp=None`) | seq `:68` / READS |
| SAVE+WRITE+RB CTRL | 358–383 | save `0x0`; write `0x1`; readback `0x1` | seq `:71-78` |
| SCR / REGION / INTR | 385–467 | pattern write/readback OK | seq `:71-78` |
| restore sweep | 468–537 | restore + readback through scoreboard #35 | seq `:80-85` |
| depth gate + VIP | 539–550 | `accesses==35` implied (PASS); VIP marker; `PASS=1` | seq `:87-88` |

</details>

## Not concluded

- Whether a UART/log-engine RW sweep proves the SPEC properties a future card would
  require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
