---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_telemetry_receiver_csr_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094638__verilator__smc_telemetry_receiver_csr_test/smc_telemetry_receiver_csr_test/logs/smc_telemetry_receiver_csr_test.log
  sha256: 24a5318676bcac1b61af52a1a70890136e1bf1b7d66f3de47d90916cdb090e2e
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
  tag: '[TIMEOUT-MUST-FAIL]'
  severity: Blocking
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_telemetry_receiver_csr_test_seq.py:56-65
  observed: >-
    `_atb_write_beat` waits up to 64 `RisingEdge(clk_smc_i)` for
    `tb_telemetry0_atready` then unconditionally clears `atvalid` with no raise
    on expiry. A stalled ATB ready path can drop beats without failing the
    testcase. This PASS seed reached U4-6b ATB stimulus (STATUS.~EMPTY +
    PROBE_ID=0x05), so the silent-expiry helper is on the exercised proof path;
    handshake completion was lucky, not FAIL-ON-timeout.
  closure_condition: >-
    Convert the ready wait into a bounded handshake that raises on timeout with
    last-state diagnostics (atvalid/atready/beat index); do not deassert atvalid
    and continue after an unanswered beat.
  waived_by: null
- id: FIND-002
  tag: '[NO-BLIND-DELAY-SYNC]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_telemetry_receiver_csr_test_seq.py:126-162
  observed: >-
    After CLOCK_GATE ungate the sequence settles with fixed
    `ClockCycles(dut.clk_smc_i, 8)` (`:126`) before INTR_TEST; after
    INTR_ENABLE/INTR_TEST writes it uses bare `ClockCycles(..., 8)` then samples
    `tb_telemetry_irq_any` (`:136-137`); the W1C/clear path likewise uses
    `ClockCycles(..., 8)` before the stuck-high assert (`:151-153`); post-ATB
    message uses `ClockCycles(..., 16)` before the STATUS.~EMPTY poll
    (`:162-163`). Those fixed settles stand in for IRQ/ATB completion
    handshakes. Reached and passed this seed.
  closure_condition: >-
    Replace fixed cycle settles used as sync with event/handshake waits that
    FAIL-ON timeout (e.g. wait for `tb_telemetry_irq_any` edge/level with a
    bound; drop the blind delay before the existing STATUS.~EMPTY poll). Keep a
    bare delay only when latency itself is the checked quantity.
  waived_by: null
- id: FIND-003
  tag: '[ADDRESS-FROM-AUTHORITATIVE-MAP]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_telemetry_receiver_csr_test_seq.py:45-46
  observed: >-
    CSR bases now come from PeakRDL via `smc_indexed_addr` / `smc_addr` (correct
    0xC0009xxx / 0xC0010018 traffic this seed). Residual hand bit masks remain:
    `_STATUS_EMPTY = 0x1` and `_INTR_MISSING_LAST = 0x1` while generated
    `TELEMETRY_RECEIVER__STATUS__BUFFER_EMPTY_bm` and
    `TELEMETRY_RECEIVER__INTR_STATUS__MISSING_LAST_bm` (also INTR_ENABLE /
    INTR_TEST) exist in
    `hw/ip/telemetry_receiver/regs/gen/c/telemetry_receiver_wrap.h` (and bootrom
    `TELEMETRY_RECEIVER_INTR_*_MISSING_LAST_MASK`). Values match today (latent
    rot only) — Major per policy §3 conditional severity.
  closure_condition: >-
    Import EMPTY / MISSING_LAST bit masks by symbol from the generated telemetry
    receiver header (or a `smc_addr_map` export of those `_bm` constants); delete
    the hand `_STATUS_EMPTY` / `_INTR_MISSING_LAST` literals on the proof path.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_telemetry_receiver_csr_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🔴 1 Blocking · 🟠 2 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect** in the test by itself. Kept log is a sim **PASS** (seed 1, verilator 5.050):
> TELEMETRY_RECEIVER_0/1/2 CTRL reset reads at PeakRDL `0xc0009000/9100/9200`,
> INTR_TEST→`tb_telemetry_irq_any`, and ATB message→PROBE_ID=0x05 completed —
> Layer 2 entry is still not evaluated in this mode.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `880c71f6…`)

