---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_octs_dual_sync_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094610__verilator__smc_octs_dual_sync_test/smc_octs_dual_sync_test/logs/smc_octs_dual_sync_test.log
  sha256: 6dce558d31d996c76846240570c41fb2682fd799c0633b4ebcbced75b5a1fe78
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
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_octs_dual_sync_test_seq.py:98-161
  observed: >-
    Secondary COUNT hard-gate uses a loose window
    `[PRESET+CREDIT, PRESET+2*CREDIT+16]` (`expected_lo`/`expected_hi` with
    unexplained `+16` slack). Primary gates only assert `sync_edges >= 1`,
    `credit_edges >= 2`, and `count_pri > PRESET` — activity/minimum
    thresholds, not exact values or transitions. Kept log L351 COUNT=0x102f
    (inside the +16 window around PRESET+2*CREDIT=0x1020) and L408
    `sync_edges=1 credit_edges=16 COUNT=0x10fd` — both pass without proving
    an exact credit/COUNT/edge contract.
  closure_condition: >-
    Bind exact COUNT / edge / STATUS expectations from SPEC or an approved
    fixed vector table (or document an exact closed-form model); remove
    unexplained slack; keep `assert` FAIL-ON paths for those exacts.
  waived_by: null
- id: FIND-002
  tag: '[NO-BLIND-DELAY-SYNC]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_octs_dual_sync_test_seq.py:96-102
  observed: >-
    After `drive_secondary_sync_then_credits`, the sequence waits a fixed
    `ClockCycles(clk, 4)` then samples COUNT and STATUS.RUNNING with no
    handshake/event that the secondary sync/credit path has completed —
    classic blind-delay sync before the assertion. (Primary pad observe uses
    a bounded RisingEdge window + post-window assert, which is not this
    finding.) Reached and passed this run (L329 inject done → L351 PASS).
  closure_condition: >-
    Replace the fixed post-inject settle with an event/handshake wait
    (STATUS.RUNNING set, COUNT change, or pad/CDC complete) with a bounded
    timeout that fails on expiry (`[TIMEOUT-MUST-FAIL]`); keep cycle delays
    only when the delay itself is the SPEC quantity under test.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_octs_dual_sync_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🟠 2 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect** in the test by itself. Kept log is a sim **PASS** (seed 1); Layer 2 entry
> is not evaluated in this mode.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `edb43279…`)