| Item | Prior (log `880c71f6…`, FAIL) | This audit (log `24a53186…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🔴 2 Blocking · 🟠 1 Major | 🔴 1 Blocking · 🟠 2 Major |
| Prior FIND-001 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` (bases) | open Blocking — hand `0xC000D000/D100/D200` → DECERR | **closed** — `smc_indexed_addr` / `smc_addr`; log OKAY @ `0xc0009xxx` / `0xc0010018` |
| Prior FIND-002 `[TIMEOUT-MUST-FAIL]` | open Blocking — ATB ready silent expiry (unreached) | **still open** as FIND-001 Blocking — ATB path exercised this seed |
| Prior FIND-003 `[NO-BLIND-DELAY-SYNC]` | open Major — fixed ClockCycles (unreached) | **still open** as FIND-002 Major — IRQ/ATB settles reached |
| Field bit masks | not scored (run died at first CSR) | **new** FIND-003 Major — residual hand `_STATUS_EMPTY` / `_INTR_MISSING_LAST` vs generated `_bm` |
| Kept log | `880c71f61e4d96da2737b073aa76bc03cbb51e73af69f24141220436b24fddd6` (FAIL) | `24a5318676bcac1b61af52a1a70890136e1bf1b7d66f3de47d90916cdb090e2e` (PASS) |
| Repo rev | `2ecc7b227e3926b253c65b5aac21239eec24ba5f` | `c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7` |
| Waivers carried | none signed (`waivers: []`) | none (nothing to drop; no signed entries) |

## Your to-do — 3 items (🔴 1 Blocking · 🟠 2 Major)

| # | Kind | Id | Severity / grade | Where |
|---|---|---|---|---|
| 1 | finding | FIND-001 | 🔴 Blocking | `smc_telemetry_receiver_csr_test_seq.py:56-65` |
| 2 | finding | FIND-002 | 🟠 Major | `smc_telemetry_receiver_csr_test_seq.py:126-162` |
| 3 | finding | FIND-003 | 🟠 Major | `smc_telemetry_receiver_csr_test_seq.py:45-46` |

<details>
<summary>1. FIND-001 — 🔴 Blocking <code>[TIMEOUT-MUST-FAIL]</code> — ATB beat ready wait expires silently</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_telemetry_receiver_csr_test_seq.py:56-65` (`_atb_write_beat`)
- **Observed:** 64-cycle `atready` poll clears `atvalid` without raise on expiry. This PASS
  exercised U4-6b ATB; silent expiry remains on the proof path.
- **Closure:** Bounded ready handshake that raises on timeout with diagnostics; never continue
  after an unanswered beat.

</details>

<details>
<summary>2. FIND-002 — 🟠 Major <code>[NO-BLIND-DELAY-SYNC]</code> — fixed ClockCycles before IRQ / ATB samples</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_telemetry_receiver_csr_test_seq.py:126-162`
- **Observed:** Bare `ClockCycles(..., 8/16)` stands in for CG/IRQ assertion / clear / post-ATB
  settle. Reached this seed.
- **Closure:** Event/handshake + FAIL-ON timeout; do not treat fixed settle as proof sync.

</details>

<details>
<summary>3. FIND-003 — 🟠 Major <code>[ADDRESS-FROM-AUTHORITATIVE-MAP]</code> — residual hand EMPTY / MISSING_LAST bit masks</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_telemetry_receiver_csr_test_seq.py:45-46`
- **Observed:** Bases fixed via PeakRDL; `_STATUS_EMPTY` / `_INTR_MISSING_LAST` still hand
  `0x1` while `TELEMETRY_RECEIVER__STATUS__BUFFER_EMPTY_bm` /
  `TELEMETRY_RECEIVER__INTR_*__MISSING_LAST_bm` exist. Latent rot → Major.
- **Closure:** Import generated `_bm` symbols; drop the hand bit literals.

</details>

**Then:** owner remediates FIND-001 ATB ready timeout, FIND-002 IRQ/ATB handshake sync, and
FIND-003 field-mask sourcing on `smc_telemetry_receiver_csr_test_seq`, re-keeps a PASS log,
and re-invokes `/dv_test_audit smc_telemetry_receiver_csr_test`. Do not invent a card here
(`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN SYS AXI via `SmcSysAxiItem`; ATB uses TB pad drive (`tb_telemetry0_at*`); IRQ samples are passive; no force/deposit on proof path; ROM/efuse hex is post-PASS trailer |
| F2 can't-fail checker | ✅ clean — scoreboard `assert item.resp_ok` / value compare; seq asserts on STATUS.EMPTY, INTR quiet, IRQ high/low, PROBE_ID, ATB EMPTY timeout; final test gate `assert seq.telemetry_irq_ok and seq.telemetry_atb_ok` |
| E1 skip-to-pass | ✅ clean — missing `tb_telemetry0_atvalid` raises; no missing-handle skip-to-pass branch; CSR + IRQ + ATB phases executed |
| E2 empty phase | ✅ clean — CSR reset reads, CLOCK_GATE ungate, INTR_TEST IRQ, ATB message→PROBE_ID are coded with real stimulus (all reached this seed) |
| S1 silent fail | ✅ clean on scored CSR/IRQ/PROBE paths (assert/raise); ATB ready silent-expiry covered by FIND-001 not as S1 log-only mismatch |
| O1 checker disabled | ✅ clean — SYS AXI scoreboard analysis active (checks #1–#16); `auto_protocol_vip = False` is VIP recording opt-out after the scenario, not a disabled scoreboard |
| Phase-S obligations — L1 | 🔴 Blocking — FIND-001; 🟠 Major — FIND-002, FIND-003; else STATUS.~EMPTY poll raises on timeout, addresses from `smc_addr_map`, seed logged, enrolled in `p1_coverage_gap.toml`, no unconditional CHK token; TELEMETRY_CG_EN from generated `_bm` |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_telemetry_receiver_csr_test.py`
- Sequence (discovered): `hw/sys/smc/dv/cocotb/seq_lib/smc_telemetry_receiver_csr_test_seq.py`
- CSR helper: `hw/sys/smc/dv/cocotb/seq_lib/smc_csr_seq_utils.py` (`SmcCsrSeq.csr_read` / `csr_write`)
- Scoreboard (proof path): `hw/sys/smc/dv/cocotb/env/smc_scoreboard.py` `_check_sys_axi`
- Authoritative map: `hw/sys/smc/regs/gen/c/smc_addr.h` via `smc_addr_map.py`; field masks
  `hw/ip/telemetry_receiver/regs/gen/c/telemetry_receiver_wrap.h` (not yet imported for EMPTY /
  MISSING_LAST)
- Log: `hw/sys/smc/dv/build/runs/20260806_094638__verilator__smc_telemetry_receiver_csr_test/smc_telemetry_receiver_csr_test/logs/smc_telemetry_receiver_csr_test.log`
  sha256 `24a5318676bcac1b61af52a1a70890136e1bf1b7d66f3de47d90916cdb090e2e`
  (verified via `sha256sum` / workspace hash scan; matches kept-log identity)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary L416–L418:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Final assertion gate: `assert seq.telemetry_irq_ok and seq.telemetry_atb_ok` reached
  (log L406 `Telemetry U4-6 PASS`; VIP `irq=True atb=True`)
- AXI monitor: `9 R beats, 7 B resps; R-resp tally OKAY=9; 0 errors`
- Address / value cites (kept log):
  - TELEMETRY_0/1/2 CTRL `0xc0009000/9100/9200` → `0x0` exp match (L280–L308)
  - STATUS `0xc0009004` → `0x1` EMPTY at reset (L309–L314); later `0x0` post-ATB (L378–L383)
  - INTR_STATUS `0xc0009008` quiet then `0x1` after INTR_TEST (L316–L362)
  - CLOCK_GATE `0xc0010018` ungate/restore (L323–L341, L399–L404)
  - PROBE_ID `0xc0009014` → `0x5` (L385–L390)
- Enrollment: `hw/sys/smc/dv/testlists/p1_coverage_gap.toml`
- Bring-up trailer (post-PASS flush): efuse/ROM hex preload — not used as telemetry golden
- No unexplained `ERROR`/`FATAL`/`Traceback` in the kept log (DeprecationWarning only)
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`); auditor
  `run_id: cursor/grok/4.5-reaudit-20260806`

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>24a53186…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| TELEMETRY_0/1/2 CTRL RD | 280–308 | OKAY `0xc0009x00` rdata `0x0` | seq `TELEMETRY_READS` |
| STATUS / INTR reset | 309–321 | STATUS=`0x1`; INTR=`0x0` | seq `:109-118` |
| CLOCK_GATE ungate | 323–341 | RD/WR `0xc0010018` | seq `:120-126` |
| INTR_TEST IRQ | 343–377 | ENABLE/TEST WR; STATUS W1C; ENABLE off | seq `:128-155` |
| ATB → PROBE_ID | 378–398 | STATUS non-empty; PROBE_ID=`0x5`; BUFFER_POP | seq `:157-180` |
| U4-6 PASS / VIP | 406–410 | `irq=True atb=True`; OKAY=9 | test gate + monitor |
| cocotb result | 412–418 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | — |

</details>

## Not concluded

- Whether CSR reset + INTR_TEST IRQ + ATB→PROBE_ID proves the SPEC telemetry properties a future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