| Item | Prior (log `edb43279…`, FAIL) | This audit (log `6dce558d…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🔴 1 Blocking · 🟠 2 Major | 🟠 2 Major |
| Prior FIND-001 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` | open Blocking — OCTS literals at `0xC000Exxx` → DECERR | **closed** — `_OCTS_*` via `smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_*")`; kept log hits `0xc000a000`–`a020` with OKAY CSR traffic |
| Prior FIND-002 `[EXACT-EXPECTATION]` | open Major — COUNT window / edge minima | **still open** as FIND-001 Major — same loose window + minima; now exercised (COUNT=0x102f, credit_edges=16) |
| Prior FIND-003 `[NO-BLIND-DELAY-SYNC]` | open Major — `ClockCycles(4)` then sample | **still open** as FIND-002 Major — same post-inject settle; now reached |
| Kept log | `edb43279695b3a74a1249a1d88720f76d84214d4847431657b6e82cda978d748` (FAIL) | `6dce558d31d996c76846240570c41fb2682fd799c0633b4ebcbced75b5a1fe78` (PASS) |
| Repo rev | `2ecc7b227e3926b253c65b5aac21239eec24ba5f` | `c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7` |
| Waivers carried | none signed (`waivers: []`) | none (nothing to drop; no signed entries) |

## Your to-do — 2 items (🟠 2 Major)

| # | Kind | Id | Severity / grade | Where |
|---|---|---|---|---|
| 1 | finding | FIND-001 | 🟠 Major | `smc_octs_dual_sync_test_seq.py:98-161` |
| 2 | finding | FIND-002 | 🟠 Major | `smc_octs_dual_sync_test_seq.py:96-102` |

<details>
<summary>1. FIND-001 — 🟠 Major <code>[EXACT-EXPECTATION]</code> — COUNT/edge gates are ranges and minima, not exacts</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_octs_dual_sync_test_seq.py:98-161`
- **Observed:** Secondary COUNT window includes unexplained `+16`; primary asserts `edges >= N` and `COUNT > PRESET` only. Kept log: COUNT=0x102f; sync_edges=1, credit_edges=16.
- **Closure:** Use SPEC/table-derived exact COUNT/edge/STATUS expects with fail-capable asserts; remove unexplained slack.

</details>

<details>
<summary>2. FIND-002 — 🟠 Major <code>[NO-BLIND-DELAY-SYNC]</code> — fixed ClockCycles then sample after secondary inject</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_octs_dual_sync_test_seq.py:96-102`
- **Observed:** `await ClockCycles(clk, 4)` then COUNT/STATUS.RUNNING sample with no completion handshake. Reached this PASS.
- **Closure:** Event/handshake wait with bounded timeout that fails on expiry.

</details>

**Then:** owner remediates FIND-001 and FIND-002 on the sequence, re-keeps a PASS log for `smc_octs_dual_sync_test`, and re-invokes `/dv_test_audit smc_octs_dual_sync_test`; do not invent a card here (`STANDALONE-REQUEST`). Closure claims need `/dv_vplan_gen` first.

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — SEP_IN SYS AXI frontdoor via `SmcCsrSeq`/`SmcSysAxiItem`; TB `tb_chiplet_is_primary` / `tb_octs_*_ext` are top-level strap/pad stimulus (tb_top → DUT ports / pad mux), not success-state fabrication; ROM/efuse hex preload is bring-up trailer |
| F2 can't-fail checker | ✅ clean — scoreboard `assert item.resp_ok` and sequence asserts are fail-capable (prior FAIL fired on DECERR; this PASS exercises COUNT/edge asserts) |
| E1 skip-to-pass | ✅ clean — missing TB pin uses hard `assert hasattr`; AXI non-OKAY raises |
| E2 empty phase | ✅ clean — secondary inject + primary TIMER_START + pad edge counts + VIP record all reached (scoreboard SYS AXI #1–#16) |
| S1 silent fail | ✅ clean — scoreboard raises on non-OKAY; sequence mismatches raise `AssertionError` |
| O1 checker disabled | ✅ clean — SYS AXI scoreboard path active (checks #1–#16); protocol VIP `passed` is a non-asserted completion marker only |
| Phase-S obligations — L1 | 🟠 Major — FIND-001, FIND-002; else addresses via `smc_addr`/`smc_addr.h`, seed=1 logged, enrolled in `batch_d.toml`/`all.toml`, primary edge helper X-aware (`is_resolvable`), secondary/primary pad path force-free at TB pins, no unconditional CHK token; primary window fails via post-count assert |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_octs_dual_sync_test.py`
  sha256 `7d3899d985c7f4e2c9ca677e7c3aaea15423e4a6089fbe75d89ce2e9b541d86d`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_octs_dual_sync_test_seq.py`
  sha256 `02d756ccae4b0be5905ed14f2289aa639384624fda9fd2a58edf4d508a6791b0`
- Sideband BFM: `hw/sys/smc/dv/cocotb/seq_lib/smc_octs_sync_bfm.py`
  sha256 `345ec9589c22301bd72cd7d9b7dd13d856846e806eb6e4e143ddc3115840f33c`
  (`drive_secondary_sync_then_credits`, `count_rising_edges`)
- CSR helpers: `hw/sys/smc/dv/cocotb/seq_lib/smc_csr_seq_utils.py`
- Addr map: `hw/sys/smc/dv/cocotb/seq_lib/smc_addr_map.py` →
  `hw/sys/smc/regs/gen/c/smc_addr.h` (`SMC_TOP_SMC_SYSTEM_TIMER_OCTS_*`)
- Scoreboard (proof path): `hw/sys/smc/dv/cocotb/env/smc_scoreboard.py` `_check_sys_axi`
- Log: `hw/sys/smc/dv/build/runs/20260806_094610__verilator__smc_octs_dual_sync_test/smc_octs_dual_sync_test/logs/smc_octs_dual_sync_test.log`
  sha256 `6dce558d31d996c76846240570c41fb2682fd799c0633b4ebcbced75b5a1fe78`
  (matches claimed / `sha256sum`)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary L414–L420:
  `smc_octs_dual_sync_test … PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Stimulus reached: strap SECONDARY → CSR program @ `0xc000a004`/`a020`/`a00c`/`a010`
  → STATUS.MODE=SECONDARY → sync+2 credits → COUNT/RUNNING gate → strap PRIMARY →
  TIMER_START @ `0xc000a000` → pad55/56 edge counts → VIP record
- Observed PASS cites: secondary `STATUS=0x11 COUNT=0x102f` (L351);
  dual-sync `sync_edges=1 credit_edges=16 COUNT=0x10fd` (L408)
- Authoritative OCTS (hit): TIMER_START `0xC000A000`, CTRL `0xC000A004`,
  STATUS `0xC000A008`, PRESET_LO/HI `0xC000A00C/A010`, COUNT_LO/HI `0xC000A014/A018`,
  GPIO_ENABLE `0xC000A020`
- Enrollment: `hw/sys/smc/dv/testlists/batch_d.toml`, `all.toml`
- Bring-up trailer: efuse/ROM hex preload after PASS flush; not used as OCTS golden
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`); auditor
  `run_id: cursor/grok/4.5-reaudit-20260806`

</details>

<details>
<summary>Stimulus / PASS cites (kept log <code>6dce558d…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| Seed | 13 | `Seeding Python random module with supplied seed 1` | cocotb |
| Bring-up | 257–267 | clocks + cold reset release | `smc_base_test` |
| Secondary CSR | 280–327 | writes/reads `0xc000a004`…`a008` OKAY; STATUS=0x1 | seq `:75-85` |
| Inject done | 329 | `sync + 2 credits (pulse_width=4)` | bfm |
| Secondary gate | 330–351 | COUNT=0x102f STATUS=0x11 PASS | seq `:96-117` |
| Primary CSR + start | 352–393 | MODE clear; TIMER_START `0xc000a000` | seq `:125-147` |
| Primary gate | 394–408 | sync_edges=1 credit_edges=16 COUNT=0x10fd PASS | seq `:149-169` |
| VIP + result | 409–420 | protocol VIP; `PASS=1` | test + cocotb |

</details>

## Not concluded

- Whether this dual-chiplet OCTS scenario matches the SPEC properties a future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
